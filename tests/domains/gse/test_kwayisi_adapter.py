import httpx
import respx
from gse_mcp.adapters.kwayisi import KwayisiAdapter


@respx.mock
async def test_get_live_prices(gse_settings, fixture):
    respx.get("https://dev.kwayisi.org/apis/gse/live").mock(
        return_value=httpx.Response(200, json=fixture("live_all"))
    )
    adapter = KwayisiAdapter(gse_settings)
    try:
        stocks = await adapter.get_live_prices()
    finally:
        await adapter.close()

    assert len(stocks) == 4
    mtn = next(s for s in stocks if s.symbol == "MTN")
    assert mtn.price == 25.50
    assert mtn.change == 0.72
    assert mtn.volume == 374476
    # change_pct should be derived: 0.72 / (25.50 - 0.72) * 100
    assert round(mtn.change_pct, 2) == 2.91


@respx.mock
async def test_get_stock_price(gse_settings, fixture):
    respx.get("https://dev.kwayisi.org/apis/gse/live/MTN").mock(
        return_value=httpx.Response(200, json=fixture("live_mtn"))
    )
    adapter = KwayisiAdapter(gse_settings)
    try:
        stock = await adapter.get_stock_price("mtn")
    finally:
        await adapter.close()
    assert stock is not None
    assert stock.symbol == "MTN"
    assert stock.price == 25.50


@respx.mock
async def test_get_stock_price_404_returns_none(gse_settings):
    respx.get("https://dev.kwayisi.org/apis/gse/live/NOPE").mock(
        return_value=httpx.Response(404, json={})
    )
    adapter = KwayisiAdapter(gse_settings)
    try:
        result = await adapter.get_stock_price("NOPE")
    finally:
        await adapter.close()
    assert result is None


@respx.mock
async def test_get_equity(gse_settings, fixture):
    respx.get("https://dev.kwayisi.org/apis/gse/equities/MTN").mock(
        return_value=httpx.Response(200, json=fixture("equities_mtn"))
    )
    adapter = KwayisiAdapter(gse_settings)
    try:
        equity = await adapter.get_equity("MTN")
    finally:
        await adapter.close()
    assert equity is not None
    assert equity.symbol == "MTN"
    assert equity.eps == 0.14
    assert equity.company is not None
    assert equity.company.name == "MTN Ghana"
    assert len(equity.company.directors) == 2


@respx.mock
async def test_get_market_summary_derived_from_live(gse_settings, fixture):
    respx.get("https://dev.kwayisi.org/apis/gse/live").mock(
        return_value=httpx.Response(200, json=fixture("live_all"))
    )
    adapter = KwayisiAdapter(gse_settings)
    try:
        summary = await adapter.get_market_summary()
    finally:
        await adapter.close()
    assert summary is not None
    assert summary.gainers == 2  # MTN, GOIL
    assert summary.losers == 1  # GCB
    assert summary.unchanged == 1  # EGH
    assert summary.total_volume == 374476 + 12000 + 4500 + 22000


@respx.mock
async def test_health_check_ok(gse_settings):
    respx.get("https://dev.kwayisi.org/apis/gse/live").mock(
        return_value=httpx.Response(200, json=[])
    )
    adapter = KwayisiAdapter(gse_settings)
    try:
        assert await adapter.health_check() is True
    finally:
        await adapter.close()
