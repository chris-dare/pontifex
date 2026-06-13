"""Redis token cache backend, Fernet encryption, and the env-driven factory (#47)."""

import pytest
from cryptography.fernet import Fernet
from pontifex_mcp.connectors.token_exchange import (
    FernetEncryptor,
    InMemoryTokenCache,
    RedisTokenCache,
    default_token_cache,
)


class _FakeRedis:
    """Minimal async Redis stub: in-memory get/setex, records what was stored."""

    def __init__(self) -> None:
        self.store: dict[str, bytes] = {}
        self.ttls: dict[str, int] = {}
        self.closed = False

    async def get(self, key: str):
        return self.store.get(key)

    async def setex(self, key: str, ttl: int, value: bytes) -> None:
        self.store[key] = value
        self.ttls[key] = ttl

    async def aclose(self) -> None:
        self.closed = True


# --- Fernet encryptor --------------------------------------------------------


def test_fernet_round_trip():
    enc = FernetEncryptor(Fernet.generate_key().decode())
    ct = enc.encrypt(b"secret-token")
    assert ct != b"secret-token"
    assert enc.decrypt(ct) == b"secret-token"


def test_fernet_rejects_bad_key():
    with pytest.raises(ValueError, match="Fernet key"):
        FernetEncryptor("not-a-valid-key")


# --- RedisTokenCache ---------------------------------------------------------


def _cache(redis):
    return RedisTokenCache(FernetEncryptor(Fernet.generate_key().decode()), redis_client=redis)


async def test_redis_cache_stores_ciphertext_and_decrypts_on_read():
    redis = _FakeRedis()
    cache = _cache(redis)

    calls = {"n": 0}

    async def loader():
        calls["n"] += 1
        return "downstream-token", 300

    first = await cache.get_or_load("k1", loader)
    assert first.reveal() == "downstream-token"

    # At rest it's ciphertext, not the token — and TTL was applied.
    stored = redis.store["pontifex:tokx:k1"]
    assert b"downstream-token" not in stored
    assert redis.ttls["pontifex:tokx:k1"] == 300

    # Second read comes from Redis (decrypted), loader not called again.
    second = await cache.get_or_load("k1", loader)
    assert second.reveal() == "downstream-token"
    assert calls["n"] == 1


async def test_redis_cache_reexchanges_on_decrypt_failure():
    # A value encrypted under a different (rotated) key can't be decrypted —
    # the cache must treat it as a miss and re-mint, not raise.
    redis = _FakeRedis()
    old_key = FernetEncryptor(Fernet.generate_key().decode())
    redis.store["pontifex:tokx:k1"] = old_key.encrypt(b"stale-token")

    cache = _cache(redis)  # a fresh, different key
    calls = {"n": 0}

    async def loader():
        calls["n"] += 1
        return "fresh-token", 300

    result = await cache.get_or_load("k1", loader)
    assert result.reveal() == "fresh-token"
    assert calls["n"] == 1  # re-minted rather than failing the call


async def test_redis_cache_skips_caching_nonpositive_ttl():
    redis = _FakeRedis()
    cache = _cache(redis)

    async def loader():
        return "tok", 0  # non-positive TTL must not crash SETEX

    result = await cache.get_or_load("k", loader)
    assert result.reveal() == "tok"
    assert "pontifex:tokx:k" not in redis.store  # not cached


async def test_redis_cache_single_flight_per_process():
    import asyncio

    redis = _FakeRedis()
    cache = _cache(redis)
    calls = {"n": 0}

    async def loader():
        calls["n"] += 1
        await asyncio.sleep(0)
        return "tok", 300

    results = await asyncio.gather(*(cache.get_or_load("k", loader) for _ in range(5)))
    assert all(r.reveal() == "tok" for r in results)
    assert calls["n"] == 1  # five concurrent misses → one loader call


async def test_redis_cache_aclose_closes_client():
    redis = _FakeRedis()
    cache = _cache(redis)
    await cache.aclose()
    assert redis.closed is True


def test_redis_cache_requires_url_or_client():
    with pytest.raises(ValueError, match="redis_url or redis_client"):
        RedisTokenCache(FernetEncryptor(Fernet.generate_key().decode()))


# --- factory -----------------------------------------------------------------


def test_factory_defaults_to_memory(monkeypatch):
    monkeypatch.delenv("PONTIFEX_TOKEN_CACHE", raising=False)
    assert isinstance(default_token_cache(), InMemoryTokenCache)


def test_factory_redis_requires_redis_url(monkeypatch):
    monkeypatch.setenv("PONTIFEX_TOKEN_CACHE", "redis")
    monkeypatch.delenv("REDIS_URL", raising=False)
    with pytest.raises(ValueError, match="REDIS_URL"):
        default_token_cache()


def test_factory_redis_requires_key(monkeypatch):
    monkeypatch.setenv("PONTIFEX_TOKEN_CACHE", "redis")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.delenv("PONTIFEX_TOKEN_CACHE_KEY", raising=False)
    with pytest.raises(ValueError, match="PONTIFEX_TOKEN_CACHE_KEY"):
        default_token_cache()


def test_factory_builds_redis_backend(monkeypatch):
    monkeypatch.setenv("PONTIFEX_TOKEN_CACHE", "redis")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("PONTIFEX_TOKEN_CACHE_KEY", Fernet.generate_key().decode())
    assert isinstance(default_token_cache(), RedisTokenCache)


def test_factory_rejects_unknown_backend(monkeypatch):
    monkeypatch.setenv("PONTIFEX_TOKEN_CACHE", "memcached")
    with pytest.raises(ValueError, match="must be 'memory' or 'redis'"):
        default_token_cache()
