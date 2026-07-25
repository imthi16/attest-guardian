#!/usr/bin/env python3
"""In-memory stand-in for the Attest Guardian API, for viewing the UI locally.

This exists only so the Next.js client can be exercised on a machine without
Docker, PostgreSQL, Redis, or MinIO. It implements the same request and response
contracts as `apps/api` for the auth and workspace endpoints, including the
stable `{"detail": {"code", "message"}}` error envelope and the role matrix from
`apps/api/app/auth/permissions.py`, so the UI behaves exactly as it does against
the real service.

It is NOT the product and must never be deployed: state is a process-local dict,
passwords are compared in plaintext, and tokens are counters. Run the real API
with `make infra-up && make dev-api` once Docker is available.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

PORT = 8000

# Role matrix mirrored from apps/api/app/auth/permissions.py.
MANAGEABLE: dict[str, set[str]] = {
    "owner": {"owner", "admin", "member", "viewer"},
    "admin": {"member", "viewer"},
    "member": set(),
    "viewer": set(),
}
CAN_MANAGE_MEMBERS = {"owner", "admin"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Store:
    """Process-local state, seeded with a workspace you can sign into."""

    def __init__(self) -> None:
        self.users: dict[str, dict[str, Any]] = {}
        self.passwords: dict[str, str] = {}
        self.workspaces: dict[str, dict[str, Any]] = {}
        self.members: dict[str, dict[str, str]] = {}  # workspace_id -> user_id -> role
        self.access: dict[str, str] = {}  # access token -> user_id
        self.refresh: dict[str, str] = {}  # refresh token -> user_id
        self.counter = 0
        self._seed()

    def add_user(self, email: str, full_name: str, password: str) -> dict[str, Any]:
        user = {
            "id": str(uuid.uuid4()),
            "email": email.lower(),
            "full_name": full_name,
            "is_active": True,
            "created_at": now(),
        }
        self.users[user["id"]] = user
        self.passwords[user["email"]] = password
        return user

    def user_by_email(self, email: str) -> dict[str, Any] | None:
        for user in self.users.values():
            if user["email"] == email.lower():
                return user
        return None

    def _seed(self) -> None:
        ravi = self.add_user("ravi@example.com", "Ravi Kumar", "demo-password-1")
        priya = self.add_user("priya@example.com", "Priya Selvam", "demo-password-1")
        arun = self.add_user("arun@example.com", "Arun Balaji", "demo-password-1")
        meena = self.add_user("meena@example.com", "Meena Lakshmi", "demo-password-1")

        compliance = self.add_workspace("Tamil Nadu Compliance", ravi["id"])
        self.members[compliance["id"]].update(
            {priya["id"]: "admin", arun["id"]: "member", meena["id"]: "viewer"}
        )
        audit = self.add_workspace("Statutory Audit Archive", priya["id"])
        self.members[audit["id"]][ravi["id"]] = "viewer"

    def add_workspace(self, name: str, owner_id: str) -> dict[str, Any]:
        slug_stem = re.sub(r"-{2,}", "-", re.sub(r"[^a-z0-9-]+", "-", name.lower())).strip("-")
        workspace = {
            "id": str(uuid.uuid4()),
            "name": name,
            "slug": f"{slug_stem or 'workspace'}-{uuid.uuid4().hex[:6]}",
            "created_at": now(),
        }
        self.workspaces[workspace["id"]] = workspace
        self.members[workspace["id"]] = {owner_id: "owner"}
        return workspace

    def issue_tokens(self, user_id: str) -> dict[str, Any]:
        self.counter += 1
        access = f"access-{self.counter}"
        refresh = f"refresh-{self.counter}"
        self.access[access] = user_id
        self.refresh[refresh] = user_id
        return {
            "access_token": access,
            "refresh_token": refresh,
            "token_type": "bearer",
            "expires_in": 900,
        }


STORE = Store()

ERRORS = {
    "email_already_registered": (409, "An account with this email already exists."),
    "invalid_credentials": (401, "The email or password is incorrect."),
    "invalid_refresh_token": (401, "The refresh token is invalid or expired."),
    "not_authenticated": (401, "A valid bearer access token is required."),
    "workspace_not_found": (404, "The workspace does not exist or you are not a member."),
    "insufficient_role": (403, "Your workspace role does not allow this action."),
    "cannot_manage_role": (403, "Your workspace role cannot grant or manage the requested role."),
    "user_not_found": (404, "No account exists for this email."),
    "member_not_found": (404, "This user is not a member of the workspace."),
    "member_already_exists": (409, "This user is already a member of the workspace."),
    "last_owner": (409, "A workspace must keep at least one owner."),
    "not_found": (404, "Not found."),
}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
        print(f"  api  {fmt % args}", flush=True)

    # ---------------------------------------------------------------- helpers
    def send_json(self, code: int, payload: Any) -> None:
        raw = b"" if payload is None else json.dumps(payload).encode()
        self.send_response(code)
        if raw:
            self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        if raw:
            self.wfile.write(raw)

    def fail(self, code_name: str) -> None:
        status, message = ERRORS[code_name]
        self.send_json(status, {"detail": {"code": code_name, "message": message}})

    def body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        try:
            return json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return {}

    def caller(self) -> dict[str, Any] | None:
        header = self.headers.get("Authorization") or ""
        token = header.removeprefix("Bearer ").strip()
        user_id = STORE.access.get(token)
        return STORE.users.get(user_id) if user_id else None

    def context(self, workspace_id: str) -> tuple[dict[str, Any], str] | None:
        """Membership proves visibility; non-members get the same 404 as absent."""
        user = self.caller()
        if user is None or workspace_id not in STORE.workspaces:
            return None
        role = STORE.members.get(workspace_id, {}).get(user["id"])
        return (user, role) if role else None

    def member_payload(self, workspace_id: str, user_id: str) -> dict[str, Any]:
        user = STORE.users[user_id]
        return {
            "user_id": user_id,
            "email": user["email"],
            "full_name": user["full_name"],
            "role": STORE.members[workspace_id][user_id],
            "joined_at": user["created_at"],
        }

    # ------------------------------------------------------------------ POST
    def do_POST(self) -> None:  # noqa: N802
        path = self.path
        data = self.body()

        if path == "/api/v1/auth/register":
            email = str(data.get("email", "")).strip().lower()
            if STORE.user_by_email(email) is not None:
                return self.fail("email_already_registered")
            user = STORE.add_user(email, str(data.get("full_name", "")), str(data.get("password", "")))
            return self.send_json(201, user)

        if path == "/api/v1/auth/login":
            email = str(data.get("email", "")).strip().lower()
            user = STORE.user_by_email(email)
            if user is None or STORE.passwords.get(email) != data.get("password"):
                return self.fail("invalid_credentials")
            return self.send_json(200, STORE.issue_tokens(user["id"]))

        if path == "/api/v1/auth/refresh":
            token = str(data.get("refresh_token", ""))
            user_id = STORE.refresh.pop(token, None)
            if user_id is None:
                return self.fail("invalid_refresh_token")
            return self.send_json(200, STORE.issue_tokens(user_id))

        if path == "/api/v1/auth/logout":
            STORE.refresh.pop(str(data.get("refresh_token", "")), None)
            return self.send_json(204, None)

        if path == "/api/v1/workspaces":
            user = self.caller()
            if user is None:
                return self.fail("not_authenticated")
            workspace = STORE.add_workspace(str(data.get("name", "Workspace")), user["id"])
            return self.send_json(201, {**workspace, "role": "owner"})

        match = re.fullmatch(r"/api/v1/workspaces/([^/]+)/members", path)
        if match:
            found = self.context(match.group(1))
            if found is None:
                return self.fail("workspace_not_found")
            _, actor_role = found
            workspace_id = match.group(1)
            if actor_role not in CAN_MANAGE_MEMBERS:
                return self.fail("insufficient_role")
            role = str(data.get("role", "member"))
            if role not in MANAGEABLE[actor_role]:
                return self.fail("cannot_manage_role")
            invitee = STORE.user_by_email(str(data.get("email", "")))
            if invitee is None:
                return self.fail("user_not_found")
            if invitee["id"] in STORE.members[workspace_id]:
                return self.fail("member_already_exists")
            STORE.members[workspace_id][invitee["id"]] = role
            return self.send_json(201, self.member_payload(workspace_id, invitee["id"]))

        return self.fail("not_found")

    # ------------------------------------------------------------------- GET
    def do_GET(self) -> None:  # noqa: N802
        path = self.path

        if path in {"/health", "/api/v1/health"}:
            return self.send_json(200, {"status": "ok", "service": "attest-api-demo"})

        user = self.caller()
        if user is None:
            return self.fail("not_authenticated")

        if path == "/api/v1/auth/me":
            return self.send_json(200, user)

        if path == "/api/v1/workspaces":
            mine = [
                {**STORE.workspaces[wid], "role": roles[user["id"]]}
                for wid, roles in STORE.members.items()
                if user["id"] in roles
            ]
            return self.send_json(200, mine)

        match = re.fullmatch(r"/api/v1/workspaces/([^/]+)", path)
        if match:
            found = self.context(match.group(1))
            if found is None:
                return self.fail("workspace_not_found")
            return self.send_json(200, {**STORE.workspaces[match.group(1)], "role": found[1]})

        match = re.fullmatch(r"/api/v1/workspaces/([^/]+)/members", path)
        if match:
            workspace_id = match.group(1)
            if self.context(workspace_id) is None:
                return self.fail("workspace_not_found")
            return self.send_json(
                200,
                [self.member_payload(workspace_id, uid) for uid in STORE.members[workspace_id]],
            )

        return self.fail("not_found")

    # ----------------------------------------------------------------- PATCH
    def do_PATCH(self) -> None:  # noqa: N802
        match = re.fullmatch(r"/api/v1/workspaces/([^/]+)/members/([^/]+)", self.path)
        if not match:
            return self.fail("not_found")
        workspace_id, target_id = match.groups()
        found = self.context(workspace_id)
        if found is None:
            return self.fail("workspace_not_found")
        _, actor_role = found
        if actor_role not in CAN_MANAGE_MEMBERS:
            return self.fail("insufficient_role")
        roles = STORE.members[workspace_id]
        if target_id not in roles:
            return self.fail("member_not_found")
        new_role = str(self.body().get("role", ""))
        if roles[target_id] not in MANAGEABLE[actor_role] or new_role not in MANAGEABLE[actor_role]:
            return self.fail("cannot_manage_role")
        owners = sum(1 for role in roles.values() if role == "owner")
        if roles[target_id] == "owner" and new_role != "owner" and owners == 1:
            return self.fail("last_owner")
        roles[target_id] = new_role
        return self.send_json(200, self.member_payload(workspace_id, target_id))

    # ---------------------------------------------------------------- DELETE
    def do_DELETE(self) -> None:  # noqa: N802
        match = re.fullmatch(r"/api/v1/workspaces/([^/]+)/members/([^/]+)", self.path)
        if not match:
            return self.fail("not_found")
        workspace_id, target_id = match.groups()
        found = self.context(workspace_id)
        if found is None:
            return self.fail("workspace_not_found")
        _, actor_role = found
        if actor_role not in CAN_MANAGE_MEMBERS:
            return self.fail("insufficient_role")
        roles = STORE.members[workspace_id]
        if target_id not in roles:
            return self.fail("member_not_found")
        if roles[target_id] not in MANAGEABLE[actor_role]:
            return self.fail("cannot_manage_role")
        owners = sum(1 for role in roles.values() if role == "owner")
        if roles[target_id] == "owner" and owners == 1:
            return self.fail("last_owner")
        del roles[target_id]
        return self.send_json(204, None)


if __name__ == "__main__":
    print(f"Demo API (in-memory, not the product) on http://127.0.0.1:{PORT}", flush=True)
    print("Sign in with ravi@example.com / demo-password-1", flush=True)
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
