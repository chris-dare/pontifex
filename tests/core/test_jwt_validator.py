"""Tests for :class:`pontifex_mcp.auth.jwt_validator.JWTValidator`.

A self-signed RSA keypair is generated once per module and exposed as both a
JWKS document (mocked via httpx) and a signer used to mint test JWTs.
"""

from __future__ import annotations

import json
import time
from typing import Any

import httpx
import pytest
from authlib.jose import JsonWebKey, jwt
from pontifex_mcp.auth.jwt_validator import JWTValidationError, JWTValidator

_ISSUER = "https://issuer.example.com/"
_AUDIENCE = "mcp-platform"
_JWKS_URL = "https://issuer.example.com/.well-known/jwks.json"


@pytest.fixture(scope="module")
def signing_key():
    """Generate one RSA keypair for all tests in this module."""
    return JsonWebKey.generate_key("RSA", 2048, options={"kid": "test-key-1"}, is_private=True)


@pytest.fixture(scope="module")
def jwks_doc(signing_key):
    return {"keys": [signing_key.as_dict(is_private=False)]}


@pytest.fixture
def make_token(signing_key):
    """Mint a JWT signed with the module's RSA key."""

    def _mint(claims_override: dict[str, Any] | None = None) -> str:
        now = int(time.time())
        claims: dict[str, Any] = {
            "iss": _ISSUER,
            "aud": _AUDIENCE,
            "sub": "user_kwame",
            "exp": now + 600,
            "nbf": now - 5,
            "iat": now,
            "permissions": ["gse:live_prices:read", "gse:market_summary:read"],
        }
        if claims_override is not None:
            claims.update(claims_override)
        header = {"alg": "RS256", "kid": "test-key-1"}
        token = jwt.encode(header, claims, signing_key)
        return token.decode() if isinstance(token, bytes) else token

    return _mint


@pytest.fixture
def validator(jwks_doc):
    """Build a JWTValidator wired to a mock JWKS endpoint."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == _JWKS_URL
        return httpx.Response(200, json=jwks_doc)

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    v = JWTValidator(
        jwks_url=_JWKS_URL,
        issuer=_ISSUER,
        audience=_AUDIENCE,
        scopes_claim="permissions",
        http_client=client,
    )
    yield v


@pytest.mark.asyncio
async def test_validates_well_formed_token(validator, make_token):
    identity = await validator.validate(make_token())
    assert identity.owner_id == "user_kwame"
    assert identity.scopes == ["gse:live_prices:read", "gse:market_summary:read"]
    assert identity.transport == "http"


@pytest.mark.asyncio
async def test_rate_limit_is_server_default_not_from_token(jwks_doc, signing_key):
    """The rate limit comes from the server-configured default, never the token
    — a caller can't raise their own ceiling with a forged claim."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=jwks_doc)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    v = JWTValidator(
        jwks_url=_JWKS_URL,
        issuer=_ISSUER,
        audience=_AUDIENCE,
        scopes_claim="permissions",
        default_rate_limit_rpm=42,
        http_client=client,
    )
    now = int(time.time())
    header = {"alg": "RS256", "kid": "test-key-1"}
    token = jwt.encode(
        header,
        {
            "iss": _ISSUER,
            "aud": _AUDIENCE,
            "sub": "user_x",
            "exp": now + 600,
            "rate_limit_rpm": 999999,  # attacker tries to grant themselves more
        },
        signing_key,
    )
    if isinstance(token, bytes):
        token = token.decode()
    identity = await v.validate(token)
    assert identity.rate_limit_rpm == 42  # server default wins, token claim ignored


@pytest.mark.asyncio
async def test_rejection_message_is_generic(validator, make_token):
    """Rejections return a single generic message — no validation oracle."""
    token = make_token({"exp": int(time.time()) - 10})  # expired
    with pytest.raises(JWTValidationError) as exc:
        await validator.validate(token)
    assert str(exc.value) == "Invalid or expired token."


@pytest.mark.asyncio
async def test_extracts_scopes_from_string_claim(validator, make_token):
    token = make_token({"permissions": "gse:live_prices:read gse:stock_price:read"})
    identity = await validator.validate(token)
    assert identity.scopes == ["gse:live_prices:read", "gse:stock_price:read"]


@pytest.mark.asyncio
async def test_extracts_scopes_from_array_claim(validator, make_token):
    token = make_token({"permissions": ["gse:*:read"]})
    identity = await validator.validate(token)
    assert identity.scopes == ["gse:*:read"]


@pytest.mark.asyncio
async def test_missing_scope_claim_yields_empty_scopes(validator, make_token):
    token = make_token({"permissions": None})
    identity = await validator.validate(token)
    assert identity.scopes == []


@pytest.mark.asyncio
async def test_configurable_claim_name(jwks_doc, signing_key):
    """Provider-agnostic: claim name comes from config (Entra uses 'scp')."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=jwks_doc)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    v = JWTValidator(
        jwks_url=_JWKS_URL,
        issuer=_ISSUER,
        audience=_AUDIENCE,
        scopes_claim="scp",
        http_client=client,
    )
    now = int(time.time())
    header = {"alg": "RS256", "kid": "test-key-1"}
    token = jwt.encode(
        header,
        {
            "iss": _ISSUER,
            "aud": _AUDIENCE,
            "sub": "user_x",
            "exp": now + 600,
            "scp": "gse:live_prices:read",
        },
        signing_key,
    )
    if isinstance(token, bytes):
        token = token.decode()
    identity = await v.validate(token)
    assert identity.scopes == ["gse:live_prices:read"]


@pytest.mark.asyncio
async def test_rejects_expired_token(validator, make_token):
    token = make_token({"exp": int(time.time()) - 10})
    with pytest.raises(JWTValidationError):
        await validator.validate(token)


@pytest.mark.asyncio
async def test_rejects_wrong_issuer(validator, make_token):
    token = make_token({"iss": "https://attacker.example.com/"})
    with pytest.raises(JWTValidationError):
        await validator.validate(token)


@pytest.mark.asyncio
async def test_rejects_wrong_audience(validator, make_token):
    token = make_token({"aud": "some-other-api"})
    with pytest.raises(JWTValidationError):
        await validator.validate(token)


@pytest.mark.asyncio
async def test_rejects_missing_sub(validator, make_token):
    token = make_token({"sub": ""})
    with pytest.raises(JWTValidationError):
        await validator.validate(token)


@pytest.mark.asyncio
async def test_rejects_garbage_token(validator):
    with pytest.raises(JWTValidationError):
        await validator.validate("not.a.jwt")


@pytest.mark.asyncio
async def test_rejects_unsigned_alg_none_token(validator):
    """A token claiming alg=none must never pass validation, even if its
    payload looks correct.  Defends against the classic 'alg: none' attack."""
    import base64

    def _b64(obj: dict[str, Any]) -> str:
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).rstrip(b"=").decode()

    header = _b64({"alg": "none", "typ": "JWT"})
    payload = _b64(
        {
            "iss": _ISSUER,
            "aud": _AUDIENCE,
            "sub": "user_attacker",
            "exp": int(time.time()) + 600,
        }
    )
    token = f"{header}.{payload}."
    with pytest.raises(JWTValidationError):
        await validator.validate(token)


@pytest.mark.asyncio
async def test_jwks_refreshed_on_key_rotation(jwks_doc, signing_key):
    """When a token is signed by a rotated key, the validator should refetch
    JWKS and accept the token if the new key is now present."""
    rotated_key = JsonWebKey.generate_key(
        "RSA", 2048, options={"kid": "test-key-2"}, is_private=True
    )

    # First response: old keyset only.  Second response: includes rotated key.
    responses = [
        {"keys": [signing_key.as_dict(is_private=False)]},
        {
            "keys": [
                signing_key.as_dict(is_private=False),
                rotated_key.as_dict(is_private=False),
            ]
        },
    ]
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        idx = min(call_count["n"], len(responses) - 1)
        call_count["n"] += 1
        return httpx.Response(200, json=responses[idx])

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    v = JWTValidator(
        jwks_url=_JWKS_URL,
        issuer=_ISSUER,
        audience=_AUDIENCE,
        scopes_claim="permissions",
        http_client=client,
    )

    now = int(time.time())
    header = {"alg": "RS256", "kid": "test-key-2"}
    token = jwt.encode(
        header,
        {
            "iss": _ISSUER,
            "aud": _AUDIENCE,
            "sub": "user_y",
            "exp": now + 600,
            "permissions": ["gse:*:read"],
        },
        rotated_key,
    )
    if isinstance(token, bytes):
        token = token.decode()

    identity = await v.validate(token)
    assert identity.owner_id == "user_y"
    # First call hit the old keyset (1), then refetched (2).
    assert call_count["n"] == 2


def test_init_rejects_incomplete_config():
    with pytest.raises(ValueError):
        JWTValidator(jwks_url="", issuer="x", audience="y")
    with pytest.raises(ValueError):
        JWTValidator(jwks_url="x", issuer="", audience="y")
    with pytest.raises(ValueError):
        JWTValidator(jwks_url="x", issuer="y", audience="")
