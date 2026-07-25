/**
 * Explicit rendering for authorization and availability failures.
 *
 * A refused request must look refused: the visitor sees why, what to do, and
 * the stable code, never a blank page or a silently empty list. Workspace
 * absence and non-membership share one message because the API deliberately
 * does not disclose whether a workspace exists.
 */
import Link from "next/link";

import { errorCodes } from "../lib/contracts";

type AccessNoticeProps = Readonly<{
  code: string;
  message: string;
}>;

type Notice = Readonly<{ heading: string; guidance: string }>;

const notices: Record<string, Notice> = {
  [errorCodes.insufficientRole]: {
    heading: "Access denied",
    guidance: "Your workspace role does not allow this. Ask an owner to raise your role.",
  },
  [errorCodes.cannotManageRole]: {
    heading: "Access denied",
    guidance: "Only an owner can grant or manage this role.",
  },
  [errorCodes.workspaceNotFound]: {
    heading: "Workspace not found",
    guidance: "It does not exist, or you are not a member of it. Choose another workspace.",
  },
  [errorCodes.rateLimited]: {
    heading: "Too many attempts",
    guidance: "Wait a moment before trying again.",
  },
};

const fallback: Notice = {
  heading: "Something went wrong",
  guidance: "The request could not be completed. Try again, or choose another workspace.",
};

export function AccessNotice({ code, message }: AccessNoticeProps) {
  const notice = notices[code] ?? fallback;
  return (
    <section aria-labelledby="access-notice-title" className="access-notice" role="alert">
      <p className="state-label">Request refused</p>
      <h2 id="access-notice-title">{notice.heading}</h2>
      <p>{message}</p>
      <p className="access-guidance">{notice.guidance}</p>
      <p className="feedback-code">Reference: {code}</p>
      <Link className="secondary-button" href="/workspaces">
        Back to workspaces
      </Link>
    </section>
  );
}
