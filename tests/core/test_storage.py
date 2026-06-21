"""Dialect-agnostic storage: SQLite quickstart path + Postgres-unchanged DDL.

SQLite is the zero-config local datastore (create_all, single file, no schemas);
Postgres stays Alembic-managed with native column types. These tests pin both:
the SQLite engine round-trips audit + api-key rows, and the Postgres DDL still
emits the native types the existing migrations created.
"""

from datetime import UTC, datetime

import pytest
from pontifex_mcp.models.db import ApiKeyModel, AuditLogModel
from pontifex_mcp.storage import (
    create_db_engine,
    ensure_sqlite_schema,
    is_sqlite,
    normalize_db_url,
)
from sqlalchemy import select
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.schema import CreateTable


def test_normalize_db_url():
    assert normalize_db_url("audit.db") == "sqlite+aiosqlite:///audit.db"
    assert normalize_db_url("sqlite:///x.db") == "sqlite+aiosqlite:///x.db"
    assert normalize_db_url("postgresql://u@h/db") == "postgresql+asyncpg://u@h/db"
    assert normalize_db_url("postgres://u@h/db") == "postgresql+asyncpg://u@h/db"
    already = "postgresql+asyncpg://u@h/db"
    assert normalize_db_url(already) == already
    assert is_sqlite("sqlite+aiosqlite:///x") is True
    assert is_sqlite("postgresql+asyncpg://x") is False


def test_postgres_ddl_keeps_native_types():
    """Variants keep Postgres on JSONB / text[] / INET / BIGSERIAL — unchanged
    from the existing migrations, so no new migration is needed."""
    pg = postgresql.dialect()
    audit = str(CreateTable(AuditLogModel.__table__).compile(dialect=pg))
    keys = str(CreateTable(ApiKeyModel.__table__).compile(dialect=pg))
    assert "JSONB" in audit
    assert "INET" in audit
    assert "BIGSERIAL" in audit
    assert "VARCHAR[]" in keys  # scopes stays an array on Postgres


def test_sqlite_ddl_uses_portable_types():
    sl = sqlite.dialect()
    audit = str(CreateTable(AuditLogModel.__table__).compile(dialect=sl))
    assert "JSON" in audit
    assert "INTEGER" in audit  # BigInteger PK -> INTEGER (rowid alias) on SQLite
    assert "INET" not in audit


@pytest.mark.asyncio
async def test_sqlite_roundtrip_audit_and_apikey():
    """create_all builds the core tables on SQLite (schema translated away),
    and both models round-trip — including JSON list scopes and autoincrement id."""
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    await ensure_sqlite_schema(engine)
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async with sessions() as s:
        s.add(
            AuditLogModel(
                timestamp=datetime.now(UTC),
                namespace="payments",
                key_id="k",
                owner_id="o",
                owner_label="L",
                transport="stdio",
                tool_name="issue_refund",
                tool_params={"charge_id": "ch_1", "amount": 500},
                data_source="fake_stripe",
                cache_hit=False,
                response_ms=12,
                error=None,
                ip_address="127.0.0.1",
                delegated_audience=None,
            )
        )
        s.add(
            ApiKeyModel(
                key_id="key1",
                key_hash="h",
                owner_id="o",
                owner_label="L",
                scopes=["payments:refunds:execute", "payments:*:read"],
                rate_limit_rpm=60,
                is_active=True,
            )
        )
        await s.commit()

    async with sessions() as s:
        audit = (await s.execute(select(AuditLogModel))).scalar_one()
        key = (await s.execute(select(ApiKeyModel))).scalar_one()

    assert audit.id == 1  # autoincrement worked
    assert audit.tool_params == {"charge_id": "ch_1", "amount": 500}
    assert audit.ip_address == "127.0.0.1"
    assert key.scopes == ["payments:refunds:execute", "payments:*:read"]

    await engine.dispose()
