"""Per-user downstream auth via OAuth 2.0 Token Exchange (RFC 8693).

The caller authenticates to Pontifex with their JWT; this strategy exchanges
that token at the shared IdP for a *new* token carrying the downstream API's
audience, on behalf of the user — the downstream then enforces its own per-user
authorization. The inbound token is never forwarded (no passthrough).

Security posture (see issues #41, #47):
  - Exchanged tokens are cached via a `TokenCache`: in-process memory by default
    (never at rest), or Redis with Fernet encryption-at-rest (key from the
    environment, not Redis). For the in-memory backend, encryption would be
    theatre — the key is co-resident — so the real controls there are short TTL,
    a redaction wrapper, a bounded LRU, and keeping tokens out of logs/errors.
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
from typing import Any, Protocol

import httpx
import redis.asyncio as redis_asyncio
import structlog
from cryptography.fernet import Fernet, InvalidToken

from pontifex_mcp.connectors.adapter import UpstreamAuthUnavailable
from pontifex_mcp.connectors.auth import AuthContext, _require_env
from pontifex_mcp.observability.metrics import counter, histogram
from pontifex_mcp.utils.circuit_breaker import CircuitBreaker

_logger = structlog.get_logger(__name__)

_GRANT_TYPE = "urn:ietf:params:oauth:grant-type:token-exchange"
_ACCESS_TOKEN_TYPE = "urn:ietf:params:oauth:token-type:access_token"

# Observability for the token-exchange path (#48). Attributes are non-sensitive:
# the downstream audience, the exchange outcome, and the cache result — never
# tokens or subject identifiers.
_exchange_requests = counter(
    "pontifex.token_exchange.requests", description="Token-exchange attempts by outcome"
)
_exchange_duration = histogram(
    "pontifex.token_exchange.duration_ms", unit="ms", description="Token-exchange IdP call duration"
)
_cache_requests = counter(
    "pontifex.token_cache.requests", description="Token cache lookups by result"
)


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

    Implemented by :class:`InMemoryTokenCache` (tokens never leave the process)
    and :class:`RedisTokenCache` (shared, encrypted at rest). Selected at runtime
    by :func:`default_token_cache`; both drop in without touching
    :class:`TokenExchange`.
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
                _cache_requests.add(1, {"result": "hit"})
                return secret
            del self._entries[key]

        # Single-flight: concurrent misses for the same key share one task, so
        # the loader runs once. Both the creator and any waiters await the task,
        # so a loader failure is retrieved by all of them (no orphaned-exception
        # warnings) and propagates to each caller.
        inflight = self._inflight.get(key)
        if inflight is None:
            _cache_requests.add(1, {"result": "miss"})
            inflight = asyncio.ensure_future(self._load_and_store(key, loader))
            self._inflight[key] = inflight
        else:
            _cache_requests.add(1, {"result": "coalesced"})
        return await inflight

    async def _load_and_store(
        self, key: str, loader: Callable[[], Awaitable[tuple[str, int]]]
    ) -> _Secret:
        try:
            value, ttl_seconds = await loader()
            secret = _Secret(value)
            self._store(key, secret, self._clock() + ttl_seconds)
            return secret
        finally:
            self._inflight.pop(key, None)

    def _store(self, key: str, secret: _Secret, expiry: float) -> None:
        self._entries[key] = (secret, expiry)
        self._entries.move_to_end(key)
        while len(self._entries) > self._max:
            self._entries.popitem(last=False)


class TokenEncryptor(Protocol):
    """Encrypts/decrypts token bytes for a cache backend that stores at rest."""

    def encrypt(self, plaintext: bytes) -> bytes: ...
    def decrypt(self, ciphertext: bytes) -> bytes: ...


class FernetEncryptor:
    """AES-CBC + HMAC via Fernet, with the key held outside the datastore.

    For the shared (Redis) cache this is a real control: a Redis dump alone can't
    reveal tokens because the key lives in the environment, not in Redis. (For the
    in-memory cache it would be theatre — the key is co-resident — so it isn't
    used there.)
    """

    def __init__(self, key: str) -> None:
        try:
            self._fernet = Fernet(key.encode())
        except (ValueError, TypeError) as exc:
            raise ValueError(
                "PONTIFEX_TOKEN_CACHE_KEY must be a urlsafe-base64 32-byte Fernet key "
                "(generate one with cryptography.fernet.Fernet.generate_key())"
            ) from exc

    def encrypt(self, plaintext: bytes) -> bytes:
        return self._fernet.encrypt(plaintext)

    def decrypt(self, ciphertext: bytes) -> bytes:
        return self._fernet.decrypt(ciphertext)


class RedisTokenCache:
    """Shared exchanged-token cache backed by Redis, encrypted at rest.

    Tokens are Fernet-encrypted before storage and TTL'd via SETEX, so they
    expire and a Redis dump yields only ciphertext. Single-flight is per-process
    (best-effort — bounds IdP load on this worker; concurrent workers may each
    exchange once, which is acceptable). `redis_client` is injectable for testing.
    """

    def __init__(
        self,
        encryptor: TokenEncryptor,
        *,
        redis_url: str | None = None,
        # Any: redis.asyncio's client type is awkward to annotate across versions;
        # this is an injection seam for a fake client in tests.
        redis_client: Any = None,
        key_prefix: str = "pontifex:tokx:",
    ) -> None:
        if redis_client is not None:
            self._redis = redis_client
        elif redis_url:
            self._redis = redis_asyncio.from_url(redis_url)
        else:
            raise ValueError("RedisTokenCache requires redis_url or redis_client")
        self._enc = encryptor
        self._prefix = key_prefix
        self._inflight: dict[str, asyncio.Future[_Secret]] = {}

    async def aclose(self) -> None:
        await self._redis.aclose()

    async def get_or_load(
        self, key: str, loader: Callable[[], Awaitable[tuple[str, int]]]
    ) -> _Secret:
        rkey = self._prefix + key
        cached = await self._redis.get(rkey)
        if cached is not None:
            try:
                secret = _Secret(self._enc.decrypt(cached).decode())
                _cache_requests.add(1, {"result": "hit"})
                return secret
            except InvalidToken:
                # Key rotated or value corrupt — treat as a miss and re-mint,
                # rather than failing the call (and tripping the connector
                # breaker) until the entry's TTL expires. Self-heals on rotation.
                pass

        inflight = self._inflight.get(key)
        if inflight is None:
            _cache_requests.add(1, {"result": "miss"})
            inflight = asyncio.ensure_future(self._load_and_store(rkey, key, loader))
            self._inflight[key] = inflight
        else:
            _cache_requests.add(1, {"result": "coalesced"})
        return await inflight

    async def _load_and_store(
        self, rkey: str, key: str, loader: Callable[[], Awaitable[tuple[str, int]]]
    ) -> _Secret:
        try:
            value, ttl_seconds = await loader()
            # SETEX rejects a non-positive TTL; the shipped loader guarantees
            # ttl >= 1, but this is a reusable seam — skip caching rather than
            # crash if a loader returns a non-positive TTL.
            if ttl_seconds > 0:
                await self._redis.setex(rkey, ttl_seconds, self._enc.encrypt(value.encode()))
            return _Secret(value)
        finally:
            self._inflight.pop(key, None)


def default_token_cache() -> TokenCache:
    """Build the token cache from the environment.

    `PONTIFEX_TOKEN_CACHE=memory` (default) → in-process only, never at rest.
    `=redis` → shared Redis, requiring `REDIS_URL` and a Fernet
    `PONTIFEX_TOKEN_CACHE_KEY`. Missing requirements fail at startup.
    """
    backend = os.environ.get("PONTIFEX_TOKEN_CACHE", "memory").lower()
    if backend == "memory":
        return InMemoryTokenCache()
    if backend == "redis":
        redis_url = os.environ.get("REDIS_URL")
        if not redis_url:
            raise ValueError("PONTIFEX_TOKEN_CACHE=redis requires REDIS_URL")
        key = os.environ.get("PONTIFEX_TOKEN_CACHE_KEY")
        if not key:
            raise ValueError(
                "PONTIFEX_TOKEN_CACHE=redis requires PONTIFEX_TOKEN_CACHE_KEY (a Fernet key)"
            )
        return RedisTokenCache(FernetEncryptor(key), redis_url=redis_url)
    raise ValueError(f"PONTIFEX_TOKEN_CACHE must be 'memory' or 'redis', got {backend!r}")


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
        self._cache = cache or default_token_cache()
        self._client = http_client or httpx.AsyncClient(timeout=timeout)
        self._breaker = breaker or CircuitBreaker(
            name=f"token-exchange:{audience}", failure_threshold=3, recovery_timeout=30.0
        )
        self._skew = skew_seconds

    async def close(self) -> None:
        await self._client.aclose()
        cache_close = getattr(self._cache, "aclose", None)
        if cache_close is not None:
            await cache_close()

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
        # Time the exchange and record its outcome (audience-labelled, no tokens).
        start = time.monotonic()
        outcome = "ok"
        try:
            return await self._exchange_inner(subject_token)
        except UpstreamAuthUnavailable:
            outcome = "unavailable"
            raise
        except TokenExchangeRejected:
            outcome = "rejected"
            raise
        except asyncio.CancelledError:
            # CancelledError is a BaseException, not Exception — catch it so a
            # cancelled exchange isn't recorded as a success.
            outcome = "cancelled"
            raise
        except Exception:
            outcome = "error"
            raise
        finally:
            _exchange_duration.record(
                (time.monotonic() - start) * 1000.0, {"audience": self.audience}
            )
            _exchange_requests.add(1, {"audience": self.audience, "outcome": outcome})

    async def _exchange_inner(self, subject_token: str) -> tuple[str, int]:
        if not self._breaker.is_available:
            raise UpstreamAuthUnavailable("token-exchange circuit open")
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
            raise UpstreamAuthUnavailable(f"token endpoint unreachable: {exc!r}") from exc

        if response.status_code >= 500:
            self._breaker.record_failure()
            _logger.warning(
                "token_exchange_5xx", audience=self.audience, status=response.status_code
            )
            raise UpstreamAuthUnavailable(f"token endpoint returned {response.status_code}")
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
