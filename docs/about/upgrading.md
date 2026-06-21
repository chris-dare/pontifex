# Upgrading

The steps to take when a release changes something you depend on. This page lists
breaking changes only. For everything that shipped in a version, read the
[release notes on GitHub](https://github.com/chris-dare/pontifex/releases).

Pontifex is pre-1.0, so pin the version you depend on and read this page before you bump a
minor.

---

## 0.5.0: domain → namespace

0.5.0 renames the **domain** concept to **namespace**: the first segment of a scope
(`namespace:resource:action`), plus the per-namespace schema and registry. You namespace a
server now.

Your scope values, API keys, tools, and auth configuration stay the same. Existing keys
keep authenticating as before. The rename touches terminology and three things you may
need to update.

### 1. Run the migration

```bash
pontifex-mcp db upgrade
```

`core_0005` renames the `audit_log.domain` column to `namespace` and the `domain_registry`
table to `namespace_registry`. It renames in place, so existing rows survive. On the SQLite
floor, `db upgrade` rebuilds the schema from the models and lands in the same place.

If you query the audit table from dashboards, exports, or ad-hoc SQL, rename `domain` to
`namespace` there too.

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

Pontifex still derives scopes as `namespace:resource:action`.

### 3. Update the renamed import

```python
from pontifex_mcp.models import NamespaceRegistryModel   # was: DomainRegistryModel
```

Most code never imports this. It lives on a deeper path that the public API marks as
internal.

### What stays the same

- `PontifexMCP("payments")` and `@mcp.tool(scope="balance:read")` keep their signatures.
- `ApiKeyAuth` / `JwtAuth` and the `AUTH_*` / `DATABASE_URL` / `REDIS_URL` env vars.
- The `pontifex-mcp` CLI commands and flags.
- Every stored scope value (`payments:balance:read`, `gse:*:*`, and the rest) and every
  issued API key.

!!! note "Contributors"
    The worked example moved from `domains/` to `examples/`, along with `tests/domains` and
    `alembic/domains`. This changes the repo layout. The published `pontifex-mcp` package
    and the `gse-mcp` module name stay the same.
