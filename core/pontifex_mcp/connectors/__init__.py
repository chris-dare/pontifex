"""Connectors — auto-generate governed MCP tools from an OpenAPI spec.

Turns operations described by an OpenAPI 3.x spec into tools that run through
the exact same `tool_runtime` seam as hand-written tools: scope check, audit
row, error envelope, and a circuit-broken `DataAdapter` for the downstream
HTTP calls. Auto-generated does not mean ungoverned.

Code-first:

    from pontifex_mcp.connectors import BearerFromEnv, register_openapi_tools

    register_openapi_tools(
        mcp,
        spec="https://api.internal/openapi.json",
        domain="orders",
        base_url="https://api.internal",
        audit=audit,
        auth=BearerFromEnv("ORDERS_API_TOKEN"),
        include=["GET /orders/{id}", "GET /orders"],
    )

Config-first: point `PONTIFEX_CONNECTORS_CONFIG` at a connectors YAML file
(see `pontifex_mcp.connectors.config`) and the server factory registers the
tools at startup — no domain code required.
"""

from pontifex_mcp.connectors.adapter import ConnectorUnavailable, OpenAPIAdapter
from pontifex_mcp.connectors.auth import BackendAuth, BearerFromEnv, HeaderFromEnv
from pontifex_mcp.connectors.config import (
    ConnectorsConfig,
    load_connectors_config,
    register_connectors_from_config,
)
from pontifex_mcp.connectors.register import register_openapi_tools

__all__ = [
    "BackendAuth",
    "BearerFromEnv",
    "ConnectorUnavailable",
    "ConnectorsConfig",
    "HeaderFromEnv",
    "OpenAPIAdapter",
    "load_connectors_config",
    "register_connectors_from_config",
    "register_openapi_tools",
]
