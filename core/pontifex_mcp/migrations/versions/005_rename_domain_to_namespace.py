"""rename domain → namespace

Renames the `domain` column on `audit_log`, the `domain_registry` table and its
`domain` primary key, and the `idx_audit_domain` index. Column renames preserve
data — stored scope values (e.g. `payments:balance:read`) are unaffected; only the
identifier the first segment is *called* changes.

Revision ID: core_0005
Revises: core_0004
"""

from alembic import op

revision = "core_0005"
down_revision = "core_0004"
branch_labels = None
depends_on = None

_SCHEMA = "pontifex_mcp_core"


def upgrade() -> None:
    op.alter_column("audit_log", "domain", new_column_name="namespace", schema=_SCHEMA)
    op.execute(f"ALTER INDEX {_SCHEMA}.idx_audit_domain RENAME TO idx_audit_namespace")
    op.rename_table("domain_registry", "namespace_registry", schema=_SCHEMA)
    op.alter_column("namespace_registry", "domain", new_column_name="namespace", schema=_SCHEMA)


def downgrade() -> None:
    op.alter_column("namespace_registry", "namespace", new_column_name="domain", schema=_SCHEMA)
    op.rename_table("namespace_registry", "domain_registry", schema=_SCHEMA)
    op.execute(f"ALTER INDEX {_SCHEMA}.idx_audit_namespace RENAME TO idx_audit_domain")
    op.alter_column("audit_log", "namespace", new_column_name="domain", schema=_SCHEMA)
