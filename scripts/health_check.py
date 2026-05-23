"""Probe a running MCP server's /health/ready endpoint. Exit 0 if 200, else 1."""

import sys
import urllib.request

import structlog

logger = structlog.get_logger(__name__)


def main() -> int:
    url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8080/health/ready"
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return 0 if r.status == 200 else 1
    except Exception as exc:
        logger.error("health_check_failed", url=url, error=repr(exc))
        return 1


if __name__ == "__main__":
    sys.exit(main())
