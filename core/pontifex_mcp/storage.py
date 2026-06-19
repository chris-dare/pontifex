"""Dialect-aware SQL engine creation for audit / API-key storage.

Two dialects are supported, detected from the connection-string scheme:

  - **SQLite** (`sqlite+aiosqlite://...`) — the zero-config quickstart/local
    store. Tables are created on first use via `create_all` (no Alembic), in a
    single file with no schemas. The models hardcode `schema="core"` for
    Postgres, so for SQLite we translate `core` → the default schema via
    `schema_translate_map`.
  - **Postgres** (`postgresql+asyncpg://...`) — production. Alembic owns the
    schema (schema-per-domain isolation), so we never `create_all` here.

`MySQL is intentionally unsupported.`
"""

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import StaticPool

from pontifex_mcp.models.db import Base

# SQLite has no schemas; map the models' `core` schema to the default one.
_SQLITE_SCHEMA_MAP = {"core": None}


def normalize_db_url(value: str) -> str:
    """Coerce a user-supplied datastore value into an async SQLAlchemy URL.

    - A bare path (`audit.db`, `/tmp/x.sqlite`) → a SQLite file URL.
    - `sqlite://...` / `postgresql://...` / `postgres://...` → the async driver.
    - Anything already carrying an async driver is returned unchanged.
    """
    if "://" not in value:
        return f"sqlite+aiosqlite:///{value}"
    scheme, rest = value.split("://", 1)
    if scheme == "sqlite":
        return f"sqlite+aiosqlite://{rest}"
    if scheme in ("postgresql", "postgres"):
        return f"postgresql+asyncpg://{rest}"
    return value


def is_sqlite(url: str) -> bool:
    return url.startswith("sqlite")


def create_db_engine(url: str) -> AsyncEngine:
    """Build an `AsyncEngine` configured for the URL's dialect.

    For SQLite the engine carries the `core` → default schema translation so the
    Postgres-shaped models work unchanged; an in-memory database additionally
    uses a `StaticPool` so every connection sees the same database.
    """
    if is_sqlite(url):
        kwargs: dict = {"connect_args": {"check_same_thread": False}}
        if ":memory:" in url:
            kwargs["poolclass"] = StaticPool
        engine = create_async_engine(url, **kwargs)
        return engine.execution_options(schema_translate_map=_SQLITE_SCHEMA_MAP)
    return create_async_engine(url, pool_size=5, max_overflow=10)


async def ensure_sqlite_schema(engine: AsyncEngine) -> None:
    """Create the core tables for a SQLite engine. No-op-safe (`checkfirst`).

    Only call this for SQLite — Postgres schemas are owned by Alembic.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
