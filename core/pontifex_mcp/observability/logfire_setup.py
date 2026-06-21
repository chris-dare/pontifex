from typing import Any

import structlog

logger = structlog.get_logger(__name__)


def setup_logfire(app: Any, namespace: str, token: str) -> None:
    """Instrument FastAPI/httpx/Redis with Logfire if it's installed.

    Logfire is optional; if the package isn't installed, this is a no-op.
    """
    try:
        import logfire
    except ImportError:
        logger.info("logfire_not_installed", namespace=namespace)
        return

    logfire.configure(token=token, service_name=f"{namespace}-mcp")
    logfire.instrument_fastapi(app)
    try:
        logfire.instrument_httpx()
    except Exception:
        pass
    try:
        logfire.instrument_redis()
    except Exception:
        pass
