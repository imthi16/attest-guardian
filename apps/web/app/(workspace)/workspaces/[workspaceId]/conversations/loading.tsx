import { SystemState } from "../../../../../components/system-state";

/** Streaming placeholder while the workspace's threads are fetched. */
export default function ConversationsLoading() {
  return (
    <main className="workspace-main" id="main-content">
      <SystemState
        description="Fetching the questions asked in this workspace."
        state="loading"
        title="Loading conversations"
      />
    </main>
  );
}
