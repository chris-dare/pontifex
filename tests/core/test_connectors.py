"""Connectors: OpenAPI spec parsing, allowlist selection, and governed tool generation."""

import json

import httpx
import pytest
import respx
from mcp import types
from mcp.server.fastmcp import FastMCP
from pontifex_mcp.auth.context import set_stdio_caller
from pontifex_mcp.auth.identity import CallerIdentity
from pontifex_mcp.connectors import register_openapi_tools
from pontifex_mcp.connectors.spec import load_spec, parse_operations, select_operations

BASE_URL = "https://api.test"

SAMPLE_SPEC = {
    "openapi": "3.0.3",
    "info": {"title": "Orders API", "version": "1.0.0"},
    "paths": {
        "/orders": {
            "get": {
                "operationId": "listOrders",
                "summary": "List orders",
                "parameters": [
                    {
                        "name": "status",
                        "in": "query",
                        "schema": {"type": "string", "default": "open"},
                    },
                    {"$ref": "#/components/parameters/Limit"},
                ],
            },
            "post": {
                "operationId": "createOrder",
                "summary": "Create an order",
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {"schema": {"$ref": "#/components/schemas/Order"}}
                    },
                },
            },
        },
        "/orders/{order_id}": {
            "parameters": [
                {"name": "order_id", "in": "path", "required": True, "schema": {"type": "integer"}}
            ],
            "get": {"operationId": "getOrder", "summary": "Get one order"},
            "delete": {"operationId": "deleteOrder", "summary": "Delete an order"},
        },
    },
    "components": {
        "parameters": {"Limit": {"name": "limit", "in": "query", "schema": {"type": "integer"}}},
        "schemas": {"Order": {"type": "object", "properties": {"sku": {"type": "string"}}}},
    },
}

# The exact kwargs tool_runtime passes to AuditWriter.write — generated tools
# must produce audit rows identical in shape to hand-written ones.
AUDIT_FIELDS = {
    "domain",
    "key_id",
    "owner_id",
    "owner_label",
    "transport",
    "tool_name",
    "tool_params",
    "data_source",
    "cache_hit",
    "response_ms",
    "error",
    "ip_address",
}


class _RecordingAudit:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def write(self, **kwargs) -> None:
        self.calls.append(kwargs)


@pytest.fixture
def build_server():
    """Factory: scopes -> (mcp, audit) with the sample spec registered."""

    def _make(scopes: list[str], **kwargs) -> tuple[FastMCP, _RecordingAudit]:
        audit = _RecordingAudit()
        mcp = FastMCP(name="test-connectors", stateless_http=True)
        kwargs.setdefault("include", ["GET /orders", "GET /orders/{order_id}"])
        register_openapi_tools(
            mcp,
            spec=SAMPLE_SPEC,
            domain="orders",
            base_url=BASE_URL,
            audit=audit,
            **kwargs,
        )
        set_stdio_caller(
            CallerIdentity(
                key_id="k1",
                owner_id="o1",
                owner_label="test",
                scopes=scopes,
                rate_limit_rpm=60,
                transport="stdio",
            )
        )
        return mcp, audit

    return _make


def _payload(result) -> dict:
    text = result[0].text if isinstance(result, list) else result.content[0].text
    return json.loads(text)


def _error(result) -> dict:
    assert isinstance(result, types.CallToolResult)
    assert result.isError is True
    return json.loads(result.content[0].text)


# --- spec parsing & selection ------------------------------------------------


def test_parse_operations_resolves_refs_and_merges_params():
    ops = {op.key: op for op in parse_operations(SAMPLE_SPEC)}
    assert set(ops) == {
        "GET /orders",
        "POST /orders",
        "GET /orders/{order_id}",
        "DELETE /orders/{order_id}",
    }
    list_orders = ops["GET /orders"]
    assert {p.name for p in list_orders.parameters} == {"status", "limit"}
    get_order = ops["GET /orders/{order_id}"]
    assert [(p.name, p.location, p.required) for p in get_order.parameters] == [
        ("order_id", "path", True)
    ]
    create = ops["POST /orders"]
    assert create.request_body_required is True
    assert create.request_body_schema == {
        "type": "object",
        "properties": {"sku": {"type": "string"}},
    }


def test_scope_derivation():
    ops = {op.key: op for op in parse_operations(SAMPLE_SPEC)}
    assert (ops["GET /orders"].resource, ops["GET /orders"].action) == ("orders", "read")
    assert ops["POST /orders"].action == "write"
    assert ops["DELETE /orders/{order_id}"].action == "delete"


def test_select_unknown_include_raises():
    ops = parse_operations(SAMPLE_SPEC)
    with pytest.raises(ValueError, match="matches no operation"):
        select_operations(ops, ["GET /nope"], allow_mutations=False)


def test_select_mutating_requires_opt_in():
    ops = parse_operations(SAMPLE_SPEC)
    with pytest.raises(ValueError, match="allow_mutations"):
        select_operations(ops, ["POST /orders"], allow_mutations=False)
    selected = select_operations(ops, ["POST /orders"], allow_mutations=True)
    assert selected[0].operation_id == "createOrder"


def test_load_spec_from_yaml_path(tmp_path):
    path = tmp_path / "spec.yaml"
    path.write_text("openapi: 3.0.3\npaths:\n  /things:\n    get:\n      operationId: listThings\n")
    spec = load_spec(str(path))
    assert parse_operations(spec)[0].key == "GET /things"


# --- generated tools ---------------------------------------------------------


async def test_registers_one_tool_per_included_operation(build_server):
    mcp, _ = build_server(["orders:*:*"])
    tools = {t.name: t for t in await mcp.list_tools()}
    assert set(tools) == {"orders_list_orders", "orders_get_order"}
    schema = tools["orders_list_orders"].inputSchema
    assert set(schema["properties"]) >= {"status", "limit"}
    assert "GET /orders" in tools["orders_list_orders"].description


@respx.mock
async def test_call_success_and_audit_shape(build_server):
    respx.get(f"{BASE_URL}/orders").mock(return_value=httpx.Response(200, json=[{"id": 1}]))
    mcp, audit = build_server(["orders:orders:read"])
    result = await mcp.call_tool("orders_list_orders", {"status": "open"})
    body = _payload(result)
    assert body["source"] == "openapi:orders"
    assert body["cache_hit"] is False
    assert body["status_code"] == 200
    assert body["data"] == [{"id": 1}]
    row = audit.calls[-1]
    assert set(row) == AUDIT_FIELDS
    assert row["domain"] == "orders"
    assert row["tool_name"] == "orders_list_orders"
    # FastMCP fills omitted optional params with their defaults before the
    # call, so they appear in the audited params — same as hand-written tools.
    assert row["tool_params"] == {"status": "open", "limit": None}
    assert row["data_source"] == "openapi:orders"
    assert row["error"] is None


@respx.mock
async def test_path_param_substitution_and_query(build_server):
    route = respx.get(f"{BASE_URL}/orders/42").mock(
        return_value=httpx.Response(200, json={"id": 42})
    )
    mcp, _ = build_server(["orders:*:read"])
    result = await mcp.call_tool("orders_get_order", {"order_id": 42})
    assert _payload(result)["data"] == {"id": 42}
    assert route.called


@respx.mock
async def test_bearer_auth_header_sent(build_server, monkeypatch):
    monkeypatch.setenv("ORDERS_API_TOKEN", "sekrit")
    from pontifex_mcp.connectors import BearerFromEnv

    route = respx.get(f"{BASE_URL}/orders").mock(return_value=httpx.Response(200, json=[]))
    mcp, _ = build_server(["orders:*:*"], auth=BearerFromEnv("ORDERS_API_TOKEN"))
    await mcp.call_tool("orders_list_orders", {})
    assert route.calls.last.request.headers["Authorization"] == "Bearer sekrit"


async def test_scope_denied(build_server):
    mcp, audit = build_server(["orders:other:read"])
    result = await mcp.call_tool("orders_list_orders", {})
    err = _error(result)
    assert err["error_code"] == "scope_denied"
    assert err["status"] == 403
    assert "orders:orders:read" in err["message"]
    assert audit.calls[-1]["error"] == "scope_denied"


@respx.mock
async def test_mutating_tool_enforces_write_scope(build_server):
    respx.post(f"{BASE_URL}/orders").mock(return_value=httpx.Response(201, json={"id": 2}))
    mcp, _ = build_server(["orders:orders:read"], include=["POST /orders"], allow_mutations=True)
    denied = await mcp.call_tool("orders_create_order", {"body": {"sku": "x"}})
    assert _error(denied)["error_code"] == "scope_denied"

    set_stdio_caller(
        CallerIdentity(
            key_id="k1",
            owner_id="o1",
            owner_label="test",
            scopes=["orders:orders:write"],
            rate_limit_rpm=60,
            transport="stdio",
        )
    )
    result = await mcp.call_tool("orders_create_order", {"body": {"sku": "x"}})
    assert _payload(result)["status_code"] == 201


@respx.mock
async def test_downstream_4xx_maps_to_invalid_input(build_server):
    respx.get(f"{BASE_URL}/orders/9").mock(return_value=httpx.Response(404, text="not found"))
    mcp, audit = build_server(["orders:*:*"])
    result = await mcp.call_tool("orders_get_order", {"order_id": 9})
    err = _error(result)
    assert err["error_code"] == "invalid_input"
    assert audit.calls[-1]["error"] is not None


@respx.mock
async def test_downstream_failure_maps_to_source_unavailable(build_server):
    respx.get(f"{BASE_URL}/orders").mock(side_effect=httpx.ConnectError("boom"))
    mcp, _ = build_server(["orders:*:*"])
    result = await mcp.call_tool("orders_list_orders", {})
    err = _error(result)
    assert err["error_code"] == "source_unavailable"
    assert err["status"] == 503
