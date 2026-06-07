import hashlib
import json
from dataclasses import asdict
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from pontifex_mcp.auth.identity import CallerIdentity
from pontifex_mcp.models.db import ApiKeyModel


def hash_key(raw_key: str, algorithm: str = "sha256") -> str:
    """SHA-256 hash of a plaintext API key. Used as the lookup index."""
    h = hashlib.new(algorithm)
    h.update(raw_key.encode())
    return h.hexdigest()


class APIKeyResolver:
    """Resolves an API key to a CallerIdentity. Redis-first, Postgres-fallback."""

    def __init__(
        self,
        redis_client: Any,
        db_session_factory: async_sessionmaker,
        cache_ttl: int = 300,
        transport: str = "http",
    ) -> None:
        self.redis = redis_client
        self.db = db_session_factory
        self.cache_ttl = cache_ttl
        self.transport = transport

    async def resolve(self, raw_key: str) -> CallerIdentity | None:
        key_hash = hash_key(raw_key)

        cached = await self.redis.get(f"apikey:{key_hash}")
        if cached:
            data = json.loads(cached)
            return CallerIdentity(**data)

        async with self.db() as session:
            result = await session.execute(
                select(ApiKeyModel)
                .where(ApiKeyModel.key_hash == key_hash)
                .where(ApiKeyModel.is_active.is_(True))
                .where((ApiKeyModel.expires_at.is_(None)) | (ApiKeyModel.expires_at > func.now()))
            )
            record = result.scalar_one_or_none()
            if not record:
                return None

            identity = CallerIdentity(
                key_id=record.key_id,
                owner_id=record.owner_id,
                owner_label=record.owner_label,
                scopes=list(record.scopes),
                rate_limit_rpm=record.rate_limit_rpm,
                transport=self.transport,
            )

        await self.redis.setex(
            f"apikey:{key_hash}",
            self.cache_ttl,
            json.dumps(asdict(identity)),
        )
        return identity
