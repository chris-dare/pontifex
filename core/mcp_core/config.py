from pydantic_settings import BaseSettings, SettingsConfigDict


class CoreSettings(BaseSettings):
    """Settings shared by all domain modules."""

    host: str = "0.0.0.0"
    port: int = 8080
    transport: str = "streamable-http"
    log_level: str = "INFO"

    redis_url: str = "redis://localhost:6379/0"
    database_url: str = "postgresql+asyncpg://mcp:mcp@localhost:5432/mcp_platform"

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

    # OAuth 2.1 / OIDC settings (provider-agnostic).  When `auth_jwks_url` is
    # set, tokens that don't start with `sk_live_` are validated as JWTs against
    # the provider's JWKS.  When empty, only API-key auth is enabled.
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
    auth_jwks_url: str = ""
    auth_issuer: str = ""
    auth_audience: str = ""
    auth_scopes_claim: str = "permissions"
    auth_authorization_server: str = ""

    # stdio-mode local identity (only used when transport == "stdio"; see §11.7).
    # `stdio_scopes` is a comma-separated list of scope patterns, e.g. "gse:*:*".
    stdio_key_id: str = "local"
    stdio_owner_id: str = "local"
    stdio_owner_label: str = "Local stdio"
    stdio_scopes: str = ""

    model_config = SettingsConfigDict(extra="ignore")
