"""Tests for the Redis-backed fixed-window RateLimiter."""

from __future__ import annotations

import pytest
from pontifex_mcp.middleware.rate_limit import RateLimiter


class _FakeRedis:
    """Minimal in-memory stand-in for the bits RateLimiter uses."""

    def __init__(self) -> None:
        self.counts: dict[str, int] = {}
        self.expirations: dict[str, int] = {}

    async def incr(self, key: str) -> int:
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]

    async def expire(self, key: str, seconds: int) -> bool:
        self.expirations[key] = seconds
        return True


@pytest.mark.asyncio
async def test_allows_up_to_limit_then_denies():
    limiter = RateLimiter(_FakeRedis())
    results = [await limiter.allow("usr_1", limit_rpm=3) for _ in range(4)]
    assert results == [True, True, True, False]


@pytest.mark.asyncio
async def test_sets_ttl_only_on_first_request():
    redis = _FakeRedis()
    limiter = RateLimiter(redis, window_seconds=60)
    await limiter.allow("usr_1", limit_rpm=10)
    await limiter.allow("usr_1", limit_rpm=10)
    # Exactly one key, TTL set to the window.
    assert len(redis.expirations) == 1
    assert next(iter(redis.expirations.values())) == 60


@pytest.mark.asyncio
async def test_identities_have_independent_buckets():
    limiter = RateLimiter(_FakeRedis())
    assert await limiter.allow("usr_a", limit_rpm=1) is True
    assert await limiter.allow("usr_a", limit_rpm=1) is False
    # A different identity is unaffected.
    assert await limiter.allow("usr_b", limit_rpm=1) is True


@pytest.mark.asyncio
async def test_non_positive_limit_means_unlimited():
    redis = _FakeRedis()
    limiter = RateLimiter(redis)
    for _ in range(100):
        assert await limiter.allow("usr_1", limit_rpm=0) is True
    # Never touched Redis.
    assert redis.counts == {}
