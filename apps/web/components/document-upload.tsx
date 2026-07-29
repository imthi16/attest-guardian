/**
 * Upload form with byte-level progress.
 *
 * `XMLHttpRequest` is used deliberately: it is the only browser API that
 * reports how much of a request body has been sent, and a reviewer uploading a
 * 20 MB scan needs to see that it is moving. The request goes to this app's own
 * route handler, so no bearer token is ever present in the browser, and the
 * API — not this component — decides whether the upload is allowed and whether
 * the bytes are what the filename claims.
 *
 * The local checks here only fail fast with the same stable codes the API uses;
 * they are never the enforcement point.
 */
"use client";

import { useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { Feedback } from "./feedback";
import { apiErrorDetailSchema, clientErrorCodes, documentSchema } from "../lib/contracts";
import {
  ACCEPT_ATTRIBUTE,
  ACCEPTED_EXTENSIONS,
  MAX_UPLOAD_BYTES,
  formatBytes,
  rejectionFor,
} from "../lib/upload-rules";

type UploadState =
  | Readonly<{ kind: "done"; filename: string }>
  | Readonly<{ kind: "failed"; code: string; message: string }>
  | Readonly<{ kind: "idle" }>
  | Readonly<{ kind: "sending"; filename: string; percent: number }>;

type DocumentUploadProps = Readonly<{ workspaceId: string }>;

function describeXhrFailure(
  status: number,
  responseText: string,
): Readonly<{
  code: string;
  message: string;
}> {
  try {
    const parsed = apiErrorDetailSchema.safeParse(JSON.parse(responseText));
    if (parsed.success) {
      return parsed.data.detail;
    }
  } catch {
    // A non-JSON body means the failure did not come from our own API layer.
  }
  return {
    code: `http_${status}`,
    message: "The upload was refused. Please try again.",
  };
}

export function DocumentUpload({ workspaceId }: DocumentUploadProps) {
  const [state, setState] = useState<UploadState>({ kind: "idle" });
  const inputRef = useRef<HTMLInputElement>(null);
  const router = useRouter();

  function send(file: File): void {
    const form = new FormData();
    form.append("file", file);

    const request = new XMLHttpRequest();
    request.open("POST", `/api/workspaces/${encodeURIComponent(workspaceId)}/documents`);
    request.responseType = "text";
    request.upload.addEventListener("progress", (event) => {
      // `lengthComputable` is false for chunked bodies; keep the last known
      // percentage rather than showing a misleading zero.
      if (event.lengthComputable) {
        setState({
          filename: file.name,
          kind: "sending",
          percent: Math.round((event.loaded / event.total) * 100),
        });
      }
    });
    request.addEventListener("load", () => {
      if (
        request.status === 201 &&
        documentSchema.safeParse(safeJson(request.responseText)).success
      ) {
        setState({ filename: file.name, kind: "done" });
        if (inputRef.current !== null) {
          inputRef.current.value = "";
        }
        // The list is server rendered from the API, so refresh rather than
        // splicing an optimistic row the API has not confirmed.
        router.refresh();
        return;
      }
      if (request.status === 401) {
        router.push(`/login?expired=1&next=/workspaces/${workspaceId}/documents`);
        return;
      }
      const { code, message } = describeXhrFailure(request.status, request.responseText);
      setState({ code, kind: "failed", message });
    });
    request.addEventListener("error", () => {
      setState({
        code: clientErrorCodes.network,
        kind: "failed",
        message: "The upload could not reach the service. Please try again.",
      });
    });
    request.addEventListener("abort", () => {
      setState({
        code: clientErrorCodes.uploadAborted,
        kind: "failed",
        message: "The upload was cancelled.",
      });
    });

    setState({ filename: file.name, kind: "sending", percent: 0 });
    request.send(form);
  }

  function onSubmit(event: React.FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    const file = inputRef.current?.files?.[0];
    if (file === undefined) {
      setState({
        code: clientErrorCodes.validation,
        kind: "failed",
        message: "Choose a file to upload.",
      });
      return;
    }
    const rejection = rejectionFor(file);
    if (rejection !== null) {
      setState({ code: rejection.code, kind: "failed", message: rejection.message });
      return;
    }
    send(file);
  }

  const sending = state.kind === "sending";
  return (
    <form className="upload-form" onSubmit={onSubmit}>
      <p className="field">
        <label htmlFor="document-file">Document</label>
        <span className="field-hint" id="document-file-hint">
          {ACCEPTED_EXTENSIONS.join(", ")} up to {formatBytes(MAX_UPLOAD_BYTES)}. Uploads are
          scanned and validated before anything is stored.
        </span>
        {/* Deliberately not `required`: the native validation bubble would
            compete with the announced, code-carrying message this form shows
            for a missing file, and only one of the two can be the explanation. */}
        <input
          accept={ACCEPT_ATTRIBUTE}
          aria-describedby="document-file-hint"
          disabled={sending}
          id="document-file"
          name="file"
          ref={inputRef}
          type="file"
        />
      </p>

      <button aria-busy={sending} className="primary-button" disabled={sending} type="submit">
        {sending ? "Uploading" : "Upload document"}
      </button>

      {sending ? (
        <p className="upload-progress">
          <progress max={100} value={state.percent}>
            {state.percent}%
          </progress>
          <span aria-live="polite" className="upload-progress-text">
            Sending {state.filename}: {state.percent}%
          </span>
        </p>
      ) : null}

      {state.kind === "failed" ? (
        <Feedback code={state.code} message={state.message} tone="error" />
      ) : null}
      {state.kind === "done" ? (
        <Feedback
          message={`${state.filename} was accepted and queued for processing. It becomes evidence only once processing succeeds.`}
          tone="success"
        />
      ) : null}
    </form>
  );
}

function safeJson(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}
