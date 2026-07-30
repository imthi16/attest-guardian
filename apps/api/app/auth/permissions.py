"""The workspace role matrix.

One place defines what each role may do; routes and services ask questions
about it instead of comparing roles ad hoc. `VIEWER` is the read-only
reviewer role: it can see the workspace and query evidence but changes
nothing. Member management is deliberately asymmetric: admins run the
day-to-day roster but cannot touch or mint privileged roles.

Document lifecycle is split in two: uploading (and retrying a failed
ingestion, which only reprocesses bytes already accepted) is day-to-day
member work, while archiving, restoring, and deleting withdraw or destroy
evidence and are therefore reserved for owners and admins.

Conversations split the same way, and `QUERY` deliberately does not cover
them. `QUERY` is the read-only right to ask a question and read the answer,
which is why a viewer holds it; writing a durable thread, recording feedback,
or deleting answer history are changes to workspace state, so they need
`CONVERSE` (members and up) and `MANAGE_CONVERSATIONS` (owners and admins) —
otherwise a "reads only, changes nothing" role could delete another member's
evidence-backed history.
"""

import enum

from app.db.models.enums import MembershipRole


class WorkspaceAction(enum.Enum):
    """A capability a workspace member may hold."""

    VIEW = "view"
    QUERY = "query"
    CONVERSE = "converse"
    MANAGE_CONVERSATIONS = "manage_conversations"
    UPLOAD_DOCUMENTS = "upload_documents"
    MANAGE_DOCUMENTS = "manage_documents"
    MANAGE_MEMBERS = "manage_members"


_ROLE_ACTIONS: dict[MembershipRole, frozenset[WorkspaceAction]] = {
    MembershipRole.OWNER: frozenset(WorkspaceAction),
    MembershipRole.ADMIN: frozenset(WorkspaceAction),
    MembershipRole.MEMBER: frozenset(
        {
            WorkspaceAction.VIEW,
            WorkspaceAction.QUERY,
            WorkspaceAction.CONVERSE,
            WorkspaceAction.UPLOAD_DOCUMENTS,
        }
    ),
    MembershipRole.VIEWER: frozenset({WorkspaceAction.VIEW, WorkspaceAction.QUERY}),
}

# Roles an actor may grant, change, or remove. Only owners handle
# privileged roles, so an admin can never lock owners out or escalate.
_MANAGEABLE_ROLES: dict[MembershipRole, frozenset[MembershipRole]] = {
    MembershipRole.OWNER: frozenset(MembershipRole),
    MembershipRole.ADMIN: frozenset({MembershipRole.MEMBER, MembershipRole.VIEWER}),
    MembershipRole.MEMBER: frozenset(),
    MembershipRole.VIEWER: frozenset(),
}


def allows(role: MembershipRole, action: WorkspaceAction) -> bool:
    """Whether a role holds a capability."""
    return action in _ROLE_ACTIONS[role]


def can_manage_role(actor: MembershipRole, target: MembershipRole) -> bool:
    """Whether an actor may grant `target` or manage a member holding it."""
    return target in _MANAGEABLE_ROLES[actor]
