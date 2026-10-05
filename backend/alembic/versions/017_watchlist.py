"""watchlist_items (user-curated observação list)."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "017_watchlist"
down_revision: Union[str, None] = "016_hv_dip_learning"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "watchlist_items",
        sa.Column("id", sa.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "account_id",
            sa.UUID(as_uuid=False),
            sa.ForeignKey("investment_accounts.id"),
            nullable=False,
        ),
        sa.Column("ticker", sa.String(length=16), nullable=False),
        sa.Column("added_by_user_id", sa.UUID(as_uuid=False), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("account_id", "ticker", name="uq_watchlist_account_ticker"),
    )
    op.create_index("ix_watchlist_items_account_id", "watchlist_items", ["account_id"])
    op.create_index("ix_watchlist_items_ticker", "watchlist_items", ["ticker"])


def downgrade() -> None:
    op.drop_index("ix_watchlist_items_ticker", table_name="watchlist_items")
    op.drop_index("ix_watchlist_items_account_id", table_name="watchlist_items")
    op.drop_table("watchlist_items")
