# Errors & scopes

The two contracts a caller has to reason about: the scopes that grant access, and the
errors returned when something is wrong.

## Scopes

A scope is `namespace:resource:action`, lowercase, colon-separated. For example,
`orders:order:read`.

A tool declares the scope it requires. `scopes_match` checks the caller's scopes
against it, **case-insensitively**, accepting any of four patterns:

| Pattern | Grants |
| --- | --- |
| `namespace:*:*` | every resource and action in the namespace |
| `namespace:*:action` | one action across every resource (e.g. read-only) |
| `namespace:resource:*` | every action on one resource |
| `namespace:resource:action` | exactly one action on one resource |

A caller satisfies the check if **any** of their scopes matches one of these patterns
for the required `namespace` / `resource` / `action`. If none match, the call is rejected
with `scope_denied`.

```python
from pontifex_mcp import scopes_match

scopes_match(["orders:*:read"], "orders", "order", "read")    # True
scopes_match(["orders:order:read"], "orders", "order", "write")  # False
```

Scopes are granted by the caller's API key or their verified JWT claims, and are never
expanded at runtime. Issuing them: [Authenticate
callers](../guides/authenticate-callers.md).

## Error codes

A tool error is returned as a structured `ToolError`, not a stack trace. Messages are
written for an agent to act on: what went wrong, and what to do next.

| Code | Status | Retry | Meaning |
| --- | --- | --- | --- |
| `auth_failed` | 401 | No | No valid identity: missing, invalid, expired, or revoked credential. |
| `scope_denied` | 403 | No | Valid identity, but missing the required scope. |
| `rate_limited` | 429 | Yes | Caller's request rate exceeded. Returned by the middleware before the tool runs. |
| `invalid_input` | 400 | No | Bad argument, e.g. an unknown value, or an API-key caller hitting a token-exchange connector. |
| `source_unavailable` | 503 | Yes | All data sources failed or are circuit-broken. Includes `retry_after_seconds` (30). |
| `internal_error` | 500 | Yes | Unexpected server error. |

`auth_failed`, `scope_denied`, and `invalid_input` are **caller errors**: retrying
without changing the request won't help. `rate_limited`, `source_unavailable`, and
`internal_error` are **transient**: retry, honoring `retry_after_seconds` when present.

## The error envelope

```python
class ToolError:
    error_code: str                  # one of the codes above
    message: str                     # human- and agent-readable
    status: int                      # HTTP-style status
    retry: bool                      # should the caller retry?
    retry_after_seconds: int | None  # set on source_unavailable
    detail: str | None               # optional extra context
```

Raise `InvalidInput` inside a handler to return `invalid_input` cleanly. The runtime
produces every other code; you don't construct them by hand.
