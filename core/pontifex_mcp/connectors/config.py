"""Declarative connector registration from a YAML config file.

Lets a deployment onboard an API with config alone — no namespace code. The file
shape (see deploy/connectors.example.yaml):

    connectors:
      - namespace: orders
        spec: https://api.internal/openapi.json
        base_url: https://api.internal
        auth:
          type: bearer_env          # or header_env (with `header:`)
          env_var: ORDERS_API_TOKEN
        include:
          - GET /orders/{id}
          - GET /orders

The server factory loads this automatically when `PONTIFEX_CONNECTORS_CONFIG`
points at such a file; each entry runs through `register_openapi_tools`.
"""

from pathlib import Path
from typing import Literal

import yaml
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, model_validator

from pontifex_mcp.adapters.manager import DataSourceManager
from pontifex_mcp.audit import AuditWriter
from pontifex_mcp.connectors.auth import BackendAuth, BearerFromEnv, HeaderFromEnv
from pontifex_mcp.connectors.register import register_openapi_tools
from pontifex_mcp.connectors.token_exchange import TokenExchange


class ConnectorAuth(BaseModel):
    """Backend-auth config. Fields are validated per `type`:

    - `bearer_env` / `header_env`: service credential from `env_var`
      (`header_env` also needs `header`). One identity for all callers.
    - `token_exchange`: per-user RFC 8693 exchange — needs `token_endpoint`,
      `audience`, and the `client_id_env` / `client_secret_env` for Pontifex's
      own IdP client.
    """

    type: Literal["bearer_env", "header_env", "token_exchange"]
    # bearer_env / header_env
    env_var: str = ""
    header: str = ""
    # token_exchange
    token_endpoint: str = ""
    audience: str = ""
    client_id_env: str = ""
    client_secret_env: str = ""
    client_auth: Literal["post", "basic"] = "post"
    default_ttl_seconds: int | None = None

    @model_validator(mode="after")
    def _validate_per_type(self) -> "ConnectorAuth":
        if self.type in ("bearer_env", "header_env") and not self.env_var:
            raise ValueError(f"auth type '{self.type}' requires 'env_var'")
        if self.type == "header_env" and not self.header:
            raise ValueError("auth type 'header_env' requires a 'header' name")
        if self.type == "token_exchange":
            missing = [
                f
                for f in ("token_endpoint", "audience", "client_id_env", "client_secret_env")
                if not getattr(self, f)
            ]
            if missing:
                raise ValueError(f"auth type 'token_exchange' requires: {', '.join(missing)}")
        return self

    def build(self) -> BackendAuth:
        if self.type == "bearer_env":
            return BearerFromEnv(self.env_var)
        if self.type == "header_env":
            return HeaderFromEnv(self.header, self.env_var)
        return TokenExchange(
            token_endpoint=self.token_endpoint,
            audience=self.audience,
            client_id_env=self.client_id_env,
            client_secret_env=self.client_secret_env,
            client_auth=self.client_auth,
            default_ttl_seconds=self.default_ttl_seconds,
        )


class ConnectorEntry(BaseModel):
    namespace: str
    spec: str
    base_url: str
    include: list[str]
    allow_mutations: bool = False
    names: dict[str, str] = {}
    timeout_seconds: float = 10.0
    auth: ConnectorAuth | None = None


class ConnectorsConfig(BaseModel):
    connectors: list[ConnectorEntry]


def load_connectors_config(path: str | Path) -> ConnectorsConfig:
    data = yaml.safe_load(Path(path).read_text())
    return ConnectorsConfig.model_validate(data)


def register_connectors_from_config(
    mcp: FastMCP,
    audit: AuditWriter,
    path: str | Path,
) -> dict[str, DataSourceManager]:
    """Register every connector in the config file; returns managers by namespace."""
    config = load_connectors_config(path)
    managers: dict[str, DataSourceManager] = {}
    for entry in config.connectors:
        managers[entry.namespace] = register_openapi_tools(
            mcp,
            spec=entry.spec,
            namespace=entry.namespace,
            base_url=entry.base_url,
            audit=audit,
            include=entry.include,
            auth=entry.auth.build() if entry.auth else None,
            allow_mutations=entry.allow_mutations,
            names=entry.names,
            timeout_seconds=entry.timeout_seconds,
        )
    return managers
