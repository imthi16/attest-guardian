import { SystemState } from "../../../../../../components/system-state";

/** Streaming placeholder while one thread and its evidence are fetched. */
export default function ConversationLoading() {
  return (
    <main className="workspace-main" id="main-content">
      <SystemState
        description="Fetching the questions, answers, and citations in this thread."
        state="loading"
        title="Loading conversation"
      />
    </main>
  );
}
