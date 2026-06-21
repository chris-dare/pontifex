"""Packaged Alembic migrations for the platform (`pontifex_mcp_core`) schema.

Shipped inside the wheel so a `pip install pontifex-mcp` user can create or
update the schema with `pontifex-mcp db upgrade` — no source checkout, no
hand-copied DDL. `db upgrade` resolves this package via `importlib.resources`.

Namespace migrations (e.g. the GSE demo) stay in the monorepo's `alembic/` tree;
they're examples, not library code.
"""
