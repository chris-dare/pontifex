"""Resolves the active CallerIdentity for a tool invocation.

Two paths:
- HTTP / Streamable HTTP: AuthMiddleware sets `request.state.caller` per request;
  this module reads it via the MCP Context's request_context.
- stdio: there is no HTTP request. A single identity is loaded at startup from
  env vars and stashed in a ContextVar.
"""

from contextvars import ContextVar
from typing import Any

from mcp_core.auth.identity import CallerIdentity

_stdio_caller: ContextVar[CallerIdentity | None] = ContextVar("stdio_caller", default=None)


def set_stdio_caller(identity: CallerIdentity) -> None:
    """Store the stdio-mode identity. Called once at startup before tools run."""
    _stdio_caller.set(identity)


def resolve_caller(ctx: Any) -> CallerIdentity | None:
    """Return the CallerIdentity for the current tool call, or None.

    `ctx` is an `mcp.server.fastmcp.Context`. For HTTP requests the resolved
    identity lives at `ctx.request_context.request.state.caller`. For stdio it
    lives in the module-level ContextVar.
    """
    if ctx is not None:
        try:
            request = ctx.request_context.request
        except (AttributeError, ValueError):
            request = None
        if request is not None:
            caller = getattr(getattr(request, "state", None), "caller", None)
            if caller is not None:
                return caller
    return _stdio_caller.get()
