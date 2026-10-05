"""forecast_ledger (measurement spine: asserted probability vs real outcome)."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "024_forecast_ledger"
down_revision: Union[str, None] = "023_desk_decisions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if insp.has_table("forecast_ledger"):
        return

    op.create_table(
        "forecast_ledger",
        sa.Column("id", sa.UUID(as_uuid=False), primary_key=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("kind", sa.String(length=48), nullable=False),
        sa.Column("ticker", sa.String(length=16), nullable=False),
        sa.Column("ref_id", sa.String(length=64), nullable=True),
        sa.Column("p_pred", sa.Float(), nullable=False),
        sa.Column("horizon_days", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("features", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("resolve_after", sa.DateTime(timezone=True), nullable=False),
        sa.Column("outcome", sa.Boolean(), nullable=True),
        sa.Column("outcome_value", sa.Float(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("brier", sa.Float(), nullable=True),
    )
    op.create_index("ix_forecast_ledger_source", "forecast_ledger", ["source"])
    op.create_index("ix_forecast_ledger_kind", "forecast_ledger", ["kind"])
    op.create_index("ix_forecast_ledger_ticker", "forecast_ledger", ["ticker"])
    op.create_index("ix_forecast_ledger_ref_id", "forecast_ledger", ["ref_id"])
    op.create_index("ix_forecast_ledger_resolve_after", "forecast_ledger", ["resolve_after"])
    # The resolver scans "due and still unresolved" every minute; without this
    # the sweep degrades into a full scan as the ledger grows.
    op.create_index(
        "ix_forecast_ledger_pending",
        "forecast_ledger",
        ["resolve_after"],
        postgresql_where=sa.text("resolved_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_forecast_ledger_pending", table_name="forecast_ledger")
    op.drop_index("ix_forecast_ledger_resolve_after", table_name="forecast_ledger")
    op.drop_index("ix_forecast_ledger_ref_id", table_name="forecast_ledger")
    op.drop_index("ix_forecast_ledger_ticker", table_name="forecast_ledger")
    op.drop_index("ix_forecast_ledger_kind", table_name="forecast_ledger")
    op.drop_index("ix_forecast_ledger_source", table_name="forecast_ledger")
    op.drop_table("forecast_ledger")
