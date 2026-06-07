from datetime import UTC, datetime
from typing import Any

import httpx
from pontifex_mcp import async_retry

from gse_mcp.models import (
    CompanyProfile,
    Director,
    Equity,
    HistoryEntry,
    MarketSummary,
    Stock,
)


class KwayisiAdapter:
    """Primary GSE data source. Free, unauthenticated, no SLA."""

    name: str = "kwayisi"
    priority: int = 1

    def __init__(self, settings: Any) -> None:
        self.base_url = settings.kwayisi_base_url.rstrip("/")
        self.timeout = settings.kwayisi_timeout_seconds
        self.max_retries = settings.kwayisi_max_retries
        self._client = httpx.AsyncClient(timeout=self.timeout)

    async def close(self) -> None:
        await self._client.aclose()

    async def health_check(self) -> bool:
        try:
            r = await self._client.get(f"{self.base_url}/live", timeout=3.0)
            return r.status_code == 200
        except Exception:
            return False

    async def _get(self, path: str) -> Any:
        @async_retry(attempts=self.max_retries, exceptions=(httpx.HTTPError,))
        async def _do() -> Any:
            r = await self._client.get(f"{self.base_url}{path}")
            r.raise_for_status()
            return r.json()

        return await _do()

    async def get_live_prices(self) -> list[Stock]:
        data = await self._get("/live")
        return [_stock_from_live(item) for item in data]

    async def get_stock_price(self, symbol: str) -> Stock | None:
        try:
            data = await self._get(f"/live/{symbol.upper()}")
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return None
            raise
        if not data:
            return None
        # /live/{symbol} returns a single object without the `name` field as symbol
        item = dict(data)
        item.setdefault("name", symbol.upper())
        return _stock_from_live(item, symbol=symbol.upper())

    async def get_stock_history(self, symbol: str, days: int) -> list[HistoryEntry]:
        # kwayisi does not expose a history endpoint. Adapter returns empty so the
        # manager falls back to internal_db.
        return []

    async def get_market_summary(self) -> MarketSummary | None:
        # Derived from the /live response.
        stocks = await self.get_live_prices()
        if not stocks:
            return None
        total_volume = sum(s.volume for s in stocks)
        gainers = sum(1 for s in stocks if s.change > 0)
        losers = sum(1 for s in stocks if s.change < 0)
        unchanged = sum(1 for s in stocks if s.change == 0)
        sorted_by_change = sorted(stocks, key=lambda s: s.change_pct, reverse=True)
        return MarketSummary(
            timestamp=datetime.now(UTC),
            total_volume=total_volume,
            total_turnover_ghs=sum(s.price * s.volume for s in stocks),
            gainers=gainers,
            losers=losers,
            unchanged=unchanged,
            top_gainers=sorted_by_change[:5],
            top_losers=list(reversed(sorted_by_change[-5:])),
        )

    async def fetch_equities(self) -> list[Equity]:
        data = await self._get("/equities")
        return [_equity_from_kwayisi(item) for item in data]

    async def get_equity(self, symbol: str) -> Equity | None:
        try:
            data = await self._get(f"/equities/{symbol.upper()}")
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return None
            raise
        if not data:
            return None
        return _equity_from_kwayisi(data, default_symbol=symbol.upper())


def _stock_from_live(item: dict, symbol: str | None = None) -> Stock:
    # kwayisi /live items look like: {"name": "SYM", "price": ..., "change": ..., "volume": ...}
    sym = symbol or item.get("name") or item.get("symbol") or ""
    price = float(item.get("price") or 0.0)
    change = float(item.get("change") or 0.0)
    change_pct = 0.0
    prev = price - change
    if prev:
        change_pct = round((change / prev) * 100, 4)
    return Stock(
        symbol=sym,
        name=item.get("company") or item.get("name"),
        price=price,
        change=change,
        change_pct=change_pct,
        volume=int(item.get("volume") or 0),
    )


def _equity_from_kwayisi(data: dict, default_symbol: str | None = None) -> Equity:
    company_raw = data.get("company") or {}
    directors = [
        Director(name=d.get("name", ""), position=d.get("position"))
        for d in company_raw.get("directors", [])
        if d.get("name")
    ]
    profile: CompanyProfile | None = None
    if company_raw:
        profile = CompanyProfile(
            name=company_raw.get("name") or data.get("name") or "",
            sector=company_raw.get("sector"),
            industry=company_raw.get("industry"),
            address=company_raw.get("address"),
            telephone=company_raw.get("telephone"),
            email=company_raw.get("email"),
            website=company_raw.get("website"),
            directors=directors,
        )
    return Equity(
        symbol=(data.get("name") or default_symbol or "").upper(),
        price=_maybe_float(data.get("price")),
        eps=_maybe_float(data.get("eps")),
        dps=_maybe_float(data.get("dps")),
        shares=_maybe_int(data.get("shares")),
        capital=_maybe_float(data.get("capital")),
        company=profile,
    )


def _maybe_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _maybe_int(v: Any) -> int | None:
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None
