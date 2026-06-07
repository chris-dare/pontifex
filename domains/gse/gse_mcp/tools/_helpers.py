"""Shared helpers for GSE MCP tools.

Tools are FastMCP `@mcp.tool()` registrations wrapped with `tool_runtime` from
pontifex_mcp. The runtime handles scope check, audit, and error envelope.
"""

from datetime import UTC, datetime
from typing import Any

from gse_mcp.data import is_trading_hours

DOMAIN = "gse"


def envelope(*, source: str, cache_hit: bool, payload: dict[str, Any]) -> dict[str, Any]:
    """Build the ToolResponse envelope returned on success.

    The `source` and `cache_hit` keys are read by the tool runtime to populate
    audit fields, so they must always be present.
    """
    return {
        "timestamp": datetime.now(UTC).isoformat(),
        "source": source,
        "is_live": is_trading_hours(),
        "cache_hit": cache_hit,
        **payload,
    }
