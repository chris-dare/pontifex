from mcp_core.config import CoreSettings
from pydantic_settings import SettingsConfigDict


class GSESettings(CoreSettings):
    kwayisi_base_url: str = "https://dev.kwayisi.org/apis/gse"
    kwayisi_timeout_seconds: float = 8.0
    kwayisi_max_retries: int = 3

    gse_official_base_url: str = ""
    gse_official_api_key: str = ""

    model_config = SettingsConfigDict(env_prefix="GSE_MCP_", extra="ignore")
