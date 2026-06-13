# Token-exchange e2e (#41)

A full end-to-end test of the `token_exchange` connector against a **real
Keycloak** (RFC 8693), proving per-user downstream delegation works through the
real HTTP path — including `AuthMiddleware` validating the caller's signed JWT
and capturing the subject token (the one path the in-process unit tests can't
cover).

## Stack (`docker-compose.yml`)

| Service | Role |
| --- | --- |
| `keycloak` | OIDC provider + RFC 8693 token exchange; realm imported from `keycloak/realm-pontifex.json` |
| `postgres` / `redis` | Pontifex audit log + rate limiting (required by the HTTP app) |
| `migrate` | one-shot `alembic upgrade heads` |
| `downstream` | a resource server (`downstream_app.py`) that verifies the bearer token's signature **and audience** (`billing-api`) against Keycloak's JWKS |
| `pontifex` | the Pontifex HTTP MCP server (`pontifex_app.py`), connectors-only, with a `token_exchange` connector (`connectors.yaml`) |
| `test` | the assertions (`run_e2e.py`) |

## Run

```bash
cd tests/e2e
docker compose up -d --build        # bring up the stack (Keycloak ~30s to import)
docker compose run --rm test        # run the e2e checks
docker compose down -v              # tear down
```

## What it proves

No human in the loop: the test mints user tokens via the **ROPC** grant (no
browser), and Keycloak is configured declaratively via realm import.

1. **Passthrough is rejected** — a user's own token (`aud=pontifex`) sent
   straight to the downstream → **403**. Exchange is necessary.
2. **alice** → Pontifex exchanges her token (`aud`→`billing-api`, sub preserved)
   → downstream returns *alice's* invoice.
3. **bob** → his own delegated token → *bob's* invoice (per-user).
4. **No credential** → Pontifex returns **401** before MCP.

## Keycloak realm notes

Standard Token Exchange (Keycloak 26.2+) has two requirements the realm config
satisfies, both learned the hard way:

- The **exchanging client** (`pontifex`) must be in the subject token's
  audience — so `mcp-cli` adds `pontifex` to the user token's `aud`
  (`AUTH_AUDIENCE=pontifex`).
- The **target audience** (`billing-api`) must be an *available* audience for
  the exchanging client — so the `pontifex` client carries an audience mapper
  for `billing-api`.
