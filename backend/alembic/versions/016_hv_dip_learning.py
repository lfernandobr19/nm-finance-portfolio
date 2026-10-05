"""hv_dip_config/history (learn-loop params + rollback)."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "016_hv_dip_learning"
down_revision: Union[str, None] = "015_hv_dip_observation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if not insp.has_table("hv_dip_config"):
        op.create_table(
            "hv_dip_config",
            sa.Column("id", sa.UUID(as_uuid=False), primary_key=True),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("params", postgresql.JSONB(), nullable=False, server_default="{}"),
            sa.Column("origin", sa.String(length=16), nullable=False, server_default="manual"),
            sa.Column("validation", postgresql.JSONB(), nullable=False, server_default="{}"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_hv_dip_config_is_active", "hv_dip_config", ["is_active"])

    if not insp.has_table("hv_dip_config_history"):
        op.create_table(
            "hv_dip_config_history",
            sa.Column("id", sa.UUID(as_uuid=False), primary_key=True),
            sa.Column("config_id", sa.UUID(as_uuid=False), sa.ForeignKey("hv_dip_config.id"), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("params", postgresql.JSONB(), nullable=False, server_default="{}"),
            sa.Column("origin", sa.String(length=16), nullable=False, server_default="manual"),
            sa.Column("reason", sa.Text(), nullable=False, server_default=""),
            sa.Column("validation", postgresql.JSONB(), nullable=False, server_default="{}"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        )
        op.create_index(
            "ix_hv_dip_config_history_config_id",
            "hv_dip_config_history",
            ["config_id"],
        )


def downgrade() -> None:
    op.drop_index("ix_hv_dip_config_history_config_id", table_name="hv_dip_config_history")
    op.drop_table("hv_dip_config_history")
    op.drop_index("ix_hv_dip_config_is_active", table_name="hv_dip_config")
    op.drop_table("hv_dip_config")
