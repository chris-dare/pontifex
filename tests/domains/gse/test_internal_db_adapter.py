"""Smoke import test. Full DB-backed behavior is integration-tested separately."""

from gse_mcp.adapters.internal_db import InternalDBAdapter


def test_init(gse_settings):
    adapter = InternalDBAdapter(gse_settings)
    assert adapter.name == "internal_db"
    assert adapter.priority == 9
