/**
 * The workspace document library as a table.
 *
 * Every row states the document's processing state explicitly, because a
 * document that is queued, failed, quarantined, or archived cannot be cited and
 * must not look like one that can. Titles and filenames come from uploaded
 * files and are rendered as text children only — never as markup, and never as
 * a preview of the file's contents.
 *
 * At phone widths the table collapses into labelled cards, so every data cell
 * carries the header text it stands in for.
 */
import Link from "next/link";

import { DocumentControls, type DocumentCapabilities } from "./document-controls";
import { StatusBadge } from "./ingestion-state";
import { formatBytes } from "../lib/upload-rules";
import type { Document } from "../lib/contracts";

type DocumentListProps = Readonly<{
  capabilities: DocumentCapabilities;
  documents: readonly Document[];
  workspaceId: string;
}>;

export function DocumentList({ capabilities, documents, workspaceId }: DocumentListProps) {
  return (
    <table className="document-table">
      <caption className="visually-hidden">
        Documents in this workspace, their processing state, and available actions
      </caption>
      <thead>
        <tr>
          <th scope="col">Document</th>
          <th scope="col">State</th>
          <th scope="col">Size</th>
          <th scope="col">Actions</th>
        </tr>
      </thead>
      <tbody>
        {documents.map((entry) => (
          <tr data-archived={entry.archived_at !== null} key={entry.id}>
            <td data-label="Document">
              <Link
                className="document-title"
                href={`/workspaces/${workspaceId}/documents/${entry.id}`}
              >
                {entry.title}
              </Link>
              <span className="document-filename">{entry.source_filename}</span>
            </td>
            <td data-label="State">
              <StatusBadge archived={entry.archived_at !== null} status={entry.status} />
            </td>
            <td data-label="Size">{formatBytes(entry.size_bytes)}</td>
            <td data-label="Actions">
              <DocumentControls
                capabilities={capabilities}
                entry={entry}
                workspaceId={workspaceId}
              />
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
