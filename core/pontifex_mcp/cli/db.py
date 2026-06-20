"""`pontifex-mcp db` — database schema management."""

import asyncio
from importlib.resources import as_file, files

import typer

from pontifex_mcp.cli._db import resolve_database_url
from pontifex_mcp.cli._output import print_json
from pontifex_mcp.storage import (
    create_db_engine,
    ensure_sqlite_schema,
    is_sqlite,
    normalize_db_url,
)

app = typer.Typer(no_args_is_help=True, help="Manage the database schema (migrations).")


@app.callback()
def db() -> None:
    """Manage the database schema (migrations)."""


def _upgrade_postgres() -> None:
    """Run the packaged Alembic migrations to the latest head."""
    # Imported lazily so the rest of the CLI doesn't pay alembic's import cost.
    from alembic.config import Config

    from alembic import command

    # Materialize the whole packaged migrations dir (zip-safe) so script_location
    # and version_locations resolve against co-located files.
    with as_file(files("pontifex_mcp.migrations")) as migrations_dir:
        config = Config(str(migrations_dir / "alembic.ini"))
        command.upgrade(config, "heads")


def _upgrade_sqlite(url: str) -> None:
    """Create the tables directly on SQLite (the Postgres-shaped Alembic
    migrations can't run there — no CREATE SCHEMA). Mirrors the server's
    first-boot path; `create_all` is idempotent."""

    async def _run() -> None:
        engine = create_db_engine(url)
        try:
            await ensure_sqlite_schema(engine)
        finally:
            await engine.dispose()

    asyncio.run(_run())


@app.command()
def upgrade(
    json_output: bool = typer.Option(False, "--json", help="Emit the result as JSON."),
) -> None:
    """Create or update the platform schema to the latest revision.

    Idempotent: safe to run twice and to drop into a deploy pipeline. Reads
    `DATABASE_URL`. On Postgres it runs the packaged Alembic migrations; on a
    SQLite file it creates the tables directly (same path the server uses on
    first boot).
    """
    url = normalize_db_url(resolve_database_url())  # clean exit 2 if unset
    backend = "sqlite" if is_sqlite(url) else "postgres"

    if backend == "sqlite":
        _upgrade_sqlite(url)
    else:
        _upgrade_postgres()

    if json_output:
        print_json({"status": "ok", "action": "upgrade", "backend": backend})
    else:
        typer.echo("Schema is up to date.")
