from mcp_core.auth.scopes import scopes_match


def test_full_wildcard():
    assert scopes_match(["gse:*:*"], "gse", "live_prices", "read")


def test_resource_wildcard_action_specific():
    assert scopes_match(["gse:*:read"], "gse", "live_prices", "read")
    assert not scopes_match(["gse:*:read"], "gse", "price_alert", "write")


def test_action_wildcard():
    assert scopes_match(["gse:live_prices:*"], "gse", "live_prices", "read")
    assert scopes_match(["gse:live_prices:*"], "gse", "live_prices", "write")


def test_exact_match():
    assert scopes_match(["gse:stock_history:read"], "gse", "stock_history", "read")
    assert not scopes_match(["gse:stock_history:read"], "gse", "live_prices", "read")


def test_no_match_returns_false():
    assert not scopes_match([], "gse", "live_prices", "read")
    assert not scopes_match(["gfi:bond_yields:read"], "gse", "live_prices", "read")


def test_case_insensitive():
    assert scopes_match(["GSE:*:READ"], "gse", "live_prices", "read")
    assert scopes_match(["gse:*:*"], "GSE", "Live_Prices", "READ")
