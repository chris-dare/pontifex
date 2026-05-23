"""create gse.historical_prices

Revision ID: gse_0002
Revises: gse_0001
"""

import sqlalchemy as sa

from alembic import op

revision = "gse_0002"
down_revision = "gse_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "historical_prices",
        sa.Column(
            "symbol",
            sa.Text,
            sa.ForeignKey("gse.symbols.ticker"),
            primary_key=True,
        ),
        sa.Column("date", sa.Date, primary_key=True),
        sa.Column("open", sa.Numeric(12, 4), nullable=True),
        sa.Column("high", sa.Numeric(12, 4), nullable=True),
        sa.Column("low", sa.Numeric(12, 4), nullable=True),
        sa.Column("close", sa.Numeric(12, 4), nullable=False),
        sa.Column("volume", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("source", sa.Text, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        schema="gse",
    )
    op.create_index(
        "idx_hist_symbol_date",
        "historical_prices",
        ["symbol", sa.text("date DESC")],
        schema="gse",
    )


def downgrade() -> None:
    op.drop_index("idx_hist_symbol_date", table_name="historical_prices", schema="gse")
    op.drop_table("historical_prices", schema="gse")
