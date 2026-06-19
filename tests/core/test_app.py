"""The PontifexMCP facade: scope folding, audit default, open-mode HTTP bind."""

import types as pytypes

import pytest
from pontifex_mcp import ApiKeyAuth, JwtAuth, PontifexMCP, StdoutAuditWriter
from pontifex_mcp.app import _parse_scope
from pontifex_mcp.auth.context import set_stdio_caller
from pontifex_mcp.auth.identity import CallerIdentity, anonymous_identity
from pontifex_mcp.server_factory import build_http_app
from starlette.testclient import TestClient


def _http_ctx(caller):
    """A fake MCP Context carrying an HTTP request whose caller is resolved."""
    request = pytypes.SimpleNamespace(state=pytypes.SimpleNamespace(caller=caller), client=None)
    return pytypes.SimpleNamespace(request_context=pytypes.SimpleNamespace(request=request))


def test_parse_scope():
    assert _parse_scope(None, "payments") == ("payments", None, None)
    assert _parse_scope("balance:read", "payments") == ("payments", "balance", "read")
    assert _parse_scope("gse:live:read", "payments") == ("gse", "live", "read")
    with pytest.raises(ValueError, match="Invalid scope"):
        _parse_scope("too:many:parts:here", "payments")
    with pytest.raises(ValueError, match="Invalid scope"):
        _parse_scope("balance:", "payments")  # empty action rejected


def test_bare_facade_defaults():
    mcp = PontifexMCP("payments")
    assert mcp._domain == "payments"
    assert mcp._auth is None
    assert isinstance(mcp._audit, StdoutAuditWriter)


def _scoped_app():
    mcp = PontifexMCP("payments")

    @mcp.tool(scope="balance:read")
    async def get_balance() -> dict:
        return {"available": 421000, "source": "fake", "cache_hit": False}

    @mcp.tool()  # advisory — no scope
    async def ping() -> dict:
        return {"ok": True, "source": "fake", "cache_hit": False}

    return mcp


@pytest.mark.asyncio
async def test_anonymous_caller_bypasses_scope():
    mcp = _scoped_app()
    fn = mcp._tool_manager.get_tool("get_balance").fn
    set_stdio_caller(anonymous_identity("stdio"))
    result = await fn()
    assert result["available"] == 421000


@pytest.mark.asyncio
async def test_scope_enforced_for_real_caller():
    mcp = _scoped_app()
    fn = mcp._tool_manager.get_tool("get_balance").fn

    set_stdio_caller(
        CallerIdentity(key_id="k", owner_id="o", owner_label="L", scopes=["payments:charges:read"])
    )
    denied = await fn()
    assert getattr(denied, "isError", False) is True

    set_stdio_caller(
        CallerIdentity(key_id="k", owner_id="o", owner_label="L", scopes=["payments:balance:read"])
    )
    allowed = await fn()
    assert allowed["available"] == 421000


@pytest.mark.asyncio
async def test_unscoped_tool_is_advisory():
    """A tool with no scope= runs even for a caller with unrelated scopes."""
    mcp = _scoped_app()
    ping = mcp._tool_manager.get_tool("ping").fn
    set_stdio_caller(
        CallerIdentity(key_id="k", owner_id="o", owner_label="L", scopes=["payments:charges:read"])
    )
    assert (await ping())["ok"] is True


def test_open_mode_http_app_serves_without_auth():
    mcp = _scoped_app()
    app = build_http_app("payments", mcp, mcp._settings, mcp._readiness, allow_anonymous=True)
    with TestClient(app) as client:
        assert client.get("/health/live").status_code == 200


def test_http_host_gate():
    """Open mode binds localhost; auth='none' opts into 0.0.0.0; a configured
    auth backend uses the settings host."""
    open_mcp = PontifexMCP("payments")
    s = open_mcp._settings
    assert open_mcp._http_host(s, open_mode=True, network_optout=None) == "127.0.0.1"
    assert open_mcp._http_host(s, open_mode=True, network_optout="none") == "0.0.0.0"

    auth_mcp = PontifexMCP("payments", auth=ApiKeyAuth())
    assert auth_mcp._http_host(auth_mcp._settings, open_mode=False, network_optout=None) == (
        auth_mcp._settings.host or "0.0.0.0"
    )


@pytest.mark.asyncio
async def test_http_caller_resolved_for_ctx_less_tool():
    """A tool written WITHOUT a ctx param (as the docs show) still resolves the
    HTTP caller and enforces scope — the wrapper injects ctx for FastMCP."""
    mcp = PontifexMCP("payments")

    @mcp.tool(scope="balance:read")
    async def get_balance(account_id: str) -> dict:
        return {"available": 1, "account": account_id, "source": "x", "cache_hit": False}

    tool = mcp._tool_manager.get_tool("get_balance")
    # ctx must not leak into the input schema.
    assert "ctx" not in tool.parameters.get("properties", {})
    assert "account_id" in tool.parameters["properties"]

    fn = tool.fn
    allowed = await fn(
        account_id="a1",
        ctx=_http_ctx(
            CallerIdentity(
                key_id="k", owner_id="o", owner_label="L", scopes=["payments:balance:read"]
            )
        ),
    )
    assert allowed["account"] == "a1"

    denied = await fn(
        account_id="a1",
        ctx=_http_ctx(
            CallerIdentity(
                key_id="k", owner_id="o", owner_label="L", scopes=["payments:charges:read"]
            )
        ),
    )
    assert getattr(denied, "isError", False) is True


def test_require_auth_env_fails_fast(monkeypatch):
    """ApiKeyAuth without DATABASE_URL/REDIS_URL fails fast; JwtAuth needs JWKS."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("AUTH_JWKS_URL", raising=False)

    api_mcp = PontifexMCP("payments", auth=ApiKeyAuth())
    with pytest.raises(ValueError, match="DATABASE_URL.*ApiKeyAuth"):
        api_mcp._require_auth_env(api_mcp._settings)

    jwt_mcp = PontifexMCP("payments", auth=JwtAuth())
    with pytest.raises(ValueError, match="AUTH_JWKS_URL.*JwtAuth"):
        jwt_mcp._require_auth_env(jwt_mcp._settings)
