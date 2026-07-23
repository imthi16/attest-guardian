"""Redis-backed queue behavior against the real Redis from `make infra-up`."""

import uuid
from collections.abc import AsyncIterator

import pytest
from app.config import Settings
from app.ingestion.queue import JobMessage, RedisJobQueue


def message() -> JobMessage:
    return JobMessage(job_id=uuid.uuid4(), workspace_id=uuid.uuid4())


@pytest.fixture
async def queue() -> AsyncIterator[RedisJobQueue]:
    prefix = f"test:{uuid.uuid4().hex}"
    instance = RedisJobQueue(
        Settings().redis_url,
        queue_key=f"{prefix}:queue",
        dead_letter_key=f"{prefix}:dead",
    )
    try:
        yield instance
    finally:
        await instance.aclose()


async def test_fifo_roundtrip(queue: RedisJobQueue) -> None:
    first, second = message(), message()
    await queue.enqueue(first)
    await queue.enqueue(second)
    assert await queue.dequeue(0) == first
    assert await queue.dequeue(0) == second
    assert await queue.dequeue(0) is None


async def test_blocking_dequeue_times_out_empty(queue: RedisJobQueue) -> None:
    assert await queue.dequeue(1) is None


async def test_dead_letter_list(queue: RedisJobQueue) -> None:
    poisoned = message()
    await queue.dead_letter(poisoned)
    assert await queue.list_dead() == [poisoned]
    assert await queue.dequeue(0) is None


def test_message_encoding_roundtrip() -> None:
    original = message()
    assert JobMessage.decode(original.encode()) == original
