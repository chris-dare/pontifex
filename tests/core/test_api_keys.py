"""APIKeyResolver cache path — the `anonymous` flag must never be trusted from
the Redis cache (a poisoned blob would otherwise bypass every scope)."""

import json

import pytest
from pontifex_mcp.auth.api_keys import APIKeyResolver


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
