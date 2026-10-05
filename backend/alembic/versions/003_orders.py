"""Phase 3: orders pipeline + account execution mode."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "003_orders"
down_revision: Union[str, None] = "002_phase2_assets"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    execution_mode = postgresql.ENUM("paper", "live", name="execution_mode", create_type=False)
    order_side = postgresql.ENUM("buy", name="order_side", create_type=False)
    order_status = postgresql.ENUM(
        "queued",
        "submitted",
        "awaiting_broker",
        "filled",
        "cancelled",
        "rejected",
        name="order_status",
        create_type=False,
    )
    postgresql.ENUM("paper", "live", name="execution_mode").create(bind, checkfirst=True)
    postgresql.ENUM("buy", name="order_side").create(bind, checkfirst=True)
    postgresql.ENUM(
        "queued",
        "submitted",
        "awaiting_broker",
        "filled",
        "cancelled",
        "rejected",
        name="order_status",
    ).create(bind, checkfirst=True)

    op.add_column(
        "investment_accounts",
        sa.Column("broker_code", sa.String(32), nullable=False, server_default="inter"),
    )
    op.add_column(
        "investment_accounts",
        sa.Column("execution_mode", execution_mode, nullable=False, server_default="paper"),
    )
    op.add_column(
        "investment_accounts",
        sa.Column("order_type", sa.String(16), nullable=False, server_default="limit"),
    )

    op.create_table(
        "orders",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("investment_accounts.id"),
            nullable=False,
        ),
        sa.Column(
            "suggestion_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("suggestions.id"),
            nullable=False,
        ),
        sa.Column("ticker", sa.String(16), nullable=False),
        sa.Column("side", order_side, nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("amount_brl", sa.Float(), nullable=False),
        sa.Column("limit_price", sa.Float(), nullable=False),
        sa.Column("status", order_status, nullable=False),
        sa.Column("broker", sa.String(32), nullable=False, server_default="inter"),
        sa.Column("execution_mode", execution_mode, nullable=False),
        sa.Column("broker_order_id", sa.String(128), nullable=True),
        sa.Column("filled_price", sa.Float(), nullable=True),
        sa.Column("filled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("execution_payload", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("acted_by_user_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_orders_account_id", "orders", ["account_id"])
    op.create_index("ix_orders_suggestion_id", "orders", ["suggestion_id"])
    op.create_index("ix_orders_status", "orders", ["status"])
    op.create_index("ix_orders_ticker", "orders", ["ticker"])


def downgrade() -> None:
    op.drop_table("orders")
    op.drop_column("investment_accounts", "order_type")
    op.drop_column("investment_accounts", "execution_mode")
    op.drop_column("investment_accounts", "broker_code")
    sa.Enum(name="order_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="order_side").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="execution_mode").drop(op.get_bind(), checkfirst=True)
