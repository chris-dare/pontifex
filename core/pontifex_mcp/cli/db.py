"""`pontifex-mcp db` — database schema management.

Commands land in #87 (`db upgrade`). The callback keeps the group resolvable
(`pontifex-mcp db --help`) before any command exists.
"""

import typer

app = typer.Typer(no_args_is_help=True, help="Manage the database schema (migrations).")


@app.callback()
def db() -> None:
    """Manage the database schema (migrations)."""
