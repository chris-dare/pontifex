import json
from typing import Any

import redis.asyncio as redis


class Cache:
    """Prefix-aware, TTL-configurable Redis cache."""

    def __init__(self, redis_url: str, prefix: str, env_prefix: str = "") -> None:
        self.client = redis.from_url(redis_url)
        self.prefix = f"{env_prefix}:{prefix}" if env_prefix else prefix

    def _key(self, key: str) -> str:
        return f"{self.prefix}:{key}"

    async def get(self, key: str) -> Any | None:
        raw = await self.client.get(self._key(key))
        if raw is None:
            return None
        return json.loads(raw)

    async def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        await self.client.setex(self._key(key), ttl_seconds, json.dumps(value))

    async def invalidate(self, pattern: str) -> None:
        keys: list[bytes] = []
        async for k in self.client.scan_iter(f"{self.prefix}:{pattern}*"):
            keys.append(k)
        if keys:
            await self.client.delete(*keys)

    async def close(self) -> None:
        await self.client.aclose()
