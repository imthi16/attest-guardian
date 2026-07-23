"""Retrieval endpoint authorization and contract, over the real app stack.

Requires `make infra-up` (or the CI containers). Focuses on the route's
authorization boundary and response shape; ranking correctness lives in
`test_retrieval.py`.
"""

from collections.abc import AsyncIterator

import httpx
import pytest
from app.config import Settings
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.apptools import Account, build_client, make_account


def settings() -> Settings:
    return Settings(auth_rate_limit_attempts=1000)


@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[httpx.AsyncClient]:
    async with build_client(db_session, settings()) as instance:
        yield instance


async def make_workspace(client: httpx.AsyncClient, account: Account) -> str:
    response = await client.post(
        "/api/v1/workspaces", json={"name": "Retrieval"}, headers=account.headers
    )
    assert response.status_code == 201, response.text
    workspace_id: str = response.json()["id"]
    return workspace_id


async def add_member(
    client: httpx.AsyncClient,
    owner: Account,
    workspace_id: str,
    email: str,
    role: str,
) -> httpx.Response:
    return await client.post(
        f"/api/v1/workspaces/{workspace_id}/members",
        json={"email": email, "role": role},
        headers=owner.headers,
    )


async def test_viewer_can_query_and_gets_trace(client: httpx.AsyncClient) -> None:
    owner = await make_account(client, "r-owner@example.com")
    viewer = await make_account(client, "r-viewer@example.com")
    workspace_id = await make_workspace(client, owner)
    enrolled = await add_member(client, owner, workspace_id, viewer.email, "viewer")
    assert enrolled.status_code == 201, enrolled.text

    response = await client.post(
        f"/api/v1/workspaces/{workspace_id}/retrieval/search",
        json={"query": "anything"},
        headers=viewer.headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["results"] == []  # empty workspace, but the query is authorized
    assert body["trace"]["workspace_id"] == workspace_id
    assert "detected_language" in body["trace"]


async def test_non_member_gets_workspace_not_found(client: httpx.AsyncClient) -> None:
    owner = await make_account(client, "r-owner2@example.com")
    outsider = await make_account(client, "r-outsider@example.com")
    workspace_id = await make_workspace(client, owner)

    response = await client.post(
        f"/api/v1/workspaces/{workspace_id}/retrieval/search",
        json={"query": "anything"},
        headers=outsider.headers,
    )
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "workspace_not_found"


async def test_unauthenticated_request_is_rejected(client: httpx.AsyncClient) -> None:
    owner = await make_account(client, "r-owner3@example.com")
    workspace_id = await make_workspace(client, owner)

    response = await client.post(
        f"/api/v1/workspaces/{workspace_id}/retrieval/search",
        json={"query": "anything"},
    )
    assert response.status_code == 401


async def test_empty_query_is_rejected_by_validation(client: httpx.AsyncClient) -> None:
    owner = await make_account(client, "r-owner4@example.com")
    workspace_id = await make_workspace(client, owner)

    response = await client.post(
        f"/api/v1/workspaces/{workspace_id}/retrieval/search",
        json={"query": ""},
        headers=owner.headers,
    )
    assert response.status_code == 422
