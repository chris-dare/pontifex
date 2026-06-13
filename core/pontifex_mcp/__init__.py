"""pontifex-mcp — build enterprise-grade MCP servers.

A toolkit for standing up Model Context Protocol servers with the cross-cutting
concerns handled for you: authentication (API keys **and** OAuth 2.1 JWTs),
scope enforcement, rate limiting, audit logging, resilient data adapters with
circuit breaking, and observability. Bring a domain; the core does the rest.

The names re-exported here are the **supported public API**. Anything imported
from a deeper path (e.g. ``pontifex_mcp.middleware``, ``pontifex_mcp.auth``)
is an internal detail and may change without a major-version bump.
"""

from pontifex_mcp.adapters.base import DataAdapter
from pontifex_mcp.adapters.manager import DataSourceManager
from pontifex_mcp.audit import AuditWriter, DbAuditWriter, NoopAuditWriter
from pontifex_mcp.auth.identity import CallerIdentity
from pontifex_mcp.auth.scopes import scopes_match
from pontifex_mcp.cache.redis_cache import Cache
from pontifex_mcp.config import CoreSettings
from pontifex_mcp.connectors import BearerFromEnv, HeaderFromEnv, register_openapi_tools
from pontifex_mcp.models.base import AuditRecord, ToolError, ToolResponse
from pontifex_mcp.server_factory import create_mcp_http_app, run_mcp_stdio
from pontifex_mcp.tool_runtime import InvalidInput, tool_runtime
from pontifex_mcp.utils.circuit_breaker import CircuitBreaker
from pontifex_mcp.utils.retry import async_retry

__version__ = "0.2.0"

__all__ = [
    "AuditRecord",
    "AuditWriter",
    "BearerFromEnv",
    "Cache",
    "CallerIdentity",
    "CircuitBreaker",
    "CoreSettings",
    "DataAdapter",
    "DataSourceManager",
    "DbAuditWriter",
    "HeaderFromEnv",
    "InvalidInput",
    "NoopAuditWriter",
    "ToolError",
    "ToolResponse",
    "async_retry",
    "create_mcp_http_app",
    "register_openapi_tools",
    "run_mcp_stdio",
    "scopes_match",
    "tool_runtime",
]
