"""Output rendering and the CLI exit-code convention.

One place so every command renders human vs ``--json`` the same way and exits
with the same codes. The ``--json`` shape is a stability contract under the
release-process rule, so it lives here rather than per-command.
"""

import json as _json
from enum import IntEnum
from typing import Any, NoReturn

import typer


class ExitCode(IntEnum):
    """Stable process exit codes. Scripts and CI branch on these.

    Note ``INFRA_ERROR`` is ``2``, which coincides with click's own usage-error
    code (a bad/missing command also exits ``2``). Both mean "couldn't run", so
    don't treat ``2`` as uniquely "infra" when branching in CI.
    """

    OK = 0
    USER_ERROR = 1  # bad arguments, not found, conflict
    INFRA_ERROR = 2  # no DATABASE_URL, connection failed


def print_json(data: Any) -> None:
    """Emit ``data`` as indented JSON on stdout. Non-serializable values fall
    back to ``str`` so a command never crashes on rendering."""
    typer.echo(_json.dumps(data, indent=2, default=str))


def fail(message: str, code: ExitCode = ExitCode.USER_ERROR) -> NoReturn:
    """Print ``message`` to stderr and exit with ``code``.

    Raises ``typer.Exit`` directly (return type ``NoReturn``), so a command body
    can call ``fail(...)`` and the type checker knows execution stops there — no
    way to forget a ``raise`` and silently continue past an intended exit.
    """
    typer.echo(message, err=True)
    raise typer.Exit(code=int(code))
