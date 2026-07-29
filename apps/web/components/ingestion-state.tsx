/**
 * Explicit rendering of every ingestion state a document can be in.
 *
 * The platform abstains rather than guesses, and the same rule applies to the
 * UI: a document that is not yet usable as evidence must say so, and say why,
 * rather than looking indistinguishable from a ready one. Every state in
 * `DocumentStatus` has wording here, so a new backend state cannot silently
 * render as blank.
 *
 * All text comes from this module. Filenames, titles, and worker error strings
 * originate in untrusted uploads, so they are only ever rendered as text
 * children — never as markup, and never as a preview of document contents.
 */
import type { DocumentProgress, DocumentStatus, IngestionStage } from "../lib/contracts";

type StateCopy = Readonly<{ label: string; explanation: string; tone: DocumentTone }>;

export type DocumentTone = "blocked" | "pending" | "ready" | "withdrawn";

const STATUS_COPY: Record<DocumentStatus, StateCopy> = {
  pending: {
    label: "Queued",
    explanation: "Waiting for a worker to pick the document up. It is not evidence yet.",
    tone: "pending",
  },
  processing: {
    label: "Processing",
    explanation: "Being validated, scanned, parsed, and chunked. It is not evidence yet.",
    tone: "pending",
  },
  ready: {
    label: "Ready",
    explanation: "Indexed with full provenance and usable as evidence.",
    tone: "ready",
  },
  failed: {
    label: "Failed",
    explanation:
      "Processing did not complete, so nothing from this document can be cited. You can try again.",
    tone: "blocked",
  },
  quarantined: {
    label: "Quarantined",
    explanation:
      "A safety check rejected this document. It is never processed again and never used as evidence.",
    tone: "blocked",
  },
};

const ARCHIVED_COPY: StateCopy = {
  label: "Archived",
  explanation:
    "Withdrawn from evidence. Answers ignore it until it is restored; nothing was deleted.",
  tone: "withdrawn",
};

const STAGE_LABELS: Record<IngestionStage, string> = {
  uploaded: "Uploaded",
  validating: "Validating the file",
  scanning: "Scanning for malware",
  parsing: "Extracting text",
  ocr: "Reading scanned pages",
  normalizing: "Normalizing language",
  chunking: "Splitting into evidence spans",
  embedding: "Building embeddings",
  indexing: "Indexing for retrieval",
  ready: "Indexed",
};

/** Wording for a document's state, archival taking precedence over status. */
export function describeState(status: DocumentStatus, archived: boolean): StateCopy {
  return archived ? ARCHIVED_COPY : STATUS_COPY[status];
}

export function stageLabel(stage: IngestionStage): string {
  return STAGE_LABELS[stage];
}

/** A compact badge for lists and headings. */
export function StatusBadge({
  archived,
  status,
}: Readonly<{ archived: boolean; status: DocumentStatus }>) {
  const copy = describeState(status, archived);
  return (
    <span className="status-badge" data-tone={copy.tone}>
      {copy.label}
    </span>
  );
}

/**
 * The full lifecycle explanation for a detail view.
 *
 * The worker's error string is shown because a reviewer needs to know why a
 * document failed, and it is rendered as plain text: it can quote bytes from an
 * untrusted file and must never be treated as markup or as instructions.
 */
export function IngestionState({ progress }: Readonly<{ progress: DocumentProgress }>) {
  const copy = describeState(progress.status, progress.archived);
  return (
    <article className="ingestion-state" data-tone={copy.tone}>
      <p className="state-label">Processing state</p>
      <h3>{copy.label}</h3>
      <p>{copy.explanation}</p>
      <dl className="ingestion-facts">
        {progress.stage === null ? null : (
          <div>
            <dt>Furthest stage</dt>
            <dd>{stageLabel(progress.stage)}</dd>
          </div>
        )}
        {progress.job_status === null ? null : (
          <div>
            <dt>Job</dt>
            <dd>{progress.job_status}</dd>
          </div>
        )}
        <div>
          <dt>Attempts</dt>
          <dd>{progress.attempts}</dd>
        </div>
        <div>
          <dt>Updated</dt>
          <dd>
            <time dateTime={progress.updated_at}>{progress.updated_at}</time>
          </dd>
        </div>
      </dl>
      {progress.error === null ? null : (
        <p className="ingestion-error">
          <span className="ingestion-error-label">Reported failure:</span> {progress.error}
        </p>
      )}
    </article>
  );
}
