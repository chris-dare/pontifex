"""End-to-end HTTP: a real MCP `tools/call` over Streamable HTTP, exercising the
full wiring the unit tests only stub — AuthMiddleware sets `request.state.caller`,
FastMCP hands that same request to the tool as `ctx`, and `tool_runtime` resolves
the caller, enforces the scope, and audits. No Postgres/Redis (open mode, or an
injected resolver); the facade is `stateless_http`, so a `TestClient` suffices.
"""

import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from pontifex_mcp import PontifexMCP
from pontifex_mcp.auth.identity import CallerIdentity
from pontifex_mcp.middleware.auth import AuthMiddleware
from pontifex_mcp.server_factory import build_http_app
from starlette.testclient import TestClient

_MCP_HEADERS = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}


def _app():
    """A payments app with one scoped, ctx-less tool."""
    mcp = PontifexMCP("payments")

    @mcp.tool(scope="balance:read")
    async def get_balance(account_id: str) -> dict:
        return {"available": 7, "account": account_id, "source": "x", "cache_hit": False}

    return mcp


def _call_tool(client: TestClient, name: str, arguments: dict, *, auth: str | None = None) -> dict:
    """Run the MCP handshake then a tools/call; return the parsed JSON-RPC response."""
    headers = dict(_MCP_HEADERS)
    if auth is not None:
        headers["Authorization"] = f"Bearer {auth}"
    init = client.post(
        "/mcp",
        headers=headers,
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "t", "version": "1"},
            },
        },
    )
    if init.status_code != 200:
        return {"_status": init.status_code}
    client.post(
        "/mcp", headers=headers, json={"jsonrpc": "2.0", "method": "notifications/initialized"}
    )
    resp = client.post(
        "/mcp",
        headers=headers,
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        },
    )
    return resp.json()


def _tool_payload(rpc: dict) -> dict:
    """Extract the tool's returned dict from a JSON-RPC tools/call response."""
    return json.loads(rpc["result"]["content"][0]["text"])


def test_e2e_open_mode_anonymous_call():
    """Open mode: the anonymous caller flows all the way through and the scoped
    (advisory) tool returns its result over real HTTP."""
    mcp = _app()
    app = build_http_app("payments", mcp, mcp._settings, mcp._readiness, allow_anonymous=True)
    with TestClient(app) as client:
        rpc = _call_tool(client, "get_balance", {"account_id": "a1"})
    assert rpc["result"]["isError"] is False
    assert _tool_payload(rpc) == {
        "available": 7,
        "account": "a1",
        "source": "x",
        "cache_hit": False,
    }


def _enforced_app(mcp: PontifexMCP, resolver: AsyncMock) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI):
        async with mcp.session_manager.run():
            yield

    app = FastAPI(lifespan=lifespan)
    app.add_middleware(AuthMiddleware, api_key_resolver=resolver)
    app.mount("/", mcp.streamable_http_app())
    return app


@pytest.mark.parametrize(
    ("scopes", "expect_error"),
    [(["payments:balance:read"], False), (["payments:charges:read"], True)],
)
def test_e2e_scope_enforced_over_http(scopes, expect_error):
    """With auth wired, a real Bearer token resolves to a caller whose scope is
    enforced at the tool boundary — granted runs, missing is scope_denied."""
    mcp = _app()
    resolver = AsyncMock()
    resolver.resolve = AsyncMock(
        return_value=CallerIdentity(key_id="k", owner_id="o", owner_label="L", scopes=scopes)
    )
    app = _enforced_app(mcp, resolver)
    with TestClient(app) as client:
        rpc = _call_tool(client, "get_balance", {"account_id": "a1"}, auth="sk_live_test")

    assert rpc["result"]["isError"] is expect_error
    if expect_error:
        assert json.loads(rpc["result"]["content"][0]["text"])["error_code"] == "scope_denied"
    else:
        assert _tool_payload(rpc)["account"] == "a1"


def test_e2e_no_token_is_rejected():
    """With auth wired, an unauthenticated request never reaches MCP — 401."""
    mcp = _app()
    resolver = AsyncMock()
    resolver.resolve = AsyncMock(return_value=None)
    app = _enforced_app(mcp, resolver)
    with TestClient(app) as client:
        rpc = _call_tool(client, "get_balance", {"account_id": "a1"})  # no Authorization
    assert rpc == {"_status": 401}
