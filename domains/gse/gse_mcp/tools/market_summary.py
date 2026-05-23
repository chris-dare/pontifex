from typing import Any

from mcp.server.fastmcp import Context, FastMCP
from mcp_core.audit import AuditWriter
from mcp_core.tool_runtime import tool_runtime

from gse_mcp.data import AllSourcesUnavailable, GSEDataService
from gse_mcp.tools._helpers import DOMAIN, envelope

DESCRIPTION = (
    "Get today's GSE market summary: composite index, total volume, turnover, gainers, losers."
)


def register(mcp: FastMCP, data_service: GSEDataService, audit: AuditWriter) -> None:
    @mcp.tool(name="gse_get_market_summary", description=DESCRIPTION, structured_output=False)
    @tool_runtime(
        domain=DOMAIN,
        tool_name="gse_get_market_summary",
        resource="market_summary",
        action="read",
        audit=audit,
        source_unavailable_exception=AllSourcesUnavailable,
    )
    async def gse_get_market_summary(ctx: Context | None = None) -> dict[str, Any]:
        summary, source, cache_hit = await data_service.get_market_summary()
        payload = summary.model_dump(mode="json") if summary else {}
        return envelope(source=source, cache_hit=cache_hit, payload=payload)
