"""Smoke import test + protected-resource metadata endpoint coverage.

Full middleware behavior needs Redis + Postgres (see testcontainers tests),
but the discovery endpoints touch neither, so they're exercised here with a
TestClient over a fully-built app.
"""

from mcp_core.config import CoreSettings
from mcp_core.server_factory import create_mcp_app, create_mcp_http_app
from starlette.testclient import TestClient


def test_import_only():
    assert callable(create_mcp_app)


def _settings(*, public_base_url: str = "", allowed_hosts: str = "mcp.example.com") -> CoreSettings:
    # Fields with a validation_alias are populated by their alias (the env-var
    # name), since the settings classes don't enable populate_by_name.
    return CoreSettings.model_validate(
        {
            "REDIS_URL": "redis://localhost:6379/0",
            "DATABASE_URL": "postgresql+asyncpg://x:x@localhost:5432/x",
            "AUTH_JWKS_URL": "https://issuer.example/.well-known/jwks.json",
            "AUTH_ISSUER": "https://issuer.example/",
            "AUTH_AUDIENCE": "https://api.example",
            "AUTH_AUTHORIZATION_SERVER": "https://issuer.example/",
            "PUBLIC_BASE_URL": public_base_url,
            "allowed_hosts": allowed_hosts,
            "logfire_token": "",
        }
    )


def _build_app(settings: CoreSettings):
    async def health() -> dict:
        return {"ok": True}

    def register_tools(_mcp, _audit) -> None:
        pass

    return create_mcp_http_app("gse", settings, register_tools, health)


def _get_metadata(settings: CoreSettings, headers: dict[str, str]) -> dict:
    with TestClient(_build_app(settings)) as client:
        resp = client.get("/.well-known/oauth-protected-resource", headers=headers)
    assert resp.status_code == 200
    return resp.json()


def test_metadata_uses_configured_public_base_url():
    """public_base_url is advertised verbatim; a spoofed host can't override it."""
    body = _get_metadata(
        _settings(public_base_url="https://mcp.example.com"),
        {"X-Forwarded-Proto": "https", "X-Forwarded-Host": "attacker.example"},
    )
    assert body["resource"] == "https://mcp.example.com/mcp"
    assert body["authorization_servers"] == ["https://issuer.example/"]
    assert body["bearer_methods_supported"] == ["header"]


def test_metadata_fallback_uses_trusted_forwarded_host():
    """No public_base_url: a forwarded host in allowed_hosts is honoured."""
    body = _get_metadata(
        _settings(allowed_hosts="mcp.example.com"),
        {"X-Forwarded-Proto": "https", "X-Forwarded-Host": "mcp.example.com"},
    )
    assert body["resource"] == "https://mcp.example.com/mcp"


def test_metadata_fallback_ignores_spoofed_forwarded_host():
    """No public_base_url: a forwarded host NOT in allowed_hosts is ignored,
    falling back to the real Host header rather than the attacker's."""
    body = _get_metadata(
        _settings(allowed_hosts="mcp.example.com"),
        {"X-Forwarded-Proto": "https", "X-Forwarded-Host": "attacker.example"},
    )
    assert "attacker.example" not in body["resource"]
