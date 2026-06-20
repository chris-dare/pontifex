"""Alembic env: multi-branch setup with one branch per schema.

Shipped in the wheel and shared by two contexts:
- `pontifex-mcp db upgrade` runs only the `core` branch packaged alongside it
  (the `pontifex_mcp_core.*` tables) — the library's schema.
- The monorepo's `alembic/alembic.ini` points `version_locations` at this same
  `core` branch plus the demo `gse` branch, so contributors get both.

`alembic upgrade heads` advances every branch present. Branches are independent;
a bad migration in `gse` does not touch `core`.
"""

import asyncio
import os
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

_env_url = os.environ.get("DATABASE_URL")
if _env_url:
    config.set_main_option("sqlalchemy.url", _env_url)

target_metadata = None


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_schemas=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_schemas=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section, {})
    url = config.get_main_option("sqlalchemy.url")
    if url is None:
        raise RuntimeError("No database URL configured. Set DATABASE_URL.")
    section["sqlalchemy.url"] = url
    engine = async_engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
