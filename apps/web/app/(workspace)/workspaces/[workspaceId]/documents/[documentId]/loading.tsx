import { SystemState } from "../../../../../../components/system-state";

/** Streaming placeholder while one document and its progress are fetched. */
export default function DocumentDetailLoading() {
  return (
    <main className="workspace-main" id="main-content">
      <SystemState
        description="Fetching the document's details and its current processing state."
        state="loading"
        title="Loading document"
      />
    </main>
  );
}
