from gse_mcp.models import Equity
from gse_mcp.symbol_registry import SymbolRegistry


class _FakeCache:
    def __init__(self):
        self.store: dict = {}

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value, ttl_seconds):
        self.store[key] = value


class _FakeAdapter:
    name = "fake"
    priority = 1
    fetch_calls = 0

    async def fetch_equities(self):
        type(self).fetch_calls += 1
        return [Equity(symbol="MTN"), Equity(symbol="GCB")]


async def test_get_all_caches_first_call():
    _FakeAdapter.fetch_calls = 0
    reg = SymbolRegistry(_FakeCache(), _FakeAdapter())
    a = await reg.get_all()
    b = await reg.get_all()
    assert {e.symbol for e in a} == {"MTN", "GCB"}
    assert len(a) == 2 == len(b)
    assert _FakeAdapter.fetch_calls == 1  # second call hits cache


async def test_get_symbol_lookup_case_insensitive():
    reg = SymbolRegistry(_FakeCache(), _FakeAdapter())
    e = await reg.get("mtn")
    assert e is not None and e.symbol == "MTN"
    assert await reg.get("nope") is None
