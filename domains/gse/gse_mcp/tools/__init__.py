from fastapi import FastAPI

from gse_mcp.data import GSEDataService
from gse_mcp.tools.company_info import register as register_company_info
from gse_mcp.tools.live_prices import register as register_live_prices
from gse_mcp.tools.market_summary import register as register_market_summary
from gse_mcp.tools.stock_history import register as register_stock_history
from gse_mcp.tools.stock_price import register as register_stock_price


def register_gse_tools(app: FastAPI, data_service: GSEDataService) -> None:
    """Register all GSE MCP tools on the FastAPI app at /tools/{tool_name}."""
    register_live_prices(app, data_service)
    register_stock_price(app, data_service)
    register_stock_history(app, data_service)
    register_market_summary(app, data_service)
    register_company_info(app, data_service)
