"""Backend authentication strategies for OpenAPI connectors.

These describe how the generated adapter authenticates to the *downstream*
API — unrelated to how MCP callers authenticate to Pontifex. Credentials are
read from the environment on every request (rotation-friendly), but presence
is checked at construction time so a missing secret fails at startup.

`headers()` is async and receives an :class:`AuthContext` (the calling user's
subject token + identity). The env-based strategies ignore it; the token-
exchange strategy needs it to mint a per-user downstream credential.
"""

import os
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from pontifex_mcp.auth.identity import CallerIdentity


@dataclass(frozen=True)
class AuthContext:
    """Per-call context handed to a backend-auth strategy.

    `subject_token` is the caller's inbound JWT (None for API-key callers and on
    health checks). `caller` is the resolved identity, for cache keying / error
    messages. An empty `AuthContext()` is what health checks pass — a strategy
    that needs a user token must degrade to no-auth here, never raise.
    """

    subject_token: str | None = None
    caller: CallerIdentity | None = None


@runtime_checkable
class BackendAuth(Protocol):
    """Produces the auth headers for each downstream request."""

    async def headers(self, ctx: AuthContext) -> dict[str, str]: ...


def _require_env(env_var: str) -> None:
    if not os.environ.get(env_var):
        raise ValueError(f"environment variable {env_var} is not set (required for backend auth)")


class BearerFromEnv:
    """`Authorization: Bearer <token>` with the token read from an env var."""

    def __init__(self, env_var: str) -> None:
        _require_env(env_var)
        self.env_var = env_var

    async def headers(self, ctx: AuthContext) -> dict[str, str]:
        return {"Authorization": f"Bearer {os.environ[self.env_var]}"}


class HeaderFromEnv:
    """A static header (e.g. `X-API-Key`) with the value read from an env var."""

    def __init__(self, header: str, env_var: str) -> None:
        _require_env(env_var)
        self.header = header
        self.env_var = env_var

    async def headers(self, ctx: AuthContext) -> dict[str, str]:
        return {self.header: os.environ[self.env_var]}
