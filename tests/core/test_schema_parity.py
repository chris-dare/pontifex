"""Guard against the SQLite floor and the Postgres migrations drifting apart.

The same models run on SQLite (built by `create_all`) and Postgres (built by the
hand-written Alembic migrations). If the migrations ever fall out of step with
the models, a developer who builds on SQLite and deploys on Postgres gets a
surprise. This compares the two and fails on any difference that affects
behavior: columns, nullability, primary keys, unique constraints.

It does NOT compare non-unique index *shape* — that difference is intentional
(SQLite gets the models' portable single-column indexes; Postgres gets
composite, time-ordered ones tuned for audit queries). See AuditLogModel.

Skipped unless TEST_DATABASE_URL points at a throwaway Postgres. CI provides one;
locally, run with TEST_DATABASE_URL=postgresql+asyncpg://... to exercise it.
"""

import asyncio
import os

import pytest
from pontifex_mcp.cli.db import _upgrade_postgres
from pontifex_mcp.storage import create_db_engine, ensure_sqlite_schema, normalize_db_url
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="set TEST_DATABASE_URL (a throwaway Postgres) to run the schema-parity guard",
)

_TABLES = ["api_keys", "audit_log", "domain_registry"]
_SCHEMA = "pontifex_mcp_core"


def _structure(sync_conn, schema):
    """The behavior-affecting shape of each table: columns + nullability, the
    primary key, and the unique constraints/indexes (as column-sets)."""
    insp = inspect(sync_conn)
    out = {}
    for table in _TABLES:
        columns = {c["name"]: bool(c["nullable"]) for c in insp.get_columns(table, schema=schema)}
        pk = frozenset(
            insp.get_pk_constraint(table, schema=schema).get("constrained_columns") or []
        )
        unique = {
            frozenset(u["column_names"]) for u in insp.get_unique_constraints(table, schema=schema)
        }
        unique |= {
            frozenset(i["column_names"])
            for i in insp.get_indexes(table, schema=schema)
            if i["unique"]
        }
        out[table] = {"columns": columns, "pk": pk, "unique": unique}
    return out


async def _sqlite_structure():
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    await ensure_sqlite_schema(engine)
    async with engine.connect() as conn:
        result = await conn.run_sync(lambda sc: _structure(sc, None))
    await engine.dispose()
    return result


async def _reset_postgres(url):
    engine = create_async_engine(normalize_db_url(url))
    async with engine.begin() as conn:
        await conn.execute(text(f"DROP SCHEMA IF EXISTS {_SCHEMA} CASCADE"))
        await conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
    await engine.dispose()


async def _postgres_structure(url):
    engine = create_async_engine(normalize_db_url(url))
    async with engine.connect() as conn:
        result = await conn.run_sync(lambda sc: _structure(sc, _SCHEMA))
    await engine.dispose()
    return result


def test_sqlite_and_postgres_schemas_match(monkeypatch):
    """SQLite (create_all) and Postgres (migrations) agree on columns,
    nullability, primary keys, and unique constraints — for every table."""
    pg_url = os.environ["TEST_DATABASE_URL"]

    # Sync test on purpose: `_upgrade_postgres` runs its own event loop, so it
    # can't be called from inside one. Each asyncio.run() finishes before the next.
    sqlite_struct = asyncio.run(_sqlite_structure())
    asyncio.run(_reset_postgres(pg_url))
    monkeypatch.setenv("DATABASE_URL", normalize_db_url(pg_url))
    _upgrade_postgres()
    postgres_struct = asyncio.run(_postgres_structure(pg_url))

    for table in _TABLES:
        s, p = sqlite_struct[table], postgres_struct[table]
        assert s["columns"] == p["columns"], f"{table}: columns/nullability drifted"
        assert s["pk"] == p["pk"], f"{table}: primary key drifted"
        assert s["unique"] == p["unique"], f"{table}: unique constraints drifted"
