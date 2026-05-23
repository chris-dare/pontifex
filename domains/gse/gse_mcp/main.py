from mcp_core.adapters.base import DataAdapter
from mcp_core.adapters.manager import DataSourceManager
from mcp_core.cache.redis_cache import Cache
from mcp_core.server_factory import create_mcp_app

from gse_mcp.adapters.gse_official import GSEOfficialAdapter
from gse_mcp.adapters.internal_db import InternalDBAdapter
from gse_mcp.adapters.kwayisi import KwayisiAdapter
from gse_mcp.config import GSESettings
from gse_mcp.data import GSEDataService
from gse_mcp.tools import register_gse_tools

settings = GSESettings()

# Adapters, priority-ordered. gse_official is only included when configured.
_adapters: list[DataAdapter] = [KwayisiAdapter(settings), InternalDBAdapter(settings)]
if settings.gse_official_base_url and settings.gse_official_api_key:
    _adapters.insert(0, GSEOfficialAdapter(settings))

manager = DataSourceManager(
    _adapters,
    cb_failure_threshold=settings.cb_failure_threshold,
    cb_recovery_timeout=settings.cb_recovery_timeout_seconds,
)

cache = Cache(settings.redis_url, prefix="gse")
data_service = GSEDataService(manager, cache)

app = create_mcp_app(
    domain_name="gse",
    settings=settings,
    register_tools=lambda app: register_gse_tools(app, data_service),
    health_check=manager.health_summary,
)
