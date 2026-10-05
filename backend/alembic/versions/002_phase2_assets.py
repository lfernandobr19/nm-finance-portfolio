"""Phase 2: FII + BDR REIT fields, effective yield rules, LLM summary."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "002_phase2_assets"
down_revision: Union[str, None] = "001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    asset_class = postgresql.ENUM("fii", "bdr_reit", name="asset_class", create_type=False)
    dividend_frequency = postgresql.ENUM(
        "monthly", "quarterly", "other", name="dividend_frequency", create_type=False
    )
    currency_exposure = postgresql.ENUM(
        "BRL", "USD_via_BDR", name="currency_exposure", create_type=False
    )
    postgresql.ENUM("fii", "bdr_reit", name="asset_class").create(bind, checkfirst=True)
    postgresql.ENUM("monthly", "quarterly", "other", name="dividend_frequency").create(
        bind, checkfirst=True
    )
    postgresql.ENUM("BRL", "USD_via_BDR", name="currency_exposure").create(bind, checkfirst=True)

    op.add_column(
        "account_rules",
        sa.Column("min_effective_yield", sa.Float(), nullable=False, server_default="8"),
    )
    op.add_column(
        "account_rules",
        sa.Column(
            "allowed_asset_classes",
            postgresql.JSONB(),
            nullable=False,
            server_default='["fii", "bdr_reit"]',
        ),
    )
    op.add_column(
        "account_rules",
        sa.Column(
            "prefer_monthly_dividends",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )
    op.execute("UPDATE account_rules SET min_effective_yield = min_dividend_yield")

    op.add_column(
        "market_snapshots",
        sa.Column("asset_class", asset_class, nullable=False, server_default="fii"),
    )
    op.add_column(
        "market_snapshots",
        sa.Column("venue", sa.String(16), nullable=False, server_default="B3"),
    )
    op.add_column(
        "market_snapshots",
        sa.Column("dividend_frequency", dividend_frequency, nullable=False, server_default="monthly"),
    )
    op.add_column(
        "market_snapshots",
        sa.Column("currency_exposure", currency_exposure, nullable=False, server_default="BRL"),
    )
    op.add_column(
        "market_snapshots",
        sa.Column("withholding_rate", sa.Float(), nullable=False, server_default="0"),
    )
    op.add_column(
        "market_snapshots",
        sa.Column("underlying_ticker", sa.String(32), nullable=False, server_default=""),
    )

    op.add_column(
        "suggestions",
        sa.Column("asset_class", asset_class, nullable=False, server_default="fii"),
    )
    op.add_column(
        "suggestions",
        sa.Column("dividend_frequency", dividend_frequency, nullable=False, server_default="monthly"),
    )
    op.add_column("suggestions", sa.Column("llm_summary", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("suggestions", "llm_summary")
    op.drop_column("suggestions", "dividend_frequency")
    op.drop_column("suggestions", "asset_class")
    op.drop_column("market_snapshots", "underlying_ticker")
    op.drop_column("market_snapshots", "withholding_rate")
    op.drop_column("market_snapshots", "currency_exposure")
    op.drop_column("market_snapshots", "dividend_frequency")
    op.drop_column("market_snapshots", "venue")
    op.drop_column("market_snapshots", "asset_class")
    op.drop_column("account_rules", "prefer_monthly_dividends")
    op.drop_column("account_rules", "allowed_asset_classes")
    op.drop_column("account_rules", "min_effective_yield")
    sa.Enum(name="currency_exposure").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="dividend_frequency").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="asset_class").drop(op.get_bind(), checkfirst=True)
