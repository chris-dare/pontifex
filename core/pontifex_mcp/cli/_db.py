"""Shared data-command plumbing: DATABASE_URL resolution, engine building, and
running an ``async def`` command body from Typer's sync call.

Commands that touch the database resolve ``DATABASE_URL`` through here so the
error and exit code are identical everywhere, and they get SQLite/Postgres
parity for free via ``storage.create_db_engine``.
"""

import asyncio
import functools
import os
from collections.abc import Callable, Coroutine
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine

from pontifex_mcp.cli._output import ExitCode, fail
from pontifex_mcp.storage import create_db_engine, normalize_db_url


def resolve_database_url() -> str:
    """Return ``DATABASE_URL`` from the environment, or exit 2 if unset."""
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise fail(
            "DATABASE_URL is not set. Point it at a SQLite file "
            "(sqlite+aiosqlite:///pontifex.db) or a Postgres URL.",
            ExitCode.INFRA_ERROR,
        )
    return url


def get_engine() -> AsyncEngine:
    """Build an ``AsyncEngine`` for ``DATABASE_URL`` (SQLite or Postgres)."""
    return create_db_engine(normalize_db_url(resolve_database_url()))


def async_command[T](fn: Callable[..., Coroutine[Any, Any, T]]) -> Callable[..., T]:
    """Adapt an ``async def`` command body to Typer's sync calling convention.

    Typer reads the wrapped function's signature for its options/arguments
    (``functools.wraps`` preserves it), then this runs the coroutine to
    completion with ``asyncio.run``.
    """

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> T:
        return asyncio.run(fn(*args, **kwargs))

    return wrapper
