"""hv_dip_observations (structural-decline watch state for Fase 5b)."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "015_hv_dip_observation"
down_revision: Union[str, None] = "014_news_events"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if not insp.has_table("hv_dip_observations"):
        op.create_table(
            "hv_dip_observations",
            sa.Column("id", sa.UUID(as_uuid=False), primary_key=True),
            sa.Column("account_id", sa.UUID(as_uuid=False), nullable=False),
            sa.Column("ticker", sa.String(length=16), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="observing"),
            sa.Column("first_seen_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("last_evaluated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("recovery_probability", sa.Float(), nullable=True),
            sa.Column("recovery_in_progress", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("active_catalyst", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("last_decision", sa.String(length=64), nullable=True),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.UniqueConstraint("account_id", "ticker", name="uq_hv_dip_obs_account_ticker"),
        )
        op.create_index("ix_hv_dip_observations_account_id", "hv_dip_observations", ["account_id"])
        op.create_index("ix_hv_dip_observations_ticker", "hv_dip_observations", ["ticker"])


def downgrade() -> None:
    op.drop_index("ix_hv_dip_observations_ticker", table_name="hv_dip_observations")
    op.drop_index("ix_hv_dip_observations_account_id", table_name="hv_dip_observations")
    op.drop_table("hv_dip_observations")
