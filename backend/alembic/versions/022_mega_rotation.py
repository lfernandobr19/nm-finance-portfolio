"""Mega Rotation strategy kind (autonomous rotational buy-dip/trailing-stop)."""

from typing import Sequence, Union

from alembic import op

revision: str = "022_mega_rotation"
down_revision: Union[str, None] = "021_index_core"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add the 'mega_rotation' value to the shared strategy_kind enum.
    op.execute("ALTER TYPE strategy_kind ADD VALUE IF NOT EXISTS 'mega_rotation'")


def downgrade() -> None:
    # NB: removing an enum value in Postgres is unsafe; leave it in place.
    pass
