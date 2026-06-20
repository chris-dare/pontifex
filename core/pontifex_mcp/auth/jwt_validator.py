"""OAuth 2.1 / OIDC JWT validation.

Validates Bearer JWTs against an external provider's JWKS endpoint and maps
the result to a :class:`CallerIdentity`.  Provider-agnostic: Auth0, Microsoft
Entra, Clerk, or any OIDC-compliant issuer works by changing env vars.

The validator handles:

* JWKS fetch with in-process caching (default 1 hour TTL).
* Single retry with cache bypass when the signing key is not in the cached
  keyset (covers key rotation).
* Standard claim validation: signature, ``exp``, ``iss``, ``aud``.
* Scope extraction from a configurable claim that may be either a
  space-delimited string (OAuth 2.0 ``scope`` style) or a JSON array
  (Auth0 ``permissions``, Entra ``roles``).
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any

import httpx
import jwt
import structlog
from jwt import PyJWK, PyJWKSet

from pontifex_mcp.auth.identity import CallerIdentity

_log = structlog.get_logger(__name__)

# Client-facing message for any token rejection.  Specific reasons are logged
# server-side so we don't hand an attacker a validation oracle.
_INVALID_TOKEN_MSG = "Invalid or expired token."

# Asymmetric algorithms only — HMAC excluded so a stolen JWKS cannot be used
# to forge HS256 tokens.
_ALLOWED_ALGORITHMS = frozenset(["RS256", "RS384", "RS512", "ES256", "ES384", "PS256"])


class JWTValidationError(Exception):
    """Raised when a JWT cannot be validated.

    The ``message`` is suitable for surfacing in the auth error response.
    """


@dataclass
class _CachedJWKS:
    keyset: PyJWKSet
    fetched_at: float


class JWTValidator:
    """Validate OAuth 2.1 JWTs against an external JWKS endpoint."""

    def __init__(
        self,
        jwks_url: str,
        issuer: str,
        audience: str,
        scopes_claim: str = "permissions",
        cache_ttl_seconds: int = 3600,
        default_rate_limit_rpm: int = 120,
        http_client: httpx.AsyncClient | None = None,
        transport: str = "http",
    ) -> None:
        if not jwks_url or not issuer or not audience:
            raise ValueError("JWTValidator requires jwks_url, issuer, and audience to be set.")
        self.jwks_url = jwks_url
        self.issuer = issuer
        self.audience = audience
        self.scopes_claim = scopes_claim
        self.cache_ttl = cache_ttl_seconds
        # Server-side default; the rate limit is NOT read from the token, so a
        # caller can't raise their own ceiling via a forged claim.
        self.default_rate_limit_rpm = default_rate_limit_rpm
        self._http = http_client or httpx.AsyncClient(timeout=5.0)
        self._owns_http = http_client is None
        self._cache: _CachedJWKS | None = None
        self._cache_lock = asyncio.Lock()
        self._transport = transport
        self._algorithms = list(_ALLOWED_ALGORITHMS)

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    async def validate(self, raw_token: str) -> CallerIdentity:
        """Validate ``raw_token`` and return a :class:`CallerIdentity`.

        Raises :class:`JWTValidationError` if the token is invalid for any
        reason (bad signature, expired, wrong issuer/audience, malformed).
        """
        try:
            header = jwt.get_unverified_header(raw_token)
        except jwt.InvalidTokenError as exc:
            _log.warning("jwt_malformed", error=str(exc))
            raise JWTValidationError(_INVALID_TOKEN_MSG) from exc

        alg = header.get("alg", "")
        if alg not in _ALLOWED_ALGORITHMS:
            _log.warning("jwt_disallowed_alg", alg=alg)
            raise JWTValidationError(_INVALID_TOKEN_MSG)

        kid = header.get("kid")
        claims = await self._resolve_and_decode(raw_token, kid)

        scopes = _extract_scopes(claims, self.scopes_claim)
        owner_id = str(claims.get("sub") or "")
        if not owner_id:
            _log.warning("jwt_missing_sub")
            raise JWTValidationError(_INVALID_TOKEN_MSG)

        owner_label = str(
            claims.get("name") or claims.get("email") or claims.get("client_id") or owner_id
        )
        # For JWTs, use the JWT ID if provided, otherwise a stable prefix of
        # the subject.  Used in audit logs.
        key_id = str(claims.get("jti") or f"jwt_{owner_id}")

        return CallerIdentity(
            key_id=key_id,
            owner_id=owner_id,
            owner_label=owner_label,
            scopes=scopes,
            rate_limit_rpm=self.default_rate_limit_rpm,
            transport=self._transport,
        )

    async def _resolve_and_decode(self, raw_token: str, kid: str | None) -> dict[str, Any]:
        """Find the signing key by ``kid`` and verify ``raw_token`` against it.

        Refetches the JWKS once — on either a missing key or a signature
        failure — to cover key rotation, including a key rotated in place under
        a reused ``kid``.  Claim failures (exp/iss/aud) are not retried, since a
        fresh keyset can't fix them.  Every failure raises the generic error.
        """
        keyset = await self._get_keyset(force_refresh=False)
        refreshed = False
        while True:
            pyjwk = _find_key(keyset, kid)
            if pyjwk is not None:
                try:
                    return jwt.decode(
                        raw_token,
                        key=pyjwk.key,
                        algorithms=self._algorithms,
                        audience=self.audience,
                        issuer=self.issuer,
                        leeway=0,
                        options={
                            "require": ["exp", "sub"],
                            "verify_aud": True,
                            "verify_iss": True,
                            "verify_exp": True,
                        },
                    )
                except jwt.InvalidSignatureError as exc:
                    # The cached key may be stale (rotated in place); refetch once.
                    if refreshed:
                        _log.warning("jwt_signature_invalid", error=str(exc))
                        raise JWTValidationError(_INVALID_TOKEN_MSG) from exc
                except jwt.InvalidTokenError as exc:
                    # exp/iss/aud/malformed — a fresh keyset won't help.
                    _log.warning("jwt_validation_failed", error=str(exc))
                    raise JWTValidationError(_INVALID_TOKEN_MSG) from exc
            elif refreshed:
                _log.warning("jwt_unknown_kid", kid=kid)
                raise JWTValidationError(_INVALID_TOKEN_MSG)

            keyset = await self._get_keyset(force_refresh=True)
            refreshed = True

    async def _get_keyset(self, *, force_refresh: bool) -> PyJWKSet:
        async with self._cache_lock:
            cached = self._cache
            fresh = (
                cached is not None
                and not force_refresh
                and (time.time() - cached.fetched_at) < self.cache_ttl
            )
            if fresh and cached is not None:
                return cached.keyset

            response = await self._http.get(self.jwks_url)
            response.raise_for_status()
            keyset = PyJWKSet.from_dict(response.json())
            self._cache = _CachedJWKS(keyset=keyset, fetched_at=time.time())
            return keyset


def _find_key(keyset: PyJWKSet, kid: str | None) -> PyJWK | None:
    for k in keyset.keys:
        if k.key_id == kid:
            return k
    # No kid in token header — fall back to the only key if the set is unambiguous.
    if kid is None and len(keyset.keys) == 1:
        return keyset.keys[0]
    return None


def _extract_scopes(claims: dict[str, Any], claim_name: str) -> list[str]:
    """Pull scopes from ``claims[claim_name]``, accepting str or list shapes.

    OAuth 2.0 ``scope`` is space-delimited; Auth0 ``permissions`` and Entra
    ``roles`` are JSON arrays.  Returns ``[]`` if the claim is missing or
    empty — scope enforcement happens downstream in tool handlers.
    """
    value = claims.get(claim_name)
    if value is None:
        return []
    if isinstance(value, str):
        return [s for s in value.split() if s]
    if isinstance(value, list):
        return [str(s) for s in value if s]
    return []
