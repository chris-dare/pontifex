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
import inspect
import time
from collections.abc import Awaitable, Callable
from typing import Any

from mcp import types
from mcp.server.fastmcp import Context
from mcp.server.fastmcp.utilities.context_injection import find_context_parameter

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


def _scope_denied(namespace: str, resource: str, action: str) -> types.CallToolResult:
    return _error_result(
        ToolError(
            error_code="scope_denied",
            message=(
                f"API key missing scope: {namespace}:{resource}:{action}. "
                f"Request a key with {namespace}:{resource}:{action}, "
                f"{namespace}:*:{action}, or {namespace}:*:*."
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
    namespace: str,
    tool_name: str,
    resource: str | None,
    action: str | None,
    audit: AuditWriter,
    source_unavailable_exception: type[BaseException] | None = None,
) -> Callable[[Callable[..., Awaitable[dict]]], Callable[..., Awaitable[Any]]]:
    """Wrap an MCP tool function.

    `source_unavailable_exception` lets a namespace plug in its own "all sources
    failed" exception type (e.g., `AllSourcesUnavailable` in the GSE namespace).

    When `resource`/`action` are None the tool declared no scope, so the scope
    check is skipped (the call is still audited and still requires a resolved
    caller). A declared scope is always enforced against the caller.

    Caller resolution needs the MCP `Context` (it carries the HTTP request). If
    the wrapped tool doesn't declare a `Context` parameter, the wrapper advertises
    one on its own signature so FastMCP injects it, then strips it before calling
    the tool — so a plain `async def f(x: int)` still resolves the HTTP caller.
    """

    def decorator(fn: Callable[..., Awaitable[dict]]) -> Callable[..., Awaitable[Any]]:
        ctx_param = find_context_parameter(fn)
        fn_has_ctx = ctx_param is not None
        ctx_key = ctx_param or "ctx"

        @functools.wraps(fn)
        async def wrapper(*args: object, **kwargs: object) -> Any:
            ctx = kwargs.get(ctx_key)
            tool_params = {k: v for k, v in kwargs.items() if k != ctx_key}

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
                if (
                    resource is not None
                    and action is not None
                    and not caller.can_use_tool(namespace, resource, action)
                ):
                    error = "scope_denied"
                    return _scope_denied(namespace, resource, action)

                # Don't pass the injected ctx to a tool that didn't ask for one.
                call_kwargs = (
                    kwargs if fn_has_ctx else {k: v for k, v in kwargs.items() if k != "ctx"}
                )
                result = await fn(*args, **call_kwargs)

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
                    namespace=namespace,
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

        if not fn_has_ctx:
            # Advertise a `ctx` parameter so FastMCP injects the Context. It must
            # appear on both the signature (schema building) and the annotations
            # (`find_context_parameter` uses `get_type_hints`); it's keyword-only
            # with a default so it never affects the tool's input schema.
            #
            # `eval_str=True` resolves the tool's annotations in *its* module, so
            # the rebuilt signature carries real types even under
            # `from __future__ import annotations` (FastMCP won't re-eval an
            # explicit `__signature__`).
            try:
                sig = inspect.signature(fn, eval_str=True)
            except Exception:
                sig = inspect.signature(fn)
            if "ctx" in sig.parameters:
                fn_name = getattr(fn, "__name__", "<tool>")
                raise TypeError(
                    f"Tool {fn_name!r} has a 'ctx' parameter that isn't typed as "
                    "Context. Rename it, or annotate it as Context so it receives the "
                    "MCP context."
                )
            ctx_param_obj = inspect.Parameter(
                "ctx",
                inspect.Parameter.KEYWORD_ONLY,
                default=None,
                annotation=Context | None,
            )
            params = list(sig.parameters.values())
            # A VAR_KEYWORD (**kwargs) must stay last; insert ctx before it.
            insert_at = next(
                (i for i, p in enumerate(params) if p.kind is inspect.Parameter.VAR_KEYWORD),
                len(params),
            )
            params.insert(insert_at, ctx_param_obj)
            wrapper.__signature__ = sig.replace(parameters=params)  # ty: ignore[unresolved-attribute]
            annotations = {
                name: p.annotation
                for name, p in sig.parameters.items()
                if p.annotation is not inspect.Parameter.empty
            }
            annotations["ctx"] = Context | None
            wrapper.__annotations__ = annotations

        return wrapper

    return decorator
