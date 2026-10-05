"""day_trade_bars (durable bar store) + day_trade_config/history (learning params)."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "013_day_trade_learning"
down_revision: Union[str, None] = "012_exit_protect"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if not insp.has_table("day_trade_bars"):
        op.create_table(
            "day_trade_bars",
            sa.Column("id", sa.UUID(as_uuid=False), primary_key=True),
            sa.Column("ticker", sa.String(length=16), nullable=False),
            sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
            sa.Column("session_date", sa.Date(), nullable=False),
            sa.Column("open", sa.Float(), nullable=False),
            sa.Column("high", sa.Float(), nullable=False),
            sa.Column("low", sa.Float(), nullable=False),
            sa.Column("close", sa.Float(), nullable=False),
            sa.Column("volume", sa.Float(), nullable=False, server_default="0"),
            sa.UniqueConstraint("ticker", "ts", name="uq_day_trade_bar_ticker_ts"),
        )
        op.create_index("ix_day_trade_bars_ticker", "day_trade_bars", ["ticker"])
        op.create_index("ix_day_trade_bars_ts", "day_trade_bars", ["ts"])
        op.create_index("ix_day_trade_bars_session_date", "day_trade_bars", ["session_date"])

    if not insp.has_table("day_trade_config"):
        op.create_table(
            "day_trade_config",
            sa.Column("id", sa.UUID(as_uuid=False), primary_key=True),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("params", postgresql.JSONB(), nullable=False, server_default="{}"),
            sa.Column("origin", sa.String(length=16), nullable=False, server_default="manual"),
            sa.Column("validation", postgresql.JSONB(), nullable=False, server_default="{}"),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_day_trade_config_is_active", "day_trade_config", ["is_active"])

    if not insp.has_table("day_trade_config_history"):
        op.create_table(
            "day_trade_config_history",
            sa.Column("id", sa.UUID(as_uuid=False), primary_key=True),
            sa.Column(
                "config_id",
                sa.UUID(as_uuid=False),
                sa.ForeignKey("day_trade_config.id"),
                nullable=False,
            ),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("params", postgresql.JSONB(), nullable=False, server_default="{}"),
            sa.Column("origin", sa.String(length=16), nullable=False, server_default="manual"),
            sa.Column("reason", sa.Text(), nullable=False, server_default=""),
            sa.Column("validation", postgresql.JSONB(), nullable=False, server_default="{}"),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
        )
        op.create_index(
            "ix_day_trade_config_history_config_id",
            "day_trade_config_history",
            ["config_id"],
        )


def downgrade() -> None:
    op.drop_table("day_trade_config_history")
    op.drop_table("day_trade_config")
    op.drop_index("ix_day_trade_bars_session_date", table_name="day_trade_bars")
    op.drop_index("ix_day_trade_bars_ts", table_name="day_trade_bars")
    op.drop_index("ix_day_trade_bars_ticker", table_name="day_trade_bars")
    op.drop_table("day_trade_bars")
