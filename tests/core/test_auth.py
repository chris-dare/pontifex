from pontifex_mcp.auth.api_keys import hash_key
from pontifex_mcp.auth.identity import CallerIdentity


def test_hash_key_is_sha256_hex():
    h = hash_key("sk_live_abc")
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)


def test_hash_key_is_deterministic():
    assert hash_key("x") == hash_key("x")


def test_caller_identity_can_use_tool():
    c = CallerIdentity(
        key_id="k1",
        owner_id="o1",
        owner_label="Test",
        scopes=["gse:live_prices:read"],
        rate_limit_rpm=60,
    )
    assert c.can_use_tool("gse", "live_prices", "read")
    assert not c.can_use_tool("gse", "stock_history", "read")
