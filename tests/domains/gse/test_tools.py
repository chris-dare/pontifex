"""Tool handler tests: GSEDataService with fake adapter, exercising tool endpoints via TestClient."""

from datetime import UTC

import pytest
from fastapi import FastAPI
from gse_mcp.data import GSEDataService
from gse_mcp.models import Equity, HistoryEntry, MarketSummary, Stock
from gse_mcp.tools import register_gse_tools
from mcp_core.adapters.manager import DataSourceManager
from mcp_core.auth.identity import CallerIdentity
from starlette.testclient import TestClient


class _FakeAdapter:
    name = "fake"
    priority = 1

    def __init__(self):
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
        from datetime import datetime

        return MarketSummary(timestamp=datetime.now(UTC), gainers=1, losers=1)

    async def fetch_equities(self) -> list[Equity]:
        return [Equity(symbol="MTN"), Equity(symbol="GCB")]

    async def get_equity(self, symbol: str) -> Equity | None:
        return Equity(symbol=symbol.upper()) if symbol.upper() in {"MTN", "GCB"} else None


class _FakeCache:
    def __init__(self):
        self.store: dict = {}

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value, ttl_seconds):
        self.store[key] = value

    async def invalidate(self, pattern):
        self.store = {k: v for k, v in self.store.items() if not k.startswith(pattern)}


@pytest.fixture
def app_factory():
    """Returns a function that builds a fresh FastAPI app for the given caller scopes."""

    def _make(scopes: list[str]) -> tuple[FastAPI, TestClient]:
        adapter = _FakeAdapter()
        manager = DataSourceManager([adapter])
        cache = _FakeCache()
        service = GSEDataService(manager, cache)
        app = FastAPI()

        @app.middleware("http")
        async def inject_caller(request, call_next):
            request.state.caller = CallerIdentity(
                key_id="k1",
                owner_id="o1",
                owner_label="Test",
                scopes=scopes,
                rate_limit_rpm=60,
            )
            return await call_next(request)

        register_gse_tools(app, service)
        return app, TestClient(app)

    return _make


def test_live_prices_ok(app_factory):
    _, client = app_factory(["gse:*:read"])
    resp = client.post("/tools/gse_get_live_prices", json={})
    assert resp.status_code == 200
    body = resp.json()
    assert body["source"] == "fake"
    assert body["cache_hit"] is False
    assert len(body["stocks"]) == 2


def test_live_prices_cache_hit_on_second_call(app_factory):
    _, client = app_factory(["gse:*:read"])
    client.post("/tools/gse_get_live_prices", json={})
    resp = client.post("/tools/gse_get_live_prices", json={})
    assert resp.json()["cache_hit"] is True


def test_scope_denied(app_factory):
    _, client = app_factory(["gse:market_summary:read"])
    resp = client.post("/tools/gse_get_live_prices", json={})
    assert resp.status_code == 403
    assert resp.json()["detail"]["error_code"] == "scope_denied"


def test_stock_price_unknown_symbol(app_factory):
    _, client = app_factory(["gse:*:*"])
    resp = client.post("/tools/gse_get_stock_price", json={"symbol": "XYZ"})
    assert resp.status_code == 400
    assert resp.json()["detail"]["error_code"] == "invalid_input"


def test_stock_price_ok(app_factory):
    _, client = app_factory(["gse:*:*"])
    resp = client.post("/tools/gse_get_stock_price", json={"symbol": "mtn"})
    assert resp.status_code == 200
    assert resp.json()["stock"]["symbol"] == "MTN"


def test_stock_history_ok(app_factory):
    _, client = app_factory(["gse:stock_history:read"])
    resp = client.post("/tools/gse_get_stock_history", json={"symbol": "GCB", "days": 10})
    assert resp.status_code == 200
    body = resp.json()
    assert body["symbol"] == "GCB"
    assert body["days"] == 10
    assert len(body["entries"]) == 1


def test_market_summary_ok(app_factory):
    _, client = app_factory(["gse:*:read"])
    resp = client.post("/tools/gse_get_market_summary", json={})
    assert resp.status_code == 200


def test_company_info_ok(app_factory):
    _, client = app_factory(["gse:company_info:read"])
    resp = client.post("/tools/gse_get_company_info", json={"symbol": "MTN"})
    assert resp.status_code == 200
    assert resp.json()["equity"]["symbol"] == "MTN"


def test_company_info_unknown(app_factory):
    _, client = app_factory(["gse:company_info:read"])
    resp = client.post("/tools/gse_get_company_info", json={"symbol": "ZZZ"})
    assert resp.status_code == 400


def test_tool_params_stashed_for_audit():
    """Tool handlers must populate request.state.tool_params for the audit middleware."""
    adapter = _FakeAdapter()
    manager = DataSourceManager([adapter])
    cache = _FakeCache()
    service = GSEDataService(manager, cache)
    app = FastAPI()
    captured: dict = {}

    @app.middleware("http")
    async def inject_and_capture(request, call_next):
        request.state.caller = CallerIdentity(
            key_id="k1", owner_id="o1", owner_label="t", scopes=["gse:*:*"], rate_limit_rpm=60
        )
        response = await call_next(request)
        captured["params"] = getattr(request.state, "tool_params", None)
        return response

    register_gse_tools(app, service)
    client = TestClient(app)

    client.post("/tools/gse_get_stock_history", json={"symbol": "GCB", "days": 7})
    assert captured["params"] == {"symbol": "GCB", "days": 7}
