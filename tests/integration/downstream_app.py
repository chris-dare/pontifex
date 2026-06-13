"""Downstream 'billing' resource server for the integration stack.

A real OAuth resource server: it verifies the bearer token's signature against
Keycloak's JWKS and requires `aud` to include `billing-api`. A passthrough token
(audience = the Pontifex gateway) is rejected; only a token Pontifex *exchanged*
for this API's audience is accepted. Per-user data is keyed by the token subject,
proving the exchanged token carried the right user.
"""

import os

import httpx
from authlib.jose import JsonWebKey, JsonWebToken
from authlib.jose.errors import JoseError
from fastapi import FastAPI, Header, HTTPException

ISSUER = os.environ["OIDC_ISSUER"]
JWKS_URL = os.environ["OIDC_JWKS_URL"]
AUDIENCE = "billing-api"

app = FastAPI(title="Billing API", version="1.0.0")
_jwt = JsonWebToken(["RS256"])
_keyset = None

INVOICES = {
    "alice": [{"id": "INV-1", "amount": 42.0}],
    "bob": [{"id": "INV-9", "amount": 7.5}],
}


def _keys():
    global _keyset
    if _keyset is None:
        _keyset = JsonWebKey.import_key_set(httpx.get(JWKS_URL, timeout=5.0).json())
    return _keyset


@app.get("/invoices")
def invoices(authorization: str | None = Header(default=None)) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    token = authorization[len("Bearer ") :]
    try:
        claims = _jwt.decode(
            token,
            _keys(),
            claims_options={
                "iss": {"essential": True, "value": ISSUER},
                "aud": {"essential": True, "value": AUDIENCE},
            },
        )
        claims.validate()
    except JoseError as exc:
        # This is what a passthrough token (aud != billing-api) hits.
        raise HTTPException(status_code=403, detail=f"token rejected: {exc}") from exc
    sub = claims.get("preferred_username") or claims.get("sub")
    return {"sub": sub, "invoices": INVOICES.get(sub, [])}
