"""Cash balance + positions for P&L tracking."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "005_positions_cash"
down_revision: Union[str, None] = "004_swing_desk"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    op.add_column(
        "investment_accounts",
        sa.Column("cash_brl", sa.Float(), nullable=False, server_default="10000"),
    )
    # Seed cash from swing equity when present
    op.execute(
        sa.text(
            "UPDATE investment_accounts SET cash_brl = COALESCE(swing_equity_brl, 10000)"
        )
    )

    position_status = postgresql.ENUM(
        "open", "closed", name="position_status", create_type=False
    )
    postgresql.ENUM("open", "closed", name="position_status").create(bind, checkfirst=True)

    exit_reason = postgresql.ENUM(
        "stop", "target", "manual", name="position_exit_reason", create_type=False
    )
    postgresql.ENUM("stop", "target", "manual", name="position_exit_reason").create(
        bind, checkfirst=True
    )

    strategy_kind = postgresql.ENUM("income", "swing", name="strategy_kind", create_type=False)

    op.create_table(
        "positions",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("investment_accounts.id"),
            nullable=False,
        ),
        sa.Column(
            "order_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("orders.id"),
            nullable=False,
        ),
        sa.Column(
            "suggestion_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("suggestions.id"),
            nullable=False,
        ),
        sa.Column("ticker", sa.String(length=16), nullable=False),
        sa.Column("strategy_kind", strategy_kind, nullable=False, server_default="income"),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("entry_price", sa.Float(), nullable=False),
        sa.Column("stop_price", sa.Float(), nullable=True),
        sa.Column("target_price", sa.Float(), nullable=True),
        sa.Column("status", position_status, nullable=False, server_default="open"),
        sa.Column("exit_reason", exit_reason, nullable=True),
        sa.Column("exit_price", sa.Float(), nullable=True),
        sa.Column("realized_pnl_brl", sa.Float(), nullable=True),
        sa.Column("realized_pnl_pct", sa.Float(), nullable=True),
        sa.Column("r_multiple_realized", sa.Float(), nullable=True),
        sa.Column("opened_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_positions_account_id", "positions", ["account_id"])
    op.create_index("ix_positions_status", "positions", ["status"])
    op.create_index("ix_positions_strategy_kind", "positions", ["strategy_kind"])
    op.create_index("ix_positions_order_id", "positions", ["order_id"], unique=True)
    op.create_index("ix_positions_ticker", "positions", ["ticker"])


def downgrade() -> None:
    op.drop_index("ix_positions_ticker", table_name="positions")
    op.drop_index("ix_positions_order_id", table_name="positions")
    op.drop_index("ix_positions_strategy_kind", table_name="positions")
    op.drop_index("ix_positions_status", table_name="positions")
    op.drop_index("ix_positions_account_id", table_name="positions")
    op.drop_table("positions")
    sa.Enum(name="position_exit_reason").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="position_status").drop(op.get_bind(), checkfirst=True)
    op.drop_column("investment_accounts", "cash_brl")
