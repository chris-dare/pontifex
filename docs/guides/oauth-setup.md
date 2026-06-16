# Set up OAuth, step by step

[Authenticate callers](authenticate-callers.md) tells you *which* variables to set. This
guide covers the other half: how to create the provider config they point at, click by
click.

Read it if OAuth isn't your home turf yet. There's a [copy-paste prompt](#hand-it-to-a-coding-agent)
at the end if you'd rather hand the whole thing to a coding agent.

We'll use **Auth0** as the worked example. It's the most common starting point, and the
steps map to any provider (see [Other providers](#other-providers)).

## The mental model

Three sentences and you've got it:

1. Pontifex is a **resource server.** It *validates* a token. It never logs anyone in.
2. Your **IdP** (Auth0) does the login and **mints the token**, stamped with an
   audience and a list of permissions.
3. The **client** (Claude Desktop, your agent) gets that token and sends it. Pontifex
   checks the signature, the audience, and the scopes, then runs the tool.

The setup, then: tell Auth0 about your API, define the permissions, and copy six
values into your environment.

!!! info "Before you start"

    You need an Auth0 tenant (the free tier is fine) and your Pontifex server's public
    URL, call it `https://your-server.example`. Have your tool scopes in mind, in
    `domain:resource:action` form (e.g. `orders:order:read`).

## Step 1: create the API

In Auth0, an "API" *is* your resource server.

1. Auth0 Dashboard → **Applications → APIs → Create API**.
2. **Name**: anything (e.g. `Pontifex`).
3. **Identifier**: a URL-like string that becomes your **audience**. Use your server URL:
   `https://your-server.example`. It's an identifier, so it doesn't have to resolve.
4. Leave the signing algorithm as **RS256**. Pontifex accepts asymmetric
   signatures only, and RS256 is one.

The Identifier you typed is your `AUTH_AUDIENCE`. Keep it handy.

## Step 2: define your permissions

These are your scopes. They have to match what your tools require, exactly.

1. Open the API → **Permissions** tab.
2. Add one row per scope, in `domain:resource:action` form:

   | Permission | Description |
   | --- | --- |
   | `orders:order:read` | Read a single order |
   | `orders:*:read` | Read anything in orders |

Add every scope your tools check. (Recap of the scope model:
[Errors & scopes](../reference/errors-and-scopes.md#scopes).)

## Step 3: put the permissions in the token

By default Auth0 won't include permissions in the access token. Turn that on.

1. API → **Settings** tab.
2. Enable **RBAC**.
3. Enable **Add Permissions in the Access Token**.
4. Save.

Now every token Auth0 mints carries a **`permissions`** array, the claim Pontifex reads.
That's why `AUTH_SCOPES_CLAIM=permissions` for Auth0.

## Step 4: register the client

The client is the app the human logs into: Claude Desktop, or your own agent.

1. Auth0 → **Applications → Applications → Create Application**.
2. Pick **Native** for a desktop client like Claude Desktop (or **Single-Page** for a
   browser app).
3. In the application's settings, note the **Client ID**. That's what you give the
   client to connect.

!!! note "Why pre-register?"

    Some MCP clients can self-register via Dynamic Client Registration. Auth0 restricts
    self-registered clients from custom APIs, so the reliable path is this one
    pre-registered app. Pontifex works with either. It validates the resulting token.
    (Background:
    [authenticating callers](authenticate-callers.md#oauth-21-interactive-clients).)

## Step 5: grant permissions to users

A user only gets a scope in their token if they're assigned it.

The quick way: **User Management → Roles → Create Role** (e.g. `orders-reader`), add
the permissions from Step 2, then assign the role to your user. For a first test you can
assign permissions to a single user directly.

## Step 6: fill in the environment

You now have every value. Each one comes from a step above:

```bash
# Replace your-tenant and the region to match your Auth0 domain.
AUTH_ISSUER=https://your-tenant.us.auth0.com/                              # trailing slash matters
AUTH_JWKS_URL=https://your-tenant.us.auth0.com/.well-known/jwks.json
AUTH_AUDIENCE=https://your-server.example                                  # the API Identifier from Step 1
AUTH_SCOPES_CLAIM=permissions                                              # Auth0 puts scopes here
AUTH_AUTHORIZATION_SERVER=https://your-tenant.us.auth0.com/
PUBLIC_BASE_URL=https://your-server.example                               # your server's real public URL
```

Setting the `AUTH_*` group is what turns the OAuth path on. Restart the server.

## Verify it works

Three checks. The first two need no client.

**1. Discovery is advertised.**

```bash
curl https://your-server.example/.well-known/oauth-protected-resource
```

You should see your `authorization_servers` pointing at the Auth0 domain.

**2. Unauthenticated calls are challenged.** A request with no token returns `401` with
a `WWW-Authenticate: Bearer …` header naming that discovery URL. MCP clients follow that
breadcrumb.

**3. A real token carries the right claims.** Grab an access token from Auth0's API →
**Test** tab and decode it at [jwt.io](https://jwt.io). Confirm:

- `aud` includes your `AUTH_AUDIENCE`
- `permissions` lists the scopes you granted

If both are right, a scoped call will pass the scope check. If `permissions` is empty,
revisit Steps 3 and 5.

## Hand it to a coding agent

To skip the clicking, paste this to a coding agent that has access to your
Auth0 tenant (the [Auth0 CLI](https://github.com/auth0/auth0-cli) or the Management
API). Fill in the three placeholders first.

```text
Set up Auth0 as the OAuth provider for my Pontifex MCP server. Use the Auth0 CLI
(or Management API) against my current tenant. Goal end-state:

1. An Auth0 API (resource server) named "Pontifex" with
   Identifier = "https://your-server.example", signing alg RS256.
2. These permissions defined on that API: orders:order:read, orders:*:read
   (replace with my actual tool scopes).
3. On that API, enable RBAC and "Add Permissions in the Access Token"
   (token_dialect = access_token_authz) so tokens include a `permissions` array.
4. A Native application named "Pontifex MCP Client"; report its Client ID.
5. A role "orders-reader" holding those permissions, assigned to user
   <my-email@example.com>.

Then output a .env block with exactly these six variables, filled in from the
tenant: AUTH_ISSUER, AUTH_JWKS_URL, AUTH_AUDIENCE, AUTH_SCOPES_CLAIM (=permissions),
AUTH_AUTHORIZATION_SERVER, PUBLIC_BASE_URL (=https://your-server.example).

Don't print any client secret. Confirm each step as you complete it.
```

The prompt states the end-state, not brittle flags, so a capable agent picks the right
commands and you stay provider-correct.

## Other providers

The same six variables work everywhere. Only three values change shape:

| | Auth0 | Microsoft Entra | Keycloak |
| --- | --- | --- | --- |
| `AUTH_ISSUER` | `https://TENANT.auth0.com/` | `https://login.microsoftonline.com/TENANT/v2.0` | `https://HOST/realms/REALM` |
| `AUTH_JWKS_URL` | `…/.well-known/jwks.json` | `…/discovery/v2.0/keys` | `…/protocol/openid-connect/certs` |
| `AUTH_SCOPES_CLAIM` | `permissions` | `scp` or `roles` | a claim you map (e.g. roles) |

The rest of the flow is the same: create an API/app registration, define scopes as
`domain:resource:action`, make sure they land in the configured claim, and assign them
to users. Switching providers is a config change, not a code change.

## Next

- Issuing `sk_…` keys for scripts and CI: [Authenticate callers](authenticate-callers.md#api-keys).
- What every variable means: [Configuration](../reference/configuration.md).
- Why the strict validation matters: [Security model](../concepts/security.md#authentication).
