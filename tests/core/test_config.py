"""Env-var aliasing for shared-infrastructure settings.

DATABASE_URL / REDIS_URL (like AUTH_* / PUBLIC_BASE_URL) read from bare,
unprefixed env vars even under a domain's `env_prefix`. The domain prefix is
NEVER applied to them — a stray GSE_MCP_DATABASE_URL must not leak in.
"""

from domains.gse.gse_mcp.config import GSESettings


def test_reads_bare_names_under_domain_prefix(monkeypatch):
    """GSESettings has env_prefix=GSE_MCP_, but these read the bare names."""
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://bare/db")
    monkeypatch.setenv("REDIS_URL", "redis://bare:6379/0")
    s = GSESettings()
    assert s.database_url == "postgresql+asyncpg://bare/db"
    assert s.redis_url == "redis://bare:6379/0"


def test_prefixed_names_are_ignored(monkeypatch):
    """A GSE_MCP_DATABASE_URL / GSE_MCP_REDIS_URL value must NOT set the field —
    only the bare names are honoured, so the prefixed values fall through to
    the defaults."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.setenv("GSE_MCP_DATABASE_URL", "postgresql+asyncpg://legacy/db")
    monkeypatch.setenv("GSE_MCP_REDIS_URL", "redis://legacy:6379/0")
    s = GSESettings()
    assert s.database_url == "postgresql+asyncpg://mcp:mcp@localhost:5432/mcp_platform"
    assert s.redis_url == "redis://localhost:6379/0"


def test_defaults_when_unset(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)
    s = GSESettings()
    assert s.database_url == "postgresql+asyncpg://mcp:mcp@localhost:5432/mcp_platform"
    assert s.redis_url == "redis://localhost:6379/0"


def test_construct_by_alias(monkeypatch):
    """Without populate_by_name, aliased fields are constructed via their alias."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)
    s = GSESettings.model_validate(
        {"DATABASE_URL": "postgresql+asyncpg://x/y", "REDIS_URL": "redis://x/0"}
    )
    assert s.database_url == "postgresql+asyncpg://x/y"
    assert s.redis_url == "redis://x/0"


def test_field_name_input_is_ignored(monkeypatch):
    """The alias is the only population path: a `database_url` key is not
    recognised, so (with extra='ignore') it's dropped and the field falls back
    to its default rather than taking the supplied value."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    s = GSESettings.model_validate({"database_url": "postgresql+asyncpg://ignored/db"})
    assert s.database_url == "postgresql+asyncpg://mcp:mcp@localhost:5432/mcp_platform"
