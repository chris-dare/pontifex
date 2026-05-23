from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from gse_mcp.data import AllSourcesUnavailable, GSEDataService
from gse_mcp.tools._helpers import (
    require_scope,
    sources_unavailable_error,
    tool_response,
)

SECTORS = {"financials", "consumer_goods", "industrials", "oil_and_gas", "technology", "all"}
SORTS = {"symbol", "price", "change", "volume"}


class LivePricesParams(BaseModel):
    sector: str = Field(default="all")
    sort_by: str = Field(default="symbol")


def register(app: FastAPI, data_service: GSEDataService) -> None:
    @app.post("/tools/gse_get_live_prices")
    async def gse_get_live_prices(params: LivePricesParams, request: Request) -> JSONResponse:
        require_scope(request, "live_prices", "read", params=params)

        sector = params.sector.lower()
        sort_by = params.sort_by.lower()
        if sector not in SECTORS or sort_by not in SORTS:
            sector = "all"
            sort_by = "symbol"

        try:
            stocks, source, cache_hit = await data_service.get_live_prices()
        except AllSourcesUnavailable as exc:
            raise sources_unavailable_error(exc) from exc

        if sector != "all":
            stocks = [s for s in stocks if (s.sector or "").lower() == sector]

        key = sort_by
        reverse = sort_by in {"price", "change", "volume"}
        stocks = sorted(
            stocks,
            key=lambda s: getattr(s, key) if getattr(s, key) is not None else 0,
            reverse=reverse,
        )

        return tool_response(
            source=source,
            cache_hit=cache_hit,
            payload={"stocks": [s.model_dump() for s in stocks]},
        )
