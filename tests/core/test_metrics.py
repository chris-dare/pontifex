"""Optional metrics helper: real metric when Logfire is present, no-op otherwise (#48)."""

from pontifex_mcp.observability import metrics


def test_noop_when_logfire_absent(monkeypatch):
    monkeypatch.setattr(metrics, "_import_logfire", lambda: None)
    c = metrics.counter("pontifex.test.c")
    h = metrics.histogram("pontifex.test.h")
    assert isinstance(c, metrics._NoopMetric)
    assert isinstance(h, metrics._NoopMetric)
    # No-ops must accept the same calls as real metrics without raising.
    c.add(1, {"outcome": "ok"})
    h.record(12.3, {"audience": "billing-api"})


def test_returns_real_metric_when_logfire_present():
    # Logfire is a dependency, so this returns a real counter/histogram (which
    # are themselves no-ops until logfire.configure() runs). Just exercise them.
    c = metrics.counter("pontifex.test.real_c")
    h = metrics.histogram("pontifex.test.real_h", unit="ms")
    c.add(1, {"outcome": "ok"})
    h.record(5.0, {"audience": "x"})
