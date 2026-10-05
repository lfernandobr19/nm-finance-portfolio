"""NM High-Vol Dip: default 4 positions, 30% max per ticker."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "007_hv_dip_limits_4_30"
down_revision: Union[str, None] = "006_hv_dip_nm"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "investment_accounts",
        "hv_dip_max_positions",
        server_default="4",
        existing_type=sa.Integer(),
        existing_nullable=False,
    )
    op.alter_column(
        "investment_accounts",
        "hv_dip_max_ticker_pct",
        server_default="30",
        existing_type=sa.Float(),
        existing_nullable=False,
    )
    op.execute(
        """
        UPDATE investment_accounts
        SET hv_dip_max_positions = 4,
            hv_dip_max_ticker_pct = 30
        WHERE broker_code = 'alpaca'
          AND currency = 'USD'
        """
    )


def downgrade() -> None:
    op.alter_column(
        "investment_accounts",
        "hv_dip_max_positions",
        server_default="2",
        existing_type=sa.Integer(),
        existing_nullable=False,
    )
    op.alter_column(
        "investment_accounts",
        "hv_dip_max_ticker_pct",
        server_default="80",
        existing_type=sa.Float(),
        existing_nullable=False,
    )
