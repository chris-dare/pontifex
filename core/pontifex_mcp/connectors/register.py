"""Generate governed MCP tools from an OpenAPI spec.

Each selected operation becomes a FastMCP tool wrapped in `tool_runtime` —
identical scope check, audit row, and error envelope to a hand-written tool.
The scope is derived from the operation: `domain:resource:action`, where
`resource` is the first static path segment and `action` maps from the verb
(GET→read, POST/PUT/PATCH→write, DELETE→delete).
"""

import inspect
import re
from datetime import UTC, datetime
from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from pontifex_mcp.adapters.manager import DataSourceManager
from pontifex_mcp.audit import AuditWriter
from pontifex_mcp.auth.context import resolve_caller, resolve_subject_token
from pontifex_mcp.connectors.adapter import (
    ConnectorUnavailable,
    DownstreamClientError,
    OpenAPIAdapter,
)
from pontifex_mcp.connectors.auth import AuthContext, BackendAuth
from pontifex_mcp.connectors.spec import (
    Operation,
    load_spec,
    normalize_operation_key,
    parse_operations,
    select_operations,
)
from pontifex_mcp.connectors.token_exchange import TokenExchangeRejected
from pontifex_mcp.tool_runtime import InvalidInput, tool_runtime

# JSON-schema primitive -> Python annotation for the generated signature.
_TYPE_MAP: dict[str, type] = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "array": list,
    "object": dict,
}


def register_openapi_tools(
    mcp: FastMCP,
    *,
    spec: str | dict[str, Any],
    domain: str,
    base_url: str,
    audit: AuditWriter,
    include: list[str],
    auth: BackendAuth | None = None,
    allow_mutations: bool = False,
    names: dict[str, str] | None = None,
    timeout_seconds: float = 10.0,
    cb_failure_threshold: int = 3,
    cb_recovery_timeout_seconds: float = 30.0,
) -> DataSourceManager:
    """Register one governed tool per allowlisted operation in the spec.

    `spec` is a URL, a file path, or an already-parsed dict (JSON or YAML).
    `include` is an explicit allowlist of operations as "VERB /path" entries,
    e.g. ["GET /orders/{id}"]; mutating verbs additionally require
    `allow_mutations=True`. `names` optionally overrides the tool name for an
    included operation (key: "VERB /path", value: name suffix) — useful when
    the spec's operationIds are machine-generated noise (e.g. FastAPI's
    defaults). Returns the `DataSourceManager` wrapping the generated adapter
    so callers can fold it into their health checks.
    """
    operations = select_operations(
        parse_operations(load_spec(spec)), include, allow_mutations=allow_mutations
    )
    overrides = {normalize_operation_key(k): v for k, v in (names or {}).items()}
    unknown = set(overrides) - {op.key for op in operations}
    if unknown:
        raise ValueError(f"names entries match no included operation: {', '.join(sorted(unknown))}")
    adapter = OpenAPIAdapter(domain=domain, base_url=base_url, auth=auth, timeout=timeout_seconds)
    manager = DataSourceManager(
        [adapter],
        cb_failure_threshold=cb_failure_threshold,
        cb_recovery_timeout=cb_recovery_timeout_seconds,
    )
    for operation in operations:
        _register_operation(
            mcp,
            operation,
            domain=domain,
            manager=manager,
            audit=audit,
            name_override=overrides.get(operation.key),
        )
    return manager


def _register_operation(
    mcp: FastMCP,
    operation: Operation,
    *,
    domain: str,
    manager: DataSourceManager,
    audit: AuditWriter,
    name_override: str | None = None,
) -> None:
    tool_name = f"{domain}_{_snake(name_override or operation.operation_id)}"
    handler = _build_handler(operation, manager)
    handler.__name__ = tool_name
    description = _description(operation)
    handler.__doc__ = description
    signature, annotations = _build_signature(operation)
    handler.__signature__ = signature  # type: ignore[attr-defined]
    handler.__annotations__ = annotations

    governed = tool_runtime(
        domain=domain,
        tool_name=tool_name,
        resource=operation.resource,
        action=operation.action,
        audit=audit,
        source_unavailable_exception=ConnectorUnavailable,
    )(handler)
    mcp.tool(name=tool_name, description=description, structured_output=False)(governed)


def _build_handler(operation: Operation, manager: DataSourceManager):
    async def handler(**kwargs: Any) -> dict[str, Any]:
        ctx = kwargs.pop("ctx", None)
        auth_ctx = AuthContext(
            subject_token=resolve_subject_token(ctx),
            caller=resolve_caller(ctx),
        )
        failures: list[str] = []
        for adapter in manager.get_available_adapters():
            if not isinstance(adapter, OpenAPIAdapter):
                continue
            # Token-exchange connectors need the caller's own token. An API-key
            # caller has none — reject cleanly rather than reaching downstream.
            if adapter.requires_subject_token and auth_ctx.subject_token is None:
                raise InvalidInput(
                    "This connector requires user authentication (an OAuth bearer "
                    "token); API-key callers cannot use it."
                )
            try:
                status_code, data = await adapter.call(operation, kwargs, auth_ctx)
            except DownstreamClientError as exc:
                # Caller error (4xx) — surface as invalid_input, don't trip the breaker.
                raise InvalidInput(str(exc)) from exc
            except TokenExchangeRejected as exc:
                # IdP refused the exchange for this caller — clean, non-retryable,
                # not an outage. Don't leak the IdP detail or trip the breaker.
                raise InvalidInput(
                    "Downstream authentication could not be established for this caller."
                ) from exc
            except Exception as exc:
                manager.record_failure(adapter.name)
                failures.append(f"{adapter.name}: {exc!r}")
                continue
            manager.record_success(adapter.name)
            envelope = {
                "timestamp": datetime.now(UTC).isoformat(),
                "source": adapter.name,
                "cache_hit": False,
                "status_code": status_code,
                "data": data,
            }
            # Record the delegation (for the audit trail) when the call reached
            # the backend via per-user token exchange.
            if adapter.delegated_audience is not None:
                envelope["delegated_audience"] = adapter.delegated_audience
            return envelope
        raise ConnectorUnavailable("; ".join(failures) or "circuit breaker open")

    return handler


def _build_signature(operation: Operation) -> tuple[inspect.Signature, dict[str, Any]]:
    """Synthesize the signature FastMCP introspects for the tool's input schema."""
    required: list[inspect.Parameter] = []
    optional: list[inspect.Parameter] = []
    annotations: dict[str, Any] = {}

    for param in operation.parameters:
        annotation: Any = _TYPE_MAP.get(param.schema.get("type", ""), str)
        default = param.schema.get("default", inspect.Parameter.empty)
        if not param.required and default is inspect.Parameter.empty:
            annotation = annotation | None
            default = None
        annotations[param.name] = annotation
        bucket = required if default is inspect.Parameter.empty else optional
        bucket.append(
            inspect.Parameter(
                param.name,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                default=default,
                annotation=annotation,
            )
        )

    if operation.request_body_schema is not None:
        body_name = "body" if "body" not in annotations else "request_body"
        annotation = dict[str, Any]
        default = inspect.Parameter.empty if operation.request_body_required else None
        if not operation.request_body_required:
            annotation = annotation | None
        annotations[body_name] = annotation
        bucket = required if operation.request_body_required else optional
        bucket.append(
            inspect.Parameter(
                body_name,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                default=default,
                annotation=annotation,
            )
        )

    ctx_annotation = Context | None
    annotations["ctx"] = ctx_annotation
    annotations["return"] = dict[str, Any]
    ctx_param = inspect.Parameter(
        "ctx",
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
        default=None,
        annotation=ctx_annotation,
    )
    return inspect.Signature([*required, *optional, ctx_param]), annotations


def _description(operation: Operation) -> str:
    parts = [
        operation.summary or f"Call {operation.key}.",
        operation.description,
        f"[generated from OpenAPI: {operation.key}]",
    ]
    return "\n\n".join(p for p in parts if p)


def _snake(value: str) -> str:
    value = re.sub(r"(?<=[a-z0-9])([A-Z])", r"_\1", value)
    return re.sub(r"[^a-z0-9_]+", "_", value.lower()).strip("_")
