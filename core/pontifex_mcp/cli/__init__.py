"""`pontifex-mcp` — the operational CLI for a Pontifex MCP server.

Noun-verb structure (`pontifex-mcp <resource> <action>`) mirroring the
`namespace:resource:action` scope model. Adding a resource is dropping one module
under `cli/` and registering it here; nothing else changes.
"""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version

import typer

from pontifex_mcp.cli import db, keys

app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
    help="Manage a Pontifex MCP server's database and API keys.",
)
app.add_typer(db.app, name="db")
app.add_typer(keys.app, name="keys")


def _package_version() -> str:
    try:
        return _pkg_version("pontifex-mcp")
    except PackageNotFoundError:  # running from a source tree without an install
        return "0.0.0+unknown"


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(_package_version())
        raise typer.Exit()


@app.callback()
def main_callback(
    version: bool = typer.Option(
        None,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show the version and exit.",
    ),
) -> None:
    """Manage a Pontifex MCP server's database and API keys."""


def main() -> None:
    """Console-script entry point (`pontifex-mcp`)."""
    app()
