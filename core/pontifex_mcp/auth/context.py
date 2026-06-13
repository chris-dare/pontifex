"""Resolves the active CallerIdentity for a tool invocation.

Two paths:
- HTTP / Streamable HTTP: AuthMiddleware sets `request.state.caller` per request;
  this module reads it via the MCP Context's request_context.
- stdio: there is no HTTP request. A single identity is loaded at startup from
  env vars and stashed in a ContextVar.

The caller's raw bearer token (the inbound JWT) is tracked the same two ways,
separately from the identity — it is the `subject_token` for downstream OAuth
token exchange (RFC 8693). It is deliberately NOT a field on `CallerIdentity`,
which is serialized and cached; keeping the token out of that struct keeps user
bearer tokens from being persisted at rest.
"""

from contextvars import ContextVar
from typing import Any

from pontifex_mcp.auth.identity import CallerIdentity

_stdio_caller: ContextVar[CallerIdentity | None] = ContextVar("stdio_caller", default=None)
_stdio_subject_token: ContextVar[str | None] = ContextVar("stdio_subject_token", default=None)


def set_stdio_caller(identity: CallerIdentity) -> None:
    """Store the stdio-mode identity. Called once at startup before tools run."""
    _stdio_caller.set(identity)


def set_stdio_subject_token(token: str | None) -> None:
    """Store the stdio-mode subject token. Usually None — the local stdio identity
    is static and carries no real user JWT to exchange."""
    _stdio_subject_token.set(token)


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


def resolve_subject_token(ctx: Any) -> str | None:
    """Return the caller's raw bearer token for the current tool call, or None.

    Mirrors :func:`resolve_caller`: for HTTP requests the token lives at
    `ctx.request_context.request.state.subject_token` (set by AuthMiddleware for
    JWT callers; None for API-key callers); for stdio it lives in a ContextVar.
    """
    if ctx is not None:
        try:
            request = ctx.request_context.request
        except (AttributeError, ValueError):
            request = None
        if request is not None:
            state = getattr(request, "state", None)
            token = getattr(state, "subject_token", None)
            if token is not None:
                return token
    return _stdio_subject_token.get()
