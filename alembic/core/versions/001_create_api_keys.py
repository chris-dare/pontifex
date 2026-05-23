"""create api_keys

Revision ID: core_0001
Revises:
Create Date: 2026-05-23
"""

import sqlalchemy as sa

from alembic import op

revision = "core_0001"
down_revision = None
branch_labels = ("core",)
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS core")
    op.create_table(
        "api_keys",
        sa.Column("key_id", sa.Text, primary_key=True),
        sa.Column("key_hash", sa.Text, nullable=False, unique=True),
        sa.Column("owner_id", sa.Text, nullable=False),
        sa.Column("owner_label", sa.Text, nullable=False),
        sa.Column("scopes", sa.ARRAY(sa.Text), nullable=False),
        sa.Column("rate_limit_rpm", sa.Integer, nullable=False, server_default="60"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        schema="core",
    )
    op.create_index("idx_api_keys_hash", "api_keys", ["key_hash"], schema="core")
    op.create_index("idx_api_keys_owner", "api_keys", ["owner_id"], schema="core")


def downgrade() -> None:
    op.drop_index("idx_api_keys_owner", table_name="api_keys", schema="core")
    op.drop_index("idx_api_keys_hash", table_name="api_keys", schema="core")
    op.drop_table("api_keys", schema="core")
