"""desk_decisions + desk_budget_config (capital orchestrator)."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "023_desk_decisions"
down_revision: Union[str, None] = "022_mega_rotation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if not insp.has_table("desk_decisions"):
        op.create_table(
            "desk_decisions",
            sa.Column("id", sa.UUID(as_uuid=False), primary_key=True),
            sa.Column(
                "account_id",
                sa.UUID(as_uuid=False),
                sa.ForeignKey("investment_accounts.id"),
                nullable=False,
            ),
            sa.Column(
                "strategy_kind",
                postgresql.ENUM(
                    "income",
                    "swing",
                    "hv_dip",
                    "index_core",
                    "mega_rotation",
                    name="strategy_kind",
                    create_type=False,
                ),
                nullable=False,
            ),
            sa.Column("ticker", sa.String(length=16), nullable=False),
            sa.Column("verdict", sa.String(length=32), nullable=False),
            sa.Column("reason", sa.String(length=128), nullable=False, server_default=""),
            sa.Column("notional", sa.Float(), nullable=False, server_default="0"),
            sa.Column("price", sa.Float(), nullable=False, server_default="0"),
            sa.Column("cash_before", sa.Float(), nullable=False, server_default="0"),
            sa.Column("score", sa.Float(), nullable=False, server_default="0"),
            sa.Column("r_multiple", sa.Float(), nullable=True),
            sa.Column("enforce", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("payload", postgresql.JSONB(), nullable=False, server_default="{}"),
            sa.Column("suggestion_id", sa.String(length=36), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_desk_decisions_account_id", "desk_decisions", ["account_id"])
        op.create_index("ix_desk_decisions_strategy_kind", "desk_decisions", ["strategy_kind"])
        op.create_index("ix_desk_decisions_ticker", "desk_decisions", ["ticker"])
        op.create_index("ix_desk_decisions_verdict", "desk_decisions", ["verdict"])

    if not insp.has_table("desk_budget_config"):
        op.create_table(
            "desk_budget_config",
            sa.Column("id", sa.UUID(as_uuid=False), primary_key=True),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("slices", postgresql.JSONB(), nullable=False, server_default="{}"),
            sa.Column("peak_equity_usd", sa.Float(), nullable=False, server_default="0"),
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
        op.create_index("ix_desk_budget_config_is_active", "desk_budget_config", ["is_active"])


def downgrade() -> None:
    op.drop_index("ix_desk_budget_config_is_active", table_name="desk_budget_config")
    op.drop_table("desk_budget_config")
    op.drop_index("ix_desk_decisions_verdict", table_name="desk_decisions")
    op.drop_index("ix_desk_decisions_ticker", table_name="desk_decisions")
    op.drop_index("ix_desk_decisions_strategy_kind", table_name="desk_decisions")
    op.drop_index("ix_desk_decisions_account_id", table_name="desk_decisions")
    op.drop_table("desk_decisions")
