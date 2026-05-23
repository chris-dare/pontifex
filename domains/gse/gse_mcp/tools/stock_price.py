from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from gse_mcp.data import AllSourcesUnavailable, GSEDataService
from gse_mcp.tools._helpers import (
    invalid_input,
    require_scope,
    sources_unavailable_error,
    tool_response,
)


class StockPriceParams(BaseModel):
    symbol: str = Field(..., description="GSE ticker symbol (case-insensitive).")


def register(app: FastAPI, data_service: GSEDataService) -> None:
    @app.post("/tools/gse_get_stock_price")
    async def gse_get_stock_price(params: StockPriceParams, request: Request) -> JSONResponse:
        require_scope(request, "stock_price", "read", params=params)

        symbol = params.symbol.strip().upper()
        if not symbol:
            raise invalid_input("symbol is required.")

        try:
            stock, source, cache_hit = await data_service.get_stock_price(symbol)
        except AllSourcesUnavailable as exc:
            raise sources_unavailable_error(exc) from exc

        if stock is None:
            raise invalid_input(f"Unknown GSE ticker: {symbol}.")

        return tool_response(
            source=source,
            cache_hit=cache_hit,
            payload={"stock": stock.model_dump()},
        )
