from datetime import datetime

from pydantic import BaseModel, Field


class Stock(BaseModel):
    symbol: str
    name: str | None = None
    price: float
    change: float = 0.0
    change_pct: float = 0.0
    volume: int = 0
    sector: str | None = None
    market_cap_ghs: float | None = None
    pe_ratio: float | None = None
    eps: float | None = None


class HistoryEntry(BaseModel):
    date: str  # YYYY-MM-DD
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float
    volume: int = 0


class MarketSummary(BaseModel):
    timestamp: datetime
    gse_ci: float | None = None
    gse_fsi: float | None = None
    total_volume: int = 0
    total_turnover_ghs: float = 0.0
    market_cap_ghs: float | None = None
    gainers: int = 0
    losers: int = 0
    unchanged: int = 0
    top_gainers: list[Stock] = Field(default_factory=list)
    top_losers: list[Stock] = Field(default_factory=list)


class Director(BaseModel):
    name: str
    position: str | None = None


class CompanyProfile(BaseModel):
    name: str
    sector: str | None = None
    industry: str | None = None
    address: str | None = None
    telephone: str | None = None
    email: str | None = None
    website: str | None = None
    directors: list[Director] = Field(default_factory=list)


class Equity(BaseModel):
    """Full equity record from kwayisi /equities endpoint."""

    symbol: str
    price: float | None = None
    eps: float | None = None
    dps: float | None = None
    shares: int | None = None
    capital: float | None = None
    company: CompanyProfile | None = None
