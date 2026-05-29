import json
from dataclasses import asdict

import redis.asyncio as redis
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from mcp_core.auth.api_keys import APIKeyResolver
from mcp_core.auth.identity import CallerIdentity
from mcp_core.auth.jwt_validator import JWTValidationError, JWTValidator

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
      (Redis-first, Postgres-fallback hash check).
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
    ) -> None:
        """Build the middleware.

        Either pass an explicit ``api_key_resolver`` (preferred in tests), or
        provide ``redis_url`` + ``database_url`` so the middleware can wire
        one up itself.
        """
        super().__init__(app)
        if api_key_resolver is not None:
            self.resolver = api_key_resolver
        else:
            if redis_url is None or database_url is None:
                raise ValueError(
                    "AuthMiddleware needs redis_url + database_url, "
                    "or an explicit api_key_resolver."
                )
            self.redis_client = redis.from_url(redis_url)
            self.engine = create_async_engine(database_url, pool_size=5, max_overflow=10)
            self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)
            self.resolver = APIKeyResolver(
                self.redis_client, self.session_factory, cache_ttl=cache_ttl
            )
        self.jwt_validator = jwt_validator

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.url.path in _PUBLIC_PATHS:
            return await call_next(request)

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return self._auth_error(request, "Missing 'Authorization: Bearer <token>' header.")
        raw_token = auth_header[len("Bearer ") :].strip()
        if not raw_token:
            return self._auth_error(request, "Empty bearer token.")

        if raw_token.startswith(_API_KEY_PREFIX):
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

        request.state.caller = identity
        return await call_next(request)

    def _auth_error(self, request: Request, message: str) -> JSONResponse:
        """Build a 401 response with an MCP-spec-compliant WWW-Authenticate header.

        Per RFC 9728 + the MCP authorization spec, clients that don't yet have
        credentials discover the protected resource metadata via the
        ``resource_metadata`` parameter of the ``WWW-Authenticate`` header on
        a 401.  We always emit the ``Bearer`` realm; the ``resource_metadata``
        URL is only included when JWT auth is configured (otherwise there's no
        OAuth flow to discover).
        """
        challenge = 'Bearer realm="mcp", error="invalid_token"'
        if self.jwt_validator is not None:
            base = f"{request.url.scheme}://{request.url.netloc}"
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


def get_caller(request: Request) -> CallerIdentity:
    """Helper for tool handlers to fetch the resolved CallerIdentity."""
    caller = getattr(request.state, "caller", None)
    if caller is None:
        raise RuntimeError("CallerIdentity not set; AuthMiddleware did not run.")
    return caller


def serialize_identity(identity: CallerIdentity) -> str:
    return json.dumps(asdict(identity))
