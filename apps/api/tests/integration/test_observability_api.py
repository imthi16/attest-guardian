"""Readiness against the real dependencies it claims to check.

A probe that passes with a stub proves only that the handler runs. The whole
value of `/readyz` is that it fails when PostgreSQL, Redis, or object storage is
genuinely unreachable, so it is exercised here with all three actually running
(`make infra-up`, or the CI containers) and then with one deliberately broken.

Requires infrastructure for the same reason the repository's other integration
tests do: the alternative is a test that would keep passing after the probe
stopped touching anything.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass

import httpx
import pytest
from app.config import Settings
from app.db.session import get_db_session
from app.main import create_app
from app.storage.s3 import S3ObjectStorage
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

# The same bucket the other storage tests use. Readiness genuinely fails when
# the configured bucket does not exist — which is correct, and is what a
# deployment's bucket-creation step exists to prevent — so the test provisions
# it rather than weakening the probe to tolerate its absence.
TEST_BUCKET = "attest-test-documents"


def probe_settings() -> Settings:
    return Settings(metrics_enabled=True, s3_bucket=TEST_BUCKET)


@dataclass
class Harness:
    """The client and the app behind it.

    The app is held explicitly rather than reached for through the client's
    private transport: these tests need to break a dependency, and doing that
    through an internal attribute would leave the test failing the day httpx
    renames it.
    """

    app: FastAPI
    http: httpx.AsyncClient

    def break_queue(self, error: Exception) -> None:
        class UnreachableQueue:
            async def ping(self) -> None:
                raise error

        self.app.state.job_queue = UnreachableQueue()


@pytest.fixture(scope="session")
def object_storage() -> S3ObjectStorage:
    storage = S3ObjectStorage(probe_settings())
    try:
        asyncio.run(storage.ensure_bucket())
    except Exception as error:  # noqa: BLE001 - fail fast with instructions
        pytest.fail(f"MinIO is required for these tests; start it with `make infra-up` ({error})")
    return storage


@pytest.fixture
async def harness(
    db_session: AsyncSession,
    object_storage: S3ObjectStorage,
) -> AsyncIterator[Harness]:
    del object_storage  # ordering only: the bucket must exist before the probe runs
    application = create_app(probe_settings())

    async def _use_test_session() -> AsyncIterator[AsyncSession]:
        yield db_session

    application.dependency_overrides[get_db_session] = _use_test_session
    transport = httpx.ASGITransport(app=application)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
        yield Harness(app=application, http=http)


async def test_readiness_reports_every_dependency_as_reachable(harness: Harness) -> None:
    response = await harness.http.get("/readyz")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "ready"
    # Named so a failure says which dependency, without saying anything else.
    assert set(body["dependencies"]) == {"database", "object_storage", "queue"}
    assert set(body["dependencies"].values()) == {"ok"}


async def test_an_unreachable_dependency_degrades_the_probe_without_explaining(
    harness: Harness,
) -> None:
    """The response must name the dependency and stop there.

    An unauthenticated probe that returned the driver's message would publish
    the DSN it failed to reach — host, port, user, sometimes a password.
    """
    harness.break_queue(
        ConnectionError("Error connecting to redis://attest:hunter2@redis.internal:6379/0")
    )

    response = await harness.http.get("/readyz")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["dependencies"]["queue"] == "unavailable"
    # The other two are still reachable, so the probe localizes the fault.
    assert body["dependencies"]["database"] == "ok"

    text = response.text
    for leak in ("hunter2", "redis.internal", "6379", "ConnectionError"):
        assert leak not in text, leak


async def test_liveness_stays_up_while_readiness_is_degraded(harness: Harness) -> None:
    """Liveness must not follow readiness, or a dependency blip rolls every replica."""
    harness.break_queue(ConnectionError("down"))

    assert (await harness.http.get("/readyz")).status_code == 503
    assert (await harness.http.get("/health")).status_code == 200


async def test_metrics_report_the_requests_that_were_served(harness: Harness) -> None:
    await harness.http.get("/health")

    response = await harness.http.get("/metrics")

    assert response.status_code == 200
    body = response.text
    assert 'attest_http_requests_total{method="GET",route="/health",status="2xx"}' in body
    assert "attest_http_request_duration_seconds_bucket" in body


async def test_metrics_never_carry_an_identifier(harness: Harness) -> None:
    """The endpoint has no authentication, so its labels are public.

    A workspace id in a label would make every scrape a tenant directory; this
    walks a real authenticated request and checks nothing of the sort appears.
    """
    await harness.http.get("/api/v1/health")

    body = (await harness.http.get("/metrics")).text

    assert "workspace_id=" not in body
    assert "document_id=" not in body
    assert "query=" not in body
    # Route templates only — no resolved path segments.
    assert "/workspaces/0" not in body
