"""investment_accounts settlement ledger (T+2)."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "019_settlement"
down_revision: Union[str, None] = "018_automation_pause"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "investment_accounts",
        sa.Column("unsettled_cash_usd", sa.Float(), nullable=False, server_default="0"),
    )
    op.add_column(
        "investment_accounts",
        sa.Column("unsettled_until", sa.Date(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("investment_accounts", "unsettled_until")
    op.drop_column("investment_accounts", "unsettled_cash_usd")
