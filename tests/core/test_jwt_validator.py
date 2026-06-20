"""Tests for :class:`pontifex_mcp.auth.jwt_validator.JWTValidator`.

A self-signed RSA keypair is generated once per module and exposed as both a
JWKS document (mocked via httpx) and a signer used to mint test JWTs.
"""

from __future__ import annotations

import json
import time
from typing import Any

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm
from pontifex_mcp.auth.jwt_validator import JWTValidationError, JWTValidator

_ISSUER = "https://issuer.example.com/"
_AUDIENCE = "mcp-platform"
_JWKS_URL = "https://issuer.example.com/.well-known/jwks.json"


@pytest.fixture(scope="module")
def signing_key():
    """Generate one RSA keypair for all tests in this module."""
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope="module")
def jwks_doc(signing_key):
    jwk = RSAAlgorithm.to_jwk(signing_key.public_key(), as_dict=True)
    jwk["kid"] = "test-key-1"
    return {"keys": [jwk]}


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
        return jwt.encode(claims, signing_key, algorithm="RS256", headers={"kid": "test-key-1"})

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
    token = jwt.encode(
        {
            "iss": _ISSUER,
            "aud": _AUDIENCE,
            "sub": "user_x",
            "exp": int(time.time()) + 600,
            "rate_limit_rpm": 999999,  # attacker tries to grant themselves more
        },
        signing_key,
        algorithm="RS256",
        headers={"kid": "test-key-1"},
    )
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
    token = jwt.encode(
        {
            "iss": _ISSUER,
            "aud": _AUDIENCE,
            "sub": "user_x",
            "exp": int(time.time()) + 600,
            "scp": "gse:live_prices:read",
        },
        signing_key,
        algorithm="RS256",
        headers={"kid": "test-key-1"},
    )
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
    rotated_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    rotated_pub_jwk = RSAAlgorithm.to_jwk(rotated_key.public_key(), as_dict=True)
    rotated_pub_jwk["kid"] = "test-key-2"

    # First response: old keyset only.  Second response: includes rotated key.
    responses = [
        {"keys": [jwks_doc["keys"][0]]},
        {"keys": [jwks_doc["keys"][0], rotated_pub_jwk]},
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

    token = jwt.encode(
        {
            "iss": _ISSUER,
            "aud": _AUDIENCE,
            "sub": "user_y",
            "exp": int(time.time()) + 600,
            "permissions": ["gse:*:read"],
        },
        rotated_key,
        algorithm="RS256",
        headers={"kid": "test-key-2"},
    )

    identity = await v.validate(token)
    assert identity.owner_id == "user_y"
    # First call hit the old keyset (1), then refetched (2).
    assert call_count["n"] == 2


@pytest.mark.asyncio
async def test_jwks_refreshed_when_key_rotated_in_place_under_same_kid(jwks_doc, signing_key):
    """A provider may rotate a signing key but reuse the same `kid`.  The token
    is then signed by a key whose `kid` IS in the cached set, but the cached key
    is stale, so the signature fails against it.  The validator must refetch and
    accept once the fresh key (same kid) is published."""
    new_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    new_pub_jwk = RSAAlgorithm.to_jwk(new_key.public_key(), as_dict=True)
    new_pub_jwk["kid"] = "test-key-1"  # SAME kid as the cached (old) key

    # First response: old key under kid test-key-1.  Second: new key, same kid.
    responses = [
        {"keys": [jwks_doc["keys"][0]]},
        {"keys": [new_pub_jwk]},
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

    token = jwt.encode(
        {
            "iss": _ISSUER,
            "aud": _AUDIENCE,
            "sub": "user_z",
            "exp": int(time.time()) + 600,
            "permissions": ["gse:*:read"],
        },
        new_key,
        algorithm="RS256",
        headers={"kid": "test-key-1"},
    )

    identity = await v.validate(token)
    assert identity.owner_id == "user_z"
    # Cached key found by kid but signature failed (1), refetched once (2).
    assert call_count["n"] == 2


def test_init_rejects_incomplete_config():
    with pytest.raises(ValueError):
        JWTValidator(jwks_url="", issuer="x", audience="y")
    with pytest.raises(ValueError):
        JWTValidator(jwks_url="x", issuer="", audience="y")
    with pytest.raises(ValueError):
        JWTValidator(jwks_url="x", issuer="y", audience="")
