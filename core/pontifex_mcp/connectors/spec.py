"""OpenAPI 3.x spec loading and operation parsing.

Parses a spec into flat `Operation` records that the generator turns into
governed tools. Only `path` and `query` parameters and `application/json`
request bodies are supported; header/cookie parameters are ignored.
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import yaml

_ACTION_BY_METHOD = {
    "get": "read",
    "head": "read",
    "post": "write",
    "put": "write",
    "patch": "write",
    "delete": "delete",
}
_MUTATING_METHODS = {"post", "put", "patch", "delete"}


@dataclass(frozen=True)
class SpecParameter:
    name: str
    location: str  # "path" | "query"
    required: bool
    schema: dict[str, Any] = field(default_factory=dict)
    description: str = ""


@dataclass(frozen=True)
class Operation:
    method: str  # uppercased HTTP verb
    path: str
    operation_id: str
    summary: str
    description: str
    parameters: tuple[SpecParameter, ...]
    request_body_schema: dict[str, Any] | None
    request_body_required: bool

    @property
    def key(self) -> str:
        """Allowlist key, e.g. 'GET /orders/{id}'."""
        return f"{self.method} {self.path}"

    @property
    def action(self) -> str:
        """Scope action derived from the HTTP verb."""
        return _ACTION_BY_METHOD[self.method.lower()]

    @property
    def is_mutating(self) -> bool:
        return self.method.lower() in _MUTATING_METHODS

    @property
    def resource(self) -> str:
        """Scope resource: first static path segment, e.g. '/orders/{id}' -> 'orders'."""
        for segment in self.path.strip("/").split("/"):
            if segment and not segment.startswith("{"):
                return _sanitize(segment)
        return _sanitize(self.operation_id)


def _sanitize(value: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", value.lower()).strip("_")


def load_spec(spec: str | dict[str, Any]) -> dict[str, Any]:
    """Load an OpenAPI spec from a dict, a URL, or a file path (JSON or YAML)."""
    if isinstance(spec, dict):
        return spec
    if spec.startswith(("http://", "https://")):
        # Sync on purpose: runs once inside the sync `register_tools` startup
        # callback, never on the request path.
        response = httpx.get(spec, timeout=10.0, follow_redirects=True)
        response.raise_for_status()
        text = response.text
    else:
        text = Path(spec).read_text()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = yaml.safe_load(text)
    if not isinstance(parsed, dict):
        raise ValueError(f"OpenAPI spec at {spec!r} did not parse to a mapping.")
    return parsed


def _resolve_ref(spec: dict[str, Any], obj: Any) -> Any:
    """Follow local '#/...' $refs to their target node."""
    while isinstance(obj, dict) and "$ref" in obj:
        ref = obj["$ref"]
        if not isinstance(ref, str) or not ref.startswith("#/"):
            raise ValueError(f"Only local '#/' $refs are supported, got: {ref!r}")
        node: Any = spec
        for part in ref[2:].split("/"):
            node = node[part.replace("~1", "/").replace("~0", "~")]
        obj = node
    return obj


def parse_operations(spec: dict[str, Any]) -> list[Operation]:
    """Flatten a spec's paths into Operation records."""
    operations: list[Operation] = []
    for path, raw_path_item in (spec.get("paths") or {}).items():
        path_item = _resolve_ref(spec, raw_path_item)
        base_params = path_item.get("parameters") or []
        for method in ("get", "put", "post", "delete", "patch", "head"):
            op = path_item.get(method)
            if not op:
                continue
            operations.append(_parse_operation(spec, method, path, op, base_params))
    return operations


def _parse_operation(
    spec: dict[str, Any],
    method: str,
    path: str,
    op: dict[str, Any],
    base_params: list[Any],
) -> Operation:
    # Operation-level parameters override path-item ones with the same (name, in).
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for raw in [*base_params, *(op.get("parameters") or [])]:
        param = _resolve_ref(spec, raw)
        merged[(param["name"], param.get("in", ""))] = param

    parameters: list[SpecParameter] = []
    for param in merged.values():
        location = param.get("in")
        if location not in {"path", "query"}:
            continue
        parameters.append(
            SpecParameter(
                name=param["name"],
                location=location,
                required=bool(param.get("required", location == "path")),
                schema=_resolve_ref(spec, param.get("schema") or {}),
                description=param.get("description", ""),
            )
        )

    body_schema: dict[str, Any] | None = None
    body_required = False
    request_body = _resolve_ref(spec, op.get("requestBody"))
    if request_body:
        body_required = bool(request_body.get("required"))
        media = (request_body.get("content") or {}).get("application/json")
        if media is not None:
            body_schema = _resolve_ref(spec, media.get("schema") or {})
        elif body_required:
            raise ValueError(
                f"{method.upper()} {path}: only application/json request bodies are supported."
            )

    operation_id = op.get("operationId") or f"{method}_{path}"
    return Operation(
        method=method.upper(),
        path=path,
        operation_id=operation_id,
        summary=op.get("summary", ""),
        description=op.get("description", ""),
        parameters=tuple(parameters),
        request_body_schema=body_schema,
        request_body_required=body_required,
    )


def select_operations(
    operations: list[Operation],
    include: list[str],
    *,
    allow_mutations: bool,
) -> list[Operation]:
    """Resolve the explicit allowlist against parsed operations.

    Fails fast on entries that match nothing (a typo must not silently expose
    less than intended) and on mutating verbs unless `allow_mutations=True`.
    """
    by_key = {op.key: op for op in operations}
    selected: list[Operation] = []
    for entry in include:
        method, _, path = entry.strip().partition(" ")
        key = f"{method.upper()} {path.strip()}"
        op = by_key.get(key)
        if op is None:
            available = ", ".join(sorted(by_key))
            raise ValueError(f"include entry {entry!r} matches no operation. Spec has: {available}")
        if op.is_mutating and not allow_mutations:
            raise ValueError(
                f"include entry {entry!r} is a mutating operation ({op.action} scope). "
                "Pass allow_mutations=True to expose it."
            )
        selected.append(op)
    return selected
