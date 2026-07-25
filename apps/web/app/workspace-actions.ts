/**
 * Server actions for workspace selection and member management.
 *
 * Every action goes through `authorizedRequest`, so the API applies the role
 * matrix and tenant isolation; the UI only relays the stable error code. An
 * expired session redirects to login rather than rendering a dead page.
 */
"use server";

import { redirect } from "next/navigation";
import { revalidatePath } from "next/cache";
import { z } from "zod";

import { addMember, changeMemberRole, createWorkspace, removeMember } from "../lib/attest-api";
import { membershipRoleSchema } from "../lib/contracts";
import { SESSION_EXPIRED, writeActiveWorkspaceId, type AuthorizedResult } from "../lib/session";
import { fieldErrorsFrom, invalidInput, type FormState } from "./form-state";

/** An expired session cannot be repaired in place; restart the sign-in flow. */
function relayFailure<T>(result: AuthorizedResult<T>): FormState {
  if (result.ok) {
    return { status: "success" };
  }
  if (result.code === SESSION_EXPIRED) {
    redirect("/login?expired=1");
  }
  return { code: result.code, message: result.message, status: "error" };
}

const workspaceIdSchema = z.string().uuid("Select a valid workspace.");

const createWorkspaceSchema = z.object({
  name: z.string().min(1, "Enter a workspace name.").max(255, "Name is too long."),
});

const addMemberSchema = z.object({
  email: z.string().email("Enter a valid email address."),
  role: membershipRoleSchema,
  workspaceId: workspaceIdSchema,
});

const changeRoleSchema = z.object({
  role: membershipRoleSchema,
  userId: z.string().uuid("Select a valid member."),
  workspaceId: workspaceIdSchema,
});

const removeMemberSchema = z.object({
  userId: z.string().uuid("Select a valid member."),
  workspaceId: workspaceIdSchema,
});

/** Remember the chosen workspace, then open it. */
export async function selectWorkspaceAction(formData: FormData): Promise<void> {
  const parsed = workspaceIdSchema.safeParse(String(formData.get("workspaceId") ?? ""));
  if (!parsed.success) {
    redirect("/workspaces");
  }
  await writeActiveWorkspaceId(parsed.data);
  redirect(`/workspaces/${parsed.data}`);
}

export async function createWorkspaceAction(
  _previous: FormState,
  formData: FormData,
): Promise<FormState> {
  const parsed = createWorkspaceSchema.safeParse({
    name: String(formData.get("name") ?? "").trim(),
  });
  if (!parsed.success) {
    return invalidInput(fieldErrorsFrom(parsed.error));
  }

  const created = await createWorkspace(parsed.data.name);
  const state = relayFailure(created);
  if (state.status === "error") {
    return state;
  }
  if (created.ok) {
    await writeActiveWorkspaceId(created.data.id);
    revalidatePath("/workspaces");
    redirect(`/workspaces/${created.data.id}`);
  }
  return state;
}

export async function addMemberAction(
  _previous: FormState,
  formData: FormData,
): Promise<FormState> {
  const parsed = addMemberSchema.safeParse({
    email: String(formData.get("email") ?? "").trim(),
    role: String(formData.get("role") ?? ""),
    workspaceId: String(formData.get("workspaceId") ?? ""),
  });
  if (!parsed.success) {
    return invalidInput(fieldErrorsFrom(parsed.error));
  }

  const state = relayFailure(await addMember(parsed.data));
  if (state.status === "success") {
    revalidatePath(`/workspaces/${parsed.data.workspaceId}/members`);
    return { message: `${parsed.data.email} was added.`, status: "success" };
  }
  return state;
}

export async function changeMemberRoleAction(
  _previous: FormState,
  formData: FormData,
): Promise<FormState> {
  const parsed = changeRoleSchema.safeParse({
    role: String(formData.get("role") ?? ""),
    userId: String(formData.get("userId") ?? ""),
    workspaceId: String(formData.get("workspaceId") ?? ""),
  });
  if (!parsed.success) {
    return invalidInput(fieldErrorsFrom(parsed.error));
  }

  const state = relayFailure(await changeMemberRole(parsed.data));
  if (state.status === "success") {
    revalidatePath(`/workspaces/${parsed.data.workspaceId}/members`);
    return { message: "The member role was updated.", status: "success" };
  }
  return state;
}

export async function removeMemberAction(
  _previous: FormState,
  formData: FormData,
): Promise<FormState> {
  const parsed = removeMemberSchema.safeParse({
    userId: String(formData.get("userId") ?? ""),
    workspaceId: String(formData.get("workspaceId") ?? ""),
  });
  if (!parsed.success) {
    return invalidInput(fieldErrorsFrom(parsed.error));
  }

  const state = relayFailure(await removeMember(parsed.data));
  if (state.status === "success") {
    revalidatePath(`/workspaces/${parsed.data.workspaceId}/members`);
    return { message: "The member was removed.", status: "success" };
  }
  return state;
}
