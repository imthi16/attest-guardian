import {
  addMemberAction,
  changeMemberRoleAction,
  createWorkspaceAction,
  removeMemberAction,
  selectWorkspaceAction,
} from "./workspace-actions";
import { addMember, changeMemberRole, createWorkspace, removeMember } from "../lib/attest-api";
import { writeActiveWorkspaceId } from "../lib/session";

vi.mock("../lib/attest-api", () => ({
  addMember: vi.fn(),
  changeMemberRole: vi.fn(),
  createWorkspace: vi.fn(),
  removeMember: vi.fn(),
}));

vi.mock("../lib/session", async () => {
  const actual = await vi.importActual<typeof import("../lib/session")>("../lib/session");
  return { SESSION_EXPIRED: actual.SESSION_EXPIRED, writeActiveWorkspaceId: vi.fn() };
});

vi.mock("next/cache", () => ({ revalidatePath: vi.fn() }));

class RedirectError extends Error {
  constructor(public readonly destination: string) {
    super(`NEXT_REDIRECT:${destination}`);
  }
}

vi.mock("next/navigation", () => ({
  redirect: (destination: string) => {
    throw new RedirectError(destination);
  },
}));

const mockedAddMember = vi.mocked(addMember);
const mockedChangeRole = vi.mocked(changeMemberRole);
const mockedCreateWorkspace = vi.mocked(createWorkspace);
const mockedRemoveMember = vi.mocked(removeMember);
const mockedWriteActive = vi.mocked(writeActiveWorkspaceId);

const WORKSPACE_ID = "11111111-1111-4111-8111-111111111111";
const USER_ID = "22222222-2222-4222-8222-222222222222";
const idle = { status: "idle" } as const;

function formData(entries: Record<string, string>): FormData {
  const data = new FormData();
  for (const [key, value] of Object.entries(entries)) {
    data.set(key, value);
  }
  return data;
}

async function expectRedirect(promise: Promise<unknown>): Promise<string> {
  try {
    await promise;
  } catch (error) {
    if (error instanceof RedirectError) {
      return error.destination;
    }
    throw error;
  }
  throw new Error("expected a redirect");
}

const member = {
  user_id: USER_ID,
  email: "priya@example.com",
  full_name: "Priya S",
  role: "member" as const,
  joined_at: "2026-01-01T00:00:00Z",
};

const failure = (code: string, message: string, status: number) =>
  ({ ok: false, code, message, status }) as const;

beforeEach(() => {
  vi.clearAllMocks();
});

describe("selectWorkspaceAction", () => {
  it("switches the active workspace", async () => {
    const destination = await expectRedirect(
      selectWorkspaceAction(formData({ workspaceId: WORKSPACE_ID })),
    );

    expect(mockedWriteActive).toHaveBeenCalledWith(WORKSPACE_ID);
    expect(destination).toBe(`/workspaces/${WORKSPACE_ID}`);
  });

  it("ignores a workspace identifier that is not a UUID", async () => {
    const destination = await expectRedirect(
      selectWorkspaceAction(formData({ workspaceId: "../../etc/passwd" })),
    );

    expect(mockedWriteActive).not.toHaveBeenCalled();
    expect(destination).toBe("/workspaces");
  });
});

describe("createWorkspaceAction", () => {
  it("creates a workspace and opens it", async () => {
    mockedCreateWorkspace.mockResolvedValue({
      ok: true,
      data: {
        id: WORKSPACE_ID,
        name: "Compliance",
        slug: "compliance-a1b2c3",
        created_at: "2026-01-01T00:00:00Z",
        role: "owner",
      },
    });

    const destination = await expectRedirect(
      createWorkspaceAction(idle, formData({ name: " Compliance " })),
    );

    expect(mockedCreateWorkspace).toHaveBeenCalledWith("Compliance");
    expect(mockedWriteActive).toHaveBeenCalledWith(WORKSPACE_ID);
    expect(destination).toBe(`/workspaces/${WORKSPACE_ID}`);
  });

  it("rejects an empty workspace name before calling the API", async () => {
    const state = await createWorkspaceAction(idle, formData({ name: "   " }));

    expect(state.fieldErrors).toEqual({ name: "Enter a workspace name." });
    expect(mockedCreateWorkspace).not.toHaveBeenCalled();
  });

  it("surfaces slug_already_exists", async () => {
    mockedCreateWorkspace.mockResolvedValue(
      failure("slug_already_exists", "A workspace with this slug already exists.", 409),
    );

    const state = await createWorkspaceAction(idle, formData({ name: "Compliance" }));

    expect(state).toMatchObject({ code: "slug_already_exists", status: "error" });
  });
});

describe("addMemberAction", () => {
  it("adds a member", async () => {
    mockedAddMember.mockResolvedValue({ ok: true, data: member });

    const state = await addMemberAction(
      idle,
      formData({ email: " priya@example.com ", role: "member", workspaceId: WORKSPACE_ID }),
    );

    expect(mockedAddMember).toHaveBeenCalledWith({
      email: "priya@example.com",
      role: "member",
      workspaceId: WORKSPACE_ID,
    });
    expect(state).toEqual({ message: "priya@example.com was added.", status: "success" });
  });

  it("surfaces user_not_found", async () => {
    mockedAddMember.mockResolvedValue(
      failure("user_not_found", "No account exists for this email.", 404),
    );

    const state = await addMemberAction(
      idle,
      formData({ email: "absent@example.com", role: "member", workspaceId: WORKSPACE_ID }),
    );

    expect(state).toMatchObject({ code: "user_not_found", status: "error" });
  });

  it("surfaces member_already_exists", async () => {
    mockedAddMember.mockResolvedValue(
      failure("member_already_exists", "This user is already a member.", 409),
    );

    const state = await addMemberAction(
      idle,
      formData({ email: "priya@example.com", role: "member", workspaceId: WORKSPACE_ID }),
    );

    expect(state).toMatchObject({ code: "member_already_exists", status: "error" });
  });

  it("surfaces cannot_manage_role", async () => {
    mockedAddMember.mockResolvedValue(
      failure("cannot_manage_role", "Your role cannot grant the requested role.", 403),
    );

    const state = await addMemberAction(
      idle,
      formData({ email: "priya@example.com", role: "owner", workspaceId: WORKSPACE_ID }),
    );

    expect(state).toMatchObject({ code: "cannot_manage_role", status: "error" });
  });

  it("rejects an unknown role without calling the API", async () => {
    const state = await addMemberAction(
      idle,
      formData({ email: "priya@example.com", role: "superuser", workspaceId: WORKSPACE_ID }),
    );

    expect(state.status).toBe("error");
    expect(mockedAddMember).not.toHaveBeenCalled();
  });

  it("sends an expired session back to the login page", async () => {
    mockedAddMember.mockResolvedValue(failure("session_expired", "Your session expired.", 401));

    const destination = await expectRedirect(
      addMemberAction(
        idle,
        formData({ email: "priya@example.com", role: "member", workspaceId: WORKSPACE_ID }),
      ),
    );

    expect(destination).toBe("/login?expired=1");
  });
});

describe("changeMemberRoleAction", () => {
  it("changes a member role", async () => {
    mockedChangeRole.mockResolvedValue({ ok: true, data: { ...member, role: "admin" } });

    const state = await changeMemberRoleAction(
      idle,
      formData({ role: "admin", userId: USER_ID, workspaceId: WORKSPACE_ID }),
    );

    expect(mockedChangeRole).toHaveBeenCalledWith({
      role: "admin",
      userId: USER_ID,
      workspaceId: WORKSPACE_ID,
    });
    expect(state).toEqual({ message: "The member role was updated.", status: "success" });
  });

  it("surfaces last_owner", async () => {
    mockedChangeRole.mockResolvedValue(
      failure("last_owner", "A workspace must keep at least one owner.", 409),
    );

    const state = await changeMemberRoleAction(
      idle,
      formData({ role: "viewer", userId: USER_ID, workspaceId: WORKSPACE_ID }),
    );

    expect(state).toMatchObject({ code: "last_owner", status: "error" });
  });

  it("rejects a malformed member identifier", async () => {
    const state = await changeMemberRoleAction(
      idle,
      formData({ role: "viewer", userId: "not-a-uuid", workspaceId: WORKSPACE_ID }),
    );

    expect(state.fieldErrors).toEqual({ userId: "Select a valid member." });
    expect(mockedChangeRole).not.toHaveBeenCalled();
  });
});

describe("removeMemberAction", () => {
  it("removes a member after confirmation", async () => {
    mockedRemoveMember.mockResolvedValue({ ok: true, data: null });

    const state = await removeMemberAction(
      idle,
      formData({ userId: USER_ID, workspaceId: WORKSPACE_ID }),
    );

    expect(mockedRemoveMember).toHaveBeenCalledWith({
      userId: USER_ID,
      workspaceId: WORKSPACE_ID,
    });
    expect(state).toEqual({ message: "The member was removed.", status: "success" });
  });

  it("surfaces member_not_found", async () => {
    mockedRemoveMember.mockResolvedValue(
      failure("member_not_found", "This user is not a member of the workspace.", 404),
    );

    const state = await removeMemberAction(
      idle,
      formData({ userId: USER_ID, workspaceId: WORKSPACE_ID }),
    );

    expect(state).toMatchObject({ code: "member_not_found", status: "error" });
  });

  it("rejects a malformed workspace identifier", async () => {
    const state = await removeMemberAction(
      idle,
      formData({ userId: USER_ID, workspaceId: "1; DROP TABLE memberships" }),
    );

    expect(state.status).toBe("error");
    expect(mockedRemoveMember).not.toHaveBeenCalled();
  });
});
