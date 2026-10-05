"""Add password reset code fields on users."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "009_password_reset"
down_revision: Union[str, None] = "008_hv_dip_floor_30_ticker_80"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("password_reset_code_hash", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("password_reset_expires_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "password_reset_expires_at")
    op.drop_column("users", "password_reset_code_hash")
