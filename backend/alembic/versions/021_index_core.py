"""Index Core strategy kind (autonomous index DCA)."""

from typing import Sequence, Union

from alembic import op

revision: str = "021_index_core"
down_revision: Union[str, None] = "020_sell_oco"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add the 'index_core' value to the shared strategy_kind enum.
    op.execute("ALTER TYPE strategy_kind ADD VALUE IF NOT EXISTS 'index_core'")


def downgrade() -> None:
    # NB: removing an enum value in Postgres is unsafe; leave it in place.
    pass
