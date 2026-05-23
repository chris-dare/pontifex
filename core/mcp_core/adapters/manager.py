from mcp_core.adapters.base import DataAdapter
from mcp_core.utils.circuit_breaker import CircuitBreaker


class DataSourceManager:
    """Manages a set of adapters with circuit breakers and priority fallback."""

    def __init__(
        self,
        adapters: list[DataAdapter],
        cb_failure_threshold: int = 3,
        cb_recovery_timeout: float = 30.0,
    ) -> None:
        self.adapters: list[DataAdapter] = sorted(adapters, key=lambda a: a.priority)
        self.breakers: dict[str, CircuitBreaker] = {
            a.name: CircuitBreaker(
                name=a.name,
                failure_threshold=cb_failure_threshold,
                recovery_timeout=cb_recovery_timeout,
            )
            for a in adapters
        }

    def get_available_adapters(self) -> list[DataAdapter]:
        return [a for a in self.adapters if self.breakers[a.name].is_available]

    def record_success(self, adapter_name: str) -> None:
        self.breakers[adapter_name].record_success()

    def record_failure(self, adapter_name: str) -> None:
        self.breakers[adapter_name].record_failure()

    async def health_summary(self) -> dict[str, dict[str, object]]:
        result: dict[str, dict[str, object]] = {}
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
