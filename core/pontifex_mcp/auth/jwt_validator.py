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
import structlog
from authlib.jose import JsonWebKey, JsonWebToken
from authlib.jose.errors import JoseError

from pontifex_mcp.auth.identity import CallerIdentity

_log = structlog.get_logger(__name__)

# Client-facing message for any token rejection.  Specific reasons (bad
# signature, wrong issuer, expired, …) are logged server-side, not returned,
# so we don't hand an attacker a validation oracle.
_INVALID_TOKEN_MSG = "Invalid or expired token."


class JWTValidationError(Exception):
    """Raised when a JWT cannot be validated.

    The ``message`` is suitable for surfacing in the auth error response.
    """


@dataclass
class _CachedJWKS:
    keyset: Any  # authlib.jose.JsonWebKey-like (KeySet)
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
        # RS256 is the OIDC default; ES256 and PS256 are also common.  We
        # accept all asymmetric algorithms but never the HMAC family — those
        # would let a stolen JWKS doc be used to forge tokens.
        self._jwt = JsonWebToken(["RS256", "RS384", "RS512", "ES256", "ES384", "PS256"])

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    async def validate(self, raw_token: str) -> CallerIdentity:
        """Validate ``raw_token`` and return a :class:`CallerIdentity`.

        Raises :class:`JWTValidationError` if the token is invalid for any
        reason (bad signature, expired, wrong issuer/audience, malformed).
        """
        claims_options = {
            "iss": {"essential": True, "value": self.issuer},
            "aud": {"essential": True, "value": self.audience},
            "exp": {"essential": True},
            "sub": {"essential": True},
        }

        keyset = await self._get_keyset(force_refresh=False)
        try:
            claims = self._jwt.decode(raw_token, keyset, claims_options=claims_options)
        except (JoseError, ValueError):
            # Either the signature didn't verify (rotated key) or the kid was
            # not in the cached keyset.  Refetch JWKS and retry once.
            keyset = await self._get_keyset(force_refresh=True)
            try:
                claims = self._jwt.decode(raw_token, keyset, claims_options=claims_options)
            except (JoseError, ValueError) as exc:
                _log.warning("jwt_signature_invalid", error=str(exc))
                raise JWTValidationError(_INVALID_TOKEN_MSG) from exc

        # `validate()` runs the claims_options checks plus standard time
        # validation (exp, nbf, iat).
        try:
            claims.validate(now=int(time.time()), leeway=0)
        except JoseError as exc:
            _log.warning("jwt_claims_invalid", error=str(exc))
            raise JWTValidationError(_INVALID_TOKEN_MSG) from exc

        scopes = _extract_scopes(claims, self.scopes_claim)
        owner_id = str(claims.get("sub") or "")
        if not owner_id:
            _log.warning("jwt_missing_sub")
            raise JWTValidationError(_INVALID_TOKEN_MSG)

        owner_label = str(
            claims.get("name") or claims.get("email") or claims.get("client_id") or owner_id
        )
        # `key_id` is used in audit logs.  For JWTs we use the JWT ID if
        # provided, otherwise a stable prefix of the subject.
        key_id = str(claims.get("jti") or f"jwt_{owner_id}")

        return CallerIdentity(
            key_id=key_id,
            owner_id=owner_id,
            owner_label=owner_label,
            scopes=scopes,
            rate_limit_rpm=self.default_rate_limit_rpm,
            transport=self._transport,
        )

    async def _get_keyset(self, *, force_refresh: bool) -> Any:
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
            keyset = JsonWebKey.import_key_set(response.json())
            self._cache = _CachedJWKS(keyset=keyset, fetched_at=time.time())
            return keyset


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
