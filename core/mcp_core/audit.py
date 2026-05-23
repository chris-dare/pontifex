"""Per-tool-invocation audit writer.

Replaces the HTTP AuditMiddleware approach: one MCP HTTP request can dispatch
multiple tool calls, so audit must hook at the tool boundary instead.
"""

from datetime import UTC, datetime
from typing import Protocol

import structlog
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from mcp_core.models.db import AuditLogModel

logger = structlog.get_logger(__name__)


class AuditWriter(Protocol):
    async def write(
        self,
        *,
        domain: str,
        key_id: str,
        owner_id: str,
        owner_label: str,
        transport: str,
        tool_name: str,
        tool_params: dict,
        data_source: str,
        cache_hit: bool,
        response_ms: int,
        error: str | None,
        ip_address: str | None,
    ) -> None: ...


class DbAuditWriter:
    """Writes one row to core.audit_log per tool call. Swallows DB errors."""

    def __init__(self, database_url: str) -> None:
        self.engine = create_async_engine(database_url, pool_size=5, max_overflow=10)
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)

    async def write(
        self,
        *,
        domain: str,
        key_id: str,
        owner_id: str,
        owner_label: str,
        transport: str,
        tool_name: str,
        tool_params: dict,
        data_source: str,
        cache_hit: bool,
        response_ms: int,
        error: str | None,
        ip_address: str | None,
    ) -> None:
        try:
            async with self.session_factory() as session:
                session.add(
                    AuditLogModel(
                        timestamp=datetime.now(UTC),
                        domain=domain,
                        key_id=key_id,
                        owner_id=owner_id,
                        owner_label=owner_label,
                        transport=transport,
                        tool_name=tool_name,
                        tool_params=tool_params,
                        data_source=data_source,
                        cache_hit=cache_hit,
                        response_ms=response_ms,
                        error=error,
                        ip_address=ip_address,
                    )
                )
                await session.commit()
        except Exception as exc:
            logger.warning("audit_write_failed", tool=tool_name, error=repr(exc))


class NoopAuditWriter:
    """Drops audit records on the floor. Used for stdio mode without a database."""

    async def write(self, **_: object) -> None:
        return None
