"""Sliding-window rate limiter behavior with an injected clock."""

import pytest
from app.auth.rate_limit import SlidingWindowRateLimiter


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_allows_up_to_the_limit_then_blocks() -> None:
    limiter = SlidingWindowRateLimiter(attempts=3, window_seconds=60, clock=FakeClock())
    assert all(limiter.allow("k") for _ in range(3))
    assert not limiter.allow("k")


def test_window_slides_and_frees_capacity() -> None:
    clock = FakeClock()
    limiter = SlidingWindowRateLimiter(attempts=2, window_seconds=60, clock=clock)
    assert limiter.allow("k")
    assert limiter.allow("k")
    assert not limiter.allow("k")
    clock.now += 61
    assert limiter.allow("k")


def test_keys_are_independent() -> None:
    limiter = SlidingWindowRateLimiter(attempts=1, window_seconds=60, clock=FakeClock())
    assert limiter.allow("alpha")
    assert not limiter.allow("alpha")
    assert limiter.allow("beta")


def test_rejects_nonpositive_attempts() -> None:
    with pytest.raises(ValueError, match="attempts"):
        SlidingWindowRateLimiter(attempts=0, window_seconds=60)
