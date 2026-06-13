"""Token-exchange strategy + in-memory token cache (RFC 8693, issue #41)."""

import asyncio
import base64
import json

import httpx
import pytest
import respx
from pontifex_mcp.connectors.adapter import ConnectorUnavailable
from pontifex_mcp.connectors.auth import AuthContext
from pontifex_mcp.connectors.token_exchange import (
    InMemoryTokenCache,
    TokenExchange,
    TokenExchangeRejected,
    _Secret,
)
from pontifex_mcp.utils.circuit_breaker import CircuitBreaker

IDP = "https://idp.test/oauth/token"
AUDIENCE = "https://api.internal"


def _jwt_with_aud(aud) -> str:
    payload = base64.urlsafe_b64encode(json.dumps({"aud": aud}).encode()).rstrip(b"=").decode()
    return f"header.{payload}.sig"


def _make(monkeypatch, *, clock=None, breaker=None, cache=None) -> TokenExchange:
    monkeypatch.setenv("PONTIFEX_OAUTH_CLIENT_ID", "pontifex-client")
    monkeypatch.setenv("PONTIFEX_OAUTH_CLIENT_SECRET", "shhh")
    # Always inject an in-memory cache so the test never falls through to
    # default_token_cache() (which reads PONTIFEX_TOKEN_CACHE from the shell).
    if cache is None:
        cache = InMemoryTokenCache(clock=clock) if clock is not None else InMemoryTokenCache()
    return TokenExchange(
        token_endpoint=IDP,
        audience=AUDIENCE,
        client_id_env="PONTIFEX_OAUTH_CLIENT_ID",
        client_secret_env="PONTIFEX_OAUTH_CLIENT_SECRET",
        cache=cache,
        breaker=breaker,
    )


# --- secret wrapper ----------------------------------------------------------


def test_secret_never_reveals_in_str_or_repr():
    s = _Secret("super-secret-token")
    assert "super-secret-token" not in repr(s)
    assert "super-secret-token" not in str(s)
    assert "super-secret-token" not in f"{s}"
    assert s.reveal() == "super-secret-token"


# --- construction ------------------------------------------------------------


async def test_adapter_close_cascades_to_token_exchange(monkeypatch):
    """Closing the connector adapter on shutdown also closes the TokenExchange
    HTTP client, so no client is leaked."""
    from pontifex_mcp.connectors.adapter import OpenAPIAdapter

    te = _make(monkeypatch)
    adapter = OpenAPIAdapter(domain="billing", base_url="https://api.test", auth=te)
    await adapter.close()
    assert adapter._client.is_closed
    assert te._client.is_closed


def test_missing_client_creds_fails_at_construction(monkeypatch):
    monkeypatch.delenv("PONTIFEX_OAUTH_CLIENT_ID", raising=False)
    monkeypatch.setenv("PONTIFEX_OAUTH_CLIENT_SECRET", "shhh")
    with pytest.raises(ValueError, match="PONTIFEX_OAUTH_CLIENT_ID"):
        TokenExchange(
            token_endpoint=IDP,
            audience=AUDIENCE,
            client_id_env="PONTIFEX_OAUTH_CLIENT_ID",
            client_secret_env="PONTIFEX_OAUTH_CLIENT_SECRET",
        )


# --- happy path + caching ----------------------------------------------------


@respx.mock
async def test_exchange_success_and_caches(monkeypatch):
    route = respx.post(IDP).mock(
        return_value=httpx.Response(200, json={"access_token": "downstream-tok", "expires_in": 300})
    )
    te = _make(monkeypatch)
    ctx = AuthContext(subject_token="user-jwt")

    h1 = await te.headers(ctx)
    h2 = await te.headers(ctx)  # second call served from cache

    assert h1 == {"Authorization": "Bearer downstream-tok"}
    assert h2 == h1
    assert route.call_count == 1  # cached → only one exchange

    # The exchange request was a proper RFC 8693 grant with client creds.
    sent = route.calls.last.request
    body = sent.content.decode()
    assert "grant_type=urn%3Aietf%3Aparams%3Aoauth%3Agrant-type%3Atoken-exchange" in body
    assert "subject_token=user-jwt" in body
    assert "client_secret=shhh" in body


@respx.mock
async def test_no_subject_token_returns_empty_no_call(monkeypatch):
    route = respx.post(IDP).mock(return_value=httpx.Response(200, json={}))
    te = _make(monkeypatch)
    assert await te.headers(AuthContext(subject_token=None)) == {}
    assert route.call_count == 0  # health check path makes no exchange


@respx.mock
async def test_cache_expiry_triggers_reexchange(monkeypatch):
    route = respx.post(IDP).mock(
        return_value=httpx.Response(200, json={"access_token": "tok", "expires_in": 100})
    )
    now = [1000.0]
    te = _make(monkeypatch, clock=lambda: now[0])
    ctx = AuthContext(subject_token="user-jwt")

    await te.headers(ctx)
    now[0] += 50  # still within TTL (100 - 30 skew = 70)
    await te.headers(ctx)
    assert route.call_count == 1
    now[0] += 50  # now past TTL
    await te.headers(ctx)
    assert route.call_count == 2


@respx.mock
async def test_single_flight_coalesces_concurrent_misses(monkeypatch):
    route = respx.post(IDP).mock(
        return_value=httpx.Response(200, json={"access_token": "tok", "expires_in": 300})
    )
    te = _make(monkeypatch)
    ctx = AuthContext(subject_token="user-jwt")

    results = await asyncio.gather(*(te.headers(ctx) for _ in range(5)))
    assert all(r == {"Authorization": "Bearer tok"} for r in results)
    assert route.call_count == 1  # five concurrent misses → one exchange


# --- cache key separation ----------------------------------------------------


@respx.mock
async def test_distinct_callers_get_distinct_tokens(monkeypatch):
    tokens = iter(["tok-a", "tok-b"])
    route = respx.post(IDP).mock(
        side_effect=lambda req: httpx.Response(
            200, json={"access_token": next(tokens), "expires_in": 300}
        )
    )
    te = _make(monkeypatch)
    a = await te.headers(AuthContext(subject_token="jwt-alice"))
    b = await te.headers(AuthContext(subject_token="jwt-bob"))
    assert a == {"Authorization": "Bearer tok-a"}
    assert b == {"Authorization": "Bearer tok-b"}
    assert route.call_count == 2


# --- audience verification ---------------------------------------------------


@respx.mock
async def test_audience_mismatch_rejected(monkeypatch):
    respx.post(IDP).mock(
        return_value=httpx.Response(
            200, json={"access_token": _jwt_with_aud("https://other.api"), "expires_in": 300}
        )
    )
    te = _make(monkeypatch)
    with pytest.raises(TokenExchangeRejected, match="audience mismatch"):
        await te.headers(AuthContext(subject_token="user-jwt"))


@respx.mock
async def test_matching_aud_jwt_accepted(monkeypatch):
    token = _jwt_with_aud([AUDIENCE, "other"])
    respx.post(IDP).mock(
        return_value=httpx.Response(200, json={"access_token": token, "expires_in": 300})
    )
    te = _make(monkeypatch)
    h = await te.headers(AuthContext(subject_token="user-jwt"))
    assert h == {"Authorization": f"Bearer {token}"}


# --- failure mapping ---------------------------------------------------------


@respx.mock
async def test_idp_5xx_is_unavailable_and_trips_breaker(monkeypatch):
    respx.post(IDP).mock(return_value=httpx.Response(503))
    breaker = CircuitBreaker(name="t", failure_threshold=1, recovery_timeout=30.0)
    te = _make(monkeypatch, breaker=breaker)
    with pytest.raises(ConnectorUnavailable):
        await te.headers(AuthContext(subject_token="user-jwt"))
    assert breaker.failure_count == 1
    assert breaker.is_available is False  # threshold 1 → now open


@respx.mock
async def test_idp_4xx_is_rejected_without_tripping_breaker(monkeypatch):
    respx.post(IDP).mock(return_value=httpx.Response(400, json={"error": "invalid_grant"}))
    breaker = CircuitBreaker(name="t", failure_threshold=1, recovery_timeout=30.0)
    te = _make(monkeypatch, breaker=breaker)
    with pytest.raises(TokenExchangeRejected):
        await te.headers(AuthContext(subject_token="user-jwt"))
    assert breaker.failure_count == 0  # caller problem, not an outage
    assert breaker.is_available is True


@respx.mock
async def test_open_breaker_fails_fast_without_calling_idp(monkeypatch):
    route = respx.post(IDP).mock(return_value=httpx.Response(200, json={}))
    breaker = CircuitBreaker(name="t", failure_threshold=1, recovery_timeout=30.0)
    breaker.record_failure()  # force open
    te = _make(monkeypatch, breaker=breaker)
    with pytest.raises(ConnectorUnavailable, match="circuit open"):
        await te.headers(AuthContext(subject_token="user-jwt"))
    assert route.call_count == 0


@respx.mock
async def test_missing_expires_in_rejected(monkeypatch):
    respx.post(IDP).mock(return_value=httpx.Response(200, json={"access_token": "tok"}))
    te = _make(monkeypatch)
    with pytest.raises(TokenExchangeRejected, match="expires_in"):
        await te.headers(AuthContext(subject_token="user-jwt"))


@respx.mock
async def test_missing_expires_in_uses_default_ttl_when_configured(monkeypatch):
    # A spec-compliant provider may omit expires_in (it's OPTIONAL in RFC 8693);
    # an opt-in default_ttl lets such a provider work instead of failing closed.
    route = respx.post(IDP).mock(return_value=httpx.Response(200, json={"access_token": "tok"}))
    monkeypatch.setenv("PONTIFEX_OAUTH_CLIENT_ID", "c")
    monkeypatch.setenv("PONTIFEX_OAUTH_CLIENT_SECRET", "s")
    te = TokenExchange(
        token_endpoint=IDP,
        audience=AUDIENCE,
        client_id_env="PONTIFEX_OAUTH_CLIENT_ID",
        client_secret_env="PONTIFEX_OAUTH_CLIENT_SECRET",
        default_ttl_seconds=120,
    )
    h = await te.headers(AuthContext(subject_token="user-jwt"))
    assert h == {"Authorization": "Bearer tok"}
    # Cached for the fallback TTL → a second call doesn't re-exchange.
    await te.headers(AuthContext(subject_token="user-jwt"))
    assert route.call_count == 1


@respx.mock
async def test_client_secret_basic_sends_authorization_header(monkeypatch):
    route = respx.post(IDP).mock(
        return_value=httpx.Response(200, json={"access_token": "tok", "expires_in": 300})
    )
    monkeypatch.setenv("PONTIFEX_OAUTH_CLIENT_ID", "my-client")
    monkeypatch.setenv("PONTIFEX_OAUTH_CLIENT_SECRET", "my-secret")
    te = TokenExchange(
        token_endpoint=IDP,
        audience=AUDIENCE,
        client_id_env="PONTIFEX_OAUTH_CLIENT_ID",
        client_secret_env="PONTIFEX_OAUTH_CLIENT_SECRET",
        client_auth="basic",
    )
    await te.headers(AuthContext(subject_token="user-jwt"))
    req = route.calls.last.request
    expected = "Basic " + base64.b64encode(b"my-client:my-secret").decode()
    assert req.headers["Authorization"] == expected
    # Creds go in the header, not the body.
    assert "client_secret" not in req.content.decode()


def test_invalid_client_auth_rejected(monkeypatch):
    monkeypatch.setenv("PONTIFEX_OAUTH_CLIENT_ID", "c")
    monkeypatch.setenv("PONTIFEX_OAUTH_CLIENT_SECRET", "s")
    with pytest.raises(ValueError, match="client_auth"):
        TokenExchange(
            token_endpoint=IDP,
            audience=AUDIENCE,
            client_id_env="PONTIFEX_OAUTH_CLIENT_ID",
            client_secret_env="PONTIFEX_OAUTH_CLIENT_SECRET",
            client_auth="mtls",
        )


# --- cache LRU bound ---------------------------------------------------------


async def test_cache_evicts_lru_beyond_bound():
    cache = InMemoryTokenCache(max_entries=2)

    async def loader_for(val):
        async def _load():
            return val, 300

        return _load

    await cache.get_or_load("k1", await loader_for("v1"))
    await cache.get_or_load("k2", await loader_for("v2"))
    await cache.get_or_load("k1", await loader_for("WONT-RUN"))  # touch k1 → MRU
    await cache.get_or_load("k3", await loader_for("v3"))  # evicts k2 (LRU)

    calls = {"n": 0}

    async def reload_k2():
        calls["n"] += 1
        return "v2-again", 300

    await cache.get_or_load("k2", reload_k2)
    assert calls["n"] == 1  # k2 was evicted → had to reload
