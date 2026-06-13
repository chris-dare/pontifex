"""ASGI entrypoint for the Pontifex HTTP MCP server in the e2e stack.

Connectors-only (no hand-written tools): tools come from
PONTIFEX_CONNECTORS_CONFIG, which defines a `token_exchange` connector against
the downstream billing API. JWT auth (AUTH_*) points at Keycloak.
"""

from pontifex_mcp import CoreSettings, create_mcp_http_app


async def _health() -> dict[str, str]:
    return {"status": "ok"}


settings = CoreSettings()
app = create_mcp_http_app(
    "e2e",
    settings,
    register_tools=lambda mcp, audit: None,
    health_check=_health,
)
