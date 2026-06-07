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
