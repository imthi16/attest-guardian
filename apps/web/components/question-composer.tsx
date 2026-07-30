"use client";

/**
 * Ask a question and watch the pipeline work.
 *
 * This posts to the streaming relay rather than calling a server action, because
 * an action returns once and cannot report progress. The events are the
 * pipeline's real stage transitions, so "Checking the evidence" means the
 * retrieve node genuinely finished — not a timer pretending to.
 *
 * The answer text is **not** streamed word by word, and that is deliberate
 * upstream: generation is extractive, so no partial answer exists that is safe
 * to display — a half-composed answer could show a statement whose citation had
 * not been checked yet. So the progress is live and the answer lands complete.
 *
 * Cancelling aborts the request. The API persists the answer only from a
 * terminal result, so an abandoned question leaves no answer behind claiming to
 * be one.
 *
 * Once an answer arrives the page is refreshed rather than the answer being
 * rendered from this component's state: the server-rendered thread is the
 * authority on what was stored, and painting a local copy risks showing
 * something subtly different from the record.
 */
import { useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { Feedback } from "./feedback";
import { stageLabel } from "../lib/answer-stages";
import { apiErrorDetailSchema, clientErrorCodes } from "../lib/contracts";

type QuestionComposerProps = Readonly<{
  conversationId: string;
  workspaceId: string;
}>;

type ComposerState =
  | Readonly<{ kind: "asking"; stage: string }>
  | Readonly<{ kind: "failed"; code: string; message: string }>
  | Readonly<{ kind: "idle" }>;

/** Split a chunk of an SSE body into whole `event:`/`data:` frames. */
export function parseFrames(buffer: string): Readonly<{
  events: readonly Readonly<{ data: string; name: string }>[];
  rest: string;
}> {
  const frames = buffer.split("\n\n");
  // The last piece may be a partial frame still arriving, so it stays buffered.
  const rest = frames.pop() ?? "";
  const events: Readonly<{ data: string; name: string }>[] = [];
  for (const frame of frames) {
    let name = "";
    let data = "";
    for (const line of frame.split("\n")) {
      if (line.startsWith("event: ")) {
        name = line.slice("event: ".length);
      } else if (line.startsWith("data: ")) {
        data = line.slice("data: ".length);
      }
    }
    if (name !== "") {
      events.push({ data, name });
    }
  }
  return { events, rest };
}

export function QuestionComposer({ conversationId, workspaceId }: QuestionComposerProps) {
  const [state, setState] = useState<ComposerState>({ kind: "idle" });
  const controller = useRef<AbortController | null>(null);
  const form = useRef<HTMLFormElement>(null);
  const router = useRouter();

  function cancel(): void {
    controller.current?.abort();
    controller.current = null;
    setState({ kind: "idle" });
  }

  async function ask(event: React.FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const question = String(data.get("question") ?? "").trim();
    if (question === "") {
      setState({
        code: clientErrorCodes.validation,
        kind: "failed",
        message: "Type a question first.",
      });
      return;
    }

    const abort = new AbortController();
    controller.current = abort;
    setState({ kind: "asking", stage: "authorize" });

    let response: Response;
    try {
      response = await fetch(
        `/api/workspaces/${encodeURIComponent(workspaceId)}/conversations/${encodeURIComponent(conversationId)}/stream`,
        {
          body: JSON.stringify({ question }),
          headers: { "Content-Type": "application/json" },
          method: "POST",
          signal: abort.signal,
        },
      );
    } catch {
      // An abort lands here too; cancelling already reset the state, so only a
      // genuine transport failure needs reporting.
      if (!abort.signal.aborted) {
        setState({
          code: clientErrorCodes.network,
          kind: "failed",
          message: "The service is unreachable. Please try again.",
        });
      }
      return;
    }

    if (!response.ok || response.body === null) {
      const detail = apiErrorDetailSchema.safeParse(await response.json().catch(() => null));
      if (response.status === 401) {
        router.push(`/login?expired=1&next=/workspaces/${workspaceId}/conversations`);
        return;
      }
      setState({
        code: detail.success ? detail.data.detail.code : `http_${response.status}`,
        kind: "failed",
        message: detail.success
          ? detail.data.detail.message
          : "The question could not be answered.",
      });
      return;
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let failure: Readonly<{ code: string; message: string }> | null = null;

    try {
      for (;;) {
        const { done, value } = await reader.read();
        if (done) {
          break;
        }
        buffer += decoder.decode(value, { stream: true });
        const { events, rest } = parseFrames(buffer);
        buffer = rest;
        for (const event of events) {
          if (event.name === "stage") {
            const stage = String((JSON.parse(event.data) as { stage?: unknown }).stage ?? "");
            setState({ kind: "asking", stage });
          } else if (event.name === "error") {
            const payload = JSON.parse(event.data) as { code?: string; message?: string };
            failure = {
              code: payload.code ?? clientErrorCodes.network,
              message: payload.message ?? "The answer could not be completed.",
            };
          }
        }
      }
    } catch {
      if (abort.signal.aborted) {
        return;
      }
      failure = {
        code: clientErrorCodes.network,
        message: "The connection dropped before the answer finished.",
      };
    }

    controller.current = null;
    if (failure !== null) {
      setState({ code: failure.code, kind: "failed", message: failure.message });
      return;
    }
    setState({ kind: "idle" });
    form.current?.reset();
    // The stored thread is the authority on what the answer was.
    router.refresh();
  }

  const asking = state.kind === "asking";
  return (
    <form className="composer" onSubmit={ask} ref={form}>
      <label className="field-label" htmlFor="question">
        Ask a question about this workspace&apos;s documents
      </label>
      <p className="field-hint" id="question-hint">
        Tamil, Tanglish, and English are all understood. Answers come only from your documents, with
        a citation for every statement.
      </p>
      <textarea
        aria-describedby="question-hint"
        className="composer-input"
        disabled={asking}
        id="question"
        maxLength={2000}
        name="question"
        rows={3}
      />

      <div className="composer-actions">
        <button className="primary-button" disabled={asking} type="submit">
          {asking ? "Working…" : "Ask"}
        </button>
        {asking ? (
          <button className="secondary-button" onClick={cancel} type="button">
            Cancel
          </button>
        ) : null}
      </div>

      {asking ? (
        <p aria-live="polite" className="composer-progress">
          {stageLabel(state.stage)}
        </p>
      ) : null}

      {state.kind === "failed" ? (
        <Feedback code={state.code} message={state.message} tone="error" />
      ) : null}
    </form>
  );
}
