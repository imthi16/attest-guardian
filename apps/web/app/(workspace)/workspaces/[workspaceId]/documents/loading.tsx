import { SystemState } from "../../../../../components/system-state";

/** Streaming placeholder while the library is fetched from the API. */
export default function DocumentsLoading() {
  return (
    <main className="workspace-main" id="main-content">
      <SystemState
        description="Fetching the documents you are allowed to see in this workspace."
        state="loading"
        title="Loading documents"
      />
    </main>
  );
}
