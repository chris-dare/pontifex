"""Backend authentication strategies for OpenAPI connectors.

These describe how the generated adapter authenticates to the *downstream*
API — unrelated to how MCP callers authenticate to Pontifex. Credentials are
read from the environment on every request (rotation-friendly), but presence
is checked at construction time so a missing secret fails at startup.
"""

import os
from typing import Protocol, runtime_checkable


@runtime_checkable
class BackendAuth(Protocol):
    """Produces the auth headers for each downstream request."""

    def headers(self) -> dict[str, str]: ...


def _require_env(env_var: str) -> None:
    if not os.environ.get(env_var):
        raise ValueError(f"environment variable {env_var} is not set (required for backend auth)")


class BearerFromEnv:
    """`Authorization: Bearer <token>` with the token read from an env var."""

    def __init__(self, env_var: str) -> None:
        _require_env(env_var)
        self.env_var = env_var

    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {os.environ[self.env_var]}"}


class HeaderFromEnv:
    """A static header (e.g. `X-API-Key`) with the value read from an env var."""

    def __init__(self, header: str, env_var: str) -> None:
        _require_env(env_var)
        self.header = header
        self.env_var = env_var

    def headers(self) -> dict[str, str]:
        return {self.header: os.environ[self.env_var]}
