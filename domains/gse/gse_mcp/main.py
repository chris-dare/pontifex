"""GSE MCP entrypoint.

Transport selection via `GSE_MCP_TRANSPORT`:
  - `streamable-http` (default): exposes FastAPI ASGI app `app` for uvicorn.
  - `stdio`: runs the MCP stdio server when this module is executed
    (`python -m gse_mcp.main`).
"""

from mcp.server.fastmcp import FastMCP
from mcp_core.adapters.base import DataAdapter
from mcp_core.adapters.manager import DataSourceManager
from mcp_core.audit import AuditWriter
from mcp_core.cache.redis_cache import Cache
from mcp_core.server_factory import create_mcp_http_app, run_mcp_stdio

from gse_mcp.adapters.gse_official import GSEOfficialAdapter
from gse_mcp.adapters.internal_db import InternalDBAdapter
from gse_mcp.adapters.kwayisi import KwayisiAdapter
from gse_mcp.config import GSESettings
from gse_mcp.data import GSEDataService
from gse_mcp.tools import register_gse_tools

_INSTRUCTIONS = (
    "Ghana Stock Exchange market data — live prices, stock history, "
    "company profiles, and market summaries."
)

settings = GSESettings()

_adapters: list[DataAdapter] = [KwayisiAdapter(settings), InternalDBAdapter(settings)]
if settings.gse_official_base_url and settings.gse_official_api_key:
    _adapters.insert(0, GSEOfficialAdapter(settings))

manager = DataSourceManager(
    _adapters,
    cb_failure_threshold=settings.cb_failure_threshold,
    cb_recovery_timeout=settings.cb_recovery_timeout_seconds,
)

cache = Cache(settings.redis_url, prefix="gse")
data_service = GSEDataService(manager, cache)


def _register(mcp: FastMCP, audit: AuditWriter) -> None:
    register_gse_tools(mcp, data_service, audit)


# Streamable HTTP: import-time FastAPI app for `uvicorn gse_mcp.main:app`.
# In stdio mode this module isn't imported via uvicorn; we run it as a script.
if settings.transport == "stdio":
    app = None  # uvicorn entry not used
else:
    app = create_mcp_http_app(
        domain_name="gse",
        settings=settings,
        register_tools=_register,
        health_check=manager.health_summary,
        instructions=_INSTRUCTIONS,
    )


def main() -> None:
    """Script entrypoint. Selects transport based on settings."""
    if settings.transport == "stdio":
        run_mcp_stdio(
            domain_name="gse",
            settings=settings,
            register_tools=_register,
            instructions=_INSTRUCTIONS,
        )
    else:
        import uvicorn

        uvicorn.run(
            "gse_mcp.main:app",
            host=settings.host,
            port=settings.port,
            log_level=settings.log_level.lower(),
        )


if __name__ == "__main__":
    main()
