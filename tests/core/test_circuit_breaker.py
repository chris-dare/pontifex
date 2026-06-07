import time

from pontifex_mcp.utils.circuit_breaker import CircuitBreaker, State


def test_starts_closed_and_available():
    cb = CircuitBreaker(failure_threshold=3, recovery_timeout=30.0, name="x")
    assert cb.state is State.CLOSED
    assert cb.is_available is True


def test_opens_after_threshold_failures():
    cb = CircuitBreaker(failure_threshold=2, recovery_timeout=30.0, name="x")
    cb.record_failure()
    assert cb.state is State.CLOSED
    cb.record_failure()
    assert cb.state is State.OPEN
    assert cb.is_available is False


def test_half_open_after_recovery_timeout(monkeypatch):
    cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.01, name="x")
    cb.record_failure()
    assert cb.state is State.OPEN
    time.sleep(0.02)
    assert cb.is_available is True
    assert cb.state is State.HALF_OPEN


def test_success_in_half_open_closes():
    cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.01, name="x")
    cb.record_failure()
    time.sleep(0.02)
    _ = cb.is_available  # transitions to half-open
    cb.record_success()
    assert cb.state is State.CLOSED
    assert cb.failure_count == 0
