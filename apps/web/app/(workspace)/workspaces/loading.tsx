import { SystemState } from "../../../components/system-state";

/** Streaming placeholder while memberships are fetched from the API. */
export default function WorkspacesLoading() {
  return (
    <main className="workspace-main" id="main-content">
      <SystemState
        description="Fetching the workspaces your account is a member of."
        state="loading"
        title="Loading workspaces"
      />
    </main>
  );
}
