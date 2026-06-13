"""HTTP adapter backing OpenAPI-generated tools.

One `OpenAPIAdapter` serves every generated tool for a connector. It satisfies
the `DataAdapter` protocol so it runs under `DataSourceManager` and inherits
circuit breaking like any hand-written adapter.
"""

from typing import Any
from urllib.parse import quote

import httpx

from pontifex_mcp.connectors.auth import AuthContext, BackendAuth
from pontifex_mcp.connectors.spec import Operation


class ConnectorUnavailable(Exception):
    """The downstream API could not serve the request (network error or 5xx)."""


class DownstreamClientError(Exception):
    """The downstream API rejected the request (4xx) — a caller error."""

    def __init__(self, status_code: int, body: str) -> None:
        self.status_code = status_code
        super().__init__(f"downstream API returned {status_code}: {body[:500]}")


class OpenAPIAdapter:
    """Executes spec operations against the connector's base URL."""

    def __init__(
        self,
        *,
        domain: str,
        base_url: str,
        auth: BackendAuth | None = None,
        timeout: float = 10.0,
        priority: int = 1,
    ) -> None:
        self.name = f"openapi:{domain}"
        self.priority = priority
        self.base_url = base_url.rstrip("/")
        self._auth = auth
        self._client = httpx.AsyncClient(timeout=timeout)

    @property
    def requires_subject_token(self) -> bool:
        """Whether this connector's auth needs the caller's token (token exchange).

        When True, a caller without a subject token (e.g. an API-key caller) can't
        be served and the handler rejects the call rather than reaching downstream.
        """
        return getattr(self._auth, "requires_subject_token", False)

    async def close(self) -> None:
        await self._client.aclose()

    async def health_check(self) -> bool:
        try:
            # Health checks carry no caller, so pass an empty AuthContext: a
            # token-exchange strategy degrades to no-auth, while env strategies
            # still attach their service credential.
            headers = await self._auth_headers(AuthContext())
            response = await self._client.get(self.base_url, headers=headers, timeout=3.0)
            return response.status_code < 500
        except Exception:
            return False

    async def _auth_headers(self, ctx: AuthContext) -> dict[str, str]:
        return await self._auth.headers(ctx) if self._auth else {}

    async def call(
        self, operation: Operation, arguments: dict[str, Any], auth_ctx: AuthContext
    ) -> tuple[int, Any]:
        """Execute one operation; returns (status_code, decoded body)."""
        path = operation.path
        query: dict[str, Any] = {}
        for param in operation.parameters:
            value = arguments.get(param.name)
            if param.location == "path":
                path = path.replace(f"{{{param.name}}}", quote(str(value), safe=""))
            elif value is not None:
                query[param.name] = value

        body = arguments.get("body") if operation.request_body_schema is not None else None

        try:
            response = await self._client.request(
                operation.method,
                f"{self.base_url}{path}",
                params=query,
                json=body,
                headers=await self._auth_headers(auth_ctx),
            )
        except httpx.HTTPError as exc:
            raise ConnectorUnavailable(f"{operation.key}: {exc!r}") from exc

        if response.status_code >= 500:
            raise ConnectorUnavailable(f"{operation.key}: downstream {response.status_code}")
        if response.status_code >= 400:
            raise DownstreamClientError(response.status_code, response.text)

        try:
            data = response.json()
        except ValueError:
            data = response.text
        return response.status_code, data
