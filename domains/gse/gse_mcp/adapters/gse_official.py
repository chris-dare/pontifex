from typing import Any

from gse_mcp.models import Equity, HistoryEntry, MarketSummary, Stock


class GSEOfficialAdapter:
    """Stub for the licensed GSE official feed. Not implemented yet."""

    name: str = "gse_official"
    priority: int = 0  # Highest priority once enabled

    def __init__(self, settings: Any) -> None:
        self.base_url = settings.gse_official_base_url
        self.api_key = settings.gse_official_api_key
        self.enabled = bool(self.base_url and self.api_key)

    async def health_check(self) -> bool:
        return False  # Not implemented

    async def get_live_prices(self) -> list[Stock]:
        raise NotImplementedError("GSE official feed not yet integrated.")

    async def get_stock_price(self, symbol: str) -> Stock | None:
        raise NotImplementedError("GSE official feed not yet integrated.")

    async def get_stock_history(self, symbol: str, days: int) -> list[HistoryEntry]:
        raise NotImplementedError("GSE official feed not yet integrated.")

    async def get_market_summary(self) -> MarketSummary | None:
        raise NotImplementedError("GSE official feed not yet integrated.")

    async def fetch_equities(self) -> list[Equity]:
        raise NotImplementedError("GSE official feed not yet integrated.")

    async def get_equity(self, symbol: str) -> Equity | None:
        raise NotImplementedError("GSE official feed not yet integrated.")
