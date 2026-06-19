from pydantic import Field, HttpUrl, TypeAdapter, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_HTTP_URL = TypeAdapter(HttpUrl)


def require_url(value: str, env_var: str, feature: str) -> str:
    """Return `value`, or raise if it's empty.

    DB/Redis URLs default to empty and are only required when a feature that
    needs them is enabled (SQL audit, API-key auth, Redis cache, rate limiting).
    Backends call this at construction so the error names both the missing env
    var and the feature that needs it, instead of failing opaquely later.
    """
    if not value:
        raise ValueError(
            f"{feature} requires {env_var} to be set, but it is empty. "
            f"Set {env_var}, or disable {feature}."
        )
    return value


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
    #
    # Optional by default — empty is valid. A bare server (stdio, or HTTP with
    # no auth and stdout audit) needs neither. Each is required only when a
    # feature that uses it is enabled: `database_url` for SQL audit / API-key
    # auth, `redis_url` for the Redis cache / API-key resolver cache / rate
    # limiting. That check happens at backend construction via `require_url`,
    # so the error names the missing var and the feature — not here, which would
    # force infra on every server including stdio.
    redis_url: str = Field(default="", validation_alias="REDIS_URL")
    database_url: str = Field(default="", validation_alias="DATABASE_URL")

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

    # Path to a connectors YAML file (see pontifex_mcp.connectors.config). When
    # set, the server factory registers OpenAPI-generated tools from it at
    # startup — onboarding an API via deployment config alone. Infrastructure-
    # level (which connectors a deployment exposes), so a bare env var like
    # `AUTH_*` / `PUBLIC_BASE_URL`.
    connectors_config: str = Field(default="", validation_alias="PONTIFEX_CONNECTORS_CONFIG")

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

    # `populate_by_name` is left False (the default) on purpose: a field with a
    # `validation_alias` is then populated ONLY from that alias, never from
    # `env_prefix` + field name — so the bare `DATABASE_URL` / `REDIS_URL` are the
    # sole source for those settings even under a domain's prefix.
    model_config = SettingsConfigDict(extra="ignore")
