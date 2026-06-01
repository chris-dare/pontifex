"""Canonical external URL resolution for OAuth discovery (RFC 9728).

The MCP server advertises absolute URLs that clients use to bootstrap OAuth:
the ``resource_metadata`` URL in the ``WWW-Authenticate`` challenge and the
``resource`` field of the protected-resource metadata document.

The canonical public URL should be an explicit, stable configured value
(``public_base_url`` / ``GSE_MCP_PUBLIC_BASE_URL``).  OAuth resource identifiers
are meant to be a single fixed value, and a configured URL is immune to
``X-Forwarded-*`` header spoofing because we never read the request to build it.

When it's unset (local/dev, or a deployment that hasn't configured one) we fall
back to deriving the URL from the request, trusting ``X-Forwarded-Host`` only
when the operator has declared it in ``allowed_hosts``.
"""

from __future__ import annotations

from starlette.requests import Request


def external_base_url(
    request: Request,
    public_base_url: str = "",
    allowed_hosts: str = "",
) -> str:
    """Return the canonical ``scheme://host`` the server should advertise.

    Prefers the configured ``public_base_url`` verbatim.  Otherwise derives the
    origin from the request: ``X-Forwarded-Host`` is honoured only when it
    appears in the comma-separated ``allowed_hosts``; a host that isn't declared
    there (including a spoofed one) falls back to the real ``Host`` header.
    """
    if public_base_url:
        return public_base_url.rstrip("/")

    hosts = {h.strip() for h in allowed_hosts.split(",") if h.strip()}
    forwarded = request.headers.get("x-forwarded-host")
    host = forwarded if (forwarded and forwarded in hosts) else request.url.netloc

    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    scheme = proto if proto in ("http", "https") else "https"
    # Not a Flask/HTTP route — a helper returning a URL string.  The result is
    # used in a JSON field and a header value, never rendered as HTML, and the
    # host is pinned to allowed_hosts / public_base_url, so there's no XSS path.
    return f"{scheme}://{host}"  # nosemgrep
