from typing import Any

from mcp.server.fastmcp import Context, FastMCP
from pontifex_mcp import AuditWriter, tool_runtime

from gse_mcp.data import AllSourcesUnavailable, GSEDataService
from gse_mcp.tools._helpers import DOMAIN, envelope

SECTORS = {"financials", "consumer_goods", "industrials", "oil_and_gas", "technology", "all"}
SORTS = {"symbol", "price", "change", "volume"}

DESCRIPTION = (
    "Fetch real-time prices for all stocks on the Ghana Stock Exchange. "
    "Returns price, change, and volume for each equity. Data is from the live "
    "trading session (10:00-15:00 GMT) or the most recent close outside trading hours."
)


def register(mcp: FastMCP, data_service: GSEDataService, audit: AuditWriter) -> None:
    @mcp.tool(name="gse_get_live_prices", description=DESCRIPTION, structured_output=False)
    @tool_runtime(
        domain=DOMAIN,
        tool_name="gse_get_live_prices",
        resource="live_prices",
        action="read",
        audit=audit,
        source_unavailable_exception=AllSourcesUnavailable,
    )
    async def gse_get_live_prices(
        sector: str = "all",
        sort_by: str = "symbol",
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        sector_l = sector.lower() if sector.lower() in SECTORS else "all"
        sort_l = sort_by.lower() if sort_by.lower() in SORTS else "symbol"

        stocks, source, cache_hit = await data_service.get_live_prices()

        if sector_l != "all":
            stocks = [s for s in stocks if (s.sector or "").lower() == sector_l]

        reverse = sort_l in {"price", "change", "volume"}
        stocks = sorted(
            stocks,
            key=lambda s: getattr(s, sort_l) if getattr(s, sort_l) is not None else 0,
            reverse=reverse,
        )

        return envelope(
            source=source,
            cache_hit=cache_hit,
            payload={"stocks": [s.model_dump() for s in stocks]},
        )
