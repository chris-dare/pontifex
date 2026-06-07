from datetime import UTC, datetime

from pontifex_mcp import Cache, DataSourceManager

from gse_mcp.adapters.protocol import GSEDataAdapter
from gse_mcp.models import Equity, HistoryEntry, MarketSummary, Stock

# TTLs in seconds. The cache layer is dumb; the domain decides freshness.
TTLS: dict[str, dict[str, int]] = {
    "live": {"active": 30, "inactive": 3600},
    "history": {"active": 14400, "inactive": 14400},
    "summary": {"active": 60, "inactive": 3600},
    "equities": {"active": 86400, "inactive": 86400},
}


def is_trading_hours(now: datetime | None = None) -> bool:
    """GSE trades Mon-Fri, 10:00-15:00 GMT."""
    now = now or datetime.now(UTC)
    if now.weekday() >= 5:
        return False
    return 10 <= now.hour < 15


def get_ttl(resource: str, now: datetime | None = None) -> int:
    cfg = TTLS.get(resource, {"active": 60, "inactive": 60})
    return cfg["active"] if is_trading_hours(now) else cfg["inactive"]


class AllSourcesUnavailable(RuntimeError):
    """Raised when every adapter in the manager has failed or is circuit-broken."""


class GSEDataService:
    """GSE-specific orchestration: cache check → adapter fallback → cache write."""

    def __init__(self, manager: DataSourceManager, cache: Cache) -> None:
        self.manager = manager
        self.cache = cache

    async def get_live_prices(self) -> tuple[list[Stock], str, bool]:
        cached = await self.cache.get("live:all")
        if cached:
            return [Stock(**s) for s in cached["stocks"]], cached["source"], True

        for adapter in self.manager.get_available_adapters():
            assert isinstance(adapter, GSEDataAdapter)
            try:
                stocks = await adapter.get_live_prices()
            except Exception:
                self.manager.record_failure(adapter.name)
                continue
            self.manager.record_success(adapter.name)
            await self.cache.set(
                "live:all",
                {"stocks": [s.model_dump() for s in stocks], "source": adapter.name},
                ttl_seconds=get_ttl("live"),
            )
            return stocks, adapter.name, False

        raise AllSourcesUnavailable("All GSE data sources unavailable")

    async def get_stock_price(self, symbol: str) -> tuple[Stock | None, str, bool]:
        key = f"live:{symbol.upper()}"
        cached = await self.cache.get(key)
        if cached:
            return Stock(**cached["stock"]) if cached["stock"] else None, cached["source"], True

        for adapter in self.manager.get_available_adapters():
            assert isinstance(adapter, GSEDataAdapter)
            try:
                stock = await adapter.get_stock_price(symbol)
            except Exception:
                self.manager.record_failure(adapter.name)
                continue
            self.manager.record_success(adapter.name)
            await self.cache.set(
                key,
                {"stock": stock.model_dump() if stock else None, "source": adapter.name},
                ttl_seconds=get_ttl("live"),
            )
            return stock, adapter.name, False

        raise AllSourcesUnavailable("All GSE data sources unavailable")

    async def get_stock_history(
        self, symbol: str, days: int
    ) -> tuple[list[HistoryEntry], str, bool]:
        key = f"history:{symbol.upper()}:{days}"
        cached = await self.cache.get(key)
        if cached:
            return [HistoryEntry(**e) for e in cached["entries"]], cached["source"], True

        for adapter in self.manager.get_available_adapters():
            assert isinstance(adapter, GSEDataAdapter)
            try:
                entries = await adapter.get_stock_history(symbol, days)
            except Exception:
                self.manager.record_failure(adapter.name)
                continue
            if not entries:
                # Empty result is not a failure (e.g. kwayisi has no history endpoint).
                # Don't trip the breaker, just try the next adapter.
                continue
            self.manager.record_success(adapter.name)
            await self.cache.set(
                key,
                {"entries": [e.model_dump() for e in entries], "source": adapter.name},
                ttl_seconds=get_ttl("history"),
            )
            return entries, adapter.name, False

        return [], "none", False

    async def get_market_summary(self) -> tuple[MarketSummary | None, str, bool]:
        cached = await self.cache.get("summary")
        if cached:
            return MarketSummary(**cached["summary"]), cached["source"], True

        for adapter in self.manager.get_available_adapters():
            assert isinstance(adapter, GSEDataAdapter)
            try:
                summary = await adapter.get_market_summary()
            except Exception:
                self.manager.record_failure(adapter.name)
                continue
            if summary is None:
                continue
            self.manager.record_success(adapter.name)
            await self.cache.set(
                "summary",
                {"summary": summary.model_dump(mode="json"), "source": adapter.name},
                ttl_seconds=get_ttl("summary"),
            )
            return summary, adapter.name, False

        raise AllSourcesUnavailable("All GSE data sources unavailable")

    async def get_company_info(self, symbol: str) -> tuple[Equity | None, str, bool]:
        key = f"equities:{symbol.upper()}"
        cached = await self.cache.get(key)
        if cached:
            return Equity(**cached["equity"]) if cached["equity"] else None, cached["source"], True

        for adapter in self.manager.get_available_adapters():
            assert isinstance(adapter, GSEDataAdapter)
            try:
                equity = await adapter.get_equity(symbol)
            except Exception:
                self.manager.record_failure(adapter.name)
                continue
            self.manager.record_success(adapter.name)
            await self.cache.set(
                key,
                {"equity": equity.model_dump() if equity else None, "source": adapter.name},
                ttl_seconds=get_ttl("equities"),
            )
            return equity, adapter.name, False

        raise AllSourcesUnavailable("All GSE data sources unavailable")
