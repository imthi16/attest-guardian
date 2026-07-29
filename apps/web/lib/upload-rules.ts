/**
 * A client-side mirror of the API's upload rules.
 *
 * This exists only to fail fast and explain the rule before a large file is
 * sent: `apps/api/app/documents/validation.py` remains the enforcement point
 * and sniffs the bytes themselves, so a file that gets past this mirror is
 * still rejected with a stable code. Keep the two in sync; the parity test
 * pins the extension list.
 */
export const ACCEPTED_EXTENSIONS = [".pdf", ".txt", ".md", ".markdown", ".docx"] as const;

/** The `accept` attribute for the file input, from the same source of truth. */
export const ACCEPT_ATTRIBUTE = ACCEPTED_EXTENSIONS.join(",");

/** Mirrors `Settings.max_upload_bytes` (25 MiB) in the API. */
export const MAX_UPLOAD_BYTES = 25 * 1024 * 1024;

export const MAX_FILENAME_LENGTH = 255;

export type UploadRejection = Readonly<{ code: string; message: string }>;

export function formatBytes(bytes: number): string {
  if (bytes < 1024) {
    return `${bytes} B`;
  }
  const units = ["KB", "MB", "GB"];
  let value = bytes / 1024;
  let unit = units[0];
  for (const candidate of units.slice(1)) {
    if (value < 1024) {
      break;
    }
    value /= 1024;
    unit = candidate;
  }
  return `${value.toFixed(value < 10 ? 1 : 0)} ${unit}`;
}

function extensionOf(filename: string): string {
  const dot = filename.lastIndexOf(".");
  return dot === -1 ? "" : filename.slice(dot).toLowerCase();
}

/**
 * Check a chosen file against the mirrored rules.
 *
 * Returns `null` when nothing local rules out the upload. The codes match the
 * API's so a rejection reads the same wherever it was decided.
 */
export function rejectionFor(file: File): UploadRejection | null {
  if (file.name.length > MAX_FILENAME_LENGTH) {
    return { code: "invalid_filename", message: "The filename is too long." };
  }
  if (
    !ACCEPTED_EXTENSIONS.includes(extensionOf(file.name) as (typeof ACCEPTED_EXTENSIONS)[number])
  ) {
    return {
      code: "unsupported_file_type",
      message: `Only ${ACCEPTED_EXTENSIONS.join(", ")} files can be ingested.`,
    };
  }
  if (file.size === 0) {
    return { code: "empty_file", message: "The file is empty." };
  }
  if (file.size > MAX_UPLOAD_BYTES) {
    return {
      code: "file_too_large",
      message: `The file exceeds the ${formatBytes(MAX_UPLOAD_BYTES)} upload limit.`,
    };
  }
  return null;
}
