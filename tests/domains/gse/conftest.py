import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixture():
    def _load(name: str):
        with open(FIXTURES / f"{name}.json") as f:
            return json.load(f)

    return _load


@pytest.fixture
def gse_settings():
    from gse_mcp.config import GSESettings

    # Avoid reading env in tests.  database_url/redis_url have a validation_alias
    # and the settings don't enable populate_by_name, so pass them by alias.
    return GSESettings.model_validate(
        {
            "kwayisi_base_url": "https://dev.kwayisi.org/apis/gse",
            "kwayisi_timeout_seconds": 2.0,
            "kwayisi_max_retries": 1,
            "REDIS_URL": "redis://localhost:6379/15",
            "DATABASE_URL": "postgresql+asyncpg://mcp:mcp@localhost:5432/mcp_test",
        }
    )
