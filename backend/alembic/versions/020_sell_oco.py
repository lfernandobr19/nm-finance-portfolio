"""Order sell side + bracket linkage (Phase 2)."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "020_sell_oco"
down_revision: Union[str, None] = "019_settlement"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add the 'sell' value to the order_side enum.
    op.execute("ALTER TYPE order_side ADD VALUE IF NOT EXISTS 'sell'")

    # Sell orders have no suggestion.
    op.alter_column("orders", "suggestion_id", nullable=True)

    # Bracket / sell-order linkage (plain strings, no FK to avoid a
    # delete-ordering cycle with Position.order_id).
    op.add_column("orders", sa.Column("position_id", sa.String(36), nullable=True))
    op.add_column("orders", sa.Column("oco_group_id", sa.String(64), nullable=True))
    op.create_index("ix_orders_position_id", "orders", ["position_id"])
    op.create_index("ix_orders_oco_group_id", "orders", ["oco_group_id"])


def downgrade() -> None:
    op.drop_index("ix_orders_oco_group_id", table_name="orders")
    op.drop_index("ix_orders_position_id", table_name="orders")
    op.drop_column("orders", "oco_group_id")
    op.drop_column("orders", "position_id")
    op.alter_column("orders", "suggestion_id", nullable=False)
    # NB: removing an enum value in Postgres is unsafe; leave 'sell' in place.
