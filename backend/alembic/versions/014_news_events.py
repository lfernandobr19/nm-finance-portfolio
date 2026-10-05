"""news_events (structured US news catalyst from Finnhub + LLM classification)."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "014_news_events"
down_revision: Union[str, None] = "013_day_trade_learning"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if not insp.has_table("news_events"):
        op.create_table(
            "news_events",
            sa.Column("id", sa.UUID(as_uuid=False), primary_key=True),
            sa.Column("ticker", sa.String(length=16), nullable=True),
            sa.Column("title", sa.String(length=500), nullable=False),
            sa.Column("url", sa.String(length=1000), nullable=False),
            sa.Column("source", sa.String(length=200), nullable=False, server_default=""),
            sa.Column("event_type", sa.String(length=32), nullable=True),
            sa.Column("sentiment", sa.String(length=16), nullable=True),
            sa.Column("confidence", sa.Float(), nullable=True),
            sa.Column("impact_score", sa.Float(), nullable=True),
            sa.Column("catalyst_strength", sa.String(length=16), nullable=True),
            sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("used_in_suggestion", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("raw", postgresql.JSONB(), nullable=False, server_default="{}"),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.UniqueConstraint("url", name="uq_news_event_url"),
        )
        op.create_index("ix_news_events_ticker", "news_events", ["ticker"])
        op.create_index("ix_news_events_event_type", "news_events", ["event_type"])


def downgrade() -> None:
    op.drop_index("ix_news_events_event_type", table_name="news_events")
    op.drop_index("ix_news_events_ticker", table_name="news_events")
    op.drop_table("news_events")
