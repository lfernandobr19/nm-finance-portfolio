"""Raven Finance NM: hv_dip strategy, USD account fields, Review/tranche."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "006_hv_dip_nm"
down_revision: Union[str, None] = "005_positions_cash"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    # Extend strategy_kind enum with hv_dip
    op.execute("ALTER TYPE strategy_kind ADD VALUE IF NOT EXISTS 'hv_dip'")

    # Extend asset_class with us_equity
    op.execute("ALTER TYPE asset_class ADD VALUE IF NOT EXISTS 'us_equity'")

    account_currency = postgresql.ENUM("BRL", "USD", name="account_currency", create_type=False)
    postgresql.ENUM("BRL", "USD", name="account_currency").create(bind, checkfirst=True)

    op.add_column(
        "investment_accounts",
        sa.Column(
            "currency",
            account_currency,
            nullable=False,
            server_default="BRL",
        ),
    )
    op.add_column(
        "investment_accounts",
        sa.Column("cash_usd", sa.Float(), nullable=False, server_default="0"),
    )
    op.add_column(
        "investment_accounts",
        sa.Column("hv_dip_max_positions", sa.Integer(), nullable=False, server_default="2"),
    )
    op.add_column(
        "investment_accounts",
        sa.Column("hv_dip_cash_floor_pct", sa.Float(), nullable=False, server_default="20"),
    )
    op.add_column(
        "investment_accounts",
        sa.Column("hv_dip_max_ticker_pct", sa.Float(), nullable=False, server_default="80"),
    )
    op.add_column(
        "investment_accounts",
        sa.Column("hv_dip_equity_usd", sa.Float(), nullable=False, server_default="100"),
    )

    op.add_column("suggestions", sa.Column("setup_low", sa.Float(), nullable=True))
    op.add_column(
        "suggestions",
        sa.Column("tranche_index", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "suggestions",
        sa.Column("review_required", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column("suggestions", sa.Column("review_reason", sa.Text(), nullable=True))

    op.add_column("positions", sa.Column("setup_low", sa.Float(), nullable=True))
    op.add_column(
        "positions",
        sa.Column("tranche_index", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "positions",
        sa.Column("avg_entry_price", sa.Float(), nullable=True),
    )

    # Fractional shares for USD desk
    op.alter_column(
        "orders",
        "quantity",
        existing_type=sa.Integer(),
        type_=sa.Float(),
        postgresql_using="quantity::double precision",
    )
    op.alter_column(
        "positions",
        "quantity",
        existing_type=sa.Integer(),
        type_=sa.Float(),
        postgresql_using="quantity::double precision",
    )


def downgrade() -> None:
    op.alter_column(
        "positions",
        "quantity",
        existing_type=sa.Float(),
        type_=sa.Integer(),
        postgresql_using="quantity::integer",
    )
    op.alter_column(
        "orders",
        "quantity",
        existing_type=sa.Float(),
        type_=sa.Integer(),
        postgresql_using="quantity::integer",
    )
    op.drop_column("positions", "avg_entry_price")
    op.drop_column("positions", "tranche_index")
    op.drop_column("positions", "setup_low")
    op.drop_column("suggestions", "review_reason")
    op.drop_column("suggestions", "review_required")
    op.drop_column("suggestions", "tranche_index")
    op.drop_column("suggestions", "setup_low")
    op.drop_column("investment_accounts", "hv_dip_equity_usd")
    op.drop_column("investment_accounts", "hv_dip_max_ticker_pct")
    op.drop_column("investment_accounts", "hv_dip_cash_floor_pct")
    op.drop_column("investment_accounts", "hv_dip_max_positions")
    op.drop_column("investment_accounts", "cash_usd")
    op.drop_column("investment_accounts", "currency")
    sa.Enum(name="account_currency").drop(op.get_bind(), checkfirst=True)
