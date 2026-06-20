import asyncio
import json
from dataclasses import asdict

import redis.asyncio as redis
import structlog
from sqlalchemy.ext.asyncio import async_sessionmaker
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from pontifex_mcp.auth.api_keys import APIKeyResolver
from pontifex_mcp.auth.discovery import external_base_url
from pontifex_mcp.auth.identity import CallerIdentity, anonymous_identity
from pontifex_mcp.auth.jwt_validator import JWTValidationError, JWTValidator
from pontifex_mcp.middleware.rate_limit import RateLimiter
from pontifex_mcp.storage import (
    create_db_engine,
    ensure_sqlite_schema,
    is_sqlite,
    normalize_db_url,
)

logger = structlog.get_logger(__name__)

# Public/unauthenticated paths. Auth middleware skips these.
_PUBLIC_PATHS: tuple[str, ...] = (
    "/health/live",
    "/health/ready",
    "/docs",
    "/openapi.json",
    "/.well-known/oauth-protected-resource",
)

# API-key plaintext is prefixed `sk_<env>_<random>` — `sk_live_` in prod,
# `sk_uat_` / `sk_test_` in ephemeral and CI environments.  We route on the
# `sk_` prefix alone: OAuth JWTs are base64url-encoded JSON, so they always
# begin with `ey` (the encoding of `{"`) and never collide with `sk_`.
_API_KEY_PREFIX = "sk_"


class AuthMiddleware(BaseHTTPMiddleware):
    """Resolve a Bearer token to a :class:`CallerIdentity`.

    Two paths share the same identity contract:

    * Tokens prefixed with ``sk_live_`` are looked up via :class:`APIKeyResolver`
      (Redis-cached when configured, direct store hash check otherwise).
    * Anything else is validated as an OAuth 2.1 JWT via :class:`JWTValidator`
      against the configured JWKS endpoint.

    Either way the resolved identity lands at ``request.state.caller``.  Returns
    401 if the token is missing or invalid; scope enforcement happens in tool
    handlers.

    When ``jwt_validator`` is ``None`` only the API-key path is active — any
    non-prefixed token is rejected.
    """

    def __init__(
        self,
        app: ASGIApp,
        redis_url: str | None = None,
        database_url: str | None = None,
        cache_ttl: int = 300,
        jwt_validator: JWTValidator | None = None,
        api_key_resolver: APIKeyResolver | None = None,
        rate_limiter: RateLimiter | None = None,
        public_base_url: str = "",
        allowed_hosts: str = "",
        allow_anonymous: bool = False,
    ) -> None:
        """Build the middleware.

        Either pass an explicit ``api_key_resolver`` (preferred in tests),
        provide ``database_url`` (with optional ``redis_url``) so the middleware
        can wire one up itself, or set ``allow_anonymous=True`` for an open
        server with no auth backend at all.  ``public_base_url`` /
        ``allowed_hosts`` are passed through to :func:`external_base_url` to pin
        the host advertised in the ``WWW-Authenticate`` challenge.

        ``database_url`` accepts a SQLite file (``sqlite+aiosqlite:///x.db``) or
        a Postgres URL.  SQLite tables are created lazily on the first resolve;
        Postgres schemas are owned by Alembic.

        ``redis_url`` is optional.  With it, the middleware builds a Redis-cached
        resolver and a :class:`RateLimiter` (unless one is given).  Without it,
        the resolver reads the store directly and rate limiting is disabled with
        a startup log — there is no shared counter to enforce a per-caller limit,
        and a per-process counter would silently skew under multiple replicas.
        In the injected-resolver path a ``rate_limiter`` must be passed
        explicitly; otherwise rate limiting is off (convenient for tests).

        ``allow_anonymous`` enables an open mode: with no resolver and no JWT
        validator, every request resolves to an anonymous
        :class:`CallerIdentity` (global ``*`` scope) instead of a 401.  The
        network bind is gated to localhost in this mode by the facade.
        """
        super().__init__(app)
        self.public_base_url = public_base_url
        self.allowed_hosts = allowed_hosts
        self.rate_limiter = rate_limiter
        self.allow_anonymous = allow_anonymous
        self.jwt_validator = jwt_validator
        self.resolver: APIKeyResolver | None
        # SQLite key stores create their tables lazily on first resolve; this
        # gate stays "ready" (a no-op) for Postgres and the injected-resolver path.
        self._schema_ready = True
        self._schema_lock = asyncio.Lock()
        if api_key_resolver is not None:
            self.resolver = api_key_resolver
        elif database_url is not None:
            url = normalize_db_url(database_url)
            self.redis_client = redis.from_url(redis_url) if redis_url is not None else None
            self.engine = create_db_engine(url)
            self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)
            self.resolver = APIKeyResolver(
                self.redis_client, self.session_factory, cache_ttl=cache_ttl
            )
            if is_sqlite(url):
                self._schema_ready = False
            if self.redis_client is not None:
                if self.rate_limiter is None:
                    self.rate_limiter = RateLimiter(self.redis_client)
            else:
                # Rate limiting needs a shared counter store. Without Redis it
                # fails open (consistent with RateLimiter's own error behavior)
                # and says so, rather than faking a per-process limit that would
                # read as N× the configured value across replicas.
                logger.warning(
                    "rate_limiting_disabled",
                    msg=(
                        "rate limiting disabled: no REDIS_URL set. "
                        "Add REDIS_URL to enforce per-caller limits."
                    ),
                )
        elif allow_anonymous or jwt_validator is not None:
            # Open mode, or JWT-only (no API-key store): no resolver. An sk_
            # token then fails cleanly (the dispatch path guards a None resolver).
            self.resolver = None
        else:
            raise ValueError(
                "AuthMiddleware needs database_url, an explicit "
                "api_key_resolver, a jwt_validator, or allow_anonymous=True."
            )

    async def _ensure_schema(self) -> None:
        """Create the SQLite key-store tables once, on first resolve.

        No-op for Postgres (Alembic-owned) and the injected-resolver path, where
        ``_schema_ready`` starts True. Mirrors ``DbAuditWriter._ensure_schema``.
        """
        if self._schema_ready:
            return
        async with self._schema_lock:
            if self._schema_ready:
                return
            await ensure_sqlite_schema(self.engine)
            self._schema_ready = True

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.url.path in _PUBLIC_PATHS:
            return await call_next(request)

        # Open mode: no auth backend configured. Every request is the anonymous
        # caller (global `*` scope, advisory). Any presented token is ignored —
        # there's nothing to validate it against.
        if self.allow_anonymous and self.resolver is None and self.jwt_validator is None:
            request.state.caller = anonymous_identity("http")
            request.state.subject_token = None
            return await call_next(request)

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return self._auth_error(request, "Missing 'Authorization: Bearer <token>' header.")
        raw_token = auth_header[len("Bearer ") :].strip()
        if not raw_token:
            return self._auth_error(request, "Empty bearer token.")

        # The subject token is the inbound JWT, used downstream for OAuth token
        # exchange (RFC 8693). API-key callers have no exchangeable token.
        subject_token: str | None = None
        if raw_token.startswith(_API_KEY_PREFIX):
            if self.resolver is None:
                return self._auth_error(request, "API-key auth is not configured on this server.")
            await self._ensure_schema()
            identity = await self.resolver.resolve(raw_token)
            if identity is None:
                return self._auth_error(request, "Invalid, expired, or revoked API key.")
        else:
            if self.jwt_validator is None:
                return self._auth_error(
                    request, "JWT auth not configured on this server; use an API key."
                )
            try:
                identity = await self.jwt_validator.validate(raw_token)
            except JWTValidationError as exc:
                return self._auth_error(request, str(exc))
            subject_token = raw_token

        request.state.caller = identity
        request.state.subject_token = subject_token

        if self.rate_limiter is not None and not await self.rate_limiter.allow(
            identity.owner_id, identity.rate_limit_rpm
        ):
            return _rate_limited(identity.rate_limit_rpm)

        return await call_next(request)

    def _auth_error(self, request: Request, message: str) -> JSONResponse:
        """Build a 401 response with an MCP-spec-compliant WWW-Authenticate header.

        Per RFC 9728 + the MCP authorization spec, clients that don't yet have
        credentials discover the protected resource metadata via the
        ``resource_metadata`` parameter of the ``WWW-Authenticate`` header on
        a 401.  We always emit the ``Bearer`` realm; the ``resource_metadata``
        URL is only included when JWT auth is configured (otherwise there's no
        OAuth flow to discover).

        The advertised host comes from :func:`external_base_url`, which prefers
        the configured ``public_base_url`` and otherwise only honours
        ``X-Forwarded-Host`` when it matches ``allowed_hosts`` — so a client
        can't poison the discovery URL with an attacker-controlled host.
        """
        challenge = 'Bearer realm="mcp", error="invalid_token"'
        if self.jwt_validator is not None:
            base = external_base_url(request, self.public_base_url, self.allowed_hosts)
            challenge += f', resource_metadata="{base}/.well-known/oauth-protected-resource"'
        return JSONResponse(
            status_code=401,
            content={
                "error_code": "auth_failed",
                "message": message,
                "status": 401,
                "retry": False,
            },
            headers={"WWW-Authenticate": challenge},
        )


def _rate_limited(limit_rpm: int) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={
            "error_code": "rate_limited",
            "message": f"Rate limit of {limit_rpm} requests/minute exceeded.",
            "status": 429,
            "retry": True,
        },
        headers={"Retry-After": "60"},
    )


def get_caller(request: Request) -> CallerIdentity:
    """Helper for tool handlers to fetch the resolved CallerIdentity."""
    caller = getattr(request.state, "caller", None)
    if caller is None:
        raise RuntimeError("CallerIdentity not set; AuthMiddleware did not run.")
    return caller


def serialize_identity(identity: CallerIdentity) -> str:
    return json.dumps(asdict(identity))
