import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { DocumentUpload } from "./document-upload";
import { ACCEPTED_EXTENSIONS, DEFAULT_MAX_UPLOAD_BYTES } from "../lib/upload-rules";

const push = vi.fn();
const refresh = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, refresh }),
}));

const WORKSPACE_ID = "11111111-1111-4111-8111-111111111111";

type Listener = () => void;

/**
 * A minimal XHR stand-in. jsdom ships no upload progress events, and progress
 * is the reason this component uses XHR at all, so the test drives the events
 * itself.
 */
class FakeXhr {
  static last: FakeXhr | null = null;

  public method = "";
  public url = "";
  public responseType = "";
  public responseText = "";
  public status = 0;
  public sent: FormData | null = null;

  private readonly handlers = new Map<string, Listener[]>();
  private readonly uploadHandlers = new Map<string, ((event: unknown) => void)[]>();

  public readonly upload = {
    addEventListener: (name: string, handler: (event: unknown) => void) => {
      this.uploadHandlers.set(name, [...(this.uploadHandlers.get(name) ?? []), handler]);
    },
  };

  constructor() {
    FakeXhr.last = this;
  }

  open(method: string, url: string): void {
    this.method = method;
    this.url = url;
  }

  addEventListener(name: string, handler: Listener): void {
    this.handlers.set(name, [...(this.handlers.get(name) ?? []), handler]);
  }

  send(body: FormData): void {
    this.sent = body;
  }

  emitProgress(loaded: number, total: number, lengthComputable = true): void {
    for (const handler of this.uploadHandlers.get("progress") ?? []) {
      handler({ lengthComputable, loaded, total });
    }
  }

  emit(name: string): void {
    for (const handler of this.handlers.get(name) ?? []) {
      handler();
    }
  }
}

function acceptedDocument(): string {
  return JSON.stringify({
    id: "44444444-4444-4444-8444-444444444444",
    title: "lease.pdf",
    source_filename: "lease.pdf",
    mime_type: "application/pdf",
    size_bytes: 12,
    sha256: "a".repeat(64),
    status: "pending",
    created_at: "2026-07-29T10:00:00Z",
    archived_at: null,
    retryable: false,
  });
}

function pdf(name = "lease.pdf", size = 12): File {
  const file = new File(["%PDF-1.7 xx"], name, { type: "application/pdf" });
  Object.defineProperty(file, "size", { value: size });
  return file;
}

async function choose(file: File): Promise<void> {
  await userEvent.upload(screen.getByLabelText("Document"), file);
  await userEvent.click(screen.getByRole("button", { name: "Upload document" }));
}

beforeEach(() => {
  vi.clearAllMocks();
  FakeXhr.last = null;
  vi.stubGlobal("XMLHttpRequest", FakeXhr);
  render(
    <DocumentUpload
      acceptedExtensions={[...ACCEPTED_EXTENSIONS]}
      maxUploadBytes={DEFAULT_MAX_UPLOAD_BYTES}
      workspaceId={WORKSPACE_ID}
    />,
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("DocumentUpload", () => {
  it("reports progress while the body is being sent", async () => {
    await choose(pdf());

    const request = FakeXhr.last;
    expect(request).not.toBeNull();
    expect(request?.method).toBe("POST");
    // The upload goes to this app's own route handler, so the browser never
    // holds a bearer token.
    expect(request?.url).toBe(`/api/workspaces/${WORKSPACE_ID}/documents`);
    expect(request?.sent?.get("file")).toBeInstanceOf(File);

    request?.emitProgress(512, 1024);
    expect(await screen.findByText(/Sending lease\.pdf: 50%/)).toBeInTheDocument();
    expect(screen.getByRole("progressbar")).toHaveAttribute("value", "50");
  });

  it("keeps the last known percentage when the length is unknown", async () => {
    await choose(pdf());

    FakeXhr.last?.emitProgress(256, 1024);
    expect(await screen.findByText("Sending lease.pdf: 25%")).toBeInTheDocument();

    // A chunked body reports no total; showing 0% there would be a lie.
    FakeXhr.last?.emitProgress(0, 0, false);
    expect(screen.getByText("Sending lease.pdf: 25%")).toBeInTheDocument();
  });

  it("confirms acceptance and refreshes the server-rendered list", async () => {
    await choose(pdf());

    const request = FakeXhr.last;
    if (request !== null) {
      request.status = 201;
      request.responseText = acceptedDocument();
      request.emit("load");
    }

    expect(
      await screen.findByText(/lease\.pdf was accepted and queued for processing/),
    ).toBeInTheDocument();
    // Acceptance is not readiness: the copy must not imply the document can
    // already be cited.
    expect(screen.getByText(/becomes evidence only once processing succeeds/)).toBeInTheDocument();
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it("relays the API's stable rejection code", async () => {
    await choose(pdf());

    const request = FakeXhr.last;
    if (request !== null) {
      request.status = 422;
      request.responseText = JSON.stringify({
        detail: { code: "content_mismatch", message: "The file's contents are not a PDF." },
      });
      request.emit("load");
    }

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("The file's contents are not a PDF.");
    expect(alert).toHaveTextContent("Reference: content_mismatch");
  });

  it("falls back to a generic refusal when the body is not our error envelope", async () => {
    await choose(pdf());

    const request = FakeXhr.last;
    if (request !== null) {
      request.status = 502;
      request.responseText = "<html>gateway</html>";
      request.emit("load");
    }

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("The upload was refused.");
    expect(alert).toHaveTextContent("Reference: http_502");
  });

  it("sends an expired session back to sign in", async () => {
    await choose(pdf());

    const request = FakeXhr.last;
    if (request !== null) {
      request.status = 401;
      request.emit("load");
    }

    await waitFor(() => {
      expect(push).toHaveBeenCalledWith(
        `/login?expired=1&next=/workspaces/${WORKSPACE_ID}/documents`,
      );
    });
  });

  it("explains a network failure and an abort", async () => {
    await choose(pdf());
    FakeXhr.last?.emit("error");
    expect(await screen.findByText(/could not reach the service/)).toBeInTheDocument();

    await choose(pdf("other.pdf"));
    FakeXhr.last?.emit("abort");
    expect(await screen.findByText("The upload was cancelled.")).toBeInTheDocument();
  });

  it("rejects empty, oversized, and absurdly named files before sending anything", async () => {
    // The `accept` attribute already keeps an unsupported extension out of the
    // picker; `lib/upload-rules.test.ts` covers that branch directly.
    await choose(pdf("empty.pdf", 0));
    expect(await screen.findByText("The file is empty.")).toBeInTheDocument();
    expect(FakeXhr.last).toBeNull();

    await choose(pdf("huge.pdf", DEFAULT_MAX_UPLOAD_BYTES + 1));
    expect(await screen.findByText(/exceeds the 25 MB upload limit/)).toBeInTheDocument();
    expect(FakeXhr.last).toBeNull();

    await choose(pdf(`${"n".repeat(300)}.pdf`));
    expect(await screen.findByText("The filename is too long.")).toBeInTheDocument();
    expect(FakeXhr.last).toBeNull();
  });

  it("sends an oversized file when the deployment's cap is unknown", async () => {
    // The policy request failed, so the real cap is unknown. Enforcing the
    // compiled-in default here would refuse a file that a deployment with a
    // raised cap accepts, on the strength of a transient failure — so the file
    // goes to the API, which is the enforcement point either way.
    cleanup();
    render(
      <DocumentUpload
        acceptedExtensions={[...ACCEPTED_EXTENSIONS]}
        maxUploadBytes={null}
        workspaceId={WORKSPACE_ID}
      />,
    );

    await choose(pdf("huge.pdf", DEFAULT_MAX_UPLOAD_BYTES + 1));

    expect(FakeXhr.last).not.toBeNull();
    expect(screen.queryByText(/upload limit/)).not.toBeInTheDocument();
  });

  it("asks for a file when none was chosen", async () => {
    await userEvent.click(screen.getByRole("button", { name: "Upload document" }));

    expect(await screen.findByText("Choose a file to upload.")).toBeInTheDocument();
    expect(FakeXhr.last).toBeNull();
  });
});
