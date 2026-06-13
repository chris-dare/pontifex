"""Tool-call runtime: scope enforcement, structured error envelope, audit hook.

Wrap a tool function with `tool_runtime(...)` and FastMCP will introspect the
inner signature for the input schema (via functools.wraps), while the wrapper
handles:
  - Caller resolution (HTTP or stdio).
  - Scope check; deny → CallToolResult(isError=True, ToolError).
  - Per-tool audit row (caller, params, data_source, cache_hit, ms, error).
  - Translation of known exceptions to the spec's six error codes.
  - Catch-all for unexpected exceptions → internal_error.

Tools return a JSON-serializable dict that includes `source` and `cache_hit`
keys (the standard ToolResponse envelope). The wrapper reads those for audit.
"""

import functools
import time
from collections.abc import Awaitable, Callable
from typing import Any

from mcp import types

from pontifex_mcp.audit import AuditWriter
from pontifex_mcp.auth.context import resolve_caller
from pontifex_mcp.models.base import ToolError


class InvalidInput(Exception):
    """Raise inside a tool when input is bad in a way the schema didn't catch."""


def _error_result(error: ToolError) -> types.CallToolResult:
    content: list[
        types.TextContent
        | types.ImageContent
        | types.AudioContent
        | types.ResourceLink
        | types.EmbeddedResource
    ] = [types.TextContent(type="text", text=error.model_dump_json())]
    return types.CallToolResult(content=content, isError=True)


def _auth_failed() -> types.CallToolResult:
    return _error_result(
        ToolError(
            error_code="auth_failed",
            message="No authenticated identity for this tool call. "
            "Provide a valid 'Authorization: Bearer <key>' header or configure stdio identity.",
            status=401,
            retry=False,
        )
    )


def _scope_denied(domain: str, resource: str, action: str) -> types.CallToolResult:
    return _error_result(
        ToolError(
            error_code="scope_denied",
            message=(
                f"API key missing scope: {domain}:{resource}:{action}. "
                f"Request a key with {domain}:{resource}:{action}, "
                f"{domain}:*:{action}, or {domain}:*:*."
            ),
            status=403,
            retry=False,
        )
    )


def _invalid_input(message: str) -> types.CallToolResult:
    return _error_result(
        ToolError(
            error_code="invalid_input",
            message=message,
            status=400,
            retry=False,
        )
    )


def _source_unavailable(detail: str) -> types.CallToolResult:
    return _error_result(
        ToolError(
            error_code="source_unavailable",
            message="All data sources are currently unavailable. Retry in 30 seconds.",
            status=503,
            retry=True,
            retry_after_seconds=30,
            detail=detail,
        )
    )


def _internal_error(detail: str) -> types.CallToolResult:
    return _error_result(
        ToolError(
            error_code="internal_error",
            message="Unexpected server error. Retry in a few seconds.",
            status=500,
            retry=True,
            detail=detail,
        )
    )


def _ip_address(ctx: Any) -> str | None:
    if ctx is None:
        return None
    try:
        request = ctx.request_context.request
        if request is None or request.client is None:
            return None
        return request.client.host
    except (AttributeError, ValueError):
        return None


def tool_runtime(
    *,
    domain: str,
    tool_name: str,
    resource: str,
    action: str,
    audit: AuditWriter,
    source_unavailable_exception: type[BaseException] | None = None,
) -> Callable[[Callable[..., Awaitable[dict]]], Callable[..., Awaitable[Any]]]:
    """Wrap an MCP tool function.

    `source_unavailable_exception` lets a domain plug in its own "all sources
    failed" exception type (e.g., `AllSourcesUnavailable` in the GSE domain).
    """

    def decorator(fn: Callable[..., Awaitable[dict]]) -> Callable[..., Awaitable[Any]]:
        @functools.wraps(fn)
        async def wrapper(*args: object, **kwargs: object) -> Any:
            ctx = kwargs.get("ctx")
            tool_params = {k: v for k, v in kwargs.items() if k != "ctx"}

            start = time.monotonic()
            caller = resolve_caller(ctx)
            data_source = "unknown"
            cache_hit = False
            delegated_audience: str | None = None
            error: str | None = None

            try:
                if caller is None:
                    error = "auth_failed"
                    return _auth_failed()
                if not caller.can_use_tool(domain, resource, action):
                    error = "scope_denied"
                    return _scope_denied(domain, resource, action)

                result = await fn(*args, **kwargs)

                if isinstance(result, dict):
                    data_source = str(result.get("source", "unknown"))
                    cache_hit = bool(result.get("cache_hit", False))
                    audience = result.get("delegated_audience")
                    delegated_audience = str(audience) if audience else None
                return result
            except InvalidInput as exc:
                error = repr(exc)
                return _invalid_input(str(exc))
            except Exception as exc:
                if source_unavailable_exception is not None and isinstance(
                    exc, source_unavailable_exception
                ):
                    error = repr(exc)
                    return _source_unavailable(str(exc))
                error = repr(exc)
                return _internal_error(repr(exc))
            finally:
                elapsed_ms = int((time.monotonic() - start) * 1000)
                key_id = caller.key_id if caller else "anonymous"
                owner_id = caller.owner_id if caller else "anonymous"
                owner_label = caller.owner_label if caller else "Anonymous"
                transport = caller.transport if caller else "unknown"
                await audit.write(
                    domain=domain,
                    key_id=key_id,
                    owner_id=owner_id,
                    owner_label=owner_label,
                    transport=transport,
                    tool_name=tool_name,
                    tool_params=tool_params,
                    data_source=data_source,
                    cache_hit=cache_hit,
                    response_ms=elapsed_ms,
                    error=error,
                    ip_address=_ip_address(ctx),
                    delegated_audience=delegated_audience,
                )

        return wrapper

    return decorator
