import pytest


@pytest.fixture
def core_settings():
    from mcp_core.config import CoreSettings

    return CoreSettings(
        redis_url="redis://localhost:6379/15",
        database_url="postgresql+asyncpg://mcp:mcp@localhost:5432/mcp_test",
        logfire_token="",
    )
