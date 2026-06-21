# Authenticate to your backend

A [connector](../learn/connect-an-api.md) calls a backend on the caller's behalf. How
it authenticates to *that backend* is independent of how the caller authenticated to
Pontifex.

One question decides which mode you want:

**Does the backend need to know *which* user is calling?**

- **No, it only needs to trust Pontifex.** Use a *service credential*: one identity
  for every caller.
- **Yes, it enforces its own per-user permissions.** Use *token exchange*: Pontifex
  swaps the caller's token for a downstream one minted for that user.

## Service credential

The right default for most internal APIs. Per-user authorization still happens at
Pontifex's scope layer, and the audit log still records who made each call. The
backend sees one trusted identity.

`bearer_env`
:   Sends `Authorization: Bearer <token>`, read from the named environment variable.

`header_env` *(add a `header:` name)*
:   Sends a static header (e.g. `X-API-Key`), read from the named environment variable.

```yaml
    auth:
      type: bearer_env
      env_var: ORDERS_API_TOKEN
```

A missing variable fails at startup. The value is re-read on every request, so rotating
the secret doesn't need a restart.

## Token exchange (per-user)

For a backend that shares your OAuth provider and enforces per-user authorization.

Pontifex takes the caller's inbound token and exchanges it at the IdP
([RFC 8693](https://www.rfc-editor.org/rfc/rfc8693)) for a *new* token carrying the
backend's audience, on behalf of the user. The downstream then applies that user's own
permissions.

```yaml
    auth:
      type: token_exchange
      token_endpoint: https://idp.example.com/oauth/token
      audience: https://api.internal              # the downstream's audience
      client_id_env: PONTIFEX_OAUTH_CLIENT_ID     # Pontifex's own IdP client,
      client_secret_env: PONTIFEX_OAUTH_CLIENT_SECRET  # presence checked at boot
```

The caller's token is **never forwarded as-is.** No passthrough. A token minted for
Pontifex's audience wouldn't be accepted downstream, and forwarding it would break the
trust chain.

!!! warning "API-key callers can't use this"

    A connector is *either* service-auth *or* user-auth, never both. API-key callers
    carry no token to exchange, so a `token_exchange` connector rejects them with a
    clear `invalid_input`. If a backend needs both modes, define two
    connector entries with distinct namespaces.

### Provider differences

The request is plain RFC 8693, so any compliant provider works: Keycloak, Auth0,
Microsoft Entra (on-behalf-of), Okta. Two things differ per provider:

- **What `audience` means.** It's the downstream's identifier as your provider expects
  it: a client ID (Keycloak), an API identifier URL (Auth0), a resource/scope (Entra).
  Set it to whatever your provider puts in the exchanged token's `aud`.
- **Provider-side authorization.** Each provider gates which clients may exchange for
  which audiences in its own model. That setup lives in your IdP, not in Pontifex.

Two optional knobs cover protocol differences:

- `client_auth: post` *(default)* sends client credentials in the form. `basic` sends
  them as an HTTP Basic header, for providers that require it.
- `default_ttl_seconds`. `expires_in` is optional in RFC 8693. By default Pontifex
  rejects a response without it, since it can't size the cache TTL. Set this to supply a
  fallback.

## The exchanged-token cache

Pontifex caches exchanged tokens so a user's repeated calls don't re-hit the IdP. The
backend is a deployment-level setting:

- `PONTIFEX_TOKEN_CACHE=memory` *(default)*: in-process only. Tokens never leave the
  process or hit disk. Each worker caches on its own.
- `PONTIFEX_TOKEN_CACHE=redis`: shared across workers via Redis (reuses `REDIS_URL`).
  Pontifex encrypts the tokens **at rest** with a Fernet key from `PONTIFEX_TOKEN_CACHE_KEY`:

  ```bash
  python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
  ```

  A Redis dump yields only ciphertext. The key lives in the environment, not in Redis.
  Missing `REDIS_URL` or `PONTIFEX_TOKEN_CACHE_KEY` fails at startup.

!!! note

    Using a managed KMS instead of an env-held key is tracked in
    [#52](https://github.com/chris-dare/pontifex/issues/52).

## What you can observe

With Logfire configured, the token-exchange path emits metrics. Labels cover audience,
outcome, and cache result only, never tokens:

- `pontifex.token_exchange.requests`, by `outcome` (`ok` / `rejected` / `unavailable`
  / `error`).
- `pontifex.token_exchange.duration_ms`, the IdP exchange latency.
- `pontifex.token_cache.requests`, by `result` (`hit` / `miss` / `coalesced`).

The IdP sits on the call path. Its failures surface as `source_unavailable`, and
Pontifex circuit-breaks them independently of the downstream. A refused exchange surfaces
as `invalid_input`.
