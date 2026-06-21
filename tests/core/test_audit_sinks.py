"""Audit sink resolution + the stdout / tee / SQLite writers.

The bare default is stdout (visible, no infra); a path/URL is durable; a list
tees. SQLite tables are created lazily on first write.
"""

import pytest
import structlog
from pontifex_mcp.audit import (
    DbAuditWriter,
    NoopAuditWriter,
    StdoutAuditWriter,
    TeeAuditWriter,
    resolve_audit_writer,
)
from pontifex_mcp.models.db import AuditLogModel
from pontifex_mcp.storage import create_db_engine
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

_RECORD = dict(
    namespace="payments",
    key_id="k",
    owner_id="anonymous",
    owner_label="Anonymous",
    transport="stdio",
    tool_name="issue_refund",
    tool_params={"charge_id": "ch_1", "amount": 500, "idempotency_key": "idem-1"},
    data_source="fake_stripe",
    cache_hit=False,
    response_ms=12,
    error=None,
    ip_address=None,
)


class _RecordingWriter:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def write(self, **fields: object) -> None:
        self.calls.append(dict(fields))


def test_resolve_audit_writer_mapping():
    assert isinstance(resolve_audit_writer(None), StdoutAuditWriter)
    assert isinstance(resolve_audit_writer(True), StdoutAuditWriter)
    assert isinstance(resolve_audit_writer("stdout"), StdoutAuditWriter)
    assert isinstance(resolve_audit_writer(False), NoopAuditWriter)
    for off in ("off", "none", "noop"):
        assert isinstance(resolve_audit_writer(off), NoopAuditWriter)
    assert isinstance(resolve_audit_writer("audit.db"), DbAuditWriter)
    assert isinstance(resolve_audit_writer("postgresql+asyncpg://u@h/db"), DbAuditWriter)
    teed = resolve_audit_writer(["stdout", "audit.db"])
    assert isinstance(teed, TeeAuditWriter)
    assert len(teed.writers) == 2
    existing = NoopAuditWriter()
    assert resolve_audit_writer(existing) is existing


def test_resolve_audit_writer_rejects_garbage():
    with pytest.raises(TypeError, match="Unsupported audit spec"):
        resolve_audit_writer(123)


def test_resolve_audit_writer_rejects_sync_write_object(tmp_path):
    """A file handle has a (sync) `write` attr but is not an AuditWriter."""
    with (tmp_path / "x.log").open("w") as fh:
        with pytest.raises(TypeError, match="Unsupported audit spec"):
            resolve_audit_writer(fh)


def test_resolve_honors_real_writer_over_string_sentinel():
    """A writer whose __eq__ matches a sentinel string is still returned as-is."""

    class WeirdWriter:
        async def write(self, **_: object) -> None:
            return None

        def __eq__(self, other: object) -> bool:
            return True  # equals "stdout", "off", everything

    w = WeirdWriter()
    assert resolve_audit_writer(w) is w


@pytest.mark.asyncio
async def test_stdout_writer_emits_one_structured_line():
    writer = StdoutAuditWriter()
    with structlog.testing.capture_logs() as logs:
        await writer.write(**_RECORD)
    assert len(logs) == 1
    entry = logs[0]
    assert entry["event"] == "tool_call"
    assert entry["tool"] == "issue_refund"
    assert entry["params"]["idempotency_key"] == "idem-1"
    assert entry["owner_id"] == "anonymous"


@pytest.mark.asyncio
async def test_tee_fans_out_to_all_writers():
    a, b = _RecordingWriter(), _RecordingWriter()
    await TeeAuditWriter([a, b]).write(**_RECORD)
    assert a.calls[0]["tool_name"] == "issue_refund"
    assert b.calls[0]["tool_name"] == "issue_refund"


@pytest.mark.asyncio
async def test_db_writer_persists_to_sqlite_file(tmp_path):
    """A path produces durable rows in a SQLite file; the schema is created
    lazily on first write (no Alembic)."""
    db_path = tmp_path / "audit.db"
    writer = DbAuditWriter(str(db_path))
    await writer.write(**_RECORD)

    assert db_path.exists()
    # Re-open the file with a fresh engine to prove durability across connections.
    engine = create_db_engine(f"sqlite+aiosqlite:///{db_path}")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as s:
        row = (await s.execute(select(AuditLogModel))).scalar_one()
    assert row.tool_name == "issue_refund"
    assert row.tool_params["idempotency_key"] == "idem-1"
    await engine.dispose()
    await writer.engine.dispose()
