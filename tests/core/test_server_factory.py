"""Smoke import test. Full middleware behavior needs Redis + Postgres (see testcontainers tests)."""

from mcp_core.server_factory import create_mcp_app


def test_import_only():
    assert callable(create_mcp_app)
