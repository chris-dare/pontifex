"""Token-exchange connectors end-to-end: config validation + handler wiring (#41)."""

import json

import httpx
import pytest
import respx
from mcp import types
from mcp.server.fastmcp import FastMCP
from pontifex_mcp.auth.context import (
    set_stdio_caller,
    set_stdio_subject_token,
)
from pontifex_mcp.auth.identity import CallerIdentity
from pontifex_mcp.connectors import InMemoryTokenCache, TokenExchange, register_openapi_tools
from pontifex_mcp.connectors.config import ConnectorAuth
from pydantic import ValidationError

BASE_URL = "https://api.test"
IDP = "https://idp.test/oauth/token"

SPEC = {
    "openapi": "3.0.3",
    "info": {"title": "Orders", "version": "1.0.0"},
    "paths": {
        "/orders": {"get": {"operationId": "listOrders", "summary": "List orders"}},
    },
}


class _RecordingAudit:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def write(self, **kwargs) -> None:
        self.calls.append(kwargs)


def _payload(result) -> dict:
    text = result[0].text if isinstance(result, list) else result.content[0].text
    return json.loads(text)


def _error(result) -> dict:
    assert isinstance(result, types.CallToolResult)
    assert result.isError is True
    return json.loads(result.content[0].text)


def _set_caller(scopes, subject_token):
    set_stdio_caller(
        CallerIdentity(
            key_id="k1",
            owner_id="o1",
            owner_label="t",
            scopes=scopes,
            rate_limit_rpm=60,
            transport="stdio",
        )
    )
    set_stdio_subject_token(subject_token)


def _build(monkeypatch) -> tuple[FastMCP, _RecordingAudit]:
    monkeypatch.setenv("PONTIFEX_OAUTH_CLIENT_ID", "pontifex-client")
    monkeypatch.setenv("PONTIFEX_OAUTH_CLIENT_SECRET", "shhh")
    audit = _RecordingAudit()
    mcp = FastMCP(name="t", stateless_http=True)
    register_openapi_tools(
        mcp,
        spec=SPEC,
        domain="orders",
        base_url=BASE_URL,
        audit=audit,
        include=["GET /orders"],
        auth=TokenExchange(
            token_endpoint=IDP,
            audience=BASE_URL,
            client_id_env="PONTIFEX_OAUTH_CLIENT_ID",
            client_secret_env="PONTIFEX_OAUTH_CLIENT_SECRET",
            cache=InMemoryTokenCache(),
        ),
    )
    return mcp, audit


# --- config validation -------------------------------------------------------


def test_config_token_exchange_requires_its_fields():
    with pytest.raises(ValidationError, match="token_endpoint"):
        ConnectorAuth(type="token_exchange", audience="x")


def test_config_token_exchange_builds(monkeypatch):
    monkeypatch.setenv("CID", "c")
    monkeypatch.setenv("CSEC", "s")
    auth = ConnectorAuth(
        type="token_exchange",
        token_endpoint=IDP,
        audience=BASE_URL,
        client_id_env="CID",
        client_secret_env="CSEC",
    )
    assert isinstance(auth.build(), TokenExchange)


def test_config_bearer_still_requires_env_var():
    with pytest.raises(ValidationError, match="env_var"):
        ConnectorAuth(type="bearer_env")


# --- end-to-end through the generated tool -----------------------------------


@respx.mock
async def test_jwt_caller_exchanges_and_calls_downstream(monkeypatch):
    idp = respx.post(IDP).mock(
        return_value=httpx.Response(200, json={"access_token": "xchg-tok-123", "expires_in": 300})
    )
    api = respx.get(f"{BASE_URL}/orders").mock(return_value=httpx.Response(200, json=[{"id": 1}]))
    mcp, audit = _build(monkeypatch)
    _set_caller(["orders:*:read"], subject_token="user-jwt")

    result = await mcp.call_tool("orders_list_orders", {})
    body = _payload(result)
    assert body["data"] == [{"id": 1}]
    # The envelope surfaces the delegation audience to the client (intentional —
    # an audience identifier, not a secret; mirrors source/cache_hit).
    assert body["delegated_audience"] == BASE_URL
    assert idp.call_count == 1
    # Downstream received the *delegated* token, not the inbound user JWT.
    assert api.calls.last.request.headers["Authorization"] == "Bearer xchg-tok-123"
    assert "user-jwt" not in api.calls.last.request.headers["Authorization"]
    assert audit.calls[-1]["error"] is None
    # The delegation is recorded in the audit row (audience only, never tokens).
    assert audit.calls[-1]["delegated_audience"] == BASE_URL
    assert "xchg-tok-123" not in str(audit.calls[-1])  # no token in the row
    assert "user-jwt" not in str(audit.calls[-1])


@respx.mock
async def test_api_key_caller_rejected_without_reaching_idp_or_downstream(monkeypatch):
    idp = respx.post(IDP).mock(return_value=httpx.Response(200, json={}))
    api = respx.get(f"{BASE_URL}/orders").mock(return_value=httpx.Response(200, json=[]))
    mcp, _ = _build(monkeypatch)
    _set_caller(["orders:*:read"], subject_token=None)  # API-key caller: no JWT

    result = await mcp.call_tool("orders_list_orders", {})
    err = _error(result)
    assert err["error_code"] == "invalid_input"
    assert "user authentication" in err["message"]
    assert idp.call_count == 0
    assert api.call_count == 0


@respx.mock
async def test_idp_rejection_maps_to_invalid_input(monkeypatch):
    respx.post(IDP).mock(return_value=httpx.Response(400, json={"error": "invalid_grant"}))
    api = respx.get(f"{BASE_URL}/orders").mock(return_value=httpx.Response(200, json=[]))
    mcp, _ = _build(monkeypatch)
    _set_caller(["orders:*:read"], subject_token="user-jwt")

    result = await mcp.call_tool("orders_list_orders", {})
    err = _error(result)
    assert err["error_code"] == "invalid_input"
    # The IdP's error body must not leak to the caller.
    assert "invalid_grant" not in err["message"]
    assert api.call_count == 0


@respx.mock
async def test_idp_outage_maps_to_source_unavailable(monkeypatch):
    respx.post(IDP).mock(return_value=httpx.Response(503))
    mcp, _ = _build(monkeypatch)
    _set_caller(["orders:*:read"], subject_token="user-jwt")

    result = await mcp.call_tool("orders_list_orders", {})
    err = _error(result)
    assert err["error_code"] == "source_unavailable"
    assert err["status"] == 503


# --- breaker isolation (#46) -------------------------------------------------


def _build_with_manager(monkeypatch):
    """Register a token-exchange connector and return (mcp, manager) so the
    connector's circuit breaker can be inspected. Threshold 1: any recorded
    failure opens it."""
    monkeypatch.setenv("PONTIFEX_OAUTH_CLIENT_ID", "pontifex-client")
    monkeypatch.setenv("PONTIFEX_OAUTH_CLIENT_SECRET", "shhh")
    mcp = FastMCP(name="t", stateless_http=True)
    manager = register_openapi_tools(
        mcp,
        spec=SPEC,
        domain="orders",
        base_url=BASE_URL,
        audit=_RecordingAudit(),
        include=["GET /orders"],
        auth=TokenExchange(
            token_endpoint=IDP,
            audience=BASE_URL,
            client_id_env="PONTIFEX_OAUTH_CLIENT_ID",
            client_secret_env="PONTIFEX_OAUTH_CLIENT_SECRET",
            cache=InMemoryTokenCache(),
        ),
        cb_failure_threshold=1,
    )
    return mcp, manager


@respx.mock
async def test_idp_outage_does_not_trip_connector_breaker(monkeypatch):
    respx.post(IDP).mock(return_value=httpx.Response(503))  # IdP down
    mcp, manager = _build_with_manager(monkeypatch)
    _set_caller(["orders:*:read"], subject_token="user-jwt")

    result = await mcp.call_tool("orders_list_orders", {})
    assert _error(result)["error_code"] == "source_unavailable"
    # The downstream connector breaker must stay closed — the IdP being down
    # doesn't implicate the downstream API, and tripping it would lock out
    # callers whose delegated token is still cached. (The TokenExchange strategy
    # has its own breaker for the IdP.)
    assert manager.breakers["openapi:orders"].is_available is True


@respx.mock
async def test_cached_token_survives_idp_outage(monkeypatch):
    # The headline benefit of breaker isolation: once a user's token is cached,
    # an IdP outage doesn't lock them out — the cache short-circuits the IdP.
    idp = respx.post(IDP).mock(
        side_effect=[
            httpx.Response(200, json={"access_token": "tok", "expires_in": 300}),
            httpx.Response(503),  # IdP goes down after the first exchange
        ]
    )
    respx.get(f"{BASE_URL}/orders").mock(return_value=httpx.Response(200, json=[{"id": 1}]))
    mcp, _ = _build(monkeypatch)
    _set_caller(["orders:*:read"], subject_token="user-jwt")

    first = await mcp.call_tool("orders_list_orders", {})
    assert _payload(first)["data"] == [{"id": 1}]

    second = await mcp.call_tool("orders_list_orders", {})
    assert _payload(second)["data"] == [{"id": 1}]  # served despite the IdP being down
    assert idp.call_count == 1  # second call hit the token cache, never the IdP


@respx.mock
async def test_downstream_5xx_does_trip_connector_breaker(monkeypatch):
    respx.post(IDP).mock(
        return_value=httpx.Response(200, json={"access_token": "tok", "expires_in": 300})
    )
    respx.get(f"{BASE_URL}/orders").mock(return_value=httpx.Response(503))  # downstream down
    mcp, manager = _build_with_manager(monkeypatch)
    _set_caller(["orders:*:read"], subject_token="user-jwt")

    result = await mcp.call_tool("orders_list_orders", {})
    assert _error(result)["error_code"] == "source_unavailable"
    # A real downstream failure SHOULD open the connector breaker (contrast).
    assert manager.breakers["openapi:orders"].is_available is False


@pytest.fixture(autouse=True)
def _reset_stdio():
    yield
    set_stdio_subject_token(None)
