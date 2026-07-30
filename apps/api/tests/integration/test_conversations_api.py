"""Conversation threads, SSE streaming, and reviewer feedback over the real stack.

Requires `make infra-up` (or the CI containers). Covers what persistence adds on
top of the one-shot answer endpoint: a durable thread with citations and claim
verdicts, the streaming route's equivalence to the JSON one, tenant isolation,
and feedback that revises rather than accumulates.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator

import httpx
import pytest
from app.config import Settings
from app.db.models.conversations import Message, MessageFeedback
from app.db.models.documents import Chunk
from app.db.models.enums import DocumentStatus, MessageRole
from app.db.models.identity import User, Workspace
from app.db.models.operations import AuditLog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration import factories
from tests.integration.apptools import Account, build_client, make_account

EVIDENCE = "The invoice payment is due within thirty days of receipt."


def settings() -> Settings:
    return Settings(auth_rate_limit_attempts=1000)


@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[httpx.AsyncClient]:
    async with build_client(db_session, settings()) as instance:
        yield instance


async def make_workspace(client: httpx.AsyncClient, account: Account) -> str:
    response = await client.post(
        "/api/v1/workspaces", json={"name": "Threads"}, headers=account.headers
    )
    assert response.status_code == 201, response.text
    workspace_id: str = response.json()["id"]
    return workspace_id


async def seed_chunk(
    session: AsyncSession,
    *,
    workspace: Workspace,
    owner: User,
    content: str = EVIDENCE,
) -> Chunk:
    document = await factories.make_document(session, workspace, owner, status=DocumentStatus.READY)
    version = await factories.make_version(session, document)
    chunk = Chunk(
        workspace_id=workspace.id,
        document_version_id=version.id,
        chunk_index=0,
        content=content,
        content_hash=f"{1:064x}",
        page_number=1,
        char_start=0,
        char_end=len(content),
        language="eng",
    )
    session.add(chunk)
    await session.flush()
    return chunk


async def start_conversation(client: httpx.AsyncClient, account: Account, workspace_id: str) -> str:
    created = await client.post(
        f"/api/v1/workspaces/{workspace_id}/conversations",
        json={"title": "Invoice terms"},
        headers=account.headers,
    )
    assert created.status_code == 201, created.text
    conversation_id: str = created.json()["id"]
    return conversation_id


def error_code(response: httpx.Response) -> str:
    code: str = response.json()["detail"]["code"]
    return code


def sse_events(body: str) -> list[tuple[str, dict[str, object]]]:
    """Parse an SSE body into `(event, data)` pairs."""
    events: list[tuple[str, dict[str, object]]] = []
    for frame in body.split("\n\n"):
        if not frame.strip():
            continue
        name = ""
        payload = ""
        for line in frame.splitlines():
            if line.startswith("event: "):
                name = line.removeprefix("event: ")
            elif line.startswith("data: "):
                payload = line.removeprefix("data: ")
        events.append((name, json.loads(payload)))
    return events


async def test_asking_persists_the_question_the_answer_and_its_evidence(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    """A thread must outlive the response that produced it.

    The point of persistence is that the evidence behind an answer stays
    auditable later, so the citation and claim verdict are checked on the stored
    rows rather than only in the response body.
    """
    owner = await make_account(client, "c-owner@example.com")
    workspace_id = await make_workspace(client, owner)
    workspace = await db_session.get(Workspace, uuid.UUID(workspace_id))
    assert workspace is not None
    user = (await db_session.scalars(select(User).where(User.email == owner.email))).one()
    chunk = await seed_chunk(db_session, workspace=workspace, owner=user)

    conversation_id = await start_conversation(client, owner, workspace_id)
    answered = await client.post(
        f"/api/v1/workspaces/{workspace_id}/conversations/{conversation_id}/messages",
        json={"question": "When is the invoice payment due?"},
        headers=owner.headers,
    )
    assert answered.status_code == 200, answered.text
    body = answered.json()
    assert body["outcome"] == "answered"
    assert body["claims"]

    detail = await client.get(
        f"/api/v1/workspaces/{workspace_id}/conversations/{conversation_id}",
        headers=owner.headers,
    )
    assert detail.status_code == 200, detail.text
    messages = detail.json()["messages"]
    assert [message["role"] for message in messages] == ["user", "assistant"]

    question, answer = messages
    # Every representation of the query is kept, so a Tanglish question could be
    # re-run later without guessing what was meant.
    assert question["content"] == "When is the invoice payment due?"
    assert question["normalized_content"]
    assert question["transliterated_content"]
    assert question["language"] == "eng"

    assert answer["answer_status"] == "answered"
    assert answer["citations"], "a grounded answer must persist its evidence"
    assert answer["citations"][0]["chunk_id"] == str(chunk.id)
    assert answer["citations"][0]["quote_text"] in EVIDENCE
    assert answer["claims"][0]["verdict"] == "supported"
    assert answer["claims"][0]["verifier"]

    # The stored turn must say what the live response said, not a reduced
    # version of it: the decision and confidence are the answer's verdict, and a
    # reader of the thread has no other way to recover them.
    assert answer["decision"] == body["decision"]
    assert answer["decision_reason"] == body["decision_reason"]
    assert answer["confidence"] == pytest.approx(body["confidence"])
    assert answer["abstention_reason"] is None

    # A stored citation must be resolvable, or the evidence behind an answer is
    # only reachable while the response that produced it is still on screen.
    resolved = await client.post(
        f"/api/v1/workspaces/{workspace_id}/citations/resolve",
        json={
            "document_version_id": answer["citations"][0]["document_version_id"],
            "chunk_id": answer["citations"][0]["chunk_id"],
            "quote": answer["citations"][0]["quote_text"],
            "quote_char_start": answer["citations"][0]["quote_start"],
            "quote_char_end": answer["citations"][0]["quote_end"],
        },
        headers=owner.headers,
    )
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["supporting_text"] == answer["citations"][0]["quote_text"]

    # A user turn carries no verdict of its own.
    assert question["decision"] is None
    assert question["confidence"] is None


async def test_an_abstention_is_recorded_rather_than_dropped(
    client: httpx.AsyncClient,
) -> None:
    """An abstention is a real answer about the evidence, not a non-event.

    And it must record *which* abstention it was. Three different decisions all
    report `answer_status: "abstained"` — no usable evidence, a question needing
    clarification, and evidence that contradicts itself — so a thread keeping
    only the status could not tell a reader whether a human had been asked to
    look at something.
    """
    owner = await make_account(client, "c-empty@example.com")
    workspace_id = await make_workspace(client, owner)
    conversation_id = await start_conversation(client, owner, workspace_id)

    answered = await client.post(
        f"/api/v1/workspaces/{workspace_id}/conversations/{conversation_id}/messages",
        json={"question": "What does the contract say about termination?"},
        headers=owner.headers,
    )
    assert answered.status_code == 200, answered.text
    body = answered.json()
    assert body["abstained"] is True

    detail = await client.get(
        f"/api/v1/workspaces/{workspace_id}/conversations/{conversation_id}",
        headers=owner.headers,
    )
    messages = detail.json()["messages"]
    assert [message["role"] for message in messages] == ["user", "assistant"]
    assert messages[1]["answer_status"] == "abstained"
    assert messages[1]["citations"] == []
    assert messages[1]["claims"] == []

    assert messages[1]["abstention_reason"] == body["abstention_reason"]
    assert messages[1]["decision"] == body["decision"]
    assert messages[1]["decision_reason"] == body["decision_reason"]
    # Zero, not null: the pipeline reports no confidence in a withheld answer,
    # which is a different statement from having no opinion recorded.
    assert messages[1]["confidence"] == pytest.approx(0.0)


async def test_streaming_reports_stages_and_matches_the_json_route(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Streaming must not be a second, less-checked way to get an answer."""
    owner = await make_account(client, "c-stream@example.com")
    workspace_id = await make_workspace(client, owner)
    workspace = await db_session.get(Workspace, uuid.UUID(workspace_id))
    assert workspace is not None
    user = (await db_session.scalars(select(User).where(User.email == owner.email))).one()
    await seed_chunk(db_session, workspace=workspace, owner=user)

    conversation_id = await start_conversation(client, owner, workspace_id)
    streamed = await client.post(
        f"/api/v1/workspaces/{workspace_id}/conversations/{conversation_id}/messages/stream",
        json={"question": "When is the invoice payment due?"},
        headers=owner.headers,
    )
    assert streamed.status_code == 200, streamed.text
    assert streamed.headers["content-type"].startswith("text/event-stream")
    # Answers are tenant content and must never be cached or proxy-buffered.
    assert streamed.headers["cache-control"] == "no-store"
    assert streamed.headers["x-accel-buffering"] == "no"

    events = sse_events(streamed.text)
    names = [name for name, _ in events]
    stages = [str(data["stage"]) for name, data in events if name == "stage"]
    assert stages[:3] == ["authorize", "analyze", "retrieve"]
    # Exactly one answer, at the end: a partial state is never a usable answer.
    assert names.count("answer") == 1
    assert names[-1] == "answer"
    assert "error" not in names

    payload = events[-1][1]
    assert payload["outcome"] == "answered"
    assert payload["claims"]
    assert payload["message_id"]

    detail = await client.get(
        f"/api/v1/workspaces/{workspace_id}/conversations/{conversation_id}",
        headers=owner.headers,
    )
    messages = detail.json()["messages"]
    assert [message["role"] for message in messages] == ["user", "assistant"]
    assert messages[1]["citations"]


async def test_conversations_are_invisible_across_workspaces(
    client: httpx.AsyncClient,
) -> None:
    """A non-member learns nothing: absent, not forbidden."""
    owner = await make_account(client, "c-tenant-a@example.com")
    outsider = await make_account(client, "c-tenant-b@example.com")
    workspace_id = await make_workspace(client, owner)
    conversation_id = await start_conversation(client, owner, workspace_id)

    hidden = await client.get(
        f"/api/v1/workspaces/{workspace_id}/conversations/{conversation_id}",
        headers=outsider.headers,
    )
    assert hidden.status_code == 404
    assert error_code(hidden) == "workspace_not_found"

    # A conversation id from another workspace is absent, not forbidden.
    other_workspace = await make_workspace(client, outsider)
    borrowed = await client.get(
        f"/api/v1/workspaces/{other_workspace}/conversations/{conversation_id}",
        headers=outsider.headers,
    )
    assert borrowed.status_code == 404
    assert error_code(borrowed) == "conversation_not_found"

    asked = await client.post(
        f"/api/v1/workspaces/{other_workspace}/conversations/{conversation_id}/messages",
        json={"question": "anything"},
        headers=outsider.headers,
    )
    assert asked.status_code == 404
    assert error_code(asked) == "conversation_not_found"


async def test_feedback_revises_rather_than_accumulates(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    """The row is a reviewer's current opinion, not a log of their clicks."""
    owner = await make_account(client, "c-feedback@example.com")
    workspace_id = await make_workspace(client, owner)
    conversation_id = await start_conversation(client, owner, workspace_id)
    await client.post(
        f"/api/v1/workspaces/{workspace_id}/conversations/{conversation_id}/messages",
        json={"question": "anything at all"},
        headers=owner.headers,
    )
    assistant = (
        await db_session.scalars(select(Message).where(Message.role == MessageRole.ASSISTANT))
    ).one()

    base = (
        f"/api/v1/workspaces/{workspace_id}/conversations/{conversation_id}"
        f"/messages/{assistant.id}/feedback"
    )
    first = await client.put(
        base, json={"rating": "unhelpful", "note": "Abstained too early."}, headers=owner.headers
    )
    assert first.status_code == 200, first.text
    assert first.json()["rating"] == "unhelpful"

    revised = await client.put(base, json={"rating": "helpful"}, headers=owner.headers)
    assert revised.status_code == 200, revised.text
    assert revised.json()["rating"] == "helpful"
    assert revised.json()["note"] is None
    assert revised.json()["id"] == first.json()["id"], "the same row must be revised"

    stored = await db_session.scalar(select(func.count()).select_from(MessageFeedback))
    assert stored == 1

    listed = await client.get(base, headers=owner.headers)
    assert listed.status_code == 200
    assert [entry["rating"] for entry in listed.json()] == ["helpful"]

    rejected = await client.put(base, json={"rating": "excellent"}, headers=owner.headers)
    assert rejected.status_code == 422

    missing = await client.put(
        f"/api/v1/workspaces/{workspace_id}/conversations/{conversation_id}"
        f"/messages/{uuid.uuid4()}/feedback",
        json={"rating": "helpful"},
        headers=owner.headers,
    )
    assert missing.status_code == 404
    assert error_code(missing) == "message_not_found"


async def test_deleting_a_thread_keeps_the_evidence_it_cited(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Citations protect cited evidence, not the answer that cited it.

    `citations.chunk_id` is `ondelete=RESTRICT`, which must not make a
    conversation undeletable — the chunk and its document survive instead.
    """
    owner = await make_account(client, "c-delete@example.com")
    workspace_id = await make_workspace(client, owner)
    workspace = await db_session.get(Workspace, uuid.UUID(workspace_id))
    assert workspace is not None
    user = (await db_session.scalars(select(User).where(User.email == owner.email))).one()
    chunk = await seed_chunk(db_session, workspace=workspace, owner=user)

    conversation_id = await start_conversation(client, owner, workspace_id)
    answered = await client.post(
        f"/api/v1/workspaces/{workspace_id}/conversations/{conversation_id}/messages",
        json={"question": "When is the invoice payment due?"},
        headers=owner.headers,
    )
    assert answered.json()["claims"], "the test needs a citation to exist"

    deleted = await client.delete(
        f"/api/v1/workspaces/{workspace_id}/conversations/{conversation_id}",
        headers=owner.headers,
    )
    assert deleted.status_code == 204, deleted.text

    gone = await client.get(
        f"/api/v1/workspaces/{workspace_id}/conversations/{conversation_id}",
        headers=owner.headers,
    )
    assert gone.status_code == 404
    assert await db_session.get(Chunk, chunk.id) is not None
    assert await db_session.scalar(select(func.count()).select_from(Message)) == 0


async def test_listing_shows_a_workspace_own_threads_newest_first(
    client: httpx.AsyncClient,
) -> None:
    owner = await make_account(client, "c-list@example.com")
    workspace_id = await make_workspace(client, owner)
    first = await start_conversation(client, owner, workspace_id)
    second = await start_conversation(client, owner, workspace_id)

    listed = await client.get(
        f"/api/v1/workspaces/{workspace_id}/conversations", headers=owner.headers
    )
    assert listed.status_code == 200, listed.text
    ids = [entry["id"] for entry in listed.json()]
    assert set(ids) == {first, second}


async def enroll(
    client: httpx.AsyncClient,
    owner: Account,
    workspace_id: str,
    invitee: Account,
    role: str,
) -> None:
    added = await client.post(
        f"/api/v1/workspaces/{workspace_id}/members",
        json={"email": invitee.email, "role": role},
        headers=owner.headers,
    )
    assert added.status_code == 201, added.text


async def test_a_viewer_can_read_a_thread_but_never_write_one(
    client: httpx.AsyncClient,
) -> None:
    """`QUERY` is the read-only right to ask; it must not cover writing.

    A viewer's documented contract is "changes nothing". Writing a durable
    thread, recording feedback, and deleting answer history are all changes, so
    they need `CONVERSE` — otherwise a read-only role could destroy another
    member's evidence-backed history.
    """
    owner = await make_account(client, "c-v-owner@example.com")
    viewer = await make_account(client, "c-v-viewer@example.com")
    workspace_id = await make_workspace(client, owner)
    await enroll(client, owner, workspace_id, viewer, "viewer")
    conversation_id = await start_conversation(client, owner, workspace_id)

    base = f"/api/v1/workspaces/{workspace_id}/conversations"
    # Reading is allowed: the answers are drawn from documents they may read.
    assert (await client.get(base, headers=viewer.headers)).status_code == 200
    assert (
        await client.get(f"{base}/{conversation_id}", headers=viewer.headers)
    ).status_code == 200

    refused_create = await client.post(base, json={"title": "mine"}, headers=viewer.headers)
    assert refused_create.status_code == 403
    assert error_code(refused_create) == "insufficient_role"

    refused_ask = await client.post(
        f"{base}/{conversation_id}/messages",
        json={"question": "anything"},
        headers=viewer.headers,
    )
    assert refused_ask.status_code == 403

    refused_delete = await client.delete(f"{base}/{conversation_id}", headers=viewer.headers)
    assert refused_delete.status_code == 403

    # The one-shot answer endpoint stays open to them: asking without persisting
    # is exactly what `QUERY` is for.
    assert (
        await client.post(
            f"/api/v1/workspaces/{workspace_id}/answer",
            json={"query": "anything"},
            headers=viewer.headers,
        )
    ).status_code == 200


async def test_only_the_author_or_an_admin_may_delete_a_thread(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    """A member must not be able to destroy a colleague's answer history."""
    owner = await make_account(client, "c-d-owner@example.com")
    member = await make_account(client, "c-d-member@example.com")
    workspace_id = await make_workspace(client, owner)
    await enroll(client, owner, workspace_id, member, "member")

    base = f"/api/v1/workspaces/{workspace_id}/conversations"
    owners_thread = await start_conversation(client, owner, workspace_id)

    refused = await client.delete(f"{base}/{owners_thread}", headers=member.headers)
    assert refused.status_code == 403
    assert error_code(refused) == "insufficient_role"

    # Their own thread they may delete.
    created = await client.post(base, json={"title": "mine"}, headers=member.headers)
    assert created.status_code == 201, created.text
    own = created.json()["id"]
    assert (await client.delete(f"{base}/{own}", headers=member.headers)).status_code == 204

    # An admin may remove anyone's, and it is attributable afterwards.
    deleted = await client.delete(f"{base}/{owners_thread}", headers=owner.headers)
    assert deleted.status_code == 204, deleted.text
    logged = (
        await db_session.scalars(
            select(AuditLog).where(
                AuditLog.action == "conversation.deleted",
                AuditLog.resource_id == uuid.UUID(owners_thread),
            )
        )
    ).all()
    # The rows are cascaded away, so the audit event is the only remaining record.
    assert len(logged) == 1
    assert logged[0].actor_user_id is not None


async def test_feedback_is_only_accepted_on_an_answer(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Rating your own question would contaminate reviewer-feedback data."""
    owner = await make_account(client, "c-fb-role@example.com")
    workspace_id = await make_workspace(client, owner)
    conversation_id = await start_conversation(client, owner, workspace_id)
    await client.post(
        f"/api/v1/workspaces/{workspace_id}/conversations/{conversation_id}/messages",
        json={"question": "anything at all"},
        headers=owner.headers,
    )
    question = (
        await db_session.scalars(select(Message).where(Message.role == MessageRole.USER))
    ).one()

    refused = await client.put(
        f"/api/v1/workspaces/{workspace_id}/conversations/{conversation_id}"
        f"/messages/{question.id}/feedback",
        json={"rating": "helpful"},
        headers=owner.headers,
    )
    assert refused.status_code == 409
    assert error_code(refused) == "feedback_requires_answer"
    assert await db_session.scalar(select(func.count()).select_from(MessageFeedback)) == 0


async def test_turns_keep_their_order_and_the_thread_moves_to_the_top(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Order must be recorded, not inferred from timestamps that can tie.

    A question and its answer are written close together, and `now()` is
    transaction-start time in PostgreSQL, so ordering by `created_at` alone lets
    SQL return the answer before the question. The thread must also rise in the
    list when it gains a turn, which inserting a message alone does not do.
    """
    owner = await make_account(client, "c-order@example.com")
    workspace_id = await make_workspace(client, owner)
    base = f"/api/v1/workspaces/{workspace_id}/conversations"
    first = await start_conversation(client, owner, workspace_id)
    second = await start_conversation(client, owner, workspace_id)

    for question in ("first question", "second question"):
        asked = await client.post(
            f"{base}/{first}/messages", json={"question": question}, headers=owner.headers
        )
        assert asked.status_code == 200, asked.text
        # The persisted id travels with the answer so feedback can be attached
        # without reloading the thread.
        assert asked.json()["message_id"]

    detail = await client.get(f"{base}/{first}", headers=owner.headers)
    messages = detail.json()["messages"]
    assert [message["role"] for message in messages] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]
    assert [message["content"] for message in messages][0] == "first question"
    assert [message["content"] for message in messages][2] == "second question"

    sequences = (
        await db_session.scalars(
            select(Message.sequence)
            .where(Message.conversation_id == uuid.UUID(first))
            .order_by(Message.sequence)
        )
    ).all()
    assert list(sequences) == [0, 1, 2, 3]

    # The thread that just gained turns is listed ahead of the untouched one.
    listed = await client.get(base, headers=owner.headers)
    assert [entry["id"] for entry in listed.json()][0] == first
    assert second in [entry["id"] for entry in listed.json()]
