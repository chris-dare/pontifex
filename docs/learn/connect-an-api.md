# Connect an existing API

If a system already has an OpenAPI 3.x spec, you don't write handler code for it.
Point Pontifex at the spec, list the operations you want to expose, and it wraps them
as governed MCP tools: authenticated, scoped, and audited the same as anything you
write by hand.

## One config file, zero handlers

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

Point the server at it before you start:

```bash
export PONTIFEX_CONNECTORS_CONFIG=/app/connectors.yaml
python main.py
```

Open [MCP Inspector](https://github.com/modelcontextprotocol/inspector) and the
generated tools appear under Tools, ready to call. No server code written.

!!! tip
    Want to mix generated and hand-written tools in one server? The same generator is
    available in code as `register_openapi_tools`. See the
    [API reference](../reference/python-api.md#connectors).

## The allowlist is the safety

Exposure is **opt-in per operation.** It fails closed.

A spec with 200 operations exposes *zero* of them until you list each one. When the
upstream team adds endpoints, your MCP server doesn't change until someone opts in.

Misconfiguration never gives you a silently different exposure. The server refuses to
boot:

| You write | What happens at startup |
| --- | --- |
| `- GET /orders` (exists in spec) | tool registered |
| `- GET /orers` (typo) | refuses to start, lists the operations the spec *does* have |
| `- POST /orders` without `allow_mutations: true` | refuses to start; mutating verbs need explicit opt-in |
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

Tools are named `{domain}_{operation_id}`, snake-cased. Specs with machine-generated
operationIds (FastAPI's defaults, for example) produce noisy names. Override them per
operation:

```yaml
    names:
      GET /orders/{order_id}: get_order   # tool becomes orders_get_order
```

Only the operations you key change. Everything else keeps its spec-derived name. A
`names` key that doesn't match an included operation refuses to boot, same as an
`include` typo.

## Verify it works

Start the server and check three things:

```bash
export PONTIFEX_CONNECTORS_CONFIG=/app/connectors.yaml
python main.py
# then:
curl http://localhost:8080/health/ready
```

- **It booted.** A typo in `include` or `names` refuses to start, so a clean boot
  means every allowlisted operation resolved.
- **The connector is healthy.** `/health/ready` lists it as `connector:<domain>` (e.g.
  `connector:orders`).
- **The tool is governed.** Calling it without `orders:orders:read` returns a `403`
  before it touches the downstream.

## Hand it to a coding agent

Have a spec but don't want to hand-write the allowlist? Paste this to a coding agent
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

Then tell me which scope each generated tool will require.
```

## What's next

- **The backend needs to know which user is calling.** Service credentials vs. OAuth
  token exchange: see [Authenticate to your backend](../guides/downstream-auth.md).
- **You want to know it stays up.** Connector calls are circuit-broken and surface in
  `/health/ready`: see [Resilient adapters](../guides/resilient-adapters.md).

!!! note "v1 limits"
    Path and query parameters and `application/json` request bodies are supported.
    Header and cookie parameters are ignored. `$ref` resolution is local (`#/…`) only.
    Responses are not cached (`cache_hit` is always `false`).
