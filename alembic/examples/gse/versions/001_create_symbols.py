"""create gse.symbols

Revision ID: gse_0001
Revises:
"""

import sqlalchemy as sa

from alembic import op

revision = "gse_0001"
down_revision = None
branch_labels = ("gse",)
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS gse")
    op.create_table(
        "symbols",
        sa.Column("ticker", sa.Text, primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("sector", sa.Text, nullable=True),
        sa.Column("kwayisi_code", sa.Text, nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("listed_date", sa.Date, nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        schema="gse",
    )


def downgrade() -> None:
    op.drop_table("symbols", schema="gse")
