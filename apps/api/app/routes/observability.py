"""Readiness and metrics endpoints.

Both are operator surfaces rather than product surfaces, and both are reachable
by whoever can reach the port — a readiness probe cannot authenticate, and a
scrape target authenticates at the network layer if at all. So neither returns
anything a stranger should not see: readiness reports a dependency name and a
boolean, and metrics carry no label that could identify a tenant or a query.

Metrics are off unless enabled. A scrape endpoint published by default on a
service that has one is how request volumes and error rates end up on the public
internet; an operator who wants it turns it on and puts it behind their own
network boundary.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.session import get_db_session
from app.observability import readiness
from app.observability.metrics import REGISTRY
from app.schemas.health import ReadinessResponse

router = APIRouter(tags=["system"])

SessionDep = Annotated[AsyncSession, Depends(get_db_session)]

# Prometheus' own content type. Version pinned because a scraper negotiates on
# it, and an unversioned `text/plain` is parsed as the oldest format.
PROMETHEUS_CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"


def _probes(request: Request, session: AsyncSession) -> dict[str, readiness.Probe]:
    """One probe per dependency, each doing the cheapest real round trip.

    "Cheapest real" matters in both directions: a probe that only inspects a
    client object proves nothing, and one that runs a query proportional to the
    data would make readiness fail first on the largest workspace.
    """

    async def database() -> None:
        await session.execute(text("SELECT 1"))

    async def queue() -> None:
        await request.app.state.job_queue.ping()

    async def storage() -> None:
        # Listing an unused prefix is a real authenticated call that returns
        # nothing, so it proves credentials and reachability without paying for
        # a scan of tenant objects.
        await request.app.state.object_storage.list_keys("readiness-probe/")

    return {"database": database, "object_storage": storage, "queue": queue}


@router.get(
    "/readyz",
    response_model=ReadinessResponse,
    # Declared so a generated client can model the degraded case. Without it the
    # contract claims 200 is the only outcome, and every client treats the state
    # this endpoint exists to report as an unexpected error.
    responses={503: {"model": ReadinessResponse, "description": "A dependency is unreachable."}},
)
async def readyz(request: Request, session: SessionDep, response: Response) -> ReadinessResponse:
    """Report whether every dependency this process needs is reachable.

    A degraded result is `503`, so a load balancer stops sending traffic — but
    it is deliberately *not* wired to a restart: a database blip would otherwise
    roll every replica, turning a dependency's outage into an outage of its own.
    """
    report = await readiness.check(_probes(request, session))
    if not report.ready:
        response.status_code = 503
    return ReadinessResponse.model_validate(report.as_dict())


@router.get("/metrics", include_in_schema=False)
async def metrics(request: Request) -> Response:
    """Prometheus exposition, when the deployment has enabled it.

    Settings come from the application rather than the cached global accessor,
    so a process constructed with explicit settings — a test, or an embedding
    host — is governed by the settings it was actually given.
    """
    settings: Settings = request.app.state.settings
    if not settings.metrics_enabled:
        return Response(status_code=404)
    return Response(content=REGISTRY.render(), media_type=PROMETHEUS_CONTENT_TYPE)


__all__ = ["PROMETHEUS_CONTENT_TYPE", "router"]
