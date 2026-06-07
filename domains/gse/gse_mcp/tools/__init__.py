from mcp.server.fastmcp import FastMCP
from pontifex_mcp import AuditWriter

from gse_mcp.data import GSEDataService
from gse_mcp.tools.company_info import register as register_company_info
from gse_mcp.tools.live_prices import register as register_live_prices
from gse_mcp.tools.market_summary import register as register_market_summary
from gse_mcp.tools.stock_history import register as register_stock_history
from gse_mcp.tools.stock_price import register as register_stock_price


def register_gse_tools(mcp: FastMCP, data_service: GSEDataService, audit: AuditWriter) -> None:
    """Register all GSE MCP tools on the FastMCP server."""
    register_live_prices(mcp, data_service, audit)
    register_stock_price(mcp, data_service, audit)
    register_stock_history(mcp, data_service, audit)
    register_market_summary(mcp, data_service, audit)
    register_company_info(mcp, data_service, audit)
