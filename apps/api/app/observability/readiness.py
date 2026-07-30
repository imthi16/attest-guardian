"""Whether this process can actually serve, and which dependency cannot.

Liveness and readiness answer different questions and must not be merged.
`/health` says the process is running: it takes no locks and touches no
dependency, so an orchestrator restarting on its failure restarts something
genuinely wedged. `/readyz` says the process can do useful work, which means
reaching PostgreSQL, Redis, and object storage. Wiring a restart to *that* turns
a database blip into a rolling restart of every replica — a self-inflicted
outage on top of the real one.

**A readiness probe is unauthenticated by necessity**, so its body is read by
whoever can reach the port. It therefore reports a dependency's name and a
boolean and nothing else. The exception message from a failed connection is
exactly what an operator wants and exactly what must not be published: DSNs,
hostnames, ports, usernames, and occasionally a password in a driver's URL. It
goes to the logs, where authorization exists.

Checks run concurrently with a short timeout each. Sequentially, three
unreachable dependencies would take three times the timeout, and a probe that
takes longer than its own deadline reads as "down" for reasons of its own making.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

logger = logging.getLogger("app.readiness")

# Per-dependency budget. Short, because a probe is called on a schedule and a
# slow answer is indistinguishable from no answer to the caller.
DEFAULT_TIMEOUT_SECONDS = 2.0


@dataclass(frozen=True)
class DependencyStatus:
    """One dependency's verdict. Deliberately carries no diagnostic detail."""

    name: str
    ready: bool


@dataclass(frozen=True)
class ReadinessReport:
    dependencies: tuple[DependencyStatus, ...]

    @property
    def ready(self) -> bool:
        return all(dependency.ready for dependency in self.dependencies)

    def as_dict(self) -> dict[str, object]:
        return {
            "status": "ready" if self.ready else "degraded",
            "dependencies": {
                dependency.name: "ok" if dependency.ready else "unavailable"
                for dependency in self.dependencies
            },
        }


Probe = Callable[[], Awaitable[None]]


async def _run(name: str, probe: Probe, budget_seconds: float) -> DependencyStatus:
    """Run one probe, converting any failure into a boolean and a log line."""
    try:
        async with asyncio.timeout(budget_seconds):
            await probe()
    except TimeoutError:
        logger.warning(
            "readiness.timeout",
            extra={"dependency": name, "budget_s": budget_seconds},
        )
        return DependencyStatus(name=name, ready=False)
    except Exception as error:
        # Type only, and only to the log. A connection error's message routinely
        # contains the DSN — host, port, user, sometimes the password.
        logger.warning(
            "readiness.failed",
            extra={"dependency": name, "error_type": type(error).__name__},
        )
        return DependencyStatus(name=name, ready=False)
    return DependencyStatus(name=name, ready=True)


async def check(
    probes: dict[str, Probe],
    *,
    budget_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> ReadinessReport:
    """Run every probe concurrently and report each dependency's verdict."""
    names = sorted(probes)
    results = await asyncio.gather(*(_run(name, probes[name], budget_seconds) for name in names))
    return ReadinessReport(dependencies=tuple(results))


__all__ = [
    "DEFAULT_TIMEOUT_SECONDS",
    "DependencyStatus",
    "Probe",
    "ReadinessReport",
    "check",
]
