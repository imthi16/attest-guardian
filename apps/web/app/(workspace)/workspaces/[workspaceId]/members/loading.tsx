import { SystemState } from "../../../../../components/system-state";

/** Streaming placeholder while the roster is fetched from the API. */
export default function MembersLoading() {
  return (
    <main className="workspace-main" id="main-content">
      <SystemState
        description="Fetching the workspace roster and your role."
        state="loading"
        title="Loading members"
      />
    </main>
  );
}
