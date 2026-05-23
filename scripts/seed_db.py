"""Seed historical data into gse.symbols + gse.historical_prices.

Usage: uv run python scripts/seed_db.py [--symbols-only]
"""

import asyncio
import sys
from datetime import date, timedelta

from gse_mcp.adapters.internal_db import _CachedEOD, _HistoricalPrice, _Symbol
from gse_mcp.config import GSESettings
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

SEED_SYMBOLS = [
    ("MTN", "MTN Ghana", "Technology"),
    ("GCB", "GCB Bank", "Financials"),
    ("EGH", "Ecobank Ghana", "Financials"),
    ("GOIL", "GOIL Company", "Oil and Gas"),
]


async def main() -> None:
    symbols_only = "--symbols-only" in sys.argv
    settings = GSESettings()
    engine = create_async_engine(settings.database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session:
        for ticker, name, sector in SEED_SYMBOLS:
            await session.execute(insert(_Symbol).values(ticker=ticker, name=name, sector=sector))
        await session.commit()

        if symbols_only:
            return

        today = date.today()
        for ticker, *_ in SEED_SYMBOLS:
            for i in range(30):
                d = today - timedelta(days=i)
                await session.execute(
                    insert(_HistoricalPrice).values(
                        symbol=ticker,
                        date=d,
                        close=10.0 + i * 0.01,
                        volume=1000 + i * 10,
                        source="seed",
                    )
                )
            await session.execute(
                insert(_CachedEOD).values(
                    symbol=ticker,
                    date=today,
                    price=10.0,
                    change=0.0,
                    change_pct=0.0,
                    volume=1000,
                    source="seed",
                )
            )
        await session.commit()


if __name__ == "__main__":
    asyncio.run(main())
