"""investment_accounts.automation_paused (kill switch)."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "018_automation_pause"
down_revision: Union[str, None] = "017_watchlist"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "investment_accounts",
        sa.Column("automation_paused", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("investment_accounts", "automation_paused")
