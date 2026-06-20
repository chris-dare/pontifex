"""CLI scaffold: entry point, version, group resolution, and the shared
data-command plumbing (DATABASE_URL resolution + the async adapter).

The actual commands land in #87 (`db upgrade`) and #88 (`keys`); these lock the
conventions every later command inherits."""

from importlib.metadata import version

import pytest
import typer
from pontifex_mcp.cli import app
from pontifex_mcp.cli._db import async_command, resolve_database_url
from pontifex_mcp.cli._output import ExitCode
from typer.testing import CliRunner

runner = CliRunner()


def test_version_prints_package_version():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.output.strip() == version("pontifex-mcp")


def test_root_help_lists_groups():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "db" in result.output
    assert "keys" in result.output


def test_no_args_shows_help():
    """A bare invocation prints help (Typer's `no_args_is_help`). The exit code
    is click's usage-error 2 for "no command given", not a command outcome."""
    result = runner.invoke(app, [])
    assert "Usage" in result.output
    assert result.exit_code == 2


@pytest.mark.parametrize("group", ["db", "keys"])
def test_group_help_resolves(group):
    result = runner.invoke(app, [group, "--help"])
    assert result.exit_code == 0
    assert "Usage" in result.output


def test_resolve_database_url_missing_exits_infra(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(typer.Exit) as exc:
        resolve_database_url()
    assert exc.value.exit_code == int(ExitCode.INFRA_ERROR)


def test_resolve_database_url_present_returns_it(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///x.db")
    assert resolve_database_url() == "sqlite+aiosqlite:///x.db"


def test_async_command_preserves_signature_and_runs():
    """The async adapter must keep the wrapped signature so Typer still parses
    arguments, and must run the coroutine to completion. #87/#88 depend on this."""
    sub = typer.Typer()
    seen: dict[str, str] = {}

    @sub.command()
    @async_command
    async def greet(name: str) -> None:
        seen["name"] = name

    result = runner.invoke(sub, ["world"])
    assert result.exit_code == 0
    assert seen["name"] == "world"
