"""Connectors: declarative YAML config loading and registration."""

import json

import httpx
import pytest
import respx
import yaml
from mcp import types
from mcp.server.fastmcp import FastMCP
from pontifex_mcp.auth.context import set_stdio_caller
from pontifex_mcp.auth.identity import CallerIdentity
from pontifex_mcp.connectors import load_connectors_config, register_connectors_from_config
from pydantic import ValidationError

from tests.core.test_connectors import SAMPLE_SPEC


class _RecordingAudit:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def write(self, **kwargs) -> None:
        self.calls.append(kwargs)


@pytest.fixture
def config_path(tmp_path):
    spec_path = tmp_path / "orders.json"
    spec_path.write_text(json.dumps(SAMPLE_SPEC))
    path = tmp_path / "connectors.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "connectors": [
                    {
                        "domain": "orders",
                        "spec": str(spec_path),
                        "base_url": "https://api.test",
                        "include": ["GET /orders", "GET /orders/{order_id}"],
                        "auth": {"type": "bearer_env", "env_var": "ORDERS_API_TOKEN"},
                    }
                ]
            }
        )
    )
    return path


def test_load_connectors_config(config_path):
    config = load_connectors_config(config_path)
    assert len(config.connectors) == 1
    entry = config.connectors[0]
    assert entry.domain == "orders"
    assert entry.allow_mutations is False
    assert entry.auth is not None
    assert entry.auth.type == "bearer_env"


def test_header_env_requires_header_name():
    from pontifex_mcp.connectors.config import ConnectorAuth

    with pytest.raises(ValidationError, match="header"):
        ConnectorAuth(type="header_env", env_var="X")


def test_missing_credential_fails_at_registration(config_path, monkeypatch):
    monkeypatch.delenv("ORDERS_API_TOKEN", raising=False)
    mcp = FastMCP(name="t", stateless_http=True)
    with pytest.raises(ValueError, match="ORDERS_API_TOKEN"):
        register_connectors_from_config(mcp, _RecordingAudit(), config_path)


@respx.mock
async def test_register_from_config_end_to_end(config_path, monkeypatch):
    monkeypatch.setenv("ORDERS_API_TOKEN", "sekrit")
    respx.get("https://api.test/orders").mock(return_value=httpx.Response(200, json=[]))

    mcp = FastMCP(name="t", stateless_http=True)
    audit = _RecordingAudit()
    managers = register_connectors_from_config(mcp, audit, config_path)
    assert set(managers) == {"orders"}

    tools = {t.name for t in await mcp.list_tools()}
    assert tools == {"orders_list_orders", "orders_get_order"}

    set_stdio_caller(
        CallerIdentity(
            key_id="k1",
            owner_id="o1",
            owner_label="test",
            scopes=["orders:*:read"],
            rate_limit_rpm=60,
            transport="stdio",
        )
    )
    result = await mcp.call_tool("orders_list_orders", {})
    assert isinstance(result, list)
    block = result[0]
    assert isinstance(block, types.TextContent)
    assert json.loads(block.text)["source"] == "openapi:orders"
    assert audit.calls[-1]["tool_name"] == "orders_list_orders"
