"""add delegated_audience to audit_log

Revision ID: core_0004
Revises: core_0003
"""

import sqlalchemy as sa

from alembic import op

revision = "core_0004"
down_revision = "core_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Nullable, no backfill: existing rows keep NULL (no delegation recorded).
    op.add_column(
        "audit_log",
        sa.Column("delegated_audience", sa.Text, nullable=True),
        schema="core",
    )


def downgrade() -> None:
    op.drop_column("audit_log", "delegated_audience", schema="core")
