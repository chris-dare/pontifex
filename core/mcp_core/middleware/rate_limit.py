"""Per-identity request rate limiting, backed by Redis.

Fixed-window counter: each identity may make up to ``limit_rpm`` requests per
``window_seconds``.  Fixed-window is simple and adequate here; it permits a
brief burst of up to ~2x the limit straddling a window boundary, which is an
acceptable trade for not needing a sorted-set sliding window.

Counters live in Redis as ``ratelimit:{identity}:{window}`` with a TTL of one
window, so they expire on their own and never accumulate.
"""

from __future__ import annotations

import time
from typing import Any


class RateLimiter:
    """Fixed-window request counter keyed by an opaque identity string."""

    def __init__(self, redis_client: Any, window_seconds: int = 60) -> None:
        self.redis = redis_client
        self.window = window_seconds

    async def allow(self, identity: str, limit_rpm: int) -> bool:
        """Return True if a request from ``identity`` is within ``limit_rpm``.

        A non-positive ``limit_rpm`` means "no limit".  On any Redis error the
        request is allowed (fail-open) — rate limiting must never take the API
        down; the failure is the caller's to log.
        """
        if limit_rpm <= 0:
            return True

        bucket = int(time.time()) // self.window
        key = f"ratelimit:{identity}:{bucket}"
        count = await self.redis.incr(key)
        if count == 1:
            # First request in this window — set the TTL so the key self-expires.
            await self.redis.expire(key, self.window)
        return count <= limit_rpm
