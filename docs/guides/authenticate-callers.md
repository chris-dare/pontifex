# Authenticate callers

Every tool requires a verified identity. This guide is how callers get one.

There are two kinds of caller, and a credential type for each:

- **Scripts, CI, machine-to-machine** present an `sk_…` **API key**.
- **Interactive clients** (Claude Desktop, your own agents) present an **OAuth 2.1
  JWT** from your provider.

Both resolve to the same `CallerIdentity` and hit the same scope check. Pick whichever
fits the caller, or use both.

## API keys

An API key is an `sk_…` bearer token. The caller sends it as
`Authorization: Bearer sk_…`.

Pontifex doesn't mint keys. It **reads and enforces** them. An upstream system you
control (an admin tool, a CLI, a config file) provisions the key with a set of scopes,
and Pontifex validates each call against them.

### Provision a key

A key record carries an identity, the granted scopes, and a rate limit. The plaintext
is shown once; only its hash is stored.

```python
import hashlib, secrets

raw_key = "sk_live_" + secrets.token_urlsafe(32)
key_hash = hashlib.sha256(raw_key.encode()).hexdigest()

# Write to your store with the scopes this caller may use:
#   owner_label   = "Kwame's Claude Desktop"
#   key_hash      = key_hash
#   scopes        = ["orders:order:read"]
#   rate_limit_rpm = 120

print(f"Give this to the caller (shown once): {raw_key}")
```

!!! tip "Key environments"

    The `sk_<env>_` prefix marks the environment: `sk_live_` in production,
    `sk_test_` / `sk_uat_` for CI and ephemeral envs. They all share the `sk_`
    discriminator the middleware routes on, so a test key can never be mistaken for a
    JWT.

### Scope it to the minimum

Scopes are `domain:resource:action`. Grant the least that does the job.

| Give the caller | If they should… |
| --- | --- |
| `orders:order:read` | call exactly one tool |
| `orders:*:read` | read anything in the `orders` domain |
| `orders:*:*` | do anything in the `orders` domain |

Full rules and wildcard behavior: [Errors & scopes](../reference/errors-and-scopes.md#scopes).

## OAuth 2.1 (interactive clients)

For clients where a *human* logs in, use OAuth. Pontifex is a pure **resource
server**: it validates the JWT your provider issues and maps its claims to a
`CallerIdentity`. It never runs a login UI and never mints tokens.

!!! tip "New to OAuth?"

    This section is the reference. For a click-by-click walkthrough that covers creating
    the API, defining permissions, and filling in the variables (with a copy-paste prompt
    for a coding agent), follow [Set up OAuth, step by step](oauth-setup.md).

### Point it at your provider

Set the `AUTH_*` environment variables. That's what turns the JWT path on.

```bash
AUTH_JWKS_URL=https://your-provider.example/.well-known/jwks.json
AUTH_ISSUER=https://your-provider.example/
AUTH_AUDIENCE=<the resource-server identifier your token's `aud` carries>
AUTH_SCOPES_CLAIM=permissions     # Auth0; Entra: scp or roles
AUTH_AUTHORIZATION_SERVER=https://your-provider.example/
PUBLIC_BASE_URL=https://your-deployment.example
```

Any OIDC provider works: Auth0, Microsoft Entra, Clerk, Keycloak. To switch providers,
edit the config; the code stays the same.

### Clients bootstrap themselves

A client holding no credentials gets a `401` with a `WWW-Authenticate` challenge
pointing at `/.well-known/oauth-protected-resource` (RFC 9728). Spec-compliant MCP
clients read that, find your authorization server, and run the login flow on their own.
No out-of-band setup.

!!! note "Map roles to scopes"

    Your provider's roles and permissions need to land in the configured scopes claim
    as `domain:resource:action` strings. If your provider supports a post-login hook,
    use it to grant new users a read-only role.

## Why both paths are safe

Whichever credential a caller presents, the same rules apply downstream:

- Scopes and rate limits come from **server configuration and verified claims**, never
  from anything the caller can set.
- JWT validation is **asymmetric-only** and rejects `alg: none`.
- A rejected credential returns one generic message, with no hint about *why* it failed.

The full model is in [Security](../concepts/security.md).
