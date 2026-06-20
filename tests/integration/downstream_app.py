"""Downstream 'billing' resource server for the integration stack.

A real OAuth resource server: it verifies the bearer token's signature against
Keycloak's JWKS and requires `aud` to include `billing-api`. A passthrough token
(audience = the Pontifex gateway) is rejected; only a token Pontifex *exchanged*
for this API's audience is accepted. Per-user data is keyed by the token subject,
proving the exchanged token carried the right user.
"""

import os

import httpx
import jwt
from fastapi import FastAPI, Header, HTTPException
from jwt import PyJWKSet

ISSUER = os.environ["OIDC_ISSUER"]
JWKS_URL = os.environ["OIDC_JWKS_URL"]
AUDIENCE = "billing-api"

app = FastAPI(title="Billing API", version="1.0.0")
_keyset: PyJWKSet | None = None

INVOICES = {
    "alice": [{"id": "INV-1", "amount": 42.0}],
    "bob": [{"id": "INV-9", "amount": 7.5}],
}


def _keys() -> PyJWKSet:
    global _keyset
    if _keyset is None:
        _keyset = PyJWKSet.from_dict(httpx.get(JWKS_URL, timeout=5.0).json())
    return _keyset


@app.get("/invoices")
def invoices(authorization: str | None = Header(default=None)) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    token = authorization[len("Bearer ") :]
    try:
        header = jwt.get_unverified_header(token)
        kid = header.get("kid")
        keyset = _keys()
        pyjwk = next((k for k in keyset.keys if k.key_id == kid), None)
        if pyjwk is None:
            raise jwt.InvalidTokenError("unknown kid")
        claims = jwt.decode(
            token,
            key=pyjwk.key,
            algorithms=["RS256"],
            audience=AUDIENCE,
            issuer=ISSUER,
            options={"verify_aud": True, "verify_iss": True},
        )
    except jwt.InvalidTokenError as exc:
        # This is what a passthrough token (aud != billing-api) hits.
        raise HTTPException(status_code=403, detail=f"token rejected: {exc}") from exc
    sub = claims.get("preferred_username") or claims.get("sub")
    return {"sub": sub, "invoices": INVOICES.get(sub, [])}
