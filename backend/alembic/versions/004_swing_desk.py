"""Swing Desk: strategy_kind, swing fields, account risk controls."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "004_swing_desk"
down_revision: Union[str, None] = "003_orders"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    strategy_kind = postgresql.ENUM("income", "swing", name="strategy_kind", create_type=False)
    postgresql.ENUM("income", "swing", name="strategy_kind").create(bind, checkfirst=True)

    op.add_column(
        "investment_accounts",
        sa.Column("swing_max_positions", sa.Integer(), nullable=False, server_default="5"),
    )
    op.add_column(
        "investment_accounts",
        sa.Column("swing_cash_floor_pct", sa.Float(), nullable=False, server_default="20"),
    )
    op.add_column(
        "investment_accounts",
        sa.Column("swing_risk_pct_a", sa.Float(), nullable=False, server_default="1.5"),
    )
    op.add_column(
        "investment_accounts",
        sa.Column("swing_risk_pct_b", sa.Float(), nullable=False, server_default="1.0"),
    )
    op.add_column(
        "investment_accounts",
        sa.Column("swing_equity_brl", sa.Float(), nullable=False, server_default="10000"),
    )

    op.add_column(
        "suggestions",
        sa.Column("strategy_kind", strategy_kind, nullable=False, server_default="income"),
    )
    op.add_column("suggestions", sa.Column("swing_score_letter", sa.String(1), nullable=True))
    op.add_column("suggestions", sa.Column("entry_price", sa.Float(), nullable=True))
    op.add_column("suggestions", sa.Column("stop_price", sa.Float(), nullable=True))
    op.add_column("suggestions", sa.Column("target_price", sa.Float(), nullable=True))
    op.add_column("suggestions", sa.Column("r_multiple", sa.Float(), nullable=True))
    op.create_index("ix_suggestions_strategy_kind", "suggestions", ["strategy_kind"])

    op.add_column(
        "orders",
        sa.Column("strategy_kind", strategy_kind, nullable=False, server_default="income"),
    )
    op.create_index("ix_orders_strategy_kind", "orders", ["strategy_kind"])


def downgrade() -> None:
    op.drop_index("ix_orders_strategy_kind", table_name="orders")
    op.drop_column("orders", "strategy_kind")
    op.drop_index("ix_suggestions_strategy_kind", table_name="suggestions")
    op.drop_column("suggestions", "r_multiple")
    op.drop_column("suggestions", "target_price")
    op.drop_column("suggestions", "stop_price")
    op.drop_column("suggestions", "entry_price")
    op.drop_column("suggestions", "swing_score_letter")
    op.drop_column("suggestions", "strategy_kind")
    op.drop_column("investment_accounts", "swing_equity_brl")
    op.drop_column("investment_accounts", "swing_risk_pct_b")
    op.drop_column("investment_accounts", "swing_risk_pct_a")
    op.drop_column("investment_accounts", "swing_cash_floor_pct")
    op.drop_column("investment_accounts", "swing_max_positions")
    sa.Enum(name="strategy_kind").drop(op.get_bind(), checkfirst=True)
