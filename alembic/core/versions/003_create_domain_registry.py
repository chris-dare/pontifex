"""create domain_registry

Revision ID: core_0003
Revises: core_0002
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "core_0003"
down_revision = "core_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "domain_registry",
        sa.Column("domain", sa.Text, primary_key=True),
        sa.Column("display_name", sa.Text, nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("config_json", JSONB, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        schema="core",
    )


def downgrade() -> None:
    op.drop_table("domain_registry", schema="core")
