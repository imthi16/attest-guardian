"""The ingestion job queue.

Redis was chosen because it is already part of the local and deployed
infrastructure, gives blocking pop semantics for cheap idle workers, and a
plain list is sufficient at MVP scale — the database remains the source of
truth for job state, so the queue only ever carries pointers. Losing a queue
entry is recoverable: `requeue_stale` re-enqueues jobs whose worker died.

Messages carry `workspace_id` alongside the job id so a worker can bind
row-level security before reading any tenant row.
"""

import json
import uuid
from collections.abc import Awaitable
from dataclasses import dataclass
from typing import Protocol, TypeVar, cast

import redis.asyncio as aioredis

T = TypeVar("T")


def _op(result: "Awaitable[T] | T") -> "Awaitable[T]":
    """redis-py types commands as sync-or-async unions; async client always awaits."""
    return cast("Awaitable[T]", result)


DEFAULT_QUEUE_KEY = "attest:ingestion:queue"
DEFAULT_DEAD_LETTER_KEY = "attest:ingestion:dead"


@dataclass(frozen=True)
class JobMessage:
    """A queue pointer to one ingestion job.

    `traceparent` carries the trace of the request that enqueued the job, so the
    worker's log lines join the upload the user is waiting on. Without it the
    two halves of one user action are separate stories in separate streams, and
    "why is my document still processing" is answered by guesswork.

    It is optional: a job enqueued before this field existed, or by an operator
    tool, still decodes. A worker that refused such a message would turn a
    telemetry gap into a stuck queue.
    """

    job_id: uuid.UUID
    workspace_id: uuid.UUID
    traceparent: str | None = None

    def encode(self) -> str:
        payload = {"job_id": str(self.job_id), "workspace_id": str(self.workspace_id)}
        if self.traceparent is not None:
            payload["traceparent"] = self.traceparent
        return json.dumps(payload)

    @classmethod
    def decode(cls, raw: str) -> "JobMessage":
        payload = json.loads(raw)
        return cls(
            job_id=uuid.UUID(payload["job_id"]),
            workspace_id=uuid.UUID(payload["workspace_id"]),
            traceparent=payload.get("traceparent"),
        )


class JobQueue(Protocol):
    """Queue operations the API and worker rely on."""

    async def enqueue(self, message: JobMessage) -> None: ...

    async def dequeue(self, timeout_seconds: float) -> JobMessage | None: ...

    async def dead_letter(self, message: JobMessage) -> None: ...

    async def list_dead(self) -> list[JobMessage]: ...

    async def ping(self) -> None: ...


class RedisJobQueue:
    """A Redis list per queue; BLPOP gives blocking consumption."""

    def __init__(
        self,
        redis_url: str,
        *,
        queue_key: str = DEFAULT_QUEUE_KEY,
        dead_letter_key: str = DEFAULT_DEAD_LETTER_KEY,
    ) -> None:
        self._redis: aioredis.Redis = aioredis.Redis.from_url(redis_url, decode_responses=True)
        self._queue_key = queue_key
        self._dead_letter_key = dead_letter_key

    async def enqueue(self, message: JobMessage) -> None:
        await _op(self._redis.rpush(self._queue_key, message.encode()))

    async def dequeue(self, timeout_seconds: float) -> JobMessage | None:
        raw: str | None
        if timeout_seconds <= 0:
            raw = cast("str | None", await _op(self._redis.lpop(self._queue_key)))
        else:
            popped = await _op(self._redis.blpop([self._queue_key], timeout=timeout_seconds))
            raw = popped[1] if popped else None
        return JobMessage.decode(raw) if raw else None

    async def dead_letter(self, message: JobMessage) -> None:
        await _op(self._redis.rpush(self._dead_letter_key, message.encode()))

    async def list_dead(self) -> list[JobMessage]:
        entries: list[str] = await _op(self._redis.lrange(self._dead_letter_key, 0, -1))
        return [JobMessage.decode(entry) for entry in entries]

    async def ping(self) -> None:
        """Round-trip to Redis, for the readiness probe.

        A real command rather than an inspection of the client object: the
        client is constructed eagerly and connects lazily, so a wholly
        unreachable Redis looks healthy until the first operation.
        """
        await _op(self._redis.ping())

    async def aclose(self) -> None:
        await self._redis.aclose()
