# Build a resilient adapter

A tool should never call an external system directly. It should call through a
**`DataAdapter`** — so the I/O is testable, swappable, and protected by failover,
caching, and circuit breaking.

This guide builds one by hand. (Connectors generate adapters for you; this is for the
systems you wire yourself.)

## The protocol

A `DataAdapter` is small. The core only needs three things to orchestrate it; your
domain adds whatever methods the tool calls.

```python
from typing import Protocol

class OrdersAdapter(Protocol):
    @property
    def name(self) -> str: ...          # for logging, metrics, cache tags
    @property
    def priority(self) -> int: ...      # lower = tried first
    async def health_check(self) -> bool: ...

    async def get_order(self, order_id: str) -> dict: ...   # your method
```

Write two implementations — say, a primary API and a fallback datastore — and the
manager will prefer the primary and fall back when it's down.

## Let the manager order them

`DataSourceManager` takes your adapters, wraps each in a circuit breaker, and hands you
the ones currently available.

```python
from pontifex_mcp import DataSourceManager

manager = DataSourceManager(
    [PrimaryApiAdapter(), FallbackDbAdapter()],
    cb_failure_threshold=3,        # trip after 3 consecutive failures
    cb_recovery_timeout=30.0,      # try again 30s later
)
```

## The failover pattern

Check the cache, walk the available sources in priority order, record the outcome, and
cache a hit. Record success and failure so the breaker learns.

```python
from pontifex_mcp import Cache

cache = Cache(redis_url, prefix="orders")

async def get_order(order_id: str) -> dict:
    cached = await cache.get(f"order:{order_id}")
    if cached:
        return cached

    for adapter in manager.get_available_adapters():
        try:
            order = await adapter.get_order(order_id)
            manager.record_success(adapter.name)
            await cache.set(f"order:{order_id}", order, ttl_seconds=30)
            return order
        except Exception:
            manager.record_failure(adapter.name)
            continue

    raise RuntimeError("All order sources unavailable")
```

When every source is down, raise — and map that exception to a clean response with
`tool_runtime`'s `source_unavailable_exception` so the caller gets a retryable
`source_unavailable` (503), not a 500.

## The reliability pieces

Each is importable from `pontifex_mcp` and plugs into an adapter independently.

`Cache`
:   A namespaced, Redis-backed cache. **You** decide the TTL per write — the cache has
    no idea what your data is. Absorbs most traffic so a slow upstream is rarely hit.

`CircuitBreaker`
:   Trips after repeated failures, then recovers automatically. The manager gives each
    adapter one; you can also use it directly around any flaky call.

`async_retry`
:   Decorator that retries a coroutine with exponential backoff and jitter — for
    *transient* errors, inside a single adapter, before the breaker counts a failure.

```python
from pontifex_mcp import async_retry

@async_retry(attempts=3)
async def _call_upstream(self, order_id: str) -> dict:
    ...
```

## Surface health

Expose the manager's `health_summary` from your readiness check, and `/health/ready`
reports each adapter's state and breaker status:

```python
app = create_mcp_http_app("orders", settings, register_tools, manager.health_summary)
```

A down upstream shows up in your probes instead of as caller-facing 500s. That's the
whole goal: contain the failure, don't propagate it.
