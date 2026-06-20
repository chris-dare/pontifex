"""create audit_log

Revision ID: core_0002
Revises: core_0001
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import INET, JSONB

from alembic import op

revision = "core_0002"
down_revision = "core_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("domain", sa.Text, nullable=False),
        sa.Column("key_id", sa.Text, nullable=False),
        sa.Column("owner_id", sa.Text, nullable=False),
        sa.Column("owner_label", sa.Text, nullable=False),
        sa.Column("transport", sa.Text, nullable=False),
        sa.Column("tool_name", sa.Text, nullable=False),
        sa.Column("tool_params", JSONB, nullable=False),
        sa.Column("data_source", sa.Text, nullable=False),
        sa.Column("cache_hit", sa.Boolean, nullable=False),
        sa.Column("response_ms", sa.Integer, nullable=False),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("ip_address", INET, nullable=True),
        schema="pontifex_mcp_core",
    )
    op.create_index("idx_audit_timestamp", "audit_log", [sa.text("timestamp DESC")], schema="pontifex_mcp_core")
    op.create_index(
        "idx_audit_domain", "audit_log", ["domain", sa.text("timestamp DESC")], schema="pontifex_mcp_core"
    )
    op.create_index(
        "idx_audit_key", "audit_log", ["key_id", sa.text("timestamp DESC")], schema="pontifex_mcp_core"
    )
    op.create_index(
        "idx_audit_owner", "audit_log", ["owner_id", sa.text("timestamp DESC")], schema="pontifex_mcp_core"
    )
    op.create_index(
        "idx_audit_tool", "audit_log", ["tool_name", sa.text("timestamp DESC")], schema="pontifex_mcp_core"
    )


def downgrade() -> None:
    op.drop_index("idx_audit_tool", table_name="audit_log", schema="pontifex_mcp_core")
    op.drop_index("idx_audit_owner", table_name="audit_log", schema="pontifex_mcp_core")
    op.drop_index("idx_audit_key", table_name="audit_log", schema="pontifex_mcp_core")
    op.drop_index("idx_audit_domain", table_name="audit_log", schema="pontifex_mcp_core")
    op.drop_index("idx_audit_timestamp", table_name="audit_log", schema="pontifex_mcp_core")
    op.drop_table("audit_log", schema="pontifex_mcp_core")
