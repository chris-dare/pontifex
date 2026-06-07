"""Env-var handling for the shared-infrastructure DB/Redis settings.

`DATABASE_URL` / `REDIS_URL` (like `AUTH_*` / `PUBLIC_BASE_URL`) read from bare,
unprefixed env vars even under a domain's `env_prefix`. They are **required** —
the legacy `GSE_MCP_*` names are ignored, and a missing value fails fast rather
than silently falling back to a localhost default.
"""

import pytest
from pydantic import ValidationError

from domains.gse.gse_mcp.config import GSESettings


def test_reads_bare_names_under_domain_prefix(monkeypatch):
    """GSESettings has env_prefix=GSE_MCP_, but these read the bare names."""
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://bare/db")
    monkeypatch.setenv("REDIS_URL", "redis://bare:6379/0")
    s = GSESettings()
    assert s.database_url == "postgresql+asyncpg://bare/db"
    assert s.redis_url == "redis://bare:6379/0"


def test_missing_urls_fail_fast(monkeypatch):
    """Neither name set → construction raises rather than using a default."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)
    with pytest.raises(ValidationError):
        GSESettings()


def test_prefixed_database_url_does_not_satisfy_required(monkeypatch):
    """Setting only the legacy GSE_MCP_DATABASE_URL must NOT satisfy the required
    bare DATABASE_URL — it's ignored, so construction still fails fast."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("REDIS_URL", "redis://bare:6379/0")  # satisfy redis
    monkeypatch.setenv("GSE_MCP_DATABASE_URL", "postgresql+asyncpg://legacy/db")
    with pytest.raises(ValidationError):
        GSESettings()


def test_prefixed_redis_url_does_not_satisfy_required(monkeypatch):
    """Symmetric case: only the legacy GSE_MCP_REDIS_URL is set — it's ignored,
    so the required bare REDIS_URL is still unsatisfied and construction fails."""
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://bare/db")  # satisfy db
    monkeypatch.setenv("GSE_MCP_REDIS_URL", "redis://legacy:6379/0")
    with pytest.raises(ValidationError):
        GSESettings()


def test_construct_by_alias(monkeypatch):
    """Without populate_by_name, aliased fields are populated via their alias."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)
    s = GSESettings.model_validate(
        {"DATABASE_URL": "postgresql+asyncpg://x/y", "REDIS_URL": "redis://x/0"}
    )
    assert s.database_url == "postgresql+asyncpg://x/y"
    assert s.redis_url == "redis://x/0"
