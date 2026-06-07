"""Env-var handling for the shared-infrastructure DB/Redis settings.

`DATABASE_URL` / `REDIS_URL` (like `AUTH_*` / `PUBLIC_BASE_URL`) read from bare,
unprefixed env vars even under a domain's `env_prefix`. They are **required** —
a missing value fails fast rather than silently falling back to a localhost
default.
"""

import pytest
from pydantic import ValidationError

from domains.gse.gse_mcp.config import GSESettings


def test_reads_bare_names_under_domain_prefix(monkeypatch):
    """GSESettings sets env_prefix=GSE_MCP_, but these read the bare names."""
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://host/db")
    monkeypatch.setenv("REDIS_URL", "redis://host:6379/0")
    s = GSESettings()
    assert s.database_url == "postgresql+asyncpg://host/db"
    assert s.redis_url == "redis://host:6379/0"


def test_missing_urls_fail_fast(monkeypatch):
    """Neither name set → construction raises rather than using a default."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)
    with pytest.raises(ValidationError):
        GSESettings()


def test_construct_by_alias(monkeypatch):
    """Aliased fields are populated via their alias (populate_by_name is off)."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)
    s = GSESettings.model_validate(
        {"DATABASE_URL": "postgresql+asyncpg://x/y", "REDIS_URL": "redis://x/0"}
    )
    assert s.database_url == "postgresql+asyncpg://x/y"
    assert s.redis_url == "redis://x/0"
