# Connect an existing API

The fastest way to govern a system is to write no code for it.

If the system you're exposing already has an **OpenAPI 3.x spec**, a connector reads
the spec and generates the tools. Each one is wrapped in the same `tool_runtime` as a
hand-written tool — same scope check, same audit row, same error envelope.

**Auto-generated does not mean ungoverned.**

## One config file

```yaml
# connectors.yaml
connectors:
  - domain: orders
    spec: https://api.internal/openapi.json   # URL or file path; JSON or YAML
    base_url: https://api.internal
    auth:
      type: bearer_env                        # how Pontifex authenticates downstream
      env_var: ORDERS_API_TOKEN
    include:                                  # the allowlist — nothing else is exposed
      - GET /orders
      - GET /orders/{order_id}
```

Point the server at it and start it. No domain module required.

```bash
export PONTIFEX_CONNECTORS_CONFIG=/app/connectors.yaml
```

Every included operation is now an authenticated, scoped, audited MCP tool.

!!! tip

    Want to mix generated and hand-written tools in one domain? The same generator is
    available in code as `register_openapi_tools` — see the
    [API reference](../reference/python-api.md#connectors).

## The allowlist is the safety

Exposure is **opt-in per operation.** It fails closed.

A spec with 200 operations exposes *zero* of them until you list each one. When the
upstream team adds endpoints, your MCP server doesn't change — not until someone
deliberately opts in. The blast radius of a careless upstream is nil.

And misconfiguration never means a silently different exposure. It means the server
refuses to boot:

| You write | What happens at startup |
| --- | --- |
| `- GET /orders` (exists in spec) | tool registered |
| `- GET /orers` (typo) | refuses to start, lists the operations the spec *does* have |
| `- POST /orders` without `allow_mutations: true` | refuses to start — mutating verbs need explicit enablement |
| `- POST /orders` with `allow_mutations: true` | tool registered; callers need the `write` scope |
| *(operation in spec, not in `include`)* | not a tool — agents can't see or call it |

## Scopes come for free

Each generated tool requires a `domain:resource:action` scope, derived from the
operation. So connector tools slot into the
[scope model](../concepts/request-path.md#scopes) unchanged — wildcards and all.

| Part | Derived from | `GET /orders/{order_id}` |
| --- | --- | --- |
| `domain` | the connector's `domain` | `orders` |
| `resource` | first static path segment | `orders` |
| `action` | the verb: GET→`read`, POST/PUT/PATCH→`write`, DELETE→`delete` | `read` |

A caller needs `orders:orders:read` (or `orders:*:read`, or `orders:*:*`) before the
call reaches the downstream API.

## Naming the tools

A tool is named `{domain}_{operation_id}`, snake-cased.

Specs with machine-generated operationIds (FastAPI's defaults, for example) produce
noisy names. Override them per operation:

```yaml
    names:
      GET /orders/{order_id}: get_order   # tool becomes orders_get_order
```

Only the operations you key change. Everything else keeps its spec-derived name. A
`names` key that doesn't match an included operation refuses to boot — same as an
`include` typo.

## What's next

You've exposed an API. Two things usually follow:

- **The backend needs to know *which* user is calling.** That's downstream
  authentication — service credentials vs. OAuth token exchange. See
  [Authenticate to your backend](../guides/downstream-auth.md).
- **You want to know it stays up.** Connector calls are circuit-broken and surface in
  `/health/ready`. See [Resilient adapters](../guides/resilient-adapters.md).

!!! note "v1 limits"

    Path and query parameters and `application/json` request bodies are supported.
    Header and cookie parameters are ignored. `$ref` resolution is local (`#/…`) only.
    Responses are not cached (`cache_hit` is always `false`).
