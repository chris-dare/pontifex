"""Integration test for token-exchange connectors against a real Keycloak.

Runs inside the compose network so issuer URLs are consistent. Flow:
  1. ROPC (no browser) to mint a user's access token from Keycloak.
  2. Negative control: that token sent straight to the downstream → 403
     (wrong audience) — proves passthrough doesn't work and exchange is needed.
  3. Real MCP client → Pontifex /mcp with the user token → Pontifex exchanges it
     (RFC 8693) → downstream accepts the delegated token and returns the user's
     own data.
  4. A second user proves per-user delegation.
  5. No-token request to Pontifex → 401.
"""

import asyncio
import json
import os
import sys
import time

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

KC = os.environ["KEYCLOAK_URL"]
PONTIFEX = os.environ["PONTIFEX_URL"]
DOWNSTREAM = os.environ["DOWNSTREAM_URL"]
TOKEN_EP = f"{KC}/realms/pontifex/protocol/openid-connect/token"

_results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    _results.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"\n        {detail}" if detail else ""))


def ropc(user: str) -> str:
    r = httpx.post(
        TOKEN_EP,
        data={
            "grant_type": "password",
            "client_id": "mcp-cli",
            "username": user,
            "password": user,
            "scope": "openid",
        },
        timeout=10.0,
    )
    r.raise_for_status()
    return r.json()["access_token"]


def wait_for_keycloak() -> bool:
    for _ in range(60):
        try:
            ropc("alice")
            return True
        except Exception:
            time.sleep(2)
    return False


def downstream_status(token: str) -> int:
    """Hit the downstream directly with the given token (passthrough check)."""
    r = httpx.get(
        f"{DOWNSTREAM}/invoices",
        headers={"Authorization": f"Bearer {token}"},
        timeout=10.0,
    )
    return r.status_code


def pontifex_no_auth_status() -> int:
    """Hit Pontifex /mcp with no credential."""
    r = httpx.post(
        f"{PONTIFEX}/mcp",
        headers={
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        },
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        timeout=10.0,
    )
    return r.status_code


async def call_tool(token: str | None, name: str, args: dict):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    async with streamablehttp_client(f"{PONTIFEX}/mcp", headers=headers) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            return await session.call_tool(name, args)


def tool_body(result) -> dict:
    return json.loads(result.content[0].text)


async def latest_audit_delegation(tool_name: str) -> str | None:
    """Read delegated_audience from the most recent audit row for a tool —
    proves the delegation is queryable in the real audit table, not just logged."""
    import asyncpg

    conn = await asyncpg.connect(os.environ["PG_DSN"])
    try:
        return await conn.fetchval(
            "select delegated_audience from core.audit_log "
            "where tool_name = $1 order by id desc limit 1",
            tool_name,
        )
    finally:
        await conn.close()


async def main() -> None:
    if not wait_for_keycloak():
        check("keycloak reachable via ROPC", False, "timed out after 120s")
        _finish()
    check("keycloak reachable via ROPC", True)

    alice = ropc("alice")
    bob = ropc("bob")

    # Negative control: the user's own token has aud=pontifex, not billing-api.
    status = downstream_status(alice)
    check(
        "passthrough user token rejected by downstream (403)",
        status == 403,
        f"status={status} (proves exchange is required, not passthrough)",
    )

    # Happy path: Pontifex exchanges alice's token for a billing-api token.
    res = await call_tool(alice, "billing_list_invoices", {})
    b = tool_body(res)
    ok = (
        not res.isError
        and b.get("status_code") == 200
        and b.get("data", {}).get("sub") == "alice"
        and b.get("data", {}).get("invoices", [{}])[0].get("id") == "INV-1"
    )
    check("alice: token exchange → downstream returns alice's invoice", ok, json.dumps(b)[:300])

    # Per-user delegation: bob gets bob's data via his own exchanged token.
    res = await call_tool(bob, "billing_list_invoices", {})
    b = tool_body(res)
    ok = (
        not res.isError
        and b.get("data", {}).get("sub") == "bob"
        and b.get("data", {}).get("invoices", [{}])[0].get("id") == "INV-9"
    )
    check("bob: distinct user → bob's invoice (per-user delegation)", ok, json.dumps(b)[:300])

    # The delegation is recorded in the real audit table (#45), audience only.
    audience = await latest_audit_delegation("billing_list_invoices")
    check(
        "audit row records the delegation (billing-api)",
        audience == "billing-api",
        f"delegated_audience={audience!r}",
    )

    # No credential to Pontifex → AuthMiddleware rejects before MCP.
    status = pontifex_no_auth_status()
    check("no-token request to Pontifex rejected (401)", status == 401, f"status={status}")

    _finish()


def _finish() -> None:
    failed = [r for r in _results if not r[1]]
    print(f"\n{'=' * 52}\n{len(_results) - len(failed)}/{len(_results)} checks passed")
    sys.exit(1 if failed else 0)


asyncio.run(main())
