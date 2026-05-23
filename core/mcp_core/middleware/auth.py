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

# Public/unauthenticated paths. Auth middleware skips these.
_PUBLIC_PATHS: tuple[str, ...] = ("/health/live", "/health/ready", "/docs", "/openapi.json")


class AuthMiddleware(BaseHTTPMiddleware):
    """Extracts API key from `Authorization: Bearer <key>` and resolves to CallerIdentity.

    Stores the resolved identity at `request.state.caller`. Returns 401 if the key is
    missing or invalid. Scope enforcement happens later in tool handlers.
    """

    def __init__(
        self,
        app: ASGIApp,
        redis_url: str,
        database_url: str,
        cache_ttl: int = 300,
    ) -> None:
        super().__init__(app)
        self.redis_client = redis.from_url(redis_url)
        self.engine = create_async_engine(database_url, pool_size=5, max_overflow=10)
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)
        self.resolver = APIKeyResolver(self.redis_client, self.session_factory, cache_ttl=cache_ttl)

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.url.path in _PUBLIC_PATHS:
            return await call_next(request)

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return _auth_error("Missing 'Authorization: Bearer <key>' header.")
        raw_key = auth_header[len("Bearer ") :].strip()
        if not raw_key:
            return _auth_error("Empty API key.")

        identity = await self.resolver.resolve(raw_key)
        if identity is None:
            return _auth_error("Invalid, expired, or revoked API key.")

        request.state.caller = identity
        return await call_next(request)


def _auth_error(message: str) -> JSONResponse:
    return JSONResponse(
        status_code=401,
        content={
            "error_code": "auth_failed",
            "message": message,
            "status": 401,
            "retry": False,
        },
    )


def get_caller(request: Request) -> CallerIdentity:
    """Helper for tool handlers to fetch the resolved CallerIdentity."""
    caller = getattr(request.state, "caller", None)
    if caller is None:
        raise RuntimeError("CallerIdentity not set; AuthMiddleware did not run.")
    return caller


def serialize_identity(identity: CallerIdentity) -> str:
    return json.dumps(asdict(identity))
