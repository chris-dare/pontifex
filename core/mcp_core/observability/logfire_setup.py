from typing import Any

import structlog

logger = structlog.get_logger(__name__)


def setup_logfire(app: Any, domain: str, token: str) -> None:
    """Instrument FastAPI/httpx/Redis with Logfire if it's installed.

    Logfire is optional; if the package isn't installed, this is a no-op.
    """
    try:
        import logfire  # type: ignore
    except ImportError:
        logger.info("logfire_not_installed", domain=domain)
        return

    logfire.configure(token=token, service_name=f"{domain}-mcp")
    logfire.instrument_fastapi(app)
    try:
        logfire.instrument_httpx()
    except Exception:
        pass
    try:
        logfire.instrument_redis()
    except Exception:
        pass
