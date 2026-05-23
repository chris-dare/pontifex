import time
from datetime import UTC, datetime

import structlog
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from mcp_core.auth.identity import CallerIdentity
from mcp_core.models.db import AuditLogModel

logger = structlog.get_logger(__name__)

_TOOL_PATH_PREFIX = "/tools/"


class AuditMiddleware(BaseHTTPMiddleware):
    """Writes one row to core.audit_log per tool invocation.

    Only requests under `/tools/{name}` are audited. Health endpoints are skipped.
    """

    def __init__(self, app: ASGIApp, domain: str, db_url: str) -> None:
        super().__init__(app)
        self.domain = domain
        self.engine = create_async_engine(db_url, pool_size=5, max_overflow=10)
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)

    async def dispatch(self, request: Request, call_next) -> Response:
        if not request.url.path.startswith(_TOOL_PATH_PREFIX):
            return await call_next(request)

        start = time.monotonic()
        error: str | None = None
        response: Response | None = None
        try:
            response = await call_next(request)
        except Exception as exc:
            error = repr(exc)
            raise
        finally:
            elapsed_ms = int((time.monotonic() - start) * 1000)
            caller: CallerIdentity | None = getattr(request.state, "caller", None)
            data_source = "unknown"
            cache_hit = False
            if response is not None:
                data_source = response.headers.get("X-Data-Source", "unknown")
                cache_hit = response.headers.get("X-Cache-Hit", "false").lower() == "true"

            tool_name = request.url.path[len(_TOOL_PATH_PREFIX) :]
            await self._write_audit(
                tool_name=tool_name,
                caller=caller,
                cache_hit=cache_hit,
                data_source=data_source,
                response_ms=elapsed_ms,
                error=error,
                ip_address=request.client.host if request.client else None,
            )

        return response  # type: ignore[return-value]

    async def _write_audit(
        self,
        *,
        tool_name: str,
        caller: CallerIdentity | None,
        cache_hit: bool,
        data_source: str,
        response_ms: int,
        error: str | None,
        ip_address: str | None,
    ) -> None:
        if caller is None:
            # No caller identity = auth rejected the request. Still useful to log,
            # but with empty identifiers. Skipping for now to keep audit semantics
            # tied to authenticated calls.
            return
        try:
            async with self.session_factory() as session:
                session.add(
                    AuditLogModel(
                        timestamp=datetime.now(UTC),
                        domain=self.domain,
                        key_id=caller.key_id,
                        owner_id=caller.owner_id,
                        owner_label=caller.owner_label,
                        transport=caller.transport,
                        tool_name=tool_name,
                        tool_params={},
                        data_source=data_source,
                        cache_hit=cache_hit,
                        response_ms=response_ms,
                        error=error,
                        ip_address=ip_address,
                    )
                )
                await session.commit()
        except Exception as exc:  # Audit failures must not break the request
            logger.warning("audit_write_failed", error=repr(exc))
