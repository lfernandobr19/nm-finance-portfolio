"""Revert max ticker to 80%; cash floor 30% (stop new buys unless score A)."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "008_hv_dip_floor_30_ticker_80"
down_revision: Union[str, None] = "007_hv_dip_limits_4_30"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "investment_accounts",
        "hv_dip_max_ticker_pct",
        server_default="80",
        existing_type=sa.Float(),
        existing_nullable=False,
    )
    op.alter_column(
        "investment_accounts",
        "hv_dip_cash_floor_pct",
        server_default="30",
        existing_type=sa.Float(),
        existing_nullable=False,
    )
    op.execute(
        """
        UPDATE investment_accounts
        SET hv_dip_max_ticker_pct = 80,
            hv_dip_cash_floor_pct = 30
        WHERE broker_code = 'alpaca'
          AND currency = 'USD'
        """
    )


def downgrade() -> None:
    op.alter_column(
        "investment_accounts",
        "hv_dip_max_ticker_pct",
        server_default="30",
        existing_type=sa.Float(),
        existing_nullable=False,
    )
    op.alter_column(
        "investment_accounts",
        "hv_dip_cash_floor_pct",
        server_default="20",
        existing_type=sa.Float(),
        existing_nullable=False,
    )
