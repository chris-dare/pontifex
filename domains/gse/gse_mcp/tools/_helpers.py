from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from mcp_core.auth.identity import CallerIdentity
from mcp_core.middleware.auth import get_caller
from mcp_core.models.base import ToolError

from gse_mcp.data import AllSourcesUnavailable, is_trading_hours

DOMAIN = "gse"


def require_scope(request: Request, resource: str, action: str = "read") -> CallerIdentity:
    """Resolve the caller and enforce a single-resource scope check."""
    caller = get_caller(request)
    if not caller.can_use_tool(DOMAIN, resource, action):
        raise HTTPException(
            status_code=403,
            detail=ToolError(
                error_code="scope_denied",
                message=(
                    f"API key missing scope: {DOMAIN}:{resource}:{action}. "
                    f"Request a key with {DOMAIN}:{resource}:{action}, "
                    f"{DOMAIN}:*:{action}, or {DOMAIN}:*:*."
                ),
                status=403,
                retry=False,
            ).model_dump(),
        )
    return caller


def tool_response(
    *,
    source: str,
    cache_hit: bool,
    payload: dict[str, Any],
) -> JSONResponse:
    """Wrap a tool payload with the standard ToolResponse envelope."""
    envelope = {
        "timestamp": datetime.now(UTC).isoformat(),
        "source": source,
        "is_live": is_trading_hours(),
        "cache_hit": cache_hit,
        **payload,
    }
    headers = {
        "X-Data-Source": source,
        "X-Cache-Hit": "true" if cache_hit else "false",
    }
    return JSONResponse(content=envelope, headers=headers)


def sources_unavailable_error(exc: AllSourcesUnavailable) -> HTTPException:
    return HTTPException(
        status_code=503,
        detail=ToolError(
            error_code="source_unavailable",
            message=("All GSE data sources are currently unavailable. Retry in 30 seconds."),
            status=503,
            retry=True,
            retry_after_seconds=30,
            detail=str(exc),
        ).model_dump(),
    )


def invalid_input(message: str) -> HTTPException:
    return HTTPException(
        status_code=400,
        detail=ToolError(
            error_code="invalid_input",
            message=message,
            status=400,
            retry=False,
        ).model_dump(),
    )
