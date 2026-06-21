# Upgrading

What you need to do when a release changes something you depend on. This page covers
**breaking changes only** — for the full list of what shipped in each version, see the
[**release notes on GitHub →**](https://github.com/chris-dare/pontifex/releases) (that's
the changelog; this page is the migration steps).

Pontifex is pre-1.0, so pin the version you depend on and read this page before bumping a
minor.

---

## 0.5.0 — `domain` → `namespace`

0.5.0 renames the **domain** concept to **namespace**: the first segment of a scope
(`namespace:resource:action`) and the per-namespace schema and registry. A server is now
described as being *namespaced*, rather than as "a domain".

**Your scope values, API keys, tools, and auth configuration do not change.** Existing
keys keep authenticating exactly as before — the rename is terminology plus a few
identifiers. Three things need updating:

### 1. Run the migration

```bash
pontifex-mcp db upgrade
```

This applies `core_0005`, which renames `audit_log.domain` → `audit_log.namespace` and the
`domain_registry` table → `namespace_registry`. Existing rows are **preserved** — these are
column and table renames, not drop-and-recreate. On the SQLite floor the schema is rebuilt
from the models, with the same result.

If you read the audit table directly (dashboards, exports, ad-hoc SQL), update any
reference to the `domain` column → `namespace`.

### 2. Rename the connector YAML field

If you drive connectors from a config file (`PONTIFEX_CONNECTORS_CONFIG`), rename the
`domain:` key to `namespace:` on each entry:

```yaml
connectors:
  - namespace: orders      # was:  domain: orders
    base_url: https://api.example.com
    spec: https://api.example.com/openapi.json
    include: ["GET /orders/{id}"]
```

Scopes are still derived as `namespace:resource:action`.

### 3. Update the renamed import (only if you used it)

```python
from pontifex_mcp.models import NamespaceRegistryModel   # was: DomainRegistryModel
```

Most users never import this — it's a deeper-path internal, not part of the top-level
public API.

### What did not change

- `PontifexMCP("payments")` and `@mcp.tool(scope="balance:read")` — same signatures.
- `ApiKeyAuth` / `JwtAuth` and the `AUTH_*` / `DATABASE_URL` / `REDIS_URL` env vars.
- The `pontifex-mcp` CLI commands and flags.
- **Every stored scope value** (`payments:balance:read`, `gse:*:*`, …) and every issued
  API key.

!!! note "Contributors"
    The worked example moved from `domains/` to `examples/` (and `tests/domains` →
    `tests/examples`, `alembic/domains` → `alembic/examples`). This affects the repo
    layout only — not the published `pontifex-mcp` package or the `gse-mcp` module name.
