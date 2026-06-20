"""APIKeyResolver cache path — the `anonymous` flag must never be trusted from
the Redis cache (a poisoned blob would otherwise bypass every scope)."""

import json

import pytest
from pontifex_mcp.auth.api_keys import APIKeyResolver, hash_key
from pontifex_mcp.models.db import ApiKeyModel
from pontifex_mcp.storage import create_db_engine, ensure_sqlite_schema
from sqlalchemy.ext.asyncio import async_sessionmaker


class _FakeRedis:
    def __init__(self, blob: str | None) -> None:
        self._blob = blob

    async def get(self, _key: str) -> str | None:
        return self._blob

    async def setex(self, *_args: object) -> None:
        return None


@pytest.mark.asyncio
async def test_resolver_ignores_cached_anonymous_flag():
    poisoned = json.dumps(
        {
            "key_id": "k",
            "owner_id": "o",
            "owner_label": "L",
            "scopes": [],
            "rate_limit_rpm": 60,
            "transport": "http",
            "anonymous": True,  # forged
        }
    )
    resolver = APIKeyResolver(_FakeRedis(poisoned), db_session_factory=None)  # type: ignore[arg-type]
    identity = await resolver.resolve("sk_live_whatever")

    assert identity is not None
    assert identity.anonymous is False
    # ...so it does NOT bypass scope enforcement.
    assert not identity.can_use_tool("payments", "refunds", "execute")


@pytest.mark.asyncio
async def test_resolver_without_redis_reads_store_directly():
    """No Redis: resolve queries the store on every call. The cache only exists
    to amortize a Postgres round-trip; a local SQLite read needs none, so the
    no-Redis path is the DB lookup with no cache layer in front."""
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    await ensure_sqlite_schema(engine)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    raw_key = "sk_live_sqlitefloor"  # gitleaks:allow
    async with sessions() as session:
        session.add(
            ApiKeyModel(
                key_id="key_sqlite",
                key_hash=hash_key(raw_key),
                owner_id="usr_sqlite",
                owner_label="SQLite User",
                scopes=["payments:balance:read"],
                rate_limit_rpm=60,
                is_active=True,
            )
        )
        await session.commit()

    resolver = APIKeyResolver(None, sessions)  # redis_client=None

    identity = await resolver.resolve(raw_key)
    assert identity is not None
    assert identity.owner_id == "usr_sqlite"
    assert identity.can_use_tool("payments", "balance", "read")
    # An unknown key resolves to None without consulting any cache.
    assert await resolver.resolve("sk_live_nope") is None  # gitleaks:allow

    await engine.dispose()
