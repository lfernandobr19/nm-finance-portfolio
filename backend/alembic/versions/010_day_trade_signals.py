"""day_trade_signals table for US intraday study observer."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "010_day_trade_signals"
down_revision: Union[str, None] = "009_password_reset"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

day_trade_side = postgresql.ENUM("long", "short", name="day_trade_side", create_type=False)
day_trade_signal_status = postgresql.ENUM(
    "open", "closed", "expired", name="day_trade_signal_status", create_type=False
)


def upgrade() -> None:
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE day_trade_side AS ENUM ('long', 'short');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
        """
    )
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE day_trade_signal_status AS ENUM ('open', 'closed', 'expired');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
        """
    )
    bind = op.get_bind()
    if sa.inspect(bind).has_table("day_trade_signals"):
        return
    op.create_table(
        "day_trade_signals",
        sa.Column("id", sa.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "account_id",
            sa.UUID(as_uuid=False),
            sa.ForeignKey("investment_accounts.id"),
            nullable=False,
        ),
        sa.Column("session_date", sa.Date(), nullable=False),
        sa.Column("ticker", sa.String(length=16), nullable=False),
        sa.Column("rule_id", sa.String(length=64), nullable=False),
        sa.Column("side", day_trade_side, nullable=False),
        sa.Column("entry_price", sa.Float(), nullable=False),
        sa.Column("stop_price", sa.Float(), nullable=False),
        sa.Column("target_price", sa.Float(), nullable=False),
        sa.Column(
            "status",
            day_trade_signal_status,
            nullable=False,
            server_default="open",
        ),
        sa.Column("simulated_pnl_usd", sa.Float(), nullable=True),
        sa.Column("metrics", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_day_trade_signals_account_id", "day_trade_signals", ["account_id"])
    op.create_index("ix_day_trade_signals_session_date", "day_trade_signals", ["session_date"])
    op.create_index("ix_day_trade_signals_ticker", "day_trade_signals", ["ticker"])
    op.create_index("ix_day_trade_signals_rule_id", "day_trade_signals", ["rule_id"])
    op.create_index("ix_day_trade_signals_status", "day_trade_signals", ["status"])


def downgrade() -> None:
    op.drop_index("ix_day_trade_signals_status", table_name="day_trade_signals")
    op.drop_index("ix_day_trade_signals_rule_id", table_name="day_trade_signals")
    op.drop_index("ix_day_trade_signals_ticker", table_name="day_trade_signals")
    op.drop_index("ix_day_trade_signals_session_date", table_name="day_trade_signals")
    op.drop_index("ix_day_trade_signals_account_id", table_name="day_trade_signals")
    op.drop_table("day_trade_signals")
    op.execute("DROP TYPE IF EXISTS day_trade_signal_status")
    op.execute("DROP TYPE IF EXISTS day_trade_side")
