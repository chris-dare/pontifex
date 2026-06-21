"""Env-var handling for the shared-infrastructure DB/Redis settings.

`DATABASE_URL` / `REDIS_URL` (like `AUTH_*` / `PUBLIC_BASE_URL`) read from bare,
unprefixed env vars even under a namespace's `env_prefix`. They are **optional** —
a bare server needs neither; each is required only when a feature that uses it
is enabled, validated at backend construction via `require_url`.
"""

import pytest
from pontifex_mcp.config import require_url

from examples.gse.gse_mcp.config import GSESettings


def test_reads_bare_names_under_namespace_prefix(monkeypatch):
    """GSESettings sets env_prefix=GSE_MCP_, but these read the bare names."""
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://host/db")
    monkeypatch.setenv("REDIS_URL", "redis://host:6379/0")
    s = GSESettings()
    assert s.database_url == "postgresql+asyncpg://host/db"
    assert s.redis_url == "redis://host:6379/0"


def test_missing_urls_are_allowed(monkeypatch):
    """Neither name set → construction succeeds with empty defaults.

    A bare server (stdio, or HTTP with no auth and stdout audit) needs no DB or
    Redis, so settings must construct without them.
    """
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)
    s = GSESettings()
    assert s.database_url == ""
    assert s.redis_url == ""


def test_require_url_names_var_and_feature():
    """A backend that needs a missing URL fails with a message naming both."""
    with pytest.raises(ValueError, match="DATABASE_URL.*SQL audit"):
        require_url("", "DATABASE_URL", "SQL audit")
    assert require_url("redis://x/0", "REDIS_URL", "Redis cache") == "redis://x/0"


def test_construct_by_alias(monkeypatch):
    """Aliased fields are populated via their alias (populate_by_name is off)."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)
    s = GSESettings.model_validate(
        {"DATABASE_URL": "postgresql+asyncpg://x/y", "REDIS_URL": "redis://x/0"}
    )
    assert s.database_url == "postgresql+asyncpg://x/y"
    assert s.redis_url == "redis://x/0"
