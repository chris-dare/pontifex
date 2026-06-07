import json

import pytest
from pontifex_mcp.cache.redis_cache import Cache


class _FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def get(self, key: str):
        return self.store.get(key)

    async def setex(self, key: str, ttl: int, value: str):
        self.store[key] = value

    async def delete(self, *keys: str):
        for k in keys:
            self.store.pop(k, None)
        return len(keys)

    async def scan_iter(self, match: str):
        prefix = match.rstrip("*")
        for k in list(self.store):
            if k.startswith(prefix):
                yield k

    async def aclose(self):
        return None


@pytest.fixture
def cache(monkeypatch):
    fake = _FakeRedis()
    monkeypatch.setattr("pontifex_mcp.cache.redis_cache.redis.from_url", lambda _url: fake)
    return Cache("redis://ignored", prefix="gse"), fake


async def test_set_and_get_roundtrip(cache):
    c, fake = cache
    await c.set("live:all", {"stocks": []}, ttl_seconds=30)
    assert fake.store["gse:live:all"] == json.dumps({"stocks": []})
    assert await c.get("live:all") == {"stocks": []}


async def test_get_missing_returns_none(cache):
    c, _ = cache
    assert await c.get("missing") is None


async def test_prefix_isolation(cache):
    c, fake = cache
    await c.set("foo", {"x": 1}, ttl_seconds=10)
    assert "gse:foo" in fake.store
    assert "foo" not in fake.store


async def test_invalidate_pattern(cache):
    c, fake = cache
    await c.set("live:MTN", {"price": 1}, ttl_seconds=10)
    await c.set("live:GCB", {"price": 2}, ttl_seconds=10)
    await c.set("summary", {"x": 1}, ttl_seconds=10)
    await c.invalidate("live")
    assert "gse:live:MTN" not in fake.store
    assert "gse:live:GCB" not in fake.store
    assert "gse:summary" in fake.store
