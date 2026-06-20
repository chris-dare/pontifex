"""`pontifex-mcp keys` — API key management.

Commands land in #88 (`keys create` / `list` / `revoke`). The callback keeps the
group resolvable (`pontifex-mcp keys --help`) before any command exists.
"""

import typer

app = typer.Typer(no_args_is_help=True, help="Create, list, and revoke API keys.")


@app.callback()
def keys() -> None:
    """Create, list, and revoke API keys."""
