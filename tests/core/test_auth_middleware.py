"""Tests for the auth middleware's dual-path token routing.

Verifies that:

* Tokens prefixed with ``sk_live_`` go through the API-key resolver.
* Other tokens go through the JWT validator.
* Both produce the same ``CallerIdentity`` contract downstream.
* Missing / malformed / mis-prefixed tokens are rejected with 401.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
from mcp_core.auth.identity import CallerIdentity
from mcp_core.auth.jwt_validator import JWTValidationError
from mcp_core.middleware.auth import AuthMiddleware
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient


def _build_client(
    *,
    api_key_identity: CallerIdentity | None,
    jwt_validator: Any | None,
) -> TestClient:
    """Build a Starlette app with AuthMiddleware wired to mock dependencies."""

    async def echo(request: Request) -> JSONResponse:
        caller: CallerIdentity = request.state.caller
        return JSONResponse({"owner_id": caller.owner_id, "scopes": caller.scopes})

    resolver = AsyncMock()
    resolver.resolve = AsyncMock(return_value=api_key_identity)

    app = Starlette(routes=[Route("/mcp", echo, methods=["GET"])])
    app.add_middleware(
        AuthMiddleware,
        api_key_resolver=resolver,
        jwt_validator=jwt_validator,
    )
    return TestClient(app)


@pytest.fixture
def api_key_caller() -> CallerIdentity:
    return CallerIdentity(
        key_id="key_apikey",
        owner_id="usr_apikey",
        owner_label="API Key User",
        scopes=["gse:*:*"],
        rate_limit_rpm=120,
    )


@pytest.fixture
def jwt_caller() -> CallerIdentity:
    return CallerIdentity(
        key_id="jwt_xyz",
        owner_id="usr_jwt",
        owner_label="JWT User",
        scopes=["gse:live_prices:read"],
        rate_limit_rpm=120,
    )


def test_sk_live_prefix_uses_api_key_resolver(api_key_caller):
    """Tokens with the sk_live_ prefix go through APIKeyResolver."""
    client = _build_client(api_key_identity=api_key_caller, jwt_validator=None)
    response = client.get("/mcp", headers={"Authorization": "Bearer sk_live_abcdef123"})
    assert response.status_code == 200
    assert response.json()["owner_id"] == "usr_apikey"


def test_non_prefixed_token_routes_to_jwt_validator(jwt_caller):
    """Tokens without sk_live_ go through JWTValidator (not the API-key path)."""
    jwt_validator = AsyncMock()
    jwt_validator.validate = AsyncMock(return_value=jwt_caller)
    client = _build_client(api_key_identity=None, jwt_validator=jwt_validator)
    response = client.get("/mcp", headers={"Authorization": "Bearer eyJhbGciOi.payload.sig"})
    assert response.status_code == 200
    assert response.json()["owner_id"] == "usr_jwt"
    jwt_validator.validate.assert_awaited_once_with("eyJhbGciOi.payload.sig")


def test_jwt_validation_failure_returns_auth_failed():
    jwt_validator = AsyncMock()
    jwt_validator.validate = AsyncMock(side_effect=JWTValidationError("bad token"))
    client = _build_client(api_key_identity=None, jwt_validator=jwt_validator)
    response = client.get("/mcp", headers={"Authorization": "Bearer some.jwt.here"})
    assert response.status_code == 401
    body = response.json()
    assert body["error_code"] == "auth_failed"
    assert "bad token" in body["message"]


def test_jwt_token_without_configured_validator_is_rejected():
    """When JWT auth isn't configured, non-API-key tokens 401 cleanly."""
    client = _build_client(api_key_identity=None, jwt_validator=None)
    response = client.get("/mcp", headers={"Authorization": "Bearer eyJhbGciOi.payload.sig"})
    assert response.status_code == 401
    assert response.json()["error_code"] == "auth_failed"


def test_missing_header_returns_401():
    client = _build_client(api_key_identity=None, jwt_validator=None)
    response = client.get("/mcp")
    assert response.status_code == 401


def test_empty_bearer_returns_401():
    client = _build_client(api_key_identity=None, jwt_validator=None)
    response = client.get("/mcp", headers={"Authorization": "Bearer "})
    assert response.status_code == 401


def test_invalid_api_key_returns_401():
    """sk_live_ prefix but resolver returns None -> 401."""
    client = _build_client(api_key_identity=None, jwt_validator=None)
    # Fake fixture; our `sk_live_` prefix collides with Stripe's live-key regex.
    response = client.get(
        "/mcp",
        headers={"Authorization": "Bearer sk_live_doesnotexist"},  # gitleaks:allow
    )
    assert response.status_code == 401
    assert response.json()["error_code"] == "auth_failed"


def test_401_includes_www_authenticate_with_resource_metadata():
    """Spec-compliant MCP clients bootstrap from the WWW-Authenticate header.

    When JWT auth is configured, the header must include a
    `resource_metadata` parameter pointing at our protected-resource
    metadata endpoint so the client can discover the authorization server
    without out-of-band config.
    """
    jwt_validator = AsyncMock()
    client = _build_client(api_key_identity=None, jwt_validator=jwt_validator)
    response = client.get("/mcp")
    assert response.status_code == 401
    challenge = response.headers["www-authenticate"]
    assert challenge.startswith("Bearer ")
    assert 'realm="mcp"' in challenge
    assert "/.well-known/oauth-protected-resource" in challenge


def test_401_omits_resource_metadata_when_jwt_not_configured():
    """If JWT auth is off, there's no OAuth flow to discover; emit a bare
    Bearer challenge without resource_metadata."""
    client = _build_client(api_key_identity=None, jwt_validator=None)
    response = client.get("/mcp")
    assert response.status_code == 401
    challenge = response.headers["www-authenticate"]
    assert challenge.startswith("Bearer ")
    assert "resource_metadata" not in challenge
