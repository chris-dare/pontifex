# How a request flows

There's one thing worth understanding: the **request path**.

Every call an agent makes travels the same way. Every guarantee Pontifex offers —
authentication, least privilege, audit — is a stage on that path. Understand the path
and you understand the product.

```mermaid
flowchart TB
    req["Request"] --> auth["Authenticate<br/>API key or JWT"]
    auth --> id["CallerIdentity"]
    id --> rl["Rate limit"]
    rl --> scope["Scope check"]
    scope --> tool["Tool handler"]
    tool --> audit["Audit log"]
```

Nothing reaches your code until the call has a verified identity, that identity is
within its rate limit, and its scopes permit the tool.

Nothing leaves without a row in the audit log.

That invariant is the whole point.

## Authentication

Two credential types. **One identity.**

<div class="grid cards" markdown>

-   __API keys__

    Tokens prefixed `sk_…`, for scripts, CI, and machine-to-machine callers. Hashed at
    rest — the plaintext is never stored.

-   __OAuth 2.1 JWTs__

    For interactive clients (Claude Desktop, agents). Validated against your provider's
    JWKS. Any OIDC provider works — Auth0, Entra, Clerk, Keycloak.

</div>

Both produce a **`CallerIdentity`**: a stable `owner_id`, the granted `scopes`, and a
`rate_limit_rpm`.

Downstream code never knows which credential was used. The scope check, the audit, the
rate limit — identical either way. (Wiring each path: [Authenticate
callers](../guides/authenticate-callers.md).)

!!! note

    JWT validation is asymmetric-only and rejects `alg: none`. A caller can't forge a
    claim to raise their rate limit or widen their scopes. Those come from server
    config, not the token.

## Scopes

Permissions look like this: **`domain:resource:action`**. For example,
`orders:order:read`.

A tool declares the scope it requires. The runtime checks it **before the handler
runs.**

| Scope | Grants |
| --- | --- |
| `orders:order:read` | one tool |
| `orders:*:read` | read across the whole domain |
| `orders:*:*` | full access to the domain |

Wildcards let you grant breadth on purpose, not by accident. A caller gets scopes from
their API key or their JWT claims — and can never expand them at runtime. The full
match rules are in [Errors & scopes](../reference/errors-and-scopes.md#scopes).

## The tool runtime

`tool_runtime` is the decorator that wraps each handler. It's where the guarantees
actually happen.

Around your code, it does four things:

1.  **Checks the scope.** No `domain:resource:action`? The call is denied with a
    structured error.
2.  **Runs your handler.** You return plain data. The one exception you raise is
    `InvalidInput`, for bad arguments.
3.  **Writes the audit row.** Who called, what, when, which data source, cache hit,
    latency.
4.  **Normalizes errors.** Success passes through unchanged. A raised error becomes a
    structured `ToolError` — no stack traces leak to the caller.

Your handler stays small and domain-focused. The cross-cutting concerns live in the
decorator, applied the same way to every tool.

## Data adapters

External calls don't happen inside a tool. They go through the **`DataAdapter`**
protocol.

A **`DataSourceManager`** orders adapters by health and tracks their success and
failure. So a tool can walk the available sources and **fail over** when one is down.

!!! tip

    Keeping I/O behind adapters is what makes tools testable and resilient. It's also
    where `Cache`, `async_retry`, and `CircuitBreaker` plug in. One flaky upstream is
    contained, not handed to the caller. Building one:
    [Resilient adapters](../guides/resilient-adapters.md).

## Connectors

Already have an OpenAPI spec? A [connector](../learn/connect-an-api.md) generates the
tools for you.

Each generated tool is still wrapped in `tool_runtime`, with a derived scope, still
calling through a `DataAdapter`. Same request path. Only the authoring changes.

That's how onboarding a system becomes config instead of code.

## Audit

Every tool call produces an **`AuditRecord`**, written by an **`AuditWriter`**.

- `DbAuditWriter` persists to Postgres. The production default.
- `NoopAuditWriter` discards. For tests.

This is the trail you need for compliance and incident response — the durable answer
to *who touched what, and when.* The writer is a protocol, so you can route audit
events to your own sink too.
