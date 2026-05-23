from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import BigInteger, Boolean, Date, DateTime, Numeric, String, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from gse_mcp.models import Equity, HistoryEntry, MarketSummary, Stock


class _Base(DeclarativeBase):
    pass


class _Symbol(_Base):
    __tablename__ = "symbols"
    __table_args__ = {"schema": "gse"}

    ticker: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    sector: Mapped[str | None] = mapped_column(String, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")


class _HistoricalPrice(_Base):
    __tablename__ = "historical_prices"
    __table_args__ = {"schema": "gse"}

    symbol: Mapped[str] = mapped_column(String, primary_key=True)
    date: Mapped[datetime] = mapped_column(Date, primary_key=True)
    open: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)
    high: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)
    low: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)
    close: Mapped[float] = mapped_column(Numeric(12, 4), nullable=False)
    volume: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    source: Mapped[str] = mapped_column(String, nullable=False)


class _CachedEOD(_Base):
    __tablename__ = "cached_eod_prices"
    __table_args__ = {"schema": "gse"}

    symbol: Mapped[str] = mapped_column(String, primary_key=True)
    date: Mapped[datetime] = mapped_column(Date, primary_key=True)
    price: Mapped[float] = mapped_column(Numeric(12, 4), nullable=False)
    change: Mapped[float] = mapped_column(Numeric(12, 4), nullable=False, server_default="0")
    change_pct: Mapped[float] = mapped_column(Numeric(8, 4), nullable=False, server_default="0")
    volume: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    source: Mapped[str] = mapped_column(String, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class InternalDBAdapter:
    """Fallback adapter backed by gse.* tables. Returns last known EOD when live sources fail."""

    name: str = "internal_db"
    priority: int = 9  # Lowest priority

    def __init__(self, settings: Any) -> None:
        self.engine = create_async_engine(settings.database_url)
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)

    async def health_check(self) -> bool:
        try:
            async with self.session_factory() as session:
                await session.execute(select(1))
            return True
        except Exception:
            return False

    async def get_live_prices(self) -> list[Stock]:
        async with self.session_factory() as session:
            # Most recent cached EOD per symbol
            subq = (
                select(_CachedEOD.symbol, func.max(_CachedEOD.date).label("max_date"))
                .group_by(_CachedEOD.symbol)
                .subquery()
            )
            stmt = (
                select(_CachedEOD, _Symbol)
                .join(
                    subq,
                    (_CachedEOD.symbol == subq.c.symbol) & (_CachedEOD.date == subq.c.max_date),
                )
                .join(_Symbol, _Symbol.ticker == _CachedEOD.symbol, isouter=True)
            )
            rows = (await session.execute(stmt)).all()
            return [
                Stock(
                    symbol=row[0].symbol,
                    name=row[1].name if row[1] else None,
                    price=float(row[0].price),
                    change=float(row[0].change),
                    change_pct=float(row[0].change_pct),
                    volume=int(row[0].volume),
                    sector=row[1].sector if row[1] else None,
                )
                for row in rows
            ]

    async def get_stock_price(self, symbol: str) -> Stock | None:
        async with self.session_factory() as session:
            stmt = (
                select(_CachedEOD, _Symbol)
                .join(_Symbol, _Symbol.ticker == _CachedEOD.symbol, isouter=True)
                .where(_CachedEOD.symbol == symbol.upper())
                .order_by(_CachedEOD.date.desc())
                .limit(1)
            )
            row = (await session.execute(stmt)).first()
            if not row:
                return None
            eod, sym = row
            return Stock(
                symbol=eod.symbol,
                name=sym.name if sym else None,
                price=float(eod.price),
                change=float(eod.change),
                change_pct=float(eod.change_pct),
                volume=int(eod.volume),
                sector=sym.sector if sym else None,
            )

    async def get_stock_history(self, symbol: str, days: int) -> list[HistoryEntry]:
        cutoff = datetime.now(UTC).date() - timedelta(days=days)
        async with self.session_factory() as session:
            stmt = (
                select(_HistoricalPrice)
                .where(_HistoricalPrice.symbol == symbol.upper())
                .where(_HistoricalPrice.date >= cutoff)
                .order_by(_HistoricalPrice.date.asc())
            )
            rows = (await session.execute(stmt)).scalars().all()
            return [
                HistoryEntry(
                    date=str(r.date),
                    open=float(r.open) if r.open is not None else None,
                    high=float(r.high) if r.high is not None else None,
                    low=float(r.low) if r.low is not None else None,
                    close=float(r.close),
                    volume=int(r.volume),
                )
                for r in rows
            ]

    async def get_market_summary(self) -> MarketSummary | None:
        stocks = await self.get_live_prices()
        if not stocks:
            return None
        return MarketSummary(
            timestamp=datetime.now(UTC),
            total_volume=sum(s.volume for s in stocks),
            total_turnover_ghs=sum(s.price * s.volume for s in stocks),
            gainers=sum(1 for s in stocks if s.change > 0),
            losers=sum(1 for s in stocks if s.change < 0),
            unchanged=sum(1 for s in stocks if s.change == 0),
        )

    async def fetch_equities(self) -> list[Equity]:
        async with self.session_factory() as session:
            rows = (await session.execute(select(_Symbol))).scalars().all()
            return [Equity(symbol=r.ticker) for r in rows]

    async def get_equity(self, symbol: str) -> Equity | None:
        async with self.session_factory() as session:
            row = (
                await session.execute(select(_Symbol).where(_Symbol.ticker == symbol.upper()))
            ).scalar_one_or_none()
            if not row:
                return None
            return Equity(symbol=row.ticker)
