"""Env-var aliasing for shared-infrastructure settings.

DATABASE_URL / REDIS_URL (like AUTH_* / PUBLIC_BASE_URL) read from bare,
unprefixed env vars even under a domain's `env_prefix`, with the legacy
`GSE_MCP_*` names accepted as a transition fallback.
"""

from domains.gse.gse_mcp.config import GSESettings


def test_reads_bare_names_under_domain_prefix(monkeypatch):
    """GSESettings has env_prefix=GSE_MCP_, but these read the bare names."""
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://bare/db")
    monkeypatch.setenv("REDIS_URL", "redis://bare:6379/0")
    s = GSESettings()
    assert s.database_url == "postgresql+asyncpg://bare/db"
    assert s.redis_url == "redis://bare:6379/0"


def test_falls_back_to_prefixed_names(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.setenv("GSE_MCP_DATABASE_URL", "postgresql+asyncpg://legacy/db")
    monkeypatch.setenv("GSE_MCP_REDIS_URL", "redis://legacy:6379/0")
    s = GSESettings()
    assert s.database_url == "postgresql+asyncpg://legacy/db"
    assert s.redis_url == "redis://legacy:6379/0"


def test_bare_name_wins_when_both_set(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://bare/db")
    monkeypatch.setenv("GSE_MCP_DATABASE_URL", "postgresql+asyncpg://legacy/db")
    s = GSESettings()
    assert s.database_url == "postgresql+asyncpg://bare/db"


def test_construct_by_field_name_still_works():
    """Tests/conftest construct settings by field name; that must keep working."""
    s = GSESettings(
        database_url="postgresql+asyncpg://x/y",
        redis_url="redis://x/0",
    )
    assert s.database_url == "postgresql+asyncpg://x/y"
    assert s.redis_url == "redis://x/0"
