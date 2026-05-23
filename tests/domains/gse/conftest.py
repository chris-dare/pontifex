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

    # Avoid reading env in tests
    return GSESettings(
        kwayisi_base_url="https://dev.kwayisi.org/apis/gse",
        kwayisi_timeout_seconds=2.0,
        kwayisi_max_retries=1,
        redis_url="redis://localhost:6379/15",
        database_url="postgresql+asyncpg://mcp:mcp@localhost:5432/mcp_test",
    )
