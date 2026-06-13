"""Per-user downstream auth via OAuth 2.0 Token Exchange (RFC 8693).

The caller authenticates to Pontifex with their JWT; this strategy exchanges
that token at the shared IdP for a *new* token carrying the downstream API's
audience, on behalf of the user — the downstream then enforces its own per-user
authorization. The inbound token is never forwarded (no passthrough).

Security posture (see issue #41):
  - Exchanged tokens are cached **in process memory only**, never at rest.
    Encrypting an in-process cache is theatre — the key is co-resident — so the
    real controls are short TTL, a redaction wrapper, a bounded LRU, and
    keeping tokens out of logs/errors.
  - Cache key is `sha256(subject_token):audience` — never the plaintext token,
    and audience-scoped so a token minted for one connector can't serve another.
  - Fail closed: any ambiguity (IdP unreachable, malformed response, missing
    `expires_in`, audience mismatch) denies rather than degrading.
"""

import asyncio
import base64
import hashlib
import json
import os
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from typing import Protocol

import httpx
import structlog

from pontifex_mcp.connectors.adapter import ConnectorUnavailable
from pontifex_mcp.connectors.auth import AuthContext, _require_env
from pontifex_mcp.utils.circuit_breaker import CircuitBreaker

_logger = structlog.get_logger(__name__)

_GRANT_TYPE = "urn:ietf:params:oauth:grant-type:token-exchange"
_ACCESS_TOKEN_TYPE = "urn:ietf:params:oauth:token-type:access_token"


class TokenExchangeRejected(Exception):
    """The IdP refused the exchange (4xx) or returned an unusable token.

    A caller-/config-level problem, not an outage — does NOT trip the circuit
    breaker and is non-retryable. Messages are deliberately generic: the raw IdP
    body and the subject token are never surfaced.
    """


class _Secret:
    """Holds a token value while keeping it out of logs, reprs, and tracebacks.

    The value is only accessible via :meth:`reveal`; every string conversion
    returns a mask, so an accidental f-string or log call can't leak it.
    """

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        self._value = value

    def reveal(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return "Secret(***)"

    __str__ = __repr__


def _b64url_decode(segment: str) -> bytes:
    padding = "=" * (-len(segment) % 4)
    return base64.urlsafe_b64decode(segment + padding)


class TokenCache(Protocol):
    """Cache seam for exchanged tokens.

    v1 ships only :class:`InMemoryTokenCache` (tokens never leave the process).
    A future shared backend (encrypted Redis, short TTL) implements this same
    interface so it drops in without touching :class:`TokenExchange`.
    """

    async def get_or_load(
        self, key: str, loader: Callable[[], Awaitable[tuple[str, int]]]
    ) -> "_Secret": ...


class InMemoryTokenCache:
    """Bounded, TTL'd, single-flight token cache held only in process memory.

    `get_or_load` coalesces concurrent misses for the same key into one `loader`
    call (no stampede on cold start / expiry), evicts least-recently-used entries
    past `max_entries`, and never writes anywhere durable. `clock` is injectable
    for testing TTL expiry.
    """

    def __init__(
        self, *, max_entries: int = 1024, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._max = max_entries
        self._clock = clock
        self._entries: OrderedDict[str, tuple[_Secret, float]] = OrderedDict()
        self._inflight: dict[str, asyncio.Future[_Secret]] = {}

    async def get_or_load(
        self, key: str, loader: Callable[[], Awaitable[tuple[str, int]]]
    ) -> _Secret:
        now = self._clock()
        entry = self._entries.get(key)
        if entry is not None:
            secret, expiry = entry
            if expiry > now:
                self._entries.move_to_end(key)
                return secret
            del self._entries[key]

        inflight = self._inflight.get(key)
        if inflight is not None:
            return await inflight  # coalesce onto the in-flight exchange

        loop = asyncio.get_running_loop()
        future: asyncio.Future[_Secret] = loop.create_future()
        self._inflight[key] = future
        try:
            value, ttl_seconds = await loader()
            secret = _Secret(value)
            self._store(key, secret, self._clock() + ttl_seconds)
            future.set_result(secret)
            return secret
        except Exception as exc:
            future.set_exception(exc)
            raise
        finally:
            self._inflight.pop(key, None)

    def _store(self, key: str, secret: _Secret, expiry: float) -> None:
        self._entries[key] = (secret, expiry)
        self._entries.move_to_end(key)
        while len(self._entries) > self._max:
            self._entries.popitem(last=False)


class TokenExchange:
    """Backend-auth strategy that mints a per-user downstream token via RFC 8693.

    Client credentials (Pontifex's own IdP client) are read from env; presence is
    checked at construction so a misconfiguration fails at startup. `http_client`,
    `cache`, `breaker`, and `clock` are injectable for testing.
    """

    requires_subject_token = True

    def __init__(
        self,
        *,
        token_endpoint: str,
        audience: str,
        client_id_env: str,
        client_secret_env: str,
        client_auth: str = "post",
        default_ttl_seconds: int | None = None,
        cache: TokenCache | None = None,
        http_client: httpx.AsyncClient | None = None,
        breaker: CircuitBreaker | None = None,
        skew_seconds: int = 30,
        timeout: float = 10.0,
    ) -> None:
        _require_env(client_id_env)
        _require_env(client_secret_env)
        if client_auth not in ("post", "basic"):
            raise ValueError("client_auth must be 'post' (client_secret_post) or 'basic'")
        self.token_endpoint = token_endpoint
        self.audience = audience
        self._client_id_env = client_id_env
        self._client_secret_env = client_secret_env
        # Provider interop knobs (defaults match the strict, common case):
        #  - client_auth: how to present client creds — in the form ("post",
        #    client_secret_post) or an HTTP Basic header ("basic").
        #  - default_ttl_seconds: `expires_in` is OPTIONAL in RFC 8693; the
        #    default is to fail closed when it's absent (we can't size the cache
        #    TTL). A provider that omits it can opt into this fallback TTL.
        self._client_auth = client_auth
        self._default_ttl = default_ttl_seconds
        self._cache = cache or InMemoryTokenCache()
        self._client = http_client or httpx.AsyncClient(timeout=timeout)
        self._breaker = breaker or CircuitBreaker(
            name=f"token-exchange:{audience}", failure_threshold=3, recovery_timeout=30.0
        )
        self._skew = skew_seconds

    async def close(self) -> None:
        await self._client.aclose()

    async def headers(self, ctx: AuthContext) -> dict[str, str]:
        # No subject token → health check (or a real call that should already
        # have been rejected upstream). Degrade to no-auth; never raise here.
        if ctx.subject_token is None:
            return {}
        key = self._cache_key(ctx.subject_token)
        subject_token = ctx.subject_token
        secret = await self._cache.get_or_load(key, lambda: self._exchange(subject_token))
        return {"Authorization": f"Bearer {secret.reveal()}"}

    def _cache_key(self, subject_token: str) -> str:
        digest = hashlib.sha256(subject_token.encode()).hexdigest()
        return f"{digest}:{self.audience}"

    async def _exchange(self, subject_token: str) -> tuple[str, int]:
        if not self._breaker.is_available:
            raise ConnectorUnavailable("token-exchange circuit open")
        form = {
            "grant_type": _GRANT_TYPE,
            "subject_token": subject_token,
            "subject_token_type": _ACCESS_TOKEN_TYPE,
            "requested_token_type": _ACCESS_TOKEN_TYPE,
            "audience": self.audience,
        }
        client_id = os.environ[self._client_id_env]
        client_secret = os.environ[self._client_secret_env]
        headers: dict[str, str] = {}
        if self._client_auth == "basic":
            token = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
            headers["Authorization"] = f"Basic {token}"
        else:  # client_secret_post
            form["client_id"] = client_id
            form["client_secret"] = client_secret
        try:
            response = await self._client.post(self.token_endpoint, data=form, headers=headers)
        except httpx.HTTPError as exc:
            self._breaker.record_failure()
            _logger.warning("token_exchange_unreachable", audience=self.audience, error=repr(exc))
            raise ConnectorUnavailable(f"token endpoint unreachable: {exc!r}") from exc

        if response.status_code >= 500:
            self._breaker.record_failure()
            _logger.warning(
                "token_exchange_5xx", audience=self.audience, status=response.status_code
            )
            raise ConnectorUnavailable(f"token endpoint returned {response.status_code}")
        if response.status_code != 200:
            # Rejected exchange — caller not delegatable or bad client config.
            # Not an outage: don't trip the breaker, don't leak the IdP body.
            _logger.warning(
                "token_exchange_rejected", audience=self.audience, status=response.status_code
            )
            raise TokenExchangeRejected(f"token exchange rejected ({response.status_code})")

        self._breaker.record_success()
        try:
            payload = response.json()
        except ValueError as exc:
            raise TokenExchangeRejected("token endpoint returned non-JSON") from exc

        access = payload.get("access_token")
        if not access:
            raise TokenExchangeRejected("token response missing access_token")
        expires_in = payload.get("expires_in")
        if not isinstance(expires_in, int) or expires_in <= 0:
            # `expires_in` is OPTIONAL in RFC 8693. Fail closed unless the caller
            # configured a fallback TTL for providers that omit it.
            if self._default_ttl is None:
                raise TokenExchangeRejected("token response missing expires_in")
            expires_in = self._default_ttl
        if not self._audience_ok(access):
            raise TokenExchangeRejected("exchanged token audience mismatch")

        ttl = max(1, expires_in - self._skew)
        _logger.info("token_exchange_ok", audience=self.audience, ttl=ttl)
        return access, ttl

    def _audience_ok(self, access_token: str) -> bool:
        """Verify the exchanged token targets our audience, if inspectable.

        A 3-segment JWT carrying an `aud` claim must include our audience (guards
        against an IdP misconfigured to mint a wrong-audience token). Opaque
        tokens can't be inspected → trusted; only a *positive* mismatch denies.
        """
        parts = access_token.split(".")
        if len(parts) != 3:
            return True
        try:
            claims = json.loads(_b64url_decode(parts[1]))
        except Exception:
            return True
        aud = claims.get("aud")
        if aud is None:
            return True
        auds = aud if isinstance(aud, list) else [aud]
        return self.audience in auds
