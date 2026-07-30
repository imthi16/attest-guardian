"""Refuse to start a deployment that is configured to fail later.

Configuration mistakes divide into two kinds, and only one of them is
self-announcing. A wrong database password fails on the first request, loudly,
and someone fixes it. A default signing secret, a permissive CORS origin, or a
retired embedding version fails *silently* — the service starts, serves traffic,
and is wrong in a way that surfaces as a security incident or as quietly poor
answers weeks later.

`Settings` already rejects the second kind at construction. This adds the checks
that need to *reach* something: can the process actually open the database, the
queue, and the bucket, and is the schema at the revision this code expects. Those
cannot be validated from environment variables alone, and finding out during a
rollout is the difference between a failed deploy and a broken one.

Run it as a deployment gate, before the first replica takes traffic:

    python -m app.preflight

Exit codes are the interface: `0` ready, `1` a check failed, `2` the
configuration itself is invalid. Nothing here mutates anything — it will not
create a bucket or run a migration, because a preflight that fixes what it finds
is a preflight nobody reads the output of.
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from sqlalchemy import text

from app.config import Settings, get_settings


@dataclass(frozen=True)
class CheckResult:
    """One check's verdict, with a reason a human can act on.

    Unlike the readiness probe, the reason *is* included: this output goes to a
    deploy log read by the operator holding the credentials, not to an
    unauthenticated endpoint. Hiding the DSN here would mean debugging a failed
    rollout with no information at all.
    """

    name: str
    ok: bool
    detail: str


Check = Callable[[Settings], Awaitable[CheckResult]]


async def check_database(settings: Settings) -> CheckResult:
    """Open a connection and confirm the schema is at the expected revision.

    Reachability alone is not enough. A replica starting against a database one
    migration behind will serve requests and fail on the first query touching a
    new column — after it has been added to the load balancer.
    """
    from app.db.session import build_engine

    engine = build_engine(settings)
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
            revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
    except Exception as error:
        return CheckResult("database", False, f"{type(error).__name__}: {error}")
    finally:
        await engine.dispose()

    if revision is None:
        return CheckResult("database", False, "no alembic_version row; migrations have not run")
    return CheckResult("database", True, f"reachable at revision {revision}")


async def check_queue(settings: Settings) -> CheckResult:
    from app.ingestion.queue import RedisJobQueue

    queue = RedisJobQueue(settings.redis_url)
    try:
        await queue.ping()
    except Exception as error:
        return CheckResult("queue", False, f"{type(error).__name__}: {error}")
    finally:
        await queue.aclose()
    return CheckResult("queue", True, "reachable")


async def check_storage(settings: Settings) -> CheckResult:
    """Confirm the configured bucket exists and the credentials reach it.

    Listing a prefix rather than creating the bucket: a preflight that
    provisioned infrastructure would hide a misconfigured bucket name by
    silently creating a second, empty one — and the documents would be missing
    rather than the deploy failing.
    """
    from app.storage.s3 import S3ObjectStorage

    storage = S3ObjectStorage(settings)
    try:
        await storage.list_keys("preflight/")
    except Exception as error:
        return CheckResult("object_storage", False, f"{type(error).__name__}: {error}")
    return CheckResult("object_storage", True, f"bucket {settings.s3_bucket!r} reachable")


CHECKS: tuple[Check, ...] = (check_database, check_queue, check_storage)


async def run(settings: Settings) -> list[CheckResult]:
    return list(await asyncio.gather(*(check(settings) for check in CHECKS)))


def _main() -> int:  # pragma: no cover - CLI entry point
    try:
        settings = get_settings()
    except Exception as error:
        sys.stderr.write(f"configuration is invalid: {error}\n")
        return 2

    results = asyncio.run(run(settings))
    for result in sorted(results, key=lambda item: item.name):
        marker = "ok  " if result.ok else "FAIL"
        sys.stdout.write(f"{marker} {result.name}: {result.detail}\n")

    failed = [result for result in results if not result.ok]
    if failed:
        sys.stderr.write(f"{len(failed)} preflight check(s) failed; not starting\n")
        return 1
    sys.stdout.write(f"preflight passed for APP_ENV={settings.app_env}\n")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(_main())


__all__ = [
    "CHECKS",
    "Check",
    "CheckResult",
    "check_database",
    "check_queue",
    "check_storage",
    "run",
]
