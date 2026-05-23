from mcp_core.cache.redis_cache import Cache

from gse_mcp.adapters.protocol import GSEDataAdapter
from gse_mcp.models import Equity

EQUITIES_TTL_SECONDS = 86400  # 24h


class SymbolRegistry:
    """Dynamically built from kwayisi /equities endpoint. Cached with 24h TTL."""

    def __init__(self, cache: Cache, adapter: GSEDataAdapter) -> None:
        self.cache = cache
        self.adapter = adapter

    async def get_all(self) -> list[Equity]:
        cached = await self.cache.get("equities")
        if cached:
            return [Equity(**e) for e in cached]

        equities = await self.adapter.fetch_equities()
        await self.cache.set(
            "equities",
            [e.model_dump() for e in equities],
            ttl_seconds=EQUITIES_TTL_SECONDS,
        )
        return equities

    async def get(self, symbol: str) -> Equity | None:
        all_equities = await self.get_all()
        sym = symbol.upper()
        return next((e for e in all_equities if e.symbol.upper() == sym), None)

    async def list_symbols(self) -> list[str]:
        equities = await self.get_all()
        return [e.symbol for e in equities]
