"""Tool handler tests: drive registered FastMCP tools via call_tool."""

import json
from datetime import UTC, datetime

import pytest
from gse_mcp.data import GSEDataService
from gse_mcp.models import Equity, HistoryEntry, MarketSummary, Stock
from gse_mcp.tools import register_gse_tools
from mcp import types
from mcp.server.fastmcp import FastMCP
from mcp_core.adapters.manager import DataSourceManager
from mcp_core.auth.context import set_stdio_caller
from mcp_core.auth.identity import CallerIdentity


class _FakeAdapter:
    name = "fake"
    priority = 1

    def __init__(self) -> None:
        self._stocks = [
            Stock(
                symbol="MTN",
                name="MTN Ghana",
                price=25.5,
                change=0.72,
                change_pct=2.91,
                volume=374476,
            ),
            Stock(
                symbol="GCB",
                name="GCB Bank",
                price=5.10,
                change=-0.10,
                change_pct=-1.92,
                volume=12000,
            ),
        ]

    async def health_check(self) -> bool:
        return True

    async def get_live_prices(self) -> list[Stock]:
        return self._stocks

    async def get_stock_price(self, symbol: str) -> Stock | None:
        return next((s for s in self._stocks if s.symbol == symbol.upper()), None)

    async def get_stock_history(self, symbol: str, days: int) -> list[HistoryEntry]:
        return [HistoryEntry(date="2026-05-22", close=5.2, volume=12000)]

    async def get_market_summary(self) -> MarketSummary | None:
        return MarketSummary(timestamp=datetime.now(UTC), gainers=1, losers=1)

    async def fetch_equities(self) -> list[Equity]:
        return [Equity(symbol="MTN"), Equity(symbol="GCB")]

    async def get_equity(self, symbol: str) -> Equity | None:
        return Equity(symbol=symbol.upper()) if symbol.upper() in {"MTN", "GCB"} else None


class _FakeCache:
    def __init__(self) -> None:
        self.store: dict = {}

    async def get(self, key: str):
        return self.store.get(key)

    async def set(self, key: str, value, ttl_seconds: int) -> None:
        self.store[key] = value

    async def invalidate(self, pattern: str) -> None:
        self.store = {k: v for k, v in self.store.items() if not k.startswith(pattern)}


class _RecordingAudit:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def write(self, **kwargs) -> None:
        self.calls.append(kwargs)


@pytest.fixture
def build_server():
    """Returns a factory: scopes -> (mcp_server, audit_recorder).

    Uses stdio CallerIdentity injection so call_tool() can run without an
    HTTP request.
    """

    def _make(scopes: list[str]) -> tuple[FastMCP, _RecordingAudit]:
        adapter = _FakeAdapter()
        manager = DataSourceManager([adapter])
        cache = _FakeCache()
        service = GSEDataService(manager, cache)
        audit = _RecordingAudit()
        mcp = FastMCP(name="test-gse", stateless_http=True)
        register_gse_tools(mcp, service, audit)

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
    """Extract the JSON body from a successful tool call (dict result)."""
    if isinstance(result, dict):
        return result
    # FastMCP returns list[ContentBlock] from call_tool for unstructured returns
    text = result[0].text if isinstance(result, list) else result.content[0].text
    return json.loads(text)


def _error(result) -> dict:
    """Extract the ToolError JSON from a CallToolResult(isError=True)."""
    assert isinstance(result, types.CallToolResult)
    assert result.isError is True
    return json.loads(result.content[0].text)


async def test_lists_all_five_tools(build_server):
    mcp, _ = build_server(["gse:*:*"])
    tools = await mcp.list_tools()
    assert {t.name for t in tools} == {
        "gse_get_live_prices",
        "gse_get_stock_price",
        "gse_get_stock_history",
        "gse_get_market_summary",
        "gse_get_company_info",
    }


async def test_live_prices_ok(build_server):
    mcp, audit = build_server(["gse:*:read"])
    result = await mcp.call_tool("gse_get_live_prices", {})
    body = _payload(result)
    assert body["source"] == "fake"
    assert body["cache_hit"] is False
    assert len(body["stocks"]) == 2
    assert audit.calls[-1]["tool_name"] == "gse_get_live_prices"
    assert audit.calls[-1]["data_source"] == "fake"
    assert audit.calls[-1]["error"] is None


async def test_live_prices_cache_hit_on_second_call(build_server):
    mcp, _ = build_server(["gse:*:read"])
    await mcp.call_tool("gse_get_live_prices", {})
    result = await mcp.call_tool("gse_get_live_prices", {})
    assert _payload(result)["cache_hit"] is True


async def test_scope_denied(build_server):
    mcp, audit = build_server(["gse:market_summary:read"])
    result = await mcp.call_tool("gse_get_live_prices", {})
    err = _error(result)
    assert err["error_code"] == "scope_denied"
    assert err["status"] == 403
    assert audit.calls[-1]["error"] == "scope_denied"


async def test_stock_price_unknown_symbol(build_server):
    mcp, _ = build_server(["gse:*:*"])
    result = await mcp.call_tool("gse_get_stock_price", {"symbol": "XYZ"})
    err = _error(result)
    assert err["error_code"] == "invalid_input"


async def test_stock_price_ok(build_server):
    mcp, audit = build_server(["gse:*:*"])
    result = await mcp.call_tool("gse_get_stock_price", {"symbol": "mtn"})
    body = _payload(result)
    assert body["stock"]["symbol"] == "MTN"
    assert audit.calls[-1]["tool_params"] == {"symbol": "mtn"}


async def test_stock_history_ok(build_server):
    mcp, audit = build_server(["gse:stock_history:read"])
    result = await mcp.call_tool("gse_get_stock_history", {"symbol": "GCB", "days": 10})
    body = _payload(result)
    assert body["symbol"] == "GCB"
    assert body["days"] == 10
    assert len(body["entries"]) == 1
    assert audit.calls[-1]["tool_params"] == {"symbol": "GCB", "days": 10}


async def test_stock_history_bad_days(build_server):
    mcp, _ = build_server(["gse:*:*"])
    result = await mcp.call_tool("gse_get_stock_history", {"symbol": "GCB", "days": 0})
    assert _error(result)["error_code"] == "invalid_input"


async def test_market_summary_ok(build_server):
    mcp, _ = build_server(["gse:*:read"])
    result = await mcp.call_tool("gse_get_market_summary", {})
    body = _payload(result)
    assert body["source"] == "fake"


async def test_company_info_ok(build_server):
    mcp, _ = build_server(["gse:company_info:read"])
    result = await mcp.call_tool("gse_get_company_info", {"symbol": "MTN"})
    assert _payload(result)["equity"]["symbol"] == "MTN"


async def test_company_info_unknown(build_server):
    mcp, _ = build_server(["gse:company_info:read"])
    result = await mcp.call_tool("gse_get_company_info", {"symbol": "ZZZ"})
    assert _error(result)["error_code"] == "invalid_input"


async def test_auth_failed_when_no_caller():
    """A tool call with no resolved identity returns auth_failed."""
    adapter = _FakeAdapter()
    manager = DataSourceManager([adapter])
    service = GSEDataService(manager, _FakeCache())
    audit = _RecordingAudit()
    mcp = FastMCP(name="t", stateless_http=True)
    register_gse_tools(mcp, service, audit)

    set_stdio_caller(None)  # type: ignore[arg-type]
    result = await mcp.call_tool("gse_get_live_prices", {})
    err = _error(result)
    assert err["error_code"] == "auth_failed"
    assert err["status"] == 401
