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


class CompanyInfoParams(BaseModel):
    symbol: str = Field(..., description="GSE ticker symbol.")


def register(app: FastAPI, data_service: GSEDataService) -> None:
    @app.post("/tools/gse_get_company_info")
    async def gse_get_company_info(params: CompanyInfoParams, request: Request) -> JSONResponse:
        require_scope(request, "company_info", "read", params=params)

        symbol = params.symbol.strip().upper()
        if not symbol:
            raise invalid_input("symbol is required.")

        try:
            equity, source, cache_hit = await data_service.get_company_info(symbol)
        except AllSourcesUnavailable as exc:
            raise sources_unavailable_error(exc) from exc

        if equity is None:
            raise invalid_input(f"Unknown GSE ticker: {symbol}.")

        return tool_response(
            source=source,
            cache_hit=cache_hit,
            payload={"equity": equity.model_dump()},
        )
