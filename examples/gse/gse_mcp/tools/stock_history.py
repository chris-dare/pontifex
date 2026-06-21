from typing import Any

from mcp.server.fastmcp import Context, FastMCP
from pontifex_mcp import AuditWriter, InvalidInput, tool_runtime

from gse_mcp.data import AllSourcesUnavailable, GSEDataService
from gse_mcp.tools._helpers import NAMESPACE, envelope

DESCRIPTION = "Get historical end-of-day prices for a GSE-listed stock."


def register(mcp: FastMCP, data_service: GSEDataService, audit: AuditWriter) -> None:
    @mcp.tool(name="gse_get_stock_history", description=DESCRIPTION, structured_output=False)
    @tool_runtime(
        namespace=NAMESPACE,
        tool_name="gse_get_stock_history",
        resource="stock_history",
        action="read",
        audit=audit,
        source_unavailable_exception=AllSourcesUnavailable,
    )
    async def gse_get_stock_history(
        symbol: str,
        days: int = 30,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        sym = symbol.strip().upper()
        if not sym:
            raise InvalidInput("symbol is required.")
        if days < 1 or days > 365:
            raise InvalidInput("days must be between 1 and 365.")

        entries, source, cache_hit = await data_service.get_stock_history(sym, days)

        return envelope(
            source=source,
            cache_hit=cache_hit,
            payload={
                "symbol": sym,
                "days": days,
                "entries": [e.model_dump() for e in entries],
            },
        )
