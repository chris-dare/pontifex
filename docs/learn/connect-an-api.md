# Connect an existing API

The fastest way to govern a system is to write no code for it.

If the system you're exposing already has an **OpenAPI 3.x spec**, a connector reads
the spec and generates the tools. Each one wraps in the same `tool_runtime` as a
hand-written tool, with the same scope check, audit row, and error envelope.

Pontifex governs a generated tool the same way it governs one you write by hand.

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
    available in code as `register_openapi_tools`. See the
    [API reference](../reference/python-api.md#connectors).

## The allowlist is the safety

Exposure is **opt-in per operation.** It fails closed.

A spec with 200 operations exposes *zero* of them until you list each one. When the
upstream team adds endpoints, your MCP server doesn't change until someone opts in. A
careless upstream changes nothing you expose.

Misconfiguration never gives you a silently different exposure. The server refuses to
boot:

| You write | What happens at startup |
| --- | --- |
| `- GET /orders` (exists in spec) | tool registered |
| `- GET /orers` (typo) | refuses to start, lists the operations the spec *does* have |
| `- POST /orders` without `allow_mutations: true` | refuses to start; mutating verbs need explicit enablement |
| `- POST /orders` with `allow_mutations: true` | tool registered; callers need the `write` scope |
| *(operation in spec, not in `include`)* | not a tool; agents can't see or call it |

## Scopes come for free

Each generated tool requires a `domain:resource:action` scope, derived from the
operation. Connector tools slot into the
[scope model](../concepts/request-path.md#scopes) unchanged, wildcards and all.

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
`names` key that doesn't match an included operation refuses to boot, same as an
`include` typo.

## Verify it works

Start the server with the config set, and check three things:

```bash
export PONTIFEX_CONNECTORS_CONFIG=/app/connectors.yaml
# start your server, then:
curl http://localhost:8080/health/ready
```

- **It booted.** A typo in `include` or `names` refuses to start, so a clean boot means
  every allowlisted operation resolved.
- **The connector is healthy.** `/health/ready` lists it as `connector:<domain>` (e.g.
  `connector:orders`).
- **The tool is governed.** Calling it needs the derived scope, `orders:orders:read`
  for `GET /orders`. Pontifex rejects a caller without it before it touches the
  downstream.

## Hand it to a coding agent

Have a spec but don't want to hand-write the allowlist? Paste this to a coding agent,
with your spec URL and the operations you want exposed:

```text
Create a Pontifex connectors.yaml for the OpenAPI spec at <SPEC_URL>.

- domain: <orders>
- base_url: <https://api.internal>
- Expose ONLY these operations (allowlist): <GET /orders, GET /orders/{order_id}>
- Downstream auth: bearer token from the env var <ORDERS_API_TOKEN>.
- If any listed operation isn't in the spec, stop and show me the operations the
  spec actually has — don't guess.
- For any operation with a noisy machine-generated operationId, add a `names:`
  override to give the tool a clean name.

Then tell me to set PONTIFEX_CONNECTORS_CONFIG to the file's path, and which scope
each generated tool will require.
```

## What's next

You've exposed an API. Two things usually follow:

- **The backend needs to know *which* user is calling.** That's downstream
  authentication: service credentials vs. OAuth token exchange. See
  [Authenticate to your backend](../guides/downstream-auth.md).
- **You want to know it stays up.** Connector calls are circuit-broken and surface in
  `/health/ready`. See [Resilient adapters](../guides/resilient-adapters.md).

!!! note "v1 limits"

    Path and query parameters and `application/json` request bodies are supported.
    Header and cookie parameters are ignored. `$ref` resolution is local (`#/…`) only.
    Responses are not cached (`cache_hit` is always `false`).
