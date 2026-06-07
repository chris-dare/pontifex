# pontifex-mcp

**Build enterprise-grade [MCP](https://modelcontextprotocol.io) servers — the cross-cutting concerns handled for you.**

Bring a domain (your tools + the data behind them); `pontifex-mcp` brings the parts every serious MCP server needs:

- **Auth, two ways** — `sk_…` API keys for scripts/CI **and** OAuth 2.1 JWTs (Auth0, Entra, Clerk, Keycloak — any OIDC provider) for interactive clients like Claude Desktop. Both resolve to one `CallerIdentity`.
- **Scope enforcement** — `domain:resource:action` permissions checked before every tool call.
- **Rate limiting** — per-caller, Redis-backed.
- **Audit logging** — every call recorded (who, what, when, which data source, cache hit, latency).
- **Resilient data adapters** — a `DataAdapter` protocol with failover + circuit breaking across sources.
- **Observability** — Logfire/OpenTelemetry wiring.
- **Discovery** — RFC 9728 protected-resource metadata + `WWW-Authenticate` so MCP clients bootstrap OAuth on their own.

> **Status:** `0.x` — building in public. The public API (everything exported from `pontifex_mcp`) is stabilising; expect occasional breaking changes before `1.0`.

## Install

```bash
pip install pontifex-mcp     # or: uv add pontifex-mcp
```

Requires Python 3.12+, Postgres, and Redis.

## Build your own domain

A domain is: a settings class, one or more data adapters, and tools wrapped with `tool_runtime`. Everything below comes from the top-level package.

```python
from typing import Any

from mcp.server.fastmcp import Context, FastMCP
from pontifex_mcp import (
    AuditWriter,
    CoreSettings,
    create_mcp_http_app,
    tool_runtime,
)


class WeatherSettings(CoreSettings):
    weather_api_base: str = "https://api.example-weather.com"


def register_tools(mcp: FastMCP, audit: AuditWriter) -> None:
    @mcp.tool(name="weather_get_forecast", description="Get the forecast for a city.")
    @tool_runtime(
        domain="weather",
        tool_name="weather_get_forecast",
        resource="forecast",     # scope checked: weather:forecast:read
        action="read",
        audit=audit,
    )
    async def get_forecast(city: str, ctx: Context | None = None) -> dict[str, Any]:
        # ... fetch data (ideally through a DataAdapter) ...
        return {"source": "example-weather", "cache_hit": False, "city": city, "high_c": 31}


async def health() -> dict[str, Any]:
    return {"status": "ok"}


settings = WeatherSettings()
app = create_mcp_http_app("weather", settings, register_tools, health)
# `uv run uvicorn your_module:app` → MCP endpoint at /mcp, health at /health/ready
```

Auth, scope checks, rate limiting, the audit row, and the structured error envelope are all applied by `tool_runtime` and the server's middleware — your handler just returns data.

### Configuration

Infrastructure settings read from bare, unprefixed env vars:

```
DATABASE_URL, REDIS_URL          # required (the app fails fast if unset)
AUTH_JWKS_URL, AUTH_ISSUER, AUTH_AUDIENCE, AUTH_SCOPES_CLAIM   # enable the OAuth/JWT path
PUBLIC_BASE_URL                  # canonical URL advertised in OAuth discovery
```

Domain-specific settings on your subclass read with your domain's `env_prefix`.

## Example

See the **GSE** (Ghana Stock Exchange) reference server in [`domains/gse`](../domains/gse) for a complete, deployed example — multiple tools, multiple data adapters with failover, and a Fly.io deployment.

## License

MIT © Chris Dare. Part of [Argonauts](https://argonauts.chrisdare.me).
