"""Optional metrics, thin wrappers over Logfire's metric API.

Degrade to no-ops when Logfire isn't installed, so instrumentation never breaks
a request. When Logfire is installed but not configured, its metrics are no-ops
until `logfire.configure()` runs (via `setup_logfire`). Metric attributes carry
only non-sensitive values (audience, outcome, cache result) — never tokens or
subject identifiers.
"""

from typing import Any

# Any: Logfire's module and its metric proxy types aren't statically importable
# without hard-depending on logfire; these helpers return either a logfire metric
# or a _NoopMetric, so the call sites only rely on the .add/.record duck-shape.


def _import_logfire() -> Any:
    try:
        import logfire
    except ImportError:
        return None
    return logfire


class _NoopMetric:
    """Stand-in when Logfire isn't installed; both counter and histogram shapes."""

    def add(self, amount: float, attributes: dict[str, Any] | None = None) -> None: ...
    def record(self, amount: float, attributes: dict[str, Any] | None = None) -> None: ...


def counter(name: str, *, unit: str = "1", description: str = "") -> Any:
    """A monotonic counter (`.add(amount, attributes)`)."""
    logfire = _import_logfire()
    if logfire is None:
        return _NoopMetric()
    return logfire.metric_counter(name, unit=unit, description=description)


def histogram(name: str, *, unit: str = "", description: str = "") -> Any:
    """A value-distribution histogram (`.record(amount, attributes)`)."""
    logfire = _import_logfire()
    if logfire is None:
        return _NoopMetric()
    return logfire.metric_histogram(name, unit=unit, description=description)
