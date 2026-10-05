"""Add protect to position_exit_reason enum."""

from alembic import op

revision = "012_exit_protect"
down_revision = "011_position_metrics"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE position_exit_reason ADD VALUE IF NOT EXISTS 'protect'")


def downgrade() -> None:
    # PostgreSQL cannot remove enum values safely; no-op.
    pass
