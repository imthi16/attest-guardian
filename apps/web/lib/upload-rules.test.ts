import { readFileSync } from "node:fs";
import { join } from "node:path";

import {
  ACCEPT_ATTRIBUTE,
  ACCEPTED_EXTENSIONS,
  MAX_UPLOAD_BYTES,
  formatBytes,
  rejectionFor,
} from "./upload-rules";

/**
 * These rules only fail fast in the browser; the API sniffs the bytes and is
 * the enforcement point. A mirror that drifts is still harmful, though — it
 * would refuse a type the platform accepts, or promise one it does not — so the
 * extension list and the size cap are asserted against the Python source.
 */
const validationSource = readFileSync(
  join(process.cwd(), "..", "api", "app", "documents", "validation.py"),
  "utf8",
);

const configSource = readFileSync(join(process.cwd(), "..", "api", "app", "config.py"), "utf8");

function file(name: string, size: number): File {
  const candidate = new File(["x"], name, { type: "application/octet-stream" });
  Object.defineProperty(candidate, "size", { value: size });
  return candidate;
}

describe("upload rule mirror", () => {
  it("accepts exactly the extensions the API accepts", () => {
    const apiExtensions = [
      ...validationSource.matchAll(/^ {4}"(\.\w+)": DocumentKind\.\w+,$/gm),
    ].map((match) => match[1]);

    expect(apiExtensions.sort()).toEqual([...ACCEPTED_EXTENSIONS].sort());
    expect(ACCEPT_ATTRIBUTE.split(",").sort()).toEqual(apiExtensions.sort());
  });

  it("uses the API's upload cap", () => {
    const declared = /max_upload_bytes: int = (\d+) \* (\d+) \* (\d+)/.exec(configSource);
    expect(declared).not.toBeNull();
    const [, a, b, c] = declared ?? [];
    expect(Number(a) * Number(b) * Number(c)).toBe(MAX_UPLOAD_BYTES);
  });

  it("mirrors the API's filename length limit", () => {
    expect(validationSource).toContain("MAX_FILENAME_LENGTH = 255");
  });
});

describe("rejectionFor", () => {
  it("passes a file that nothing local rules out", () => {
    expect(rejectionFor(file("report.pdf", 1024))).toBeNull();
  });

  it("rejects an unsupported extension with the API's code", () => {
    // The `accept` attribute filters the picker, but a drag-and-drop or a
    // scripted submission can still present anything.
    expect(rejectionFor(file("installer.exe", 1024))?.code).toBe("unsupported_file_type");
    expect(rejectionFor(file("noextension", 1024))?.code).toBe("unsupported_file_type");
  });

  it("is case insensitive about the extension", () => {
    expect(rejectionFor(file("REPORT.PDF", 1024))).toBeNull();
  });

  it("rejects an empty file", () => {
    expect(rejectionFor(file("blank.pdf", 0))?.code).toBe("empty_file");
  });

  it("rejects a file over the cap", () => {
    expect(rejectionFor(file("scan.pdf", MAX_UPLOAD_BYTES + 1))?.code).toBe("file_too_large");
    expect(rejectionFor(file("scan.pdf", MAX_UPLOAD_BYTES))).toBeNull();
  });

  it("rejects an overlong filename", () => {
    expect(rejectionFor(file(`${"n".repeat(300)}.pdf`, 1024))?.code).toBe("invalid_filename");
  });
});

describe("formatBytes", () => {
  it("reads naturally at every magnitude", () => {
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(2048)).toBe("2.0 KB");
    expect(formatBytes(204800)).toBe("200 KB");
    expect(formatBytes(MAX_UPLOAD_BYTES)).toBe("25 MB");
    expect(formatBytes(5 * 1024 ** 3)).toBe("5.0 GB");
  });
});
