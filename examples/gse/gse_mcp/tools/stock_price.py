from typing import Any

from mcp.server.fastmcp import Context, FastMCP
from pontifex_mcp import AuditWriter, InvalidInput, tool_runtime

from gse_mcp.data import AllSourcesUnavailable, GSEDataService
from gse_mcp.tools._helpers import NAMESPACE, envelope

DESCRIPTION = (
    "Get current price, change, and volume for a specific stock on the Ghana Stock Exchange."
)


def register(mcp: FastMCP, data_service: GSEDataService, audit: AuditWriter) -> None:
    @mcp.tool(name="gse_get_stock_price", description=DESCRIPTION, structured_output=False)
    @tool_runtime(
        namespace=NAMESPACE,
        tool_name="gse_get_stock_price",
        resource="stock_price",
        action="read",
        audit=audit,
        source_unavailable_exception=AllSourcesUnavailable,
    )
    async def gse_get_stock_price(
        symbol: str,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        sym = symbol.strip().upper()
        if not sym:
            raise InvalidInput("symbol is required.")

        stock, source, cache_hit = await data_service.get_stock_price(sym)
        if stock is None:
            raise InvalidInput(f"Unknown GSE ticker: {sym}.")

        return envelope(
            source=source,
            cache_hit=cache_hit,
            payload={"stock": stock.model_dump()},
        )
