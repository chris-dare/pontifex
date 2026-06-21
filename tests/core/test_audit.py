"""Audit model roundtrip. Middleware behavior is integration-tested separately."""

from datetime import UTC, datetime

from pontifex_mcp.models.base import AuditRecord


def test_audit_record_serialization():
    rec = AuditRecord(
        timestamp=datetime.now(UTC),
        namespace="gse",
        key_id="k1",
        owner_id="o1",
        owner_label="Test",
        transport="http",
        tool_name="gse_get_live_prices",
        tool_params={"sector": "all"},
        data_source="kwayisi",
        cache_hit=False,
        response_ms=42,
    )
    dumped = rec.model_dump()
    assert dumped["namespace"] == "gse"
    assert dumped["tool_name"] == "gse_get_live_prices"
    assert dumped["response_ms"] == 42
