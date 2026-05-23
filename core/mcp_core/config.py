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

    logfire_token: str = ""

    model_config = SettingsConfigDict(extra="ignore")
