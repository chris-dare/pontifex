# pontifex-mcp — Solution Design

## 1. Overview

**`pontifex-mcp`** is a Python library for building enterprise-grade MCP (Model Context Protocol) servers — servers that expose your systems to AI agents without giving up control over who can call what. The library (`core/pontifex_mcp`, published to PyPI) is the product. It handles everything domain-agnostic: transport, authentication (API keys + OAuth 2.1 JWTs), scope-based permissions, caching, audit logging, circuit breaking, and observability. You write the tools; it governs every call.

You expose a system by writing a **domain module** — a self-contained set of tools and data adapters that plugs into the shared core. This repo ships one as a worked example: **Ghana Stock Exchange (GSE)** market data. It demonstrates the library against a real data source; it is a demo, not the product.

Callers present API keys (or OAuth 2.1 tokens) carrying fine-grained permission scopes (e.g. `gse:*:*`, `gse:live_prices:read`), and the library enforces them before any tool runs. It does not manage users, billing, or plan tiers — those are provisioned by whatever sits above it (your own admin tool, an enterprise panel, a config file, or, eventually, a managed "Pontifex" service that does not exist yet).

### 1.1 Scope

**Today:** The open-source `pontifex-mcp` library — authentication (API keys + OAuth 2.1), `domain:resource:action` scopes, audit, caching, resilience, observability — plus a `pontifex-mcp` CLI for schema migrations and API-key lifecycle (create / list / revoke), and the GSE domain as a worked example. It runs with zero infrastructure on a local SQLite floor (Redis optional) and scales to Postgres + Redis in production. Usable directly, or behind any system that provisions API keys.

**Ahead:** A growing set of governance capabilities (approval workflows, data masking, audit export, auto-generated connectors) and more example domains as use cases appear. The architecture already supports any number of domains — each a self-contained module deployed independently. Other domains named in this doc (GFI, NGX, logistics) are illustrative only.

The foundation is solid; the capability set is deliberately focused and expands as use cases appear.

### 1.2 Constraints

- Python 3.12+ with FastAPI
- API key + OAuth 2.1 auth with scope-based permissions; the library does not manage users, billing, or plans
- All tool invocations must be logged with caller identity, timestamp, parameters, and response latency
- External APIs may lack SLAs; the system must tolerate unavailability of any single source
- Each domain module deploys as an independent container for fault isolation

---

## 2. Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│ Upstream Platform (NOT part of this product)                     │
│  • SaaS dashboard, enterprise admin panel, or config file       │
│  • Manages users, billing, plan tiers                           │
│  • Issues API keys with permission scopes                       │
│  • Writes keys + scopes to pontifex_mcp_core.api_keys           │
└──────────────────────────┬──────────────────────────────────────┘
                           │ provisions API keys
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│ AI Agents (MCP Clients)                                         │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────────────┐  │
│  │ Claude       │  │ Claude API   │  │ Custom MCP client     │  │
│  │ Desktop      │  │ integration  │  │ (any framework)       │  │
│  └──────┬───────┘  └──────┬───────┘  └───────────┬───────────┘  │
└─────────┼─────────────────┼──────────────────────┼──────────────┘
          │ API key          │ API key              │ API key
          ▼                  ▼                      ▼
┌─────────────────────────────────────────────────────────────────┐
│ API Gateway (Kong / NGINX / Cloudflare)                         │
│  • TLS termination                                              │
│  • Rate limiting per key                                        │
│  • Route: /mcp/gse → GSE server, /mcp/{domain} → etc.          │
└──────────────┬──────────────────────────────────────────────────┘
               │
               ▼
┌──────────────────┐ ┌──────────────────────────────────────────┐
│ GSE MCP Server   │ │ Future domain servers                    │
│ (domain module)  │ │ (same pattern, added as needed)          │
│                  │ │                                          │
│ Uses: pontifex_mcp   │ │ Uses: pontifex_mcp                           │
└────────┬─────────┘ └────────┬─────────────────────────────────┘
         │                    │                    │
         ▼                    ▼                    ▼
┌─────────────────────────────────────────────────────────────────┐
│ Shared Infrastructure                                           │
│  ┌────────────┐    ┌──────────────┐    ┌──────────────┐         │
│  │ PostgreSQL │    │ Redis        │    │ Logfire      │         │
│  │ Keys+Audit │    │ Cache+Keys   │    │ Observability│         │
│  └────────────┘    └──────────────┘    └──────────────┘         │
└─────────────────────────────────────────────────────────────────┘
```

`pontifex-mcp` is a **library**, not a service. A server built with it authenticates callers, enforces permission scopes, and serves data. It does not manage users, plans, or billing — that's the job of whatever provisions the keys above it. Keys reach `pontifex_mcp_core.api_keys` one of two ways: the bundled `pontifex-mcp keys` CLI (§11.8), or an upstream system that writes records directly as part of its own billing or admin flow (the topology drawn above). Either way the server only reads the rows and enforces their scopes.

---

## 3. Project Structure

Uses [uv workspaces](https://docs.astral.sh/uv/concepts/projects/workspaces/) with flat layout — following the convention used by FastAPI, Pydantic, and Pydantic AI.

```
pontifex/
├── pyproject.toml                          # Virtual workspace root (no [project] table)
├── uv.lock                                # Auto-generated, committed to version control
├── .python-version                         # e.g. "3.12"
├── README.md
├── CLAUDE.md
├── SOLUTION_DESIGN.md
├── docker-compose.yml                      # Dev: all services + Redis + Postgres
│
├── alembic/                                # Monorepo migration config (demo domain branch)
│   ├── alembic.ini                         # Points at the in-package core branch + gse
│   └── domains/                            # Per-domain schema migrations
│       └── gse/
│           └── versions/
│               ├── 001_create_symbols.py
│               ├── 002_create_historical_prices.py
│               └── 003_create_cached_eod_prices.py
│                                           # Core schema migrations ship in the wheel
│                                           # (core/pontifex_mcp/migrations/, see §14.6)
│
├── core/                                   # ── Shared library (pontifex-mcp) ──
│   ├── pyproject.toml                      # [build-system] uses uv_build
│   └── pontifex_mcp/
│       ├── __init__.py
│       ├── py.typed                        # Type checker marker
│       ├── server_factory.py               # Creates configured MCP server from parts
│       ├── config.py                       # Base settings all domains inherit
│       ├── storage.py                      # DB engine + dialect detection (SQLite floor ↔ Postgres)
│       │
│       ├── cli/                            # `pontifex-mcp` CLI (Typer entry point)
│       │   ├── __init__.py
│       │   ├── db.py                       # `db upgrade` — migrations (PG) / create_all (SQLite)
│       │   └── keys.py                     # `keys create | list | revoke`
│       │
│       ├── migrations/                     # Core schema migrations — shipped in the wheel
│       │   ├── alembic.ini                 # %(here)s paths; `db upgrade` loads this
│       │   ├── env.py                      # Reads DATABASE_URL; advisory-locks the upgrade
│       │   └── versions/
│       │
│       ├── auth/
│       │   ├── __init__.py
│       │   ├── api_keys.py                 # API key validation + caching
│       │   ├── identity.py                 # CallerIdentity + resolution from key
│       │   └── scopes.py                   # Scope matching logic (domain:resource:action)
│       │
│       ├── adapters/
│       │   ├── __init__.py
│       │   ├── base.py                     # DataAdapter protocol (generic)
│       │   └── manager.py                  # DataSourceManager with fallback chain
│       │
│       ├── cache/
│       │   ├── __init__.py
│       │   └── redis_cache.py              # Prefix-aware, TTL-configurable cache
│       │
│       ├── middleware/
│       │   ├── __init__.py
│       │   ├── auth.py                     # API key extraction + identity resolution
│       │   └── audit.py                    # Structured audit logging to Postgres
│       │
│       ├── models/
│       │   ├── __init__.py
│       │   ├── base.py                     # ToolResponse, AuditRecord, ToolError (Pydantic)
│       │   └── db.py                       # SQLAlchemy: api_keys, audit_log, domain_registry
│       │
│       ├── observability/
│       │   ├── __init__.py
│       │   └── logfire_setup.py            # Logfire (OTEL-based) instrumentation
│       │
│       └── utils/
│           ├── __init__.py
│           ├── circuit_breaker.py          # Generic circuit breaker
│           └── retry.py                    # Exponential backoff with jitter
│
├── domains/                                # ── Domain modules ──
│   │
│   ├── gse/                                # Ghana Stock Exchange
│   │   ├── pyproject.toml                  # Depends on pontifex-mcp via workspace source
│   │   └── gse_mcp/
│   │       ├── __init__.py
│   │       ├── py.typed
│   │       ├── main.py                     # Entrypoint: wires tools + adapters → factory
│   │       ├── config.py                   # GSE-specific settings (extends base)
│   │       ├── data.py                     # GSEDataService: cache + adapter orchestration
│   │       ├── tools/
│   │       │   ├── __init__.py             # Registers all tools
│   │       │   ├── live_prices.py
│   │       │   ├── stock_price.py
│   │       │   ├── stock_history.py
│   │       │   ├── market_summary.py
│   │       │   └── company_info.py         # New tools added here as needed
│   │       ├── adapters/
│   │       │   ├── __init__.py
│   │       │   ├── protocol.py             # GSEDataAdapter (extends base DataAdapter)
│   │       │   ├── kwayisi.py              # Primary free API
│   │       │   ├── gse_official.py         # Licensed feed (stub)
│   │       │   └── internal_db.py          # Historical data store
│   │       ├── models.py                   # Stock, HistoryEntry, MarketSummary, Equity
│   │       └── symbol_registry.py          # Dynamic symbol lookup via /equities + cache
│   │
│   └── # Future domains: domains/{name}/pyproject.toml + {name}_mcp/
│
├── tests/
│   ├── conftest.py                         # Shared fixtures: Redis, Postgres, mock clock
│   ├── core/
│   │   ├── test_cache.py
│   │   ├── test_circuit_breaker.py
│   │   ├── test_audit.py
│   │   ├── test_auth.py
│   │   ├── test_scope_matching.py
│   │   ├── test_data_source_manager.py
│   │   └── test_server_factory.py
│   └── domains/
│       └── gse/
│           ├── conftest.py                 # GSE-specific fixtures, kwayisi mocks
│           ├── test_tools.py
│           ├── test_kwayisi_adapter.py
│           ├── test_internal_db_adapter.py
│           └── fixtures/                   # Recorded kwayisi API responses
│               ├── live_all.json
│               ├── live_mtn.json
│               └── history_gcb.json
│
├── scripts/
│   ├── seed_db.py                          # Seed historical data
│   ├── export_audit_logs.py                # Nightly: Postgres → Parquet cold storage
│   └── health_check.py                     # Liveness/readiness probe script
│
└── deploy/
    ├── Dockerfile.gse
    └── docker-compose.prod.yml             # Add more Dockerfiles per domain as needed
```

---


## 4. Core Library

### 4.1 Base Configuration

Every domain inherits from this. Domain-specific settings extend it with their own fields and env prefix.

```python
# core/pontifex_mcp/config.py

from pydantic_settings import BaseSettings


class CoreSettings(BaseSettings):
    """Settings shared by all domain modules."""

    # Server
    host: str = "0.0.0.0"
    port: int = 8080
    transport: str = "streamable-http"      # "stdio" or "streamable-http"
    log_level: str = "INFO"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # PostgreSQL (audit log + domain data)
    database_url: str = "postgresql+asyncpg://mcp:mcp@localhost:5432/mcp_platform"

    # Circuit breaker defaults
    cb_failure_threshold: int = 3
    cb_recovery_timeout_seconds: float = 30.0

    # Auth
    api_key_cache_ttl_seconds: int = 300  # Cache key→identity lookup for 5 min
    api_key_hash_algorithm: str = "sha256"

    # Observability
    logfire_token: str = ""               # Logfire write token (OTEL-based)
```

### 4.2 Generic Data Adapter Protocol

The adapter interface is deliberately minimal. Domains define their own method signatures by extending this protocol. The core only cares about `name`, `priority`, and `health_check` for orchestration.

```python
# core/pontifex_mcp/adapters/base.py

from typing import Protocol, runtime_checkable


@runtime_checkable
class DataAdapter(Protocol):
    """Minimum contract for any data source adapter."""

    @property
    def name(self) -> str:
        """Identifier for logging, metrics, and cache tagging."""
        ...

    @property
    def priority(self) -> int:
        """Lower = tried first in the fallback chain."""
        ...

    async def health_check(self) -> bool:
        """Can this adapter reach its data source right now?"""
        ...
```

Domains extend this with their own methods:

```python
# domains/gse/gse_mcp/adapters/protocol.py

from pontifex_mcp.adapters.base import DataAdapter
from gse_mcp.models import Stock, HistoryEntry, MarketSummary


class GSEDataAdapter(DataAdapter):
    async def get_live_prices(self) -> list[Stock]: ...
    async def get_stock_price(self, symbol: str) -> Stock | None: ...
    async def get_stock_history(self, symbol: str, days: int) -> list[HistoryEntry]: ...
    async def get_market_summary(self) -> MarketSummary | None: ...
```

A logistics domain would look completely different:

```python
# Example: domains/logistics/adapters/protocol.py

class LogisticsDataAdapter(DataAdapter):
    async def get_shipment_status(self, tracking_id: str) -> Shipment: ...
    async def get_route_eta(self, origin: str, dest: str) -> RouteETA: ...
```

### 4.3 DataSourceManager

Generic adapter orchestration. The domain passes in its typed adapters; the manager handles circuit breaking and fallback ordering. Each domain wraps this with typed methods.

```python
# core/pontifex_mcp/adapters/manager.py

from pontifex_mcp.adapters.base import DataAdapter
from pontifex_mcp.utils.circuit_breaker import CircuitBreaker


class DataSourceManager:
    """Manages a set of adapters with circuit breakers and priority fallback."""

    def __init__(self, adapters: list[DataAdapter], cb_failure_threshold: int = 3,
                 cb_recovery_timeout: float = 30.0):
        self.adapters = sorted(adapters, key=lambda a: a.priority)
        self.breakers = {
            a.name: CircuitBreaker(
                name=a.name,
                failure_threshold=cb_failure_threshold,
                recovery_timeout=cb_recovery_timeout,
            )
            for a in adapters
        }

    def get_available_adapters(self) -> list[DataAdapter]:
        """Return adapters whose circuit breakers allow a call."""
        return [a for a in self.adapters if self.breakers[a.name].is_available]

    def record_success(self, adapter_name: str) -> None:
        self.breakers[adapter_name].record_success()

    def record_failure(self, adapter_name: str) -> None:
        self.breakers[adapter_name].record_failure()

    async def health_summary(self) -> dict[str, dict]:
        """Return health and breaker state for each adapter."""
        result = {}
        for adapter in self.adapters:
            breaker = self.breakers[adapter.name]
            healthy = False
            if breaker.is_available:
                try:
                    healthy = await adapter.health_check()
                except Exception:
                    healthy = False
            result[adapter.name] = {
                "healthy": healthy,
                "circuit_state": breaker.state.value,
                "failure_count": breaker.failure_count,
            }
        return result
```

Each domain builds a typed layer on top:

```python
# domains/gse/gse_mcp/data.py (domain-level manager)

from pontifex_mcp.adapters.manager import DataSourceManager
from pontifex_mcp.cache.redis_cache import Cache
from gse_mcp.adapters.protocol import GSEDataAdapter
from gse_mcp.models import Stock


class GSEDataService:
    """GSE-specific orchestration: cache check → adapter fallback → cache write."""

    def __init__(self, manager: DataSourceManager, cache: Cache):
        self.manager = manager
        self.cache = cache

    async def get_live_prices(self) -> tuple[list[Stock], str, bool]:
        cached = await self.cache.get("live:all")
        if cached:
            stocks = [Stock(**s) for s in cached["stocks"]]
            return stocks, cached["source"], True  # cache_hit=True

        for adapter in self.manager.get_available_adapters():
            try:
                stocks = await adapter.get_live_prices()
                self.manager.record_success(adapter.name)
                await self.cache.set("live:all", {
                    "stocks": [s.model_dump() for s in stocks],
                    "source": adapter.name,
                }, ttl_seconds=30)
                return stocks, adapter.name, False
            except Exception:
                self.manager.record_failure(adapter.name)
                continue

        raise RuntimeError("All GSE data sources unavailable")
```

### 4.4 Cache Layer

The cache is prefix-aware and TTL-agnostic — the domain tells it how long to cache each key. Core has no concept of "active hours" or "trading hours." If a domain wants different TTLs at different times, it computes the TTL before calling the cache.

```python
# core/pontifex_mcp/cache/redis_cache.py

import json
import redis.asyncio as redis


class Cache:
    def __init__(self, redis_url: str, prefix: str):
        self.client = redis.from_url(redis_url)
        self.prefix = prefix                        # e.g. "gse", "logistics"

    async def get(self, key: str) -> dict | None:
        raw = await self.client.get(f"{self.prefix}:{key}")
        if raw is None:
            return None
        return json.loads(raw)

    async def set(self, key: str, value: dict, ttl_seconds: int) -> None:
        await self.client.setex(f"{self.prefix}:{key}", ttl_seconds, json.dumps(value))

    async def invalidate(self, pattern: str) -> None:
        keys = []
        async for key in self.client.scan_iter(f"{self.prefix}:{pattern}*"):
            keys.append(key)
        if keys:
            await self.client.delete(*keys)
```

The domain decides TTLs. For GSE, the data service computes TTL based on trading hours:

```python
# domains/gse/gse_mcp/data.py (excerpt)

from datetime import datetime, timezone

# TTLs in seconds
TTLS = {
    "live":    {"active": 30,  "inactive": 3600},
    "history": {"active": 14400, "inactive": 14400},  # 4 hours always
    "summary": {"active": 60,  "inactive": 3600},
    "equities": {"active": 86400, "inactive": 86400},  # 24 hours always
}

def get_ttl(resource: str) -> int:
    ttl_config = TTLS.get(resource, {"active": 60, "inactive": 60})
    if _is_trading_hours():
        return ttl_config["active"]
    return ttl_config["inactive"]

def _is_trading_hours() -> bool:
    now = datetime.now(timezone.utc)
    if now.weekday() >= 5:
        return False
    return 10 <= now.hour < 15    # GSE: Mon-Fri, 10:00-15:00 GMT

# Usage in the data service:
await cache.set("live:all", data, ttl_seconds=get_ttl("live"))
```

A non-market domain would just pass a flat TTL — no hours logic needed. The core cache doesn't care.

### 4.5 Server Factory

The factory wires all the core pieces together so each domain's `main.py` stays small.

```python
# core/pontifex_mcp/server_factory.py

from fastapi import FastAPI
from pontifex_mcp.config import CoreSettings
from pontifex_mcp.middleware.auth import AuthMiddleware
from pontifex_mcp.middleware.audit import AuditMiddleware
from pontifex_mcp.observability.logfire_setup import setup_logfire


def create_mcp_app(
    domain_name: str,
    settings: CoreSettings,
    register_tools: callable,       # Function that registers MCP tools on the server
    health_check: callable,         # Async function returning readiness status
) -> FastAPI:
    """
    Build a fully configured FastAPI + MCP server.

    The domain module provides:
      - domain_name: identifier for metrics, cache prefix, audit logs
      - settings: domain config (extends CoreSettings)
      - register_tools: function that registers MCP tools
      - health_check: async function for readiness probe

    The factory provides:
      - Transport (stdio or Streamable HTTP based on settings)
      - Auth middleware
      - Audit logging middleware
      - Health endpoints (/health/live, /health/ready)
      - Logfire (OTEL-based tracing, metrics, dashboards)
    """
    app = FastAPI(title=f"{domain_name}-mcp")

    # Observability
    if settings.logfire_token:
        setup_logfire(app, domain_name, settings.logfire_token)

    # Middleware (applied in reverse order; audit runs last = logs everything)
    app.add_middleware(AuditMiddleware, domain=domain_name, db_url=settings.database_url)
    app.add_middleware(AuthMiddleware,
                       redis_url=settings.redis_url,
                       database_url=settings.database_url,
                       cache_ttl=settings.api_key_cache_ttl_seconds)

    # Health endpoints
    @app.get("/health/live")
    async def liveness():
        return {"status": "ok"}

    @app.get("/health/ready")
    async def readiness():
        return await health_check()

    # Register MCP tools
    register_tools(app)

    return app
```

Each domain's `config.py` extends `CoreSettings` with domain-specific fields:

```python
# domains/gse/gse_mcp/config.py

from pontifex_mcp.config import CoreSettings


class GSESettings(CoreSettings):
    kwayisi_base_url: str = "https://dev.kwayisi.org/apis/gse"
    kwayisi_timeout_seconds: float = 8.0
    kwayisi_max_retries: int = 3

    gse_official_base_url: str = ""
    gse_official_api_key: str = ""

    model_config = {"env_prefix": "GSE_MCP_"}
```

Each domain's `main.py` becomes ~30 lines:

```python
# domains/gse/gse_mcp/main.py

from pontifex_mcp.server_factory import create_mcp_app
from pontifex_mcp.cache.redis_cache import Cache
from pontifex_mcp.adapters.manager import DataSourceManager
from gse_mcp.config import GSESettings
from gse_mcp.adapters.kwayisi import KwayisiAdapter
from gse_mcp.adapters.internal_db import InternalDBAdapter
from gse_mcp.data import GSEDataService
from gse_mcp.tools import register_gse_tools

settings = GSESettings()

# Adapters
adapters = [
    KwayisiAdapter(settings),
    InternalDBAdapter(settings),
]
manager = DataSourceManager(adapters, settings.cb_failure_threshold,
                            settings.cb_recovery_timeout_seconds)

# Cache with GSE trading hours
cache = Cache(settings.redis_url, prefix="gse")

# Domain data service
data_service = GSEDataService(manager, cache)

# Wire it up
app = create_mcp_app(
    domain_name="gse",
    settings=settings,
    register_tools=lambda app: register_gse_tools(app, data_service),
    health_check=manager.health_summary,
)
```

---

## 5. GSE Domain Module — Tool Specifications

All tool names are prefixed with the domain (`gse_`) so they don't collide when a client connects to multiple domain servers.

### 5.1 gse_get_live_prices

```json
{
  "name": "gse_get_live_prices",
  "description": "Fetch real-time prices for all stocks on the Ghana Stock Exchange. Returns price, change, and volume for each equity. Data is from the live trading session (10:00-15:00 GMT) or the most recent close outside trading hours.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "sector": {
        "type": "string",
        "enum": ["financials", "consumer_goods", "industrials", "oil_and_gas", "technology", "all"],
        "description": "Filter by GSE sector. Defaults to 'all'.",
        "default": "all"
      },
      "sort_by": {
        "type": "string",
        "enum": ["symbol", "price", "change", "volume"],
        "default": "symbol"
      }
    },
    "required": []
  }
}
```

**Response schema:**

```json
{
  "timestamp": "2026-05-22T14:30:00Z",
  "source": "kwayisi",
  "is_live": true,
  "cache_hit": false,
  "stocks": [
    {
      "symbol": "MTN",
      "name": "MTN Ghana",
      "price": 25.50,
      "change": 0.72,
      "change_pct": 2.91,
      "volume": 374476,
      "sector": "technology"
    }
  ]
}
```

### 5.2 gse_get_stock_price

```json
{
  "name": "gse_get_stock_price",
  "description": "Get current price, change, and volume for a specific stock on the Ghana Stock Exchange.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "symbol": {
        "type": "string",
        "description": "GSE ticker symbol (case-insensitive). Examples: MTN, GCB, ABSA, CAL, EGH, GOIL."
      }
    },
    "required": ["symbol"]
  }
}
```

**Response schema:**

```json
{
  "timestamp": "2026-05-22T14:30:00Z",
  "source": "kwayisi",
  "is_live": true,
  "cache_hit": true,
  "stock": {
    "symbol": "MTN",
    "name": "MTN Ghana",
    "price": 25.50,
    "change": 0.72,
    "change_pct": 2.91,
    "volume": 374476,
    "sector": "technology",
    "market_cap_ghs": null,
    "pe_ratio": null,
    "eps": null
  }
}
```

### 5.3 gse_get_stock_history

```json
{
  "name": "gse_get_stock_history",
  "description": "Get historical end-of-day prices for a GSE-listed stock.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "symbol": {
        "type": "string",
        "description": "GSE ticker symbol."
      },
      "days": {
        "type": "integer",
        "description": "Trading days of history. Max 365. Default 30.",
        "default": 30,
        "minimum": 1,
        "maximum": 365
      }
    },
    "required": ["symbol"]
  }
}
```

### 5.4 gse_get_market_summary

```json
{
  "name": "gse_get_market_summary",
  "description": "Get today's GSE market summary: composite index, total volume, turnover, gainers, losers.",
  "inputSchema": {
    "type": "object",
    "properties": {},
    "required": []
  }
}
```

**Response schema:**

```json
{
  "timestamp": "2026-05-22T15:00:00Z",
  "source": "kwayisi",
  "is_live": false,
  "cache_hit": true,
  "gse_ci": 15320.45,
  "gse_fsi": 2105.12,
  "total_volume": 1182029,
  "total_turnover_ghs": 4612250.32,
  "market_cap_ghs": 265400000000,
  "gainers": 2,
  "losers": 4,
  "unchanged": 16,
  "top_gainers": [{"symbol": "MTN", "change_pct": 2.91}],
  "top_losers": [{"symbol": "ETI", "change_pct": -3.40}]
}
```

### 5.5 gse_get_company_info

```json
{
  "name": "gse_get_company_info",
  "description": "Get company profile, directors, EPS, DPS, and shares outstanding for a GSE-listed equity. Data sourced from the equities registry.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "symbol": {
        "type": "string",
        "description": "GSE ticker symbol."
      }
    },
    "required": ["symbol"]
  }
}
```

**Scope:** `gse:company_info:read`

---

## 6. GSE Adapter: kwayisi

Primary adapter. Free, no authentication required.

**Base URL:** `https://dev.kwayisi.org/apis/gse`

**Endpoints:**

| Endpoint | Method | Returns |
|----------|--------|---------|
| `/live` | GET | Array of `{name, price, change, volume}` for all listed symbols |
| `/live/{symbol}` | GET | Single `{name, price, change, volume}` object |
| `/equities` | GET | Array of equity objects with company profile, EPS, DPS, shares outstanding |
| `/equities/{symbol}` | GET | Single equity object with full company details |

**`/equities/{symbol}` response shape:**

```json
{
  "capital": 383980,
  "company": {
    "address": "P. O. Box 123, Accra",
    "directors": [
      {"name": "Kofi Abanga", "position": "Chairman"},
      {"name": "Ama Nantwie", "position": null}
    ],
    "email": "abc@example.com",
    "facsimile": "+233 (302) 123 456",
    "industry": "Mining",
    "name": "ABC Company Ltd.",
    "sector": "Basic Materials",
    "telephone": "+233 (302) 123 789",
    "website": "www.example.com"
  },
  "dps": 0.07,
  "eps": 0.14,
  "name": "ABC",
  "price": 10.52,
  "shares": 36500
}
```

**Query params:** `?prettify` for formatted JSON, `?callback=fn` for JSONP.

**Dynamic symbol map:** Instead of maintaining a hardcoded symbol-to-company mapping, the adapter fetches `/equities` on startup and caches it with a 24-hour TTL. This ensures new listings and delistings are picked up automatically. The cached equities data serves as the symbol registry — providing company name, sector, industry, and other metadata for each ticker.

**Known issues and mitigations:**

| Issue | Mitigation |
|-------|------------|
| No SLA, no uptime guarantee | Circuit breaker (3 failures → open 30s) + fallback to internal DB |
| No rate limit docs | Self-impose 1 req/s; cache absorbs most traffic |
| Connection timeouts from some hosts | httpx timeout set to 8s; retry 3x with backoff |
| Some `/equities` fields (dps, eps) are null | Tolerate nulls in domain models; don't fail on missing data |
| No market summary endpoint | Derive from `/live` response (aggregate volume, count gainers/losers) |
| No CORS headers | Server-side calls only; not a concern for MCP |
| Unclear redistribution terms | Low risk for internal/developer use; use GSE official feed for commercial redistribution |

---

## 7. GSE Domain Models

```python
# domains/gse/gse_mcp/models.py

from pydantic import BaseModel, Field
from datetime import datetime


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
    date: str                           # YYYY-MM-DD
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
    eps: float | None = None             # Earnings per share
    dps: float | None = None             # Dividend per share
    shares: int | None = None            # Shares outstanding
    capital: float | None = None         # Market capitalisation
    company: CompanyProfile | None = None
```

---

## 8. GSE Symbol Registry

The symbol registry is built dynamically from the kwayisi `/equities` endpoint — not maintained as a static file. On startup, the adapter fetches the full equities list and caches it. New listings and delistings are reflected automatically.

```python
# domains/gse/gse_mcp/symbol_registry.py

from gse_mcp.models import Equity


class SymbolRegistry:
    """
    Dynamically built from kwayisi /equities endpoint.
    Cached with 24h TTL. Refreshed on cache miss.
    """

    def __init__(self, cache, adapter):
        self.cache = cache
        self.adapter = adapter

    async def get_all(self) -> list[Equity]:
        cached = await self.cache.get("equities")
        if cached:
            return [Equity(**e) for e in cached]

        equities = await self.adapter.fetch_equities()
        await self.cache.set("equities", [e.model_dump() for e in equities], ttl_seconds=86400)
        return equities

    async def get(self, symbol: str) -> Equity | None:
        all_equities = await self.get_all()
        return next((e for e in all_equities if e.symbol.upper() == symbol.upper()), None)

    async def list_symbols(self) -> list[str]:
        equities = await self.get_all()
        return [e.symbol for e in equities]
```

The old static `symbol_map.py` dict is no longer needed. See Section 6 for the `/equities` response schema that feeds this registry.

---

## 9. Core Shared Models

```python
# core/pontifex_mcp/models/base.py

from pydantic import BaseModel
from datetime import datetime


class ToolResponse(BaseModel):
    """Wrapper metadata returned with every tool call."""
    timestamp: datetime
    source: str             # Which adapter served the data
    is_live: bool           # True if the domain's active hours apply
    cache_hit: bool = False


class AuditRecord(BaseModel):
    """In-memory representation before writing to Postgres."""
    timestamp: datetime
    domain: str             # e.g. "gse", "logistics"
    key_id: str             # API key used (not the secret)
    owner_id: str           # Opaque upstream ID
    owner_label: str        # Human-readable label
    transport: str          # "stdio" | "http"
    tool_name: str
    tool_params: dict
    data_source: str
    cache_hit: bool
    response_ms: int
    error: str | None = None
    ip_address: str | None = None
```

---

## 10. Caching Strategy

### 10.1 Principle

The core cache layer is a dumb key-value store with TTLs. It does not know about trading hours, market schedules, or domain-specific freshness rules. The domain decides the TTL for each cache write — see Section 4.4 for the GSE TTL logic.

### 10.2 GSE TTL Configuration

| Cache Key | TTL (trading hours) | TTL (off hours) | Rationale |
|-----------|--------------------|--------------------|-----------|
| `gse:live:all` | 30s | 1h | Prices change intra-day; GSE is low-frequency |
| `gse:live:{symbol}` | 30s | 1h | Same |
| `gse:history:{symbol}:{days}` | 4h | 4h | EOD data changes once per day |
| `gse:summary` | 60s | 1h | Derived from live data |
| `gse:equities` | 24h | 24h | Company profiles; new listings/delistings are rare |
| `gse:equities:{symbol}` | 24h | 24h | Individual company profile |

These TTLs are computed by the GSE data service (not the cache layer) and passed as `ttl_seconds` to `cache.set()`.

### 10.3 Multi-domain Key Namespacing

Each domain uses its own prefix. All keys follow the pattern `{domain}:{resource}:{identifier}`.

| Domain | Example Keys |
|--------|-------------|
| GSE | `gse:live:all`, `gse:live:MTN`, `gse:history:GCB:30`, `gse:equities` |
| (future) | `{domain}:{resource}:{identifier}` |

All domains share a single Redis instance. Key collision is impossible because of the prefix.

---

## 11. Authentication and Authorisation

### 11.1 Principle

`pontifex-mcp` authenticates callers and enforces permission scopes. It does not manage users, billing, or plans. It accepts **two credential types**, and both resolve to the same `CallerIdentity` and flow through the same scope enforcement:

1. **API keys** (§11.3–11.5) — `sk_…` bearer tokens for scripts, CI, and service-to-service callers. Keys live in `pontifex_mcp_core.api_keys`, provisioned either by the bundled `pontifex-mcp keys` CLI or by an upstream system (SaaS dashboard, enterprise admin panel, config loader) that writes records directly (§11.8).
2. **OAuth 2.1 access tokens, represented as JWTs** (RFC 9068; §11.9–11.13) — bearer tokens minted by an external OIDC provider (Auth0, Microsoft Entra, Clerk, Keycloak, …) for interactive MCP clients (Claude Desktop, Cursor, …) that log the end-user in through a browser. (OAuth itself permits opaque access tokens; this platform validates the JWT profile.)

The middleware picks the path by token shape (§11.10) and emits an identical `CallerIdentity` either way, so scopes (§11.2), enforcement (§11.6), and audit (§12) are the same regardless of how the caller authenticated.

This keeps the library reusable: embed it in a SaaS product, deploy it inside a bank, run it from a local config file, or front it with any OIDC provider. The auth contract is the same in every case.

### 11.2 Permission Scopes

Each resolved identity carries a list of permission scopes that define exactly which tools it can call. Scopes use the colon-separated `domain:resource:action` pattern from the MCP ecosystem.

**Mapping tools to scopes:** Strip the verb prefix from the tool name — that gives you the resource. The verb tells you the action. `get_live_prices` → resource `live_prices`, action `read`. Future tools that write or mutate data would use `write` or `execute`.

**Examples:**

| Scope | Grants access to |
|-------|-----------------|
| `gse:*:*` | All resources, all actions in the GSE domain |
| `gse:*:read` | All resources in GSE, read-only |
| `gse:live_prices:read` | Only the live prices tool in GSE |
| `gse:stock_price:read` | Only the single stock price tool in GSE |
| `gse:stock_history:read` | Only the stock history tool in GSE |
| `gse:market_summary:read` | Only the market summary tool in GSE |
| `gse:company_info:read` | Only the company info tool in GSE |

A key with scopes `["gse:*:read", "gfi:bond_yields:read"]` can read any GSE data but only bond yields from a hypothetical GFI domain.

**Scope resolution rules:**

1. `{domain}:*:*` grants access to all current and future resources and actions in that domain
2. `{domain}:*:{action}` grants access to all resources for a specific action (e.g. read-only across a domain)
3. `{domain}:{resource}:*` grants all actions on a specific resource
4. `{domain}:{resource}:{action}` grants exactly one action on one resource
5. If no scope matches the requested tool, the call is rejected with `403 Forbidden`
6. Scopes are case-insensitive and stored lowercase
7. More specific scopes don't override broader ones — any matching scope is sufficient

### 11.3 API Key Format and Storage

**Key format:** `sk_<env>_` prefix + a high-entropy URL-safe random token — `sk_live_` for production, `sk_uat_` / `sk_test_` for ephemeral and CI environments. All variants share the `sk_` discriminator the middleware routes on (§11.10). The `pontifex-mcp keys create` CLI (or an upstream platform) generates the key, stores its SHA-256 hash in `pontifex_mcp_core.api_keys` along with the scopes, and shows the plaintext once.

**Key record:**

```python
# What gets stored in pontifex_mcp_core.api_keys and cached in Redis

@dataclass
class APIKeyRecord:
    key_id: str                 # e.g. "key_abc123"
    key_hash: str               # SHA-256 of the plaintext
    owner_id: str               # Opaque ID from the upstream platform (user, service account, etc.)
    owner_label: str            # Human-readable label, e.g. "Kwame's Claude Desktop"
    scopes: list[str]           # ["gse:*:*", "gfi:bond_yields:read"]
    rate_limit_rpm: int         # Requests per minute (set by upstream platform)
    is_active: bool
    expires_at: datetime | None
    created_at: datetime
```

### 11.4 CallerIdentity

When a credential is resolved, the MCP server works with a `CallerIdentity` — a thin, scope-aware object. No plan tiers, no roles, no tenant hierarchy. Just: who is this, what can they call, and how fast.

```python
# core/pontifex_mcp/middleware/auth.py

from dataclasses import dataclass


@dataclass
class CallerIdentity:
    key_id: str                 # API key identifier (for audit, not the secret)
    owner_id: str               # Opaque upstream ID
    owner_label: str            # Display name for audit logs
    scopes: list[str]           # ["gse:*:*", "gfi:bond_yields:read"]
    rate_limit_rpm: int         # Requests per minute
    transport: str              # "stdio" | "http"

    def can_use_tool(self, domain: str, resource: str, action: str) -> bool:
        """Check if this key's scopes permit domain:resource:action."""
        patterns = [
            f"{domain}:*:*",               # full domain access
            f"{domain}:*:{action}",         # all resources, specific action
            f"{domain}:{resource}:*",       # specific resource, all actions
            f"{domain}:{resource}:{action}",# exact match
        ]
        return any(p in self.scopes for p in patterns)
```

### 11.5 API Key Resolution

The auth middleware resolves raw API keys to `CallerIdentity` with a Redis-first, Postgres-fallback lookup. No IdP round-trips, no token introspection.

```python
# core/pontifex_mcp/middleware/auth.py

import hashlib
import json
from dataclasses import asdict


class APIKeyResolver:
    """Resolves an API key to a CallerIdentity."""

    def __init__(self, redis_client, db_session_factory, cache_ttl: int = 300):
        self.redis = redis_client
        self.db = db_session_factory
        self.cache_ttl = cache_ttl

    async def resolve(self, raw_key: str) -> CallerIdentity | None:
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()

        # 1. Check Redis cache
        cached = await self.redis.get(f"apikey:{key_hash}")
        if cached:
            return CallerIdentity(**json.loads(cached))

        # 2. Fall back to Postgres
        async with self.db() as session:
            row = await session.execute(
                select(ApiKeyModel)
                .where(ApiKeyModel.key_hash == key_hash)
                .where(ApiKeyModel.is_active == True)
                .where(
                    (ApiKeyModel.expires_at == None) |
                    (ApiKeyModel.expires_at > func.now())
                )
            )
            record = row.scalar_one_or_none()
            if not record:
                return None

            identity = CallerIdentity(
                key_id=record.key_id,
                owner_id=record.owner_id,
                owner_label=record.owner_label,
                scopes=record.scopes,
                rate_limit_rpm=record.rate_limit_rpm,
                transport="http",
            )

            # 3. Cache for next time
            await self.redis.setex(
                f"apikey:{key_hash}",
                self.cache_ttl,
                json.dumps(asdict(identity)),
            )
            return identity
```

### 11.6 Scope Enforcement in Domain Servers

Each domain server checks scopes before executing a tool. The check is one line — no policy objects, no tier maps.

```python
# domains/gse/gse_mcp/tools/live_prices.py (excerpt)

async def handle_get_live_prices(caller: CallerIdentity, params: dict):
    if not caller.can_use_tool("gse", "live_prices", "read"):
        raise PermissionError("API key missing scope: gse:live_prices:read (or gse:*:read, gse:*:*)")

    # ... proceed with tool logic
```

### 11.7 stdio Transport (Local / Self-hosted)

For local development and self-hosted deployments, the MCP server can run in stdio mode. In this mode, a local config file or environment variable specifies the scopes directly — no Redis or Postgres needed.

```yaml
# local_dev_config.yaml
key_id: "local_dev"
owner_id: "dev_user"
owner_label: "Local Development"
scopes: ["gse:*:*"]
rate_limit_rpm: 9999
```

### 11.8 Provisioning Keys

Keys reach `pontifex_mcp_core.api_keys` two ways.

**The bundled CLI** is the first-party path — no script to write. It works against whatever `DATABASE_URL` points at, the SQLite floor or Postgres:

```console
$ pontifex-mcp keys create --owner usr_kwame --label "Kwame's Claude Desktop" \
    --scopes "gse:*:read,gse:stock_history:read" --rate-limit-rpm 120
key_id:   key_usr_kwame
api_key:  sk_live_…   (shown once — store it now)
owner:    usr_kwame (Kwame's Claude Desktop)
scopes:   gse:*:read, gse:stock_history:read
expires:  never
```

It generates the key, stores only the SHA-256 hash, and prints the plaintext once. `keys list` shows every key (never the secret); `keys revoke <key_id>` soft-deletes it — preserving audit history — and clears the resolver's Redis cache so the revocation takes effect at once rather than after the lookup TTL.

**Direct DB writes** are the integration path for a SaaS or admin platform that mints keys inside its own billing or onboarding flow. `pontifex-mcp` doesn't care how the upstream decided what scopes to assign — a billing plan, a manual admin decision, a config file. It reads the row and enforces it:

```python
# Example: upstream platform creates a key (this code lives OUTSIDE pontifex-mcp)

import hashlib
import secrets

raw_key = "sk_live_" + secrets.token_urlsafe(32)
key_hash = hashlib.sha256(raw_key.encode()).hexdigest()

# Write to pontifex_mcp_core.api_keys (direct DB insert, or via a provisioning API)
await db.execute(
    insert(ApiKeyModel).values(
        key_id="key_abc123",
        key_hash=key_hash,
        owner_id="usr_kwame",
        owner_label="Kwame's Claude Desktop",
        scopes=["gse:*:read", "gse:stock_history:read"],
        rate_limit_rpm=120,
        is_active=True,
        expires_at=None,
    )
)

# Return raw_key to the user — shown once, never stored in plaintext
print(f"Your API key: {raw_key}")
```

### 11.9 OAuth 2.1 Authentication (JWT access tokens)

For interactive MCP clients, `pontifex-mcp` validates OAuth 2.1 access tokens in JWT form (RFC 9068) minted by an external OIDC provider. It is a pure **resource server**: it never mints tokens, runs no login UI, and stores no client records. It validates the JWT and maps its claims to a `CallerIdentity`.

Validation (`core/pontifex_mcp/auth/jwt_validator.py`):

- Fetch and cache the provider's JWKS (1 h TTL; refetch once on key rotation).
- Verify the signature using asymmetric algorithms only — `RS*`, `ES*`, `PS*`. The HMAC family and `alg: none` are rejected, so a stolen JWKS document can't be used to forge tokens.
- Require `iss`, `aud`, `exp`, and `sub`; reject the token if any is missing or fails its check. `nbf` and `iat` are validated for timing *when present* but not required — most access tokens (Auth0's included) don't issue `nbf`, and requiring it would reject otherwise-valid tokens.
- Extract scopes from a configurable claim, accepting both space-delimited strings (OAuth `scope`) and arrays (Auth0 `permissions`, Entra `roles`).

The resulting `CallerIdentity` is identical in shape to the API-key one: `owner_id` comes from `sub`, `scopes` from the configured claim, `transport = "http"`. Everything downstream is unaware of which path produced it.

### 11.10 Dual-Path Middleware

A single middleware routes each `Authorization: Bearer <token>` to the right resolver by token shape:

```python
# core/pontifex_mcp/middleware/auth.py (excerpt)

if raw_token.startswith("sk_"):
    identity = await self.api_key_resolver.resolve(raw_token)   # §11.5
else:
    identity = await self.jwt_validator.validate(raw_token)     # §11.9
```

API-key plaintext is prefixed `sk_<env>_…` (`sk_live_` in prod, `sk_uat_` / `sk_test_` in ephemeral and CI environments). OAuth JWTs are base64url-encoded JSON, so they always begin with `ey` and never collide with `sk_`. Both branches produce the same `CallerIdentity`; scope checks, audit, and rate limiting are path-agnostic. When no JWT validator is configured, only the API-key path is active and any non-`sk_` token is rejected.

### 11.11 OAuth Discovery (RFC 9728)

So that a client holding no credentials can bootstrap, the server advertises where to authenticate:

1. An unauthenticated request gets `401` with a challenge header:

   ```
   WWW-Authenticate: Bearer realm="mcp", error="invalid_token",
     resource_metadata="https://<host>/.well-known/oauth-protected-resource"
   ```

2. `GET /.well-known/oauth-protected-resource` returns the protected-resource metadata:

   ```json
   {
     "resource": "https://<host>/mcp",
     "authorization_servers": ["https://your-provider.example/"],
     "bearer_methods_supported": ["header"]
   }
   ```

   `resource` is the MCP server's own canonical URL (RFC 9728 — *not* the authorization-server audience). It's resolved by `core/pontifex_mcp/auth/discovery.py`, which prefers an explicit configured `public_base_url` (the bare `PUBLIC_BASE_URL` env var) and advertises it verbatim. A configured value is the correct design — an OAuth resource identifier is meant to be a single stable value — and it's immune to header spoofing because the request is never consulted. When unset (local/dev), the URL is derived from the request, honouring `X-Forwarded-Host`/`-Proto` but trusting a forwarded host only when it appears in `allowed_hosts`, so a client can't poison the discovery URL with an attacker-controlled host. The client then reads the provider's own OIDC discovery document to find the authorize and token endpoints.

These endpoints are only meaningful when JWT auth is configured; an API-key-only deployment emits a bare `Bearer` challenge with no `resource_metadata`.

### 11.12 Provider-Agnostic Configuration

`pontifex-mcp` is not tied to any one IdP. A handful of settings point it at any OIDC-compliant provider; switching providers is a config change, not a code change.

Domain-specific settings carry the domain's `env_prefix` — `GSESettings` sets `env_prefix="GSE_MCP_"`, so e.g. the upstream data-source URL is read from `GSE_MCP_KWAYISI_BASE_URL`. But **infrastructure-level** settings — the auth/IdP config, the canonical URL, and the shared DB/Redis connections (which provider backs the deployment, where it's hosted, what it connects to) — are not domain concerns, so they read from **bare, unprefixed** env vars via `validation_alias` (`DATABASE_URL`, `REDIS_URL`, `AUTH_*`, `PUBLIC_BASE_URL`). The var names are therefore the same for any MCP app, regardless of its domain prefix:

```
AUTH_JWKS_URL=https://your-provider.example/.well-known/jwks.json
AUTH_ISSUER=https://your-provider.example/
AUTH_AUDIENCE=<resource-server identifier the JWT's `aud` must carry>
AUTH_SCOPES_CLAIM=permissions                            # Auth0; Entra: scp|roles; Clerk: provider-specific
AUTH_AUTHORIZATION_SERVER=https://your-provider.example/  # advertised in the discovery metadata
PUBLIC_BASE_URL=https://<this-deployment's-host>          # canonical URL for discovery (§11.11)
```

Pre-prod stores these in Doppler; UAT imports `AUTH_*` from Doppler and sets `PUBLIC_BASE_URL` per ephemeral app in the deploy workflow. Everything about how the resource server **validates a token** — JWKS, issuer/audience checks, scope extraction, discovery metadata — is provider-agnostic.

### 11.13 Client Registration Is the Deployer's Choice

How an MCP client obtains a `client_id` is a property of the **authorization server**, not the resource server. The platform stays out of it and works with whatever the deployer's provider allows:

- **Pre-registered client** — the deployer registers one OAuth app and hands clients its `client_id`. Works with any client that accepts a client_id (e.g. Claude Desktop's connector UI). Simplest; requires no platform code.
- **Dynamic Client Registration (DCR)** — clients self-register for true zero-config. Whether it works depends on the provider: some let DCR clients access custom APIs, others (e.g. Auth0) restrict custom APIs to first-party clients. Bridging a restrictive provider needs a provider-specific registration proxy, which `pontifex-mcp` deliberately does **not** bundle — it would couple the otherwise provider-agnostic core to one IdP's admin API.
- **Client ID Metadata Documents (CIMD)** — the emerging direction: the `client_id` is itself a URL resolving to the client's metadata, removing registration entirely. Still draft-stage with limited provider support.

Because the resource server only ever validates the resulting JWT, `pontifex-mcp` is forward-compatible with all three — the registration mechanism can change without any change to the library.

---

## 12. Audit Logging

### 12.1 Schema

Shared across all domains. The `key_id` and `domain` columns scope records.

```sql
CREATE TABLE pontifex_mcp_core.audit_log (
    id              BIGSERIAL PRIMARY KEY,
    timestamp       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    domain          TEXT NOT NULL,              -- 'gse', 'gfi', 'ngx', etc.
    key_id          TEXT NOT NULL,              -- API key identifier (not secret)
    owner_id        TEXT NOT NULL,              -- Opaque upstream ID
    owner_label     TEXT NOT NULL,
    transport       TEXT NOT NULL,              -- 'stdio' | 'http'
    tool_name       TEXT NOT NULL,
    tool_params     JSONB NOT NULL,
    data_source     TEXT NOT NULL,
    cache_hit       BOOLEAN NOT NULL,
    response_ms     INTEGER NOT NULL,
    error           TEXT,
    ip_address      INET
);

CREATE INDEX idx_audit_timestamp ON pontifex_mcp_core.audit_log (timestamp DESC);
CREATE INDEX idx_audit_domain    ON pontifex_mcp_core.audit_log (domain, timestamp DESC);
CREATE INDEX idx_audit_key       ON pontifex_mcp_core.audit_log (key_id, timestamp DESC);
CREATE INDEX idx_audit_owner     ON pontifex_mcp_core.audit_log (owner_id, timestamp DESC);
CREATE INDEX idx_audit_tool      ON pontifex_mcp_core.audit_log (tool_name, timestamp DESC);
```

### 12.2 Retention

- Hot (PostgreSQL): 90 days
- Cold (Parquet export to data lake / S3-compatible): 7 years per regulatory requirements
- `scripts/export_audit_logs.py` runs nightly via cron, exports records older than 90 days, deletes from Postgres

---

## 13. Error Handling and Rate Limiting

### 13.1 Error Response Format

All tool errors use the MCP protocol's `isError: true` flag on the tool result, with a structured JSON body in the content. Error messages are written for AI agents — they should be actionable, not just descriptive.

**Error envelope:**

```json
{
  "content": [
    {
      "type": "text",
      "text": "{\"error_code\": \"scope_denied\", \"message\": \"API key missing scope: gse:stock_history:read. Request a key with gse:stock_history:read or gse:*:read.\", \"status\": 403, \"retry\": false}"
    }
  ],
  "isError": true
}
```

**Error codes:**

| Code | Status | Retryable | Meaning |
|------|--------|-----------|---------|
| `auth_failed` | 401 | No | Invalid, expired, or revoked API key |
| `scope_denied` | 403 | No | Valid key, but missing the required scope |
| `rate_limited` | 429 | Yes | Request rate exceeded; `retry_after_seconds` included |
| `invalid_input` | 400 | No | Bad parameter (unknown symbol, out-of-range value) |
| `source_unavailable` | 503 | Yes | All data source adapters failed or circuit-broken |
| `internal_error` | 500 | Yes | Unexpected server error |

**Error body schema:**

```python
# core/pontifex_mcp/models/base.py

class ToolError(BaseModel):
    error_code: str                     # One of the codes above
    message: str                        # Human and agent-readable explanation
    status: int                         # HTTP-style status code
    retry: bool                         # Whether the client should retry
    retry_after_seconds: int | None = None  # Seconds to wait (rate_limited, source_unavailable)
    detail: str | None = None           # Optional extra context
```

**Writing error messages for AI agents:**

Error messages should tell the agent what went wrong and what to do about it. The agent may use this to self-correct, inform the user, or try a different approach.

- Bad: `"Forbidden"`
- Good: `"API key missing scope: gse:stock_history:read. Request a key with gse:stock_history:read or gse:*:read."`
- Bad: `"Rate limit exceeded"`
- Good: `"Rate limit exceeded (60 requests/minute). Retry after 23 seconds."`
- Bad: `"Service unavailable"`
- Good: `"All GSE data sources are currently unavailable. The server is using cached data where possible. Retry in 30 seconds."`

### 13.2 Rate Limiting

#### Enforcement: API Gateway

Rate limiting is handled by the API gateway (Kong, NGINX, or Cloudflare), not the MCP server. The gateway reads `rate_limit_rpm` from the API key record (cached in Redis) and enforces it using its built-in sliding window or token bucket implementation.

The MCP server does not implement rate limiting logic. This avoids duplicating what the gateway already does well and eliminates the risk of two rate limiters conflicting.

#### Rate Limit Metadata in Responses

Following OpenAI and Anthropic's convention, the gateway attaches rate limit headers to every HTTP response. For MCP tool results (which are inside the HTTP body, not headers), the MCP server passes through the gateway's rate limit metadata in the response envelope:

```json
{
  "timestamp": "2026-05-22T14:30:00Z",
  "source": "kwayisi",
  "is_live": true,
  "cache_hit": false,
  "rate_limit": {
    "limit": 120,
    "remaining": 87,
    "reset": 1716480120
  },
  "stocks": [...]
}
```

When the gateway rejects a request (429), the MCP server never sees it — the gateway returns the error directly with a `Retry-After` header. For rate limit errors that reach the MCP server (e.g. self-imposed limits on upstream adapter calls), the `rate_limited` error code includes `retry_after_seconds`.

---

## 14. Database Design

### 14.1 Principle

Same isolation model as the codebase: one shared `pontifex_mcp_core` schema for cross-cutting infrastructure tables, one schema per domain for domain-specific data. A bad migration in GFI cannot touch GSE's tables. All schemas live in a single PostgreSQL instance so cross-schema queries (e.g. "all audit records across all domains") remain simple joins.

**Local floor.** Postgres is the production target, but the same SQLAlchemy models run on SQLite for the quickstart and local development. `pontifex-mcp db upgrade` detects the dialect: it applies the packaged Alembic migrations against Postgres, or builds the schema with `create_all` on SQLite (which has no named schemas, so `pontifex_mcp_core` collapses to the default namespace). Redis is optional in both modes — without it, the key-lookup cache and per-caller rate limiting are simply disabled and logged. A schema-parity test (`tests/core/test_schema_parity.py`) guards the two build paths against drift, so a key minted on the SQLite floor behaves the same once the deployment moves to Postgres.

### 14.2 Schema Layout

```
mcp_platform (database)
│
├── pontifex_mcp_core (schema)
│   ├── api_keys                     ← Hashed keys → owner + scopes + rate limit
│   ├── audit_log                    ← All tool invocations, all domains
│   ├── domain_registry              ← Which domains are active + metadata
│   └── circuit_breaker_state        ← Optional: persisted breaker state
│
├── gse (schema)                     ← Ghana Stock Exchange (implemented)
│   ├── symbols                      ← Canonical symbol registry
│   ├── historical_prices            ← Long-term OHLCV
│   ├── cached_eod_prices            ← End-of-day snapshots (backup to Redis)
│   └── data_quality_log             ← Cross-source discrepancy records
│
└── {domain} (schema)                ← Each future domain gets its own schema
    └── ...                              following the same pattern
```

Note: there are no `users`, `tenants`, or `plans` tables. User management and billing belong to the upstream platform. `pontifex-mcp` only stores the data it needs to authenticate and authorise requests: API keys with their scopes.

### 14.3 Core Schema DDL

```sql
CREATE SCHEMA IF NOT EXISTS pontifex_mcp_core;

-- api_keys: the only auth table pontifex-mcp owns
-- The `pontifex-mcp keys` CLI or an upstream platform (SaaS, config loader) writes rows here
CREATE TABLE pontifex_mcp_core.api_keys (
    key_id          TEXT PRIMARY KEY,            -- e.g. 'key_abc123'
    key_hash        TEXT NOT NULL UNIQUE,        -- SHA-256 of the plaintext key
    owner_id        TEXT NOT NULL,               -- Opaque ID from upstream (user, service account, etc.)
    owner_label     TEXT NOT NULL,               -- Human-readable, e.g. "Kwame's Claude Desktop"
    scopes          TEXT[] NOT NULL,             -- e.g. '{gse:*:read,gse:stock_history:read}'
    rate_limit_rpm  INTEGER NOT NULL DEFAULT 60, -- Requests per minute
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    expires_at      TIMESTAMPTZ,                 -- NULL = no expiry
    last_used_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_api_keys_hash ON pontifex_mcp_core.api_keys (key_hash);
CREATE INDEX idx_api_keys_owner ON pontifex_mcp_core.api_keys (owner_id);

-- audit_log: every tool invocation across all domains
CREATE TABLE pontifex_mcp_core.audit_log (
    id              BIGSERIAL PRIMARY KEY,
    timestamp       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    domain          TEXT NOT NULL,
    key_id          TEXT NOT NULL,
    owner_id        TEXT NOT NULL,
    owner_label     TEXT NOT NULL,
    transport       TEXT NOT NULL,
    tool_name       TEXT NOT NULL,
    tool_params     JSONB NOT NULL,
    data_source     TEXT NOT NULL,
    cache_hit       BOOLEAN NOT NULL,
    response_ms     INTEGER NOT NULL,
    error           TEXT,
    ip_address      INET
);

CREATE INDEX idx_audit_timestamp ON pontifex_mcp_core.audit_log (timestamp DESC);
CREATE INDEX idx_audit_domain    ON pontifex_mcp_core.audit_log (domain, timestamp DESC);
CREATE INDEX idx_audit_key       ON pontifex_mcp_core.audit_log (key_id, timestamp DESC);
CREATE INDEX idx_audit_owner     ON pontifex_mcp_core.audit_log (owner_id, timestamp DESC);
CREATE INDEX idx_audit_tool      ON pontifex_mcp_core.audit_log (tool_name, timestamp DESC);

-- domain_registry: tracks active domains and their config metadata
CREATE TABLE pontifex_mcp_core.domain_registry (
    domain          TEXT PRIMARY KEY,
    display_name    TEXT NOT NULL,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    config_json     JSONB,                          -- e.g. trading hours, cache TTLs
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Optional: persisted circuit breaker state (skip initially)
CREATE TABLE pontifex_mcp_core.circuit_breaker_state (
    domain          TEXT NOT NULL,
    adapter_name    TEXT NOT NULL,
    state           TEXT NOT NULL DEFAULT 'closed',
    failure_count   INTEGER NOT NULL DEFAULT 0,
    last_failure_at TIMESTAMPTZ,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (domain, adapter_name)
);
```

### 14.4 GSE Schema DDL

```sql
CREATE SCHEMA IF NOT EXISTS gse;

-- Canonical symbol registry, populated from kwayisi /equities endpoint
CREATE TABLE gse.symbols (
    ticker          TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    sector          TEXT,
    kwayisi_code    TEXT,                            -- kwayisi's internal code if different
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    listed_date     DATE,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Historical OHLCV prices (populated from internal data or nightly adapter scrapes)
CREATE TABLE gse.historical_prices (
    symbol          TEXT NOT NULL REFERENCES gse.symbols(ticker),
    date            DATE NOT NULL,
    open            NUMERIC(12,4),
    high            NUMERIC(12,4),
    low             NUMERIC(12,4),
    close           NUMERIC(12,4) NOT NULL,
    volume          BIGINT NOT NULL DEFAULT 0,
    source          TEXT NOT NULL,                   -- 'kwayisi', 'gse_official', 'manual'
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (symbol, date)
);

CREATE INDEX idx_hist_symbol_date ON gse.historical_prices (symbol, date DESC);

-- End-of-day price cache (backup to Redis; also serves as the internal_db adapter's source)
CREATE TABLE gse.cached_eod_prices (
    symbol          TEXT NOT NULL REFERENCES gse.symbols(ticker),
    date            DATE NOT NULL,
    price           NUMERIC(12,4) NOT NULL,
    change          NUMERIC(12,4) NOT NULL DEFAULT 0,
    change_pct      NUMERIC(8,4) NOT NULL DEFAULT 0,
    volume          BIGINT NOT NULL DEFAULT 0,
    source          TEXT NOT NULL,
    fetched_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (symbol, date)
);

-- Later: log discrepancies when cross-validating across adapters
CREATE TABLE gse.data_quality_log (
    id              BIGSERIAL PRIMARY KEY,
    timestamp       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    symbol          TEXT NOT NULL,
    field           TEXT NOT NULL,                   -- 'price', 'volume', etc.
    source_a        TEXT NOT NULL,
    value_a         NUMERIC(12,4) NOT NULL,
    source_b        TEXT NOT NULL,
    value_b         NUMERIC(12,4) NOT NULL,
    discrepancy_pct NUMERIC(8,4) NOT NULL,
    resolved        BOOLEAN NOT NULL DEFAULT FALSE
);
```

### 14.5 Schema Permissions

Two classes of runtime role for `pontifex-mcp` itself, plus a separate provisioning credential. Key provisioning — whether the `pontifex-mcp keys` CLI or an upstream platform — runs with a credential that holds `INSERT`/`UPDATE` on `pontifex_mcp_core.api_keys`. The domain service role holds no such grant beyond touching `last_used_at`: a running domain server reads keys to authenticate callers but cannot mint them or change their scopes, hashes, or activation, so a compromised server can't forge or escalate credentials.

- **Domain services** (`mcp_gse_service`, etc.): Read `pontifex_mcp_core.api_keys` to resolve keys (with a column-scoped `UPDATE` on `last_used_at` only), write `pontifex_mcp_core.audit_log`, full access to their own domain schema. No other write access to `api_keys`.
- **Provisioning** (the `keys` CLI, or an upstream platform using its own credentials): `INSERT`/`UPDATE` on `pontifex_mcp_core.api_keys`. Run from an operator context, not the serving path.
- **Analytics** (`mcp_analytics`): Read-only on everything for dashboards and reporting.

```sql
-- Domain service role (one per domain)
CREATE ROLE mcp_gse_service LOGIN PASSWORD '...';
-- Future: CREATE ROLE mcp_{domain}_service LOGIN PASSWORD '...';

-- Analytics role (read-only across everything)
CREATE ROLE mcp_analytics LOGIN PASSWORD '...';

-- Core schema: domain services can read api_keys, write audit
GRANT USAGE ON SCHEMA pontifex_mcp_core TO mcp_gse_service;
GRANT SELECT ON pontifex_mcp_core.api_keys TO mcp_gse_service;
GRANT UPDATE (last_used_at) ON pontifex_mcp_core.api_keys TO mcp_gse_service;
GRANT SELECT, INSERT ON pontifex_mcp_core.audit_log TO mcp_gse_service;
GRANT USAGE ON SEQUENCE pontifex_mcp_core.audit_log_id_seq TO mcp_gse_service;
GRANT SELECT ON pontifex_mcp_core.domain_registry TO mcp_gse_service;

-- Domain isolation: each service owns only its schema
GRANT ALL ON SCHEMA gse TO mcp_gse_service;
GRANT ALL ON ALL TABLES IN SCHEMA gse TO mcp_gse_service;
ALTER DEFAULT PRIVILEGES IN SCHEMA gse GRANT ALL ON TABLES TO mcp_gse_service;

-- Repeat the above pattern for each new domain

-- Analytics: read-only everywhere
GRANT USAGE ON SCHEMA pontifex_mcp_core, gse TO mcp_analytics;
GRANT SELECT ON ALL TABLES IN SCHEMA pontifex_mcp_core, gse TO mcp_analytics;
```

### 14.6 Alembic Migration Strategy

Migrations split into two independent branches: `core` (the library's
`pontifex_mcp_core` schema) and one per domain. `alembic upgrade heads` advances
every branch.

The `core` branch + `env.py` ship **inside the `pontifex-mcp` wheel**, so a
`pip install` user runs `pontifex-mcp db upgrade` to create or update the schema
(no source checkout). Domain branches stay in the monorepo as demos.

```
core/pontifex_mcp/migrations/        # shipped in the wheel
├── alembic.ini                      # %(here)s paths; db upgrade loads this
├── env.py                           # multi-branch; reads DATABASE_URL
└── versions/
    ├── 001_create_api_keys.py
    ├── 002_create_audit_log.py
    ├── 003_create_domain_registry.py
    └── 004_add_audit_delegated_audience.py

alembic/                             # monorepo: adds the demo domain branch
├── alembic.ini                      # points at the in-package core branch + gse
└── domains/
    └── gse/
        └── versions/
            ├── 001_create_symbols.py
            ├── 002_create_historical_prices.py
            └── 003_create_cached_eod_prices.py
    # Future demo domains get their own folder here
```

Two ways to run them: `pontifex-mcp db upgrade` (core only, from the installed
wheel) and `alembic -c alembic/alembic.ini upgrade heads` (core + domains, from
a source checkout — what the GSE deploy and CI use).

Each migration explicitly targets its schema using the `schema=` parameter in `op.create_table()`:

```python
# alembic/domains/gse/versions/001_create_symbols.py

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.execute("CREATE SCHEMA IF NOT EXISTS gse")
    op.create_table(
        "symbols",
        sa.Column("ticker", sa.Text, primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("sector", sa.Text),
        sa.Column("kwayisi_code", sa.Text),
        sa.Column("is_active", sa.Boolean, server_default="true"),
        sa.Column("listed_date", sa.Date),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        schema="gse",
    )


def downgrade():
    op.drop_table("symbols", schema="gse")
```

Core migrations run with a shared migration role that has `CREATE SCHEMA` privileges. Domain migrations run with the domain's service role (which already has `ALL ON SCHEMA {domain}`).

### 14.7 Connection Pooling

Each domain server maintains its own SQLAlchemy async engine with a connection pool. Recommended pool settings to start:

| Setting | Value | Rationale |
|---------|-------|-----------|
| `pool_size` | 5 | GSE has ~37 stocks; load is moderate |
| `max_overflow` | 10 | Absorb bursts during market open |
| `pool_timeout` | 30s | Fail fast if pool is exhausted |
| `pool_recycle` | 1800s | Prevent stale connections behind load balancers |

```python
from sqlalchemy.ext.asyncio import create_async_engine

engine = create_async_engine(
    settings.database_url,
    pool_size=5,
    max_overflow=10,
    pool_timeout=30,
    pool_recycle=1800,
)
```

### 14.8 The circuit_breaker_state Table

**Skip it initially.** The circuit breaker runs in-memory. When a container restarts, the breaker resets to `CLOSED` and rediscovers adapter availability by trying and failing (or succeeding). For a single container per domain, this is fine.

**When to add it:** If you scale to multiple container replicas per domain, in-memory breakers diverge — replica A might have kwayisi marked `OPEN` while replica B still thinks it's `CLOSED` and keeps hammering a dead upstream. Persisting state to `pontifex_mcp_core.circuit_breaker_state` (or Redis, which is faster for this) lets all replicas share a single view. Add this when you move to horizontal scaling.

---

## 15. Resilience

### 15.1 Circuit Breaker

```python
# core/pontifex_mcp/utils/circuit_breaker.py

import time
from enum import Enum


class State(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    def __init__(self, failure_threshold: int = 3, recovery_timeout: float = 30.0,
                 name: str = "default"):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.name = name
        self.state = State.CLOSED
        self.failure_count = 0
        self.last_failure_time = 0.0

    @property
    def is_available(self) -> bool:
        if self.state == State.CLOSED:
            return True
        if self.state == State.OPEN:
            if time.monotonic() - self.last_failure_time > self.recovery_timeout:
                self.state = State.HALF_OPEN
                return True
            return False
        return True

    def record_success(self) -> None:
        self.failure_count = 0
        self.state = State.CLOSED

    def record_failure(self) -> None:
        self.failure_count += 1
        self.last_failure_time = time.monotonic()
        if self.failure_count >= self.failure_threshold:
            self.state = State.OPEN
```

### 15.2 Retry Policy

Individual HTTP requests to external APIs: 3 attempts, base delay 0.5s, max delay 4s, jitter ±200ms. Implemented as an async decorator in `core/pontifex_mcp/utils/retry.py`.

---

## 16. Observability

### 16.1 Logfire

Observability is handled by [Logfire](https://logfire.pydantic.dev/) (Pydantic's OTEL-based observability platform). Logfire provides tracing, metrics, and dashboards in a single service. Since it's built on OpenTelemetry, switching to a self-hosted OTEL + Prometheus + Grafana stack later requires only a configuration change — the instrumentation code stays the same.

### 16.2 Span Attributes

Every tool call creates an OTEL span with these attributes:

| Attribute | Example |
|-----------|---------|
| `mcp.domain` | `gse` |
| `mcp.tool.name` | `gse_get_live_prices` |
| `mcp.caller.key_id` | `key_abc123` |
| `mcp.caller.owner_id` | `usr_kwame` |
| `adapter.name` | `kwayisi` |
| `cache.hit` | `true` |
| `response.item_count` | `37` |

Logfire auto-instruments FastAPI (request/response tracing), httpx (outbound adapter calls), and Redis (cache operations). Domain-specific spans are added in tool handlers for business-level visibility.

### 16.3 Health Endpoints

Each domain server exposes:

- `GET /health/live` — 200 if the process is running
- `GET /health/ready` — 200 if Redis is reachable and at least one adapter passes `health_check()`

---

## 17. Deployment

### 17.1 Dockerfiles

Each domain gets its own Dockerfile. They all follow the same pattern:

```dockerfile
# deploy/Dockerfile.gse

FROM python:3.12-slim AS base
WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# Copy workspace root config
COPY pyproject.toml uv.lock ./

# Copy core library
COPY core/ core/

# Copy domain module
COPY domains/gse/ domains/gse/

# Install dependencies
RUN uv sync --package gse-mcp --frozen --no-dev

# Migrations
COPY alembic/ alembic/

EXPOSE 8080
CMD ["uv", "run", "--package", "gse-mcp", "uvicorn", "gse_mcp.main:app", "--host", "0.0.0.0", "--port", "8080"]
```

### 17.2 Docker Compose (Local Development)

```yaml
version: "3.9"
services:
  gse:
    build:
      context: .
      dockerfile: deploy/Dockerfile.gse
    ports:
      - "8080:8080"
    environment:
      REDIS_URL: redis://redis:6379/0
      DATABASE_URL: postgresql+asyncpg://mcp:mcp@postgres:5432/mcp_platform
      GSE_MCP_LOG_LEVEL: DEBUG
    depends_on: [redis, postgres]

  # Add more domain services here as needed, following the same pattern

  redis:
    image: redis:7-alpine
    ports: ["6379:6379"]

  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: mcp
      POSTGRES_PASSWORD: mcp
      POSTGRES_DB: mcp_platform
    ports: ["5432:5432"]
    volumes: [pgdata:/var/lib/postgresql/data]

volumes:
  pgdata:
```

### 17.3 Production: Fly.io

Each domain server deploys as a separate Fly app. Redis and Postgres are Fly-managed services shared across apps.

**Fly app per domain:**

```toml
# fly.toml (GSE domain)

app = "mcp-gse"
primary_region = "lhr"  # London — closest Fly region to West Africa

[build]
  dockerfile = "deploy/Dockerfile.gse"

[env]
  GSE_MCP_TRANSPORT = "streamable-http"
  GSE_MCP_LOG_LEVEL = "INFO"

[http_service]
  internal_port = 8080
  force_https = true

[[http_service.checks]]
  path = "/health/ready"
  interval = 15000        # ms
  timeout = 5000

[[vm]]
  size = "shared-cpu-1x"
  memory = "512mb"
```

**Managed services:**

```bash
# Create Postgres (shared across all domain apps)
fly postgres create --name pontifex-mcp-db --region lhr

# Attach to the GSE app
fly postgres attach pontifex-mcp-db --app mcp-gse

# Create Redis (Upstash, Fly's managed Redis)
fly redis create --name pontifex-mcp-cache --region lhr

# Set secrets (not in fly.toml — stored encrypted by Fly)
fly secrets set REDIS_URL="redis://..." --app mcp-gse
fly secrets set DATABASE_URL="postgres://..." --app mcp-gse
```

**Deploy:**

```bash
fly deploy --app mcp-gse
```

**Adding a new domain** is: create a new `fly.toml`, attach the same Postgres and Redis, deploy. Each domain app scales independently.

**Region considerations:** Fly's closest region to Accra is `lhr` (London). If latency matters, consider `jnb` (Johannesburg) for a secondary region. Fly supports multi-region with read replicas for Postgres if needed later.

### 17.4 Claude Desktop Configuration

For users connecting to the GSE server via Claude Desktop:

```json
{
  "mcpServers": {
    "gse": {
      "command": "docker",
      "args": [
        "run", "--rm", "-i",
        "--env", "GSE_MCP_TRANSPORT=stdio",
        "--env", "REDIS_URL=redis://host.docker.internal:6379/0",
        "pontifex-mcp-gse:latest"
      ]
    }
  }
}
```

To connect additional domain servers later, add each as a separate MCP server entry in the same config.

---

## 18. Testing Strategy

### 18.1 Core Unit Tests (`tests/core/`)

- Circuit breaker state transitions (closed → open → half-open → closed)
- Cache get/set/invalidate with prefix isolation
- DataSourceManager fallback chain (primary fails → secondary serves)
- Auth middleware: valid key, expired key, missing scope, revoked key
- Scope matching: wildcard patterns, exact matches, action-level checks
- Audit middleware: record written with correct fields
- Server factory: app bootstraps with health endpoints

### 18.2 Domain Unit Tests (`tests/domains/gse/`)

- Mock kwayisi HTTP responses using `respx`
- Test each tool handler with known inputs and expected outputs
- Test symbol registry: fetch, cache, and lookup via /equities
- Test market summary derivation from `/live` response

### 18.3 Integration Tests

- Spin up Redis + PostgreSQL via `testcontainers-python`
- Full path: tool call → cache miss → adapter → cache write → response → audit log
- Verify audit records contain correct domain, tool, caller, latency

### 18.4 Contract Tests

- Record actual kwayisi API responses as JSON fixtures (`tests/domains/gse/fixtures/`)
- Adapter tests run against fixtures; if kwayisi changes their response shape, tests break

### 18.5 Load Tests

- `locust` simulating 50 concurrent analysts on `gse_get_live_prices`
- Target: <200ms cache hit, <2s cache miss
- Verify circuit breaker engages when upstream is slow

---

## 19. Dependencies

```toml
# pyproject.toml (workspace root — virtual, no [project] table)

[tool.uv.workspace]
members = ["core", "domains/*"]

[tool.uv]
dev-dependencies = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "respx>=0.21",
    "testcontainers>=4.0",
    "locust>=2.28",
    "ruff>=0.4",
    "ty>=0.1",
]
```

```toml
# core/pyproject.toml

[project]
name = "pontifex-mcp"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.30.0",
    "mcp>=1.0.0",
    "httpx>=0.27.0",
    "redis[hiredis]>=5.0.0",
    "sqlalchemy[asyncio]>=2.0.0",
    "asyncpg>=0.29.0",
    "alembic>=1.13.0",
    "pydantic>=2.0.0",
    "pydantic-settings>=2.0.0",
    "logfire[fastapi,httpx,redis]>=3.0.0",
    "structlog>=24.0.0",
]

[build-system]
requires = ["uv_build>=0.7"]
build-backend = "uv_build"

[tool.uv-build]
module-root = ""
```

```toml
# domains/gse/pyproject.toml

[project]
name = "gse-mcp"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "pontifex-mcp",
]

[tool.uv.sources]
pontifex-mcp = { workspace = true }

[build-system]
requires = ["uv_build>=0.7"]
build-backend = "uv_build"

[tool.uv-build]
module-root = ""
```

---

## 20. Adding a New Domain Module

To add a new domain, follow these steps:

1. **Create the directory:** `domains/{name}/{name}_mcp/`

2. **Create `pyproject.toml`** with `[build-system]` using `uv_build`, dependency on `pontifex-mcp` via `[tool.uv.sources]`, and `requires-python = ">=3.12"`. The workspace root auto-discovers it via the `domains/*` glob.

3. **Define domain models** in `models.py`. These are the Pydantic objects your tools return.

4. **Define the adapter protocol** in `adapters/protocol.py`. Extend `pontifex_mcp.adapters.base.DataAdapter` with your domain-specific methods.

5. **Implement adapters.** One per external data source. Each returns your domain models.

6. **Define tools** in `tools/`. One file per tool. Each tool calls the domain's data service.

7. **Map tool permissions.** For each tool, define the `domain:resource:action` scope. Strip the verb prefix from the tool name to get the resource, use the verb to determine the action. Document the mapping in the tool file:

    | Tool | Scope |
    |------|-------|
    | `get_bond_yields` | `gfi:bond_yields:read` |
    | `set_price_alert` | `gse:price_alert:write` |
    | `run_backtest` | `gse:backtest:execute` |

8. **Create `config.py`** extending `CoreSettings`. Add domain-specific settings (API URLs, timeouts, active hours). Set `env_prefix` to `{NAME}_MCP_`.

9. **Create `main.py`** wiring adapters → DataSourceManager → Cache → DataService → server factory. This should be ~30 lines.

10. **Create the database schema** in `alembic/domains/{name}/`. Each migration targets `schema="{name}"`.

11. **Create a database role** (`mcp_{name}_service`) with the same permission pattern as GSE.

12. **Write tests** in `tests/domains/{name}/`. Record API fixtures. Mock external calls.

13. **Create Dockerfile** in `deploy/Dockerfile.{name}`.

14. **Add to `docker-compose.yml`** with the domain's port and env vars.

The core library, auth, audit, caching, circuit breaker, observability, and health checks require zero changes.

---

## 21. Later Additions

1. **Bloomberg adapter for GSE** — cross-validate prices. Flag discrepancies above 2%.
2. **Data quality middleware** — compare across adapters before returning. Disagreement above threshold returns a warning flag.
3. **Webhook notifications** — alerts when circuit breakers open or sources disagree.
4. **Multi-region deployment** — active-passive in multiple regions for latency and availability.
5. **Provisioning REST API** — the `pontifex-mcp keys` CLI now covers operator and CI key management; a REST API would let upstream platforms manage keys programmatically without writing to the database directly.
6. **Partial wildcards** — support patterns like `gse:*:read` (already supported) and potentially `gse:price_*:read` for resource-level wildcards.

---

## 22. Open Questions

Resolve before implementation:

1. **GSE official feed** — Contact GSE data services (gse.com.gh/data-services) for pricing and endpoint details. Needed for a licensed adapter and for commercial redistribution.
2. **Data redistribution** — kwayisi's terms are unclear on redistribution. For production use serving data externally, the GSE official feed should be the primary source.
3. **Upstream integration pattern** — The `pontifex-mcp keys` CLI now handles operator and CI provisioning. Still open for SaaS integrators: keep writing API keys directly to Postgres, or expose a provisioning REST API? Direct DB writes are simpler; an API is more portable.
4. **Additional domains** — Which domains are likely next after GSE? Non-market verticals (logistics, government APIs) would help validate that the core abstractions generalise beyond market data.
5. **Upstream data source credentials** — Some future adapters will need to authenticate with their upstream APIs (API keys, OAuth tokens, client certificates). The adapter interface supports this today (pass credentials into the constructor), but there's no platform-level pattern yet for how those secrets are stored, rotated, or scoped. Decide when the first authenticated upstream is added: secrets manager (Vault, AWS Secrets Manager), encrypted env vars, or per-user "bring your own credentials" — each has different implications for the adapter and config layers.
