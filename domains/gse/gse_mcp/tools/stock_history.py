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


class StockHistoryParams(BaseModel):
    symbol: str = Field(..., description="GSE ticker symbol.")
    days: int = Field(default=30, ge=1, le=365)


def register(app: FastAPI, data_service: GSEDataService) -> None:
    @app.post("/tools/gse_get_stock_history")
    async def gse_get_stock_history(params: StockHistoryParams, request: Request) -> JSONResponse:
        require_scope(request, "stock_history", "read", params=params)

        symbol = params.symbol.strip().upper()
        if not symbol:
            raise invalid_input("symbol is required.")

        try:
            entries, source, cache_hit = await data_service.get_stock_history(symbol, params.days)
        except AllSourcesUnavailable as exc:
            raise sources_unavailable_error(exc) from exc

        return tool_response(
            source=source,
            cache_hit=cache_hit,
            payload={
                "symbol": symbol,
                "days": params.days,
                "entries": [e.model_dump() for e in entries],
            },
        )
