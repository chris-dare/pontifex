from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from gse_mcp.data import AllSourcesUnavailable, GSEDataService
from gse_mcp.tools._helpers import (
    require_scope,
    sources_unavailable_error,
    tool_response,
)


class MarketSummaryParams(BaseModel):
    pass


def register(app: FastAPI, data_service: GSEDataService) -> None:
    @app.post("/tools/gse_get_market_summary")
    async def gse_get_market_summary(
        params: MarketSummaryParams, request: Request
    ) -> JSONResponse:
        require_scope(request, "market_summary", "read")

        try:
            summary, source, cache_hit = await data_service.get_market_summary()
        except AllSourcesUnavailable as exc:
            raise sources_unavailable_error(exc) from exc

        return tool_response(
            source=source,
            cache_hit=cache_hit,
            payload=(summary.model_dump(mode="json") if summary else {}),
        )
