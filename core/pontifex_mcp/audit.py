"""Per-tool-invocation audit writers and sink resolution.

Replaces the HTTP AuditMiddleware approach: one MCP HTTP request can dispatch
multiple tool calls, so audit must hook at the tool boundary instead.

Sinks:
  - `StdoutAuditWriter` — structured line per call via structlog. The bare
    default: audit stays visible with no infra.
  - `DbAuditWriter` — durable rows in SQLite (quickstart) or Postgres (prod),
    dialect detected from the connection string.
  - `TeeAuditWriter` — fans out to several writers.
  - `NoopAuditWriter` — drops records (explicit "off").

`resolve_audit_writer` maps the facade's `audit=` value to one of these.
"""

import asyncio
import inspect
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

import structlog
from sqlalchemy.ext.asyncio import async_sessionmaker

from pontifex_mcp.models.db import AuditLogModel
from pontifex_mcp.storage import (
    create_db_engine,
    ensure_sqlite_schema,
    is_sqlite,
    normalize_db_url,
)

logger = structlog.get_logger(__name__)


@runtime_checkable
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
        delegated_audience: str | None = None,
    ) -> None: ...


class DbAuditWriter:
    """Writes one row to core.audit_log per tool call. Swallows DB errors.

    Accepts any value `normalize_db_url` understands — a bare path (`audit.db`)
    or a full URL. SQLite tables are created lazily on first write (Postgres
    schemas are owned by Alembic).
    """

    def __init__(self, datastore: str) -> None:
        url = normalize_db_url(datastore)
        self._is_sqlite = is_sqlite(url)
        self.engine = create_db_engine(url)
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)
        # Postgres schema is Alembic-managed; only SQLite needs lazy create_all.
        self._schema_ready = not self._is_sqlite
        self._schema_lock = asyncio.Lock()

    async def _ensure_schema(self) -> None:
        if self._schema_ready:
            return
        async with self._schema_lock:
            if self._schema_ready:
                return
            await ensure_sqlite_schema(self.engine)
            self._schema_ready = True

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
        delegated_audience: str | None = None,
    ) -> None:
        try:
            await self._ensure_schema()
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
                        delegated_audience=delegated_audience,
                    )
                )
                await session.commit()
        except Exception as exc:
            logger.warning("audit_write_failed", tool=tool_name, error=repr(exc))


class NoopAuditWriter:
    """Drops audit records on the floor. The explicit "off" sink."""

    async def write(self, **_: object) -> None:
        return None


class StdoutAuditWriter:
    """Emits one structured audit line per tool call via structlog.

    The bare default — audit stays visible with no infra. Switches to durable
    storage by configuring a path or URL instead.
    """

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
        delegated_audience: str | None = None,
    ) -> None:
        logger.info(
            "tool_call",
            domain=domain,
            tool=tool_name,
            owner_id=owner_id,
            owner_label=owner_label,
            transport=transport,
            params=tool_params,
            data_source=data_source,
            cache_hit=cache_hit,
            response_ms=response_ms,
            error=error,
            key_id=key_id,
            ip_address=ip_address,
            delegated_audience=delegated_audience,
        )


class TeeAuditWriter:
    """Fans each record out to several writers in order (e.g. stdout + SQLite)."""

    def __init__(self, writers: list[AuditWriter]) -> None:
        self.writers = writers

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
        delegated_audience: str | None = None,
    ) -> None:
        for writer in self.writers:
            await writer.write(
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
                delegated_audience=delegated_audience,
            )


# What the facade's `audit=` kwarg accepts. A str is a path/URL (or "stdout" /
# "off"); None is the stdout default; a list tees; an AuditWriter is used as-is.
type AuditSpec = str | bool | None | list[AuditSpec] | AuditWriter


def resolve_audit_writer(spec: object) -> AuditWriter:
    """Map a facade `audit=` value to a concrete `AuditWriter`.

    - `None` / `True` / `"stdout"` → `StdoutAuditWriter` (the bare default)
    - `False` / `"off"` / `"none"` / `"noop"` → `NoopAuditWriter`
    - a list → `TeeAuditWriter` of each resolved element
    - any other str → `DbAuditWriter` (a path like `audit.db` or a DB URL)
    - an existing `AuditWriter` → returned unchanged

    Type checks run before the string-sentinel matches so a real `AuditWriter`
    (even one with a custom ``__eq__``) is always honored as-is.
    """
    if spec is None or spec is True:
        return StdoutAuditWriter()
    if spec is False:
        return NoopAuditWriter()
    # `runtime_checkable` only verifies a `write` attribute exists, so also
    # require it to be a coroutine function — otherwise a file handle (sync
    # `write`) would be mistaken for an AuditWriter and blow up at call time.
    if isinstance(spec, AuditWriter) and inspect.iscoroutinefunction(spec.write):
        return spec
    if isinstance(spec, list):
        return TeeAuditWriter([resolve_audit_writer(s) for s in spec])
    if isinstance(spec, str):
        if spec == "stdout":
            return StdoutAuditWriter()
        if spec in ("off", "none", "noop"):
            return NoopAuditWriter()
        return DbAuditWriter(spec)
    raise TypeError(
        f"Unsupported audit spec {spec!r}: expected None, a str path/URL, "
        "a list, or an AuditWriter."
    )
