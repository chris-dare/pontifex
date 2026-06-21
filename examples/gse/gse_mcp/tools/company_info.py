from typing import Any

from mcp.server.fastmcp import Context, FastMCP
from pontifex_mcp import AuditWriter, InvalidInput, tool_runtime

from gse_mcp.data import AllSourcesUnavailable, GSEDataService
from gse_mcp.tools._helpers import NAMESPACE, envelope

DESCRIPTION = (
    "Get company profile, directors, EPS, DPS, and shares outstanding for a "
    "GSE-listed equity. Data sourced from the equities registry."
)


def register(mcp: FastMCP, data_service: GSEDataService, audit: AuditWriter) -> None:
    @mcp.tool(name="gse_get_company_info", description=DESCRIPTION, structured_output=False)
    @tool_runtime(
        namespace=NAMESPACE,
        tool_name="gse_get_company_info",
        resource="company_info",
        action="read",
        audit=audit,
        source_unavailable_exception=AllSourcesUnavailable,
    )
    async def gse_get_company_info(
        symbol: str,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        sym = symbol.strip().upper()
        if not sym:
            raise InvalidInput("symbol is required.")

        equity, source, cache_hit = await data_service.get_company_info(sym)
        if equity is None:
            raise InvalidInput(f"Unknown GSE ticker: {sym}.")

        return envelope(
            source=source,
            cache_hit=cache_hit,
            payload={"equity": equity.model_dump()},
        )
