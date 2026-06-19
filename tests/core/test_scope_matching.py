from pontifex_mcp.auth.identity import CallerIdentity, anonymous_identity
from pontifex_mcp.auth.scopes import scopes_match


def test_full_wildcard():
    assert scopes_match(["gse:*:*"], "gse", "live_prices", "read")


def test_bare_star_is_not_a_global_wildcard():
    """A literal `*` scope grants nothing — open access is via the anonymous
    flag, not a scope string, so a `*` on a real credential is inert."""
    assert not scopes_match(["*"], "gse", "live_prices", "read")
    assert not scopes_match(["*"], "payments", "refunds", "execute")


def test_anonymous_identity_bypasses_scope_check():
    assert anonymous_identity().can_use_tool("payments", "refunds", "execute")


def test_star_scope_on_non_anonymous_identity_is_denied():
    """Fail-closed: a provisioned caller carrying `*` (e.g. from a JWT claim or
    a DB row) does NOT get blanket access — only `anonymous=True` does."""
    caller = CallerIdentity(
        key_id="k", owner_id="o", owner_label="L", scopes=["*"], anonymous=False
    )
    assert not caller.can_use_tool("payments", "refunds", "execute")


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
