from pydantic import Field, HttpUrl, TypeAdapter, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_HTTP_URL = TypeAdapter(HttpUrl)


class CoreSettings(BaseSettings):
    """Settings shared by all domain modules."""

    host: str = "0.0.0.0"
    port: int = 8080
    transport: str = "streamable-http"
    log_level: str = "INFO"

    # The DB and Redis connections are shared infrastructure (one server, one
    # database with a schema per domain; one Redis namespaced per domain), not
    # domain settings — so, like `AUTH_*` / `PUBLIC_BASE_URL`, they read from
    # bare, unprefixed env vars regardless of a domain's `env_prefix`.
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        validation_alias="REDIS_URL",
    )
    database_url: str = Field(
        default="postgresql+asyncpg://mcp:mcp@localhost:5432/mcp_platform",
        validation_alias="DATABASE_URL",
    )

    cb_failure_threshold: int = 3
    cb_recovery_timeout_seconds: float = 30.0

    api_key_cache_ttl_seconds: int = 300
    api_key_hash_algorithm: str = "sha256"

    env_prefix: str = ""

    logfire_token: str = ""

    # Comma-separated list of allowed Host header values for MCP DNS rebinding
    # protection.  When non-empty, the MCP transport rejects requests whose
    # Host header does not match one of these entries (HTTP 421).  Supports
    # wildcard ports, e.g. "localhost:*".  When empty, protection is disabled
    # (safe for Bearer-token-only servers).
    allowed_hosts: str = ""

    # The server's canonical public base URL (e.g.
    # "https://pontifex-mcp-gse-preprod.fly.dev"), advertised verbatim in the
    # OAuth discovery documents — the `resource` field and the
    # `WWW-Authenticate` challenge.  OAuth resource identifiers must be a single
    # stable value, and a configured URL is immune to `X-Forwarded-*` spoofing.
    # When empty, the discovery URL is derived from the request (local/dev).
    #
    # This is an infrastructure concern (where the app is deployed), not a
    # domain one, so it reads from a bare `PUBLIC_BASE_URL` — the alias bypasses
    # a domain's `env_prefix`, so the var name is the same for any MCP app.
    public_base_url: str = Field(default="", validation_alias="PUBLIC_BASE_URL")

    # OAuth 2.1 / OIDC settings (provider-agnostic).  When `auth_jwks_url` is
    # set, tokens that don't start with `sk_` are validated as JWTs against the
    # provider's JWKS.  When empty, only API-key auth is enabled.
    #
    #   auth_jwks_url       URL of the provider's JWKS endpoint.
    #   auth_issuer         Expected `iss` claim value.
    #   auth_audience       Expected `aud` claim value (the MCP platform).
    #   auth_scopes_claim   Name of the JWT claim that carries scopes.
    #                       Auth0 -> "permissions"; Entra -> "scp" or "roles";
    #                       Clerk -> provider-specific.
    #   auth_authorization_server
    #                       Authorization server URL advertised by the
    #                       /.well-known/oauth-protected-resource document.
    # These are infrastructure-level (which IdP backs the deployment), not
    # domain settings, so — like `public_base_url` — they read from bare,
    # unprefixed `AUTH_*` env vars regardless of a domain's `env_prefix`.
    auth_jwks_url: str = Field(default="", validation_alias="AUTH_JWKS_URL")
    auth_issuer: str = Field(default="", validation_alias="AUTH_ISSUER")
    auth_audience: str = Field(default="", validation_alias="AUTH_AUDIENCE")
    auth_scopes_claim: str = Field(default="permissions", validation_alias="AUTH_SCOPES_CLAIM")
    auth_authorization_server: str = Field(default="", validation_alias="AUTH_AUTHORIZATION_SERVER")

    # Requests/minute granted to a caller authenticated by JWT.  API keys carry
    # their own per-key limit from the DB record; JWTs don't, and we never read
    # a limit from the token itself, so this server-side default applies.
    jwt_default_rate_limit_rpm: int = 120

    # stdio-mode local identity (only used when transport == "stdio"; see §11.7).
    # `stdio_scopes` is a comma-separated list of scope patterns, e.g. "gse:*:*".
    stdio_key_id: str = "local"
    stdio_owner_id: str = "local"
    stdio_owner_label: str = "Local stdio"
    stdio_scopes: str = ""

    @field_validator("public_base_url")
    @classmethod
    def _validate_public_base_url(cls, v: str) -> str:
        """Reject a malformed `public_base_url` at load time; empty is allowed."""
        if v:
            try:
                _HTTP_URL.validate_python(v)
            except ValidationError as exc:
                raise ValueError(f"public_base_url is not a valid URL: {v!r}") from exc
        return v

    model_config = SettingsConfigDict(extra="ignore", populate_by_name=True)
