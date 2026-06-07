import pytest
from pontifex_mcp.adapters.manager import DataSourceManager


class FakeAdapter:
    def __init__(self, name: str, priority: int, healthy: bool = True):
        self.name = name
        self.priority = priority
        self._healthy = healthy

    async def health_check(self) -> bool:
        return self._healthy


def test_sorts_by_priority():
    a = FakeAdapter("a", priority=3)
    b = FakeAdapter("b", priority=1)
    c = FakeAdapter("c", priority=2)
    mgr = DataSourceManager([a, b, c])
    assert [x.name for x in mgr.adapters] == ["b", "c", "a"]


def test_breaker_opens_excludes_adapter():
    a = FakeAdapter("a", priority=1)
    b = FakeAdapter("b", priority=2)
    mgr = DataSourceManager([a, b], cb_failure_threshold=2)
    mgr.record_failure("a")
    assert "a" in [x.name for x in mgr.get_available_adapters()]
    mgr.record_failure("a")
    assert "a" not in [x.name for x in mgr.get_available_adapters()]


@pytest.mark.asyncio
async def test_health_summary_reports_state():
    a = FakeAdapter("a", priority=1, healthy=True)
    b = FakeAdapter("b", priority=2, healthy=False)
    mgr = DataSourceManager([a, b])
    summary = await mgr.health_summary()
    assert summary["a"]["healthy"] is True
    assert summary["b"]["healthy"] is False
    assert summary["a"]["circuit_state"] == "closed"
