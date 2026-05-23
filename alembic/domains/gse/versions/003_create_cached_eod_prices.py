"""create gse.cached_eod_prices

Revision ID: gse_0003
Revises: gse_0002
"""

import sqlalchemy as sa

from alembic import op

revision = "gse_0003"
down_revision = "gse_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cached_eod_prices",
        sa.Column(
            "symbol",
            sa.Text,
            sa.ForeignKey("gse.symbols.ticker"),
            primary_key=True,
        ),
        sa.Column("date", sa.Date, primary_key=True),
        sa.Column("price", sa.Numeric(12, 4), nullable=False),
        sa.Column("change", sa.Numeric(12, 4), nullable=False, server_default="0"),
        sa.Column("change_pct", sa.Numeric(8, 4), nullable=False, server_default="0"),
        sa.Column("volume", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("source", sa.Text, nullable=False),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        schema="gse",
    )


def downgrade() -> None:
    op.drop_table("cached_eod_prices", schema="gse")
