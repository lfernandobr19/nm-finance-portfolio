"""Initial schema for FII Desk."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(200), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    membership_role = postgresql.ENUM(
        "owner", "operator", "viewer", name="membership_role", create_type=False
    )
    invite_role = postgresql.ENUM(
        "owner", "operator", "viewer", name="invite_role", create_type=False
    )
    suggestion_status = postgresql.ENUM(
        "pending",
        "approved",
        "rejected",
        "expired",
        "auto_approved",
        name="suggestion_status",
        create_type=False,
    )
    bind = op.get_bind()
    postgresql.ENUM(
        "owner", "operator", "viewer", name="membership_role"
    ).create(bind, checkfirst=True)
    postgresql.ENUM(
        "owner", "operator", "viewer", name="invite_role"
    ).create(bind, checkfirst=True)
    postgresql.ENUM(
        "pending",
        "approved",
        "rejected",
        "expired",
        "auto_approved",
        name="suggestion_status",
    ).create(bind, checkfirst=True)

    op.create_table(
        "investment_accounts",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("target_capital", sa.Float(), nullable=False, server_default="0"),
        sa.Column("auto_approve_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("auto_approve_min_score", sa.Float(), nullable=False, server_default="85"),
        sa.Column("daily_auto_approve_limit", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("max_ticket_brl", sa.Float(), nullable=False, server_default="5000"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_investment_accounts_owner_user_id", "investment_accounts", ["owner_user_id"])

    op.create_table(
        "account_memberships",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("investment_accounts.id"),
            nullable=False,
        ),
        sa.Column("role", membership_role, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("user_id", "account_id", name="uq_membership_user_account"),
    )

    op.create_table(
        "invites",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("investment_accounts.id"),
            nullable=False,
        ),
        sa.Column("code", sa.String(32), nullable=False),
        sa.Column("role", invite_role, nullable=False),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accepted_by_user_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("users.id"), nullable=True),
    )
    op.create_index("ix_invites_code", "invites", ["code"], unique=True)

    op.create_table(
        "account_rules",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("investment_accounts.id"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("min_dividend_yield", sa.Float(), nullable=False),
        sa.Column("max_p_vp", sa.Float(), nullable=False),
        sa.Column("min_avg_volume", sa.Float(), nullable=False),
        sa.Column("allowed_sectors", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("excluded_tickers", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("score_threshold", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )

    op.create_table(
        "market_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("ticker", sa.String(16), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("sector", sa.String(100), nullable=False),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("dividend_yield", sa.Float(), nullable=False),
        sa.Column("p_vp", sa.Float(), nullable=False),
        sa.Column("avg_volume", sa.Float(), nullable=False),
        sa.Column("change_day_pct", sa.Float(), nullable=False),
        sa.Column("change_month_pct", sa.Float(), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("raw", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.UniqueConstraint("ticker", "as_of", name="uq_snapshot_ticker_asof"),
    )
    op.create_index("ix_market_snapshots_ticker", "market_snapshots", ["ticker"])

    op.create_table(
        "suggestions",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("investment_accounts.id"),
            nullable=False,
        ),
        sa.Column("ticker", sa.String(16), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("status", suggestion_status, nullable=False),
        sa.Column("reasons", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("metrics", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("price_explanation", sa.Text(), nullable=False),
        sa.Column("rule_version", sa.Integer(), nullable=False),
        sa.Column("proposed_amount_brl", sa.Float(), nullable=False),
        sa.Column("acted_by_user_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("action_note", sa.Text(), nullable=True),
        sa.Column("acted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_suggestions_account_id", "suggestions", ["account_id"])
    op.create_index("ix_suggestions_status", "suggestions", ["status"])

    op.create_table(
        "news_items",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("ticker", sa.String(16), nullable=True),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("url", sa.String(1000), nullable=False),
        sa.Column("source", sa.String(200), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_news_items_ticker", "news_items", ["ticker"])

    op.create_table(
        "device_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("token", sa.String(512), nullable=False),
        sa.Column("platform", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("user_id", "token", name="uq_user_device_token"),
    )


def downgrade() -> None:
    op.drop_table("device_tokens")
    op.drop_table("news_items")
    op.drop_table("suggestions")
    op.drop_table("market_snapshots")
    op.drop_table("account_rules")
    op.drop_table("invites")
    op.drop_table("account_memberships")
    op.drop_table("investment_accounts")
    op.drop_table("users")
    sa.Enum(name="suggestion_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="invite_role").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="membership_role").drop(op.get_bind(), checkfirst=True)
