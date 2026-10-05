from datetime import date, datetime
from enum import Enum
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum as SAEnum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class MembershipRole(str, Enum):
    owner = "owner"
    operator = "operator"
    viewer = "viewer"


class SuggestionStatus(str, Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    expired = "expired"
    auto_approved = "auto_approved"


class AssetClass(str, Enum):
    fii = "fii"
    bdr_reit = "bdr_reit"
    us_equity = "us_equity"


class AccountCurrency(str, Enum):
    BRL = "BRL"
    USD = "USD"


class DividendFrequency(str, Enum):
    monthly = "monthly"
    quarterly = "quarterly"
    other = "other"


class CurrencyExposure(str, Enum):
    BRL = "BRL"
    USD_via_BDR = "USD_via_BDR"


class ExecutionMode(str, Enum):
    paper = "paper"
    live = "live"


class OrderStatus(str, Enum):
    queued = "queued"
    submitted = "submitted"
    awaiting_broker = "awaiting_broker"
    filled = "filled"
    cancelled = "cancelled"
    rejected = "rejected"


class OrderSide(str, Enum):
    buy = "buy"
    sell = "sell"


class PositionStatus(str, Enum):
    open = "open"
    closed = "closed"


class PositionExitReason(str, Enum):
    stop = "stop"
    target = "target"
    manual = "manual"
    protect = "protect"


class StrategyKind(str, Enum):
    income = "income"
    swing = "swing"
    hv_dip = "hv_dip"
    index_core = "index_core"
    mega_rotation = "mega_rotation"


class SwingScoreLetter(str, Enum):
    A = "A"
    B = "B"
    C = "C"


class DayTradeSignalStatus(str, Enum):
    open = "open"
    closed = "closed"
    expired = "expired"


class DayTradeSide(str, Enum):
    long = "long"
    short = "short"


def _uuid() -> str:
    return str(uuid4())


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    password_reset_code_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    password_reset_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    memberships: Mapped[list["AccountMembership"]] = relationship(back_populates="user")
    owned_accounts: Mapped[list["InvestmentAccount"]] = relationship(back_populates="owner")
    device_tokens: Mapped[list["DeviceToken"]] = relationship(back_populates="user")


class InvestmentAccount(Base):
    __tablename__ = "investment_accounts"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    owner_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    target_capital: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    auto_approve_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    auto_approve_min_score: Mapped[float] = mapped_column(Float, default=85.0, nullable=False)
    daily_auto_approve_limit: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    max_ticket_brl: Mapped[float] = mapped_column(Float, default=5000.0, nullable=False)
    broker_code: Mapped[str] = mapped_column(String(32), default="inter", nullable=False)
    execution_mode: Mapped[ExecutionMode] = mapped_column(
        SAEnum(ExecutionMode, name="execution_mode"),
        default=ExecutionMode.paper,
        nullable=False,
    )
    order_type: Mapped[str] = mapped_column(String(16), default="limit", nullable=False)
    # Swing Desk risk controls
    swing_max_positions: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    swing_cash_floor_pct: Mapped[float] = mapped_column(Float, default=20.0, nullable=False)
    swing_risk_pct_a: Mapped[float] = mapped_column(Float, default=1.5, nullable=False)
    swing_risk_pct_b: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    swing_equity_brl: Mapped[float] = mapped_column(Float, default=10000.0, nullable=False)
    cash_brl: Mapped[float] = mapped_column(Float, default=10000.0, nullable=False)
    currency: Mapped[AccountCurrency] = mapped_column(
        SAEnum(AccountCurrency, name="account_currency"),
        default=AccountCurrency.BRL,
        nullable=False,
    )
    cash_usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    hv_dip_max_positions: Mapped[int] = mapped_column(Integer, default=4, nullable=False)
    hv_dip_cash_floor_pct: Mapped[float] = mapped_column(Float, default=20.0, nullable=False)
    hv_dip_max_ticker_pct: Mapped[float] = mapped_column(Float, default=80.0, nullable=False)
    hv_dip_equity_usd: Mapped[float] = mapped_column(Float, default=100.0, nullable=False)
    # Kill switch: when True, automated buy/sell actions are suspended for this
    # account (manual review still works). Protects real-money accounts.
    automation_paused: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Settlement ledger (T+2, USD): sell proceeds are reserved here until they
    # settle. Buying power = cash_usd - unsettled_cash_usd.
    unsettled_cash_usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    unsettled_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    owner: Mapped["User"] = relationship(back_populates="owned_accounts")
    memberships: Mapped[list["AccountMembership"]] = relationship(
        back_populates="account", cascade="all, delete-orphan"
    )
    rules: Mapped[list["AccountRule"]] = relationship(
        back_populates="account", cascade="all, delete-orphan"
    )
    suggestions: Mapped[list["Suggestion"]] = relationship(back_populates="account")
    invites: Mapped[list["Invite"]] = relationship(back_populates="account")
    orders: Mapped[list["Order"]] = relationship(back_populates="account")
    positions: Mapped[list["Position"]] = relationship(back_populates="account")


class AccountMembership(Base):
    __tablename__ = "account_memberships"
    __table_args__ = (UniqueConstraint("user_id", "account_id", name="uq_membership_user_account"),)

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    account_id: Mapped[str] = mapped_column(
        ForeignKey("investment_accounts.id"), nullable=False, index=True
    )
    role: Mapped[MembershipRole] = mapped_column(
        SAEnum(MembershipRole, name="membership_role"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="memberships")
    account: Mapped["InvestmentAccount"] = relationship(back_populates="memberships")


class Invite(Base):
    __tablename__ = "invites"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    account_id: Mapped[str] = mapped_column(
        ForeignKey("investment_accounts.id"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)
    role: Mapped[MembershipRole] = mapped_column(
        SAEnum(MembershipRole, name="invite_role", create_constraint=False),
        nullable=False,
        default=MembershipRole.operator,
    )
    created_by_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    accepted_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    account: Mapped["InvestmentAccount"] = relationship(back_populates="invites")


class AccountRule(Base):
    """Versioned scoring criteria for an investment account."""

    __tablename__ = "account_rules"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    account_id: Mapped[str] = mapped_column(
        ForeignKey("investment_accounts.id"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    min_dividend_yield: Mapped[float] = mapped_column(Float, default=8.0, nullable=False)
    min_effective_yield: Mapped[float] = mapped_column(Float, default=8.0, nullable=False)
    max_p_vp: Mapped[float] = mapped_column(Float, default=1.05, nullable=False)
    min_avg_volume: Mapped[float] = mapped_column(Float, default=500_000.0, nullable=False)
    allowed_sectors: Mapped[list[Any]] = mapped_column(JSONB, default=list, nullable=False)
    excluded_tickers: Mapped[list[Any]] = mapped_column(JSONB, default=list, nullable=False)
    allowed_asset_classes: Mapped[list[Any]] = mapped_column(
        JSONB, default=lambda: ["fii", "bdr_reit"], nullable=False
    )
    prefer_monthly_dividends: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    score_threshold: Mapped[float] = mapped_column(Float, default=70.0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    account: Mapped["InvestmentAccount"] = relationship(back_populates="rules")


class MarketSnapshot(Base):
    __tablename__ = "market_snapshots"
    __table_args__ = (UniqueConstraint("ticker", "as_of", name="uq_snapshot_ticker_asof"),)

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    ticker: Mapped[str] = mapped_column(String(16), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    sector: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    dividend_yield: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    p_vp: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    avg_volume: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    change_day_pct: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    change_month_pct: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    asset_class: Mapped[AssetClass] = mapped_column(
        SAEnum(AssetClass, name="asset_class"),
        default=AssetClass.fii,
        nullable=False,
    )
    venue: Mapped[str] = mapped_column(String(16), default="B3", nullable=False)
    dividend_frequency: Mapped[DividendFrequency] = mapped_column(
        SAEnum(DividendFrequency, name="dividend_frequency"),
        default=DividendFrequency.monthly,
        nullable=False,
    )
    currency_exposure: Mapped[CurrencyExposure] = mapped_column(
        SAEnum(CurrencyExposure, name="currency_exposure"),
        default=CurrencyExposure.BRL,
        nullable=False,
    )
    withholding_rate: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    underlying_ticker: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    raw: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)


class Suggestion(Base):
    __tablename__ = "suggestions"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    account_id: Mapped[str] = mapped_column(
        ForeignKey("investment_accounts.id"), nullable=False, index=True
    )
    ticker: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    strategy_kind: Mapped[StrategyKind] = mapped_column(
        SAEnum(StrategyKind, name="strategy_kind"),
        default=StrategyKind.income,
        nullable=False,
        index=True,
    )
    asset_class: Mapped[AssetClass] = mapped_column(
        SAEnum(AssetClass, name="asset_class", create_constraint=False),
        default=AssetClass.fii,
        nullable=False,
    )
    dividend_frequency: Mapped[DividendFrequency] = mapped_column(
        SAEnum(DividendFrequency, name="dividend_frequency", create_constraint=False),
        default=DividendFrequency.monthly,
        nullable=False,
    )
    score: Mapped[float] = mapped_column(Float, nullable=False)
    swing_score_letter: Mapped[str | None] = mapped_column(String(1), nullable=True)
    entry_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    stop_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    target_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    r_multiple: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[SuggestionStatus] = mapped_column(
        SAEnum(SuggestionStatus, name="suggestion_status"),
        default=SuggestionStatus.pending,
        nullable=False,
        index=True,
    )
    reasons: Mapped[list[Any]] = mapped_column(JSONB, default=list, nullable=False)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    price_explanation: Mapped[str] = mapped_column(Text, default="", nullable=False)
    llm_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    rule_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    proposed_amount_brl: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    setup_low: Mapped[float | None] = mapped_column(Float, nullable=True)
    tranche_index: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    review_required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    review_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    acted_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    action_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    acted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    account: Mapped["InvestmentAccount"] = relationship(back_populates="suggestions")
    orders: Mapped[list["Order"]] = relationship(back_populates="suggestion")


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    account_id: Mapped[str] = mapped_column(
        ForeignKey("investment_accounts.id"), nullable=False, index=True
    )
    suggestion_id: Mapped[str | None] = mapped_column(
        ForeignKey("suggestions.id"), nullable=True, index=True
    )
    ticker: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    strategy_kind: Mapped[StrategyKind] = mapped_column(
        SAEnum(StrategyKind, name="strategy_kind", create_constraint=False),
        default=StrategyKind.income,
        nullable=False,
        index=True,
    )
    side: Mapped[OrderSide] = mapped_column(
        SAEnum(OrderSide, name="order_side"),
        default=OrderSide.buy,
        nullable=False,
    )
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    amount_brl: Mapped[float] = mapped_column(Float, nullable=False)
    limit_price: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[OrderStatus] = mapped_column(
        SAEnum(OrderStatus, name="order_status"),
        default=OrderStatus.queued,
        nullable=False,
        index=True,
    )
    broker: Mapped[str] = mapped_column(String(32), default="inter", nullable=False)
    execution_mode: Mapped[ExecutionMode] = mapped_column(
        SAEnum(ExecutionMode, name="execution_mode", create_constraint=False),
        default=ExecutionMode.paper,
        nullable=False,
    )
    broker_order_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    filled_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    filled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Sell / bracket linkage (Phase 2): a sell order closes a position, and the
    # two legs of an OCO bracket share an oco_group_id. Both are plain strings
    # (no FK) to avoid a delete-ordering cycle with Position.order_id.
    position_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    oco_group_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    execution_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    acted_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    account: Mapped["InvestmentAccount"] = relationship(back_populates="orders")
    suggestion: Mapped["Suggestion | None"] = relationship(back_populates="orders")
    position: Mapped["Position | None"] = relationship(back_populates="order", uselist=False)


class Position(Base):
    __tablename__ = "positions"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    account_id: Mapped[str] = mapped_column(
        ForeignKey("investment_accounts.id"), nullable=False, index=True
    )
    order_id: Mapped[str] = mapped_column(
        ForeignKey("orders.id"), nullable=False, unique=True, index=True
    )
    suggestion_id: Mapped[str] = mapped_column(
        ForeignKey("suggestions.id"), nullable=False, index=True
    )
    ticker: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    strategy_kind: Mapped[StrategyKind] = mapped_column(
        SAEnum(StrategyKind, name="strategy_kind", create_constraint=False),
        default=StrategyKind.income,
        nullable=False,
        index=True,
    )
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    entry_price: Mapped[float] = mapped_column(Float, nullable=False)
    stop_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    target_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    setup_low: Mapped[float | None] = mapped_column(Float, nullable=True)
    tranche_index: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    avg_entry_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[PositionStatus] = mapped_column(
        SAEnum(PositionStatus, name="position_status"),
        default=PositionStatus.open,
        nullable=False,
        index=True,
    )
    exit_reason: Mapped[PositionExitReason | None] = mapped_column(
        SAEnum(PositionExitReason, name="position_exit_reason"),
        nullable=True,
    )
    exit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    realized_pnl_brl: Mapped[float | None] = mapped_column(Float, nullable=True)
    realized_pnl_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    r_multiple_realized: Mapped[float | None] = mapped_column(Float, nullable=True)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    account: Mapped["InvestmentAccount"] = relationship(back_populates="positions")
    order: Mapped["Order"] = relationship(back_populates="position")


class NewsItem(Base):
    __tablename__ = "news_items"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    ticker: Mapped[str | None] = mapped_column(String(16), index=True, nullable=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    url: Mapped[str] = mapped_column(String(1000), nullable=False)
    source: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DeviceToken(Base):
    __tablename__ = "device_tokens"
    __table_args__ = (UniqueConstraint("user_id", "token", name="uq_user_device_token"),)

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    token: Mapped[str] = mapped_column(String(512), nullable=False)
    platform: Mapped[str] = mapped_column(String(32), default="android", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="device_tokens")


class DayTradeSignal(Base):
    __tablename__ = "day_trade_signals"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    account_id: Mapped[str] = mapped_column(
        ForeignKey("investment_accounts.id"), nullable=False, index=True
    )
    session_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    ticker: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    rule_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    side: Mapped[DayTradeSide] = mapped_column(
        SAEnum(DayTradeSide, name="day_trade_side"),
        nullable=False,
    )
    entry_price: Mapped[float] = mapped_column(Float, nullable=False)
    stop_price: Mapped[float] = mapped_column(Float, nullable=False)
    target_price: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[DayTradeSignalStatus] = mapped_column(
        SAEnum(DayTradeSignalStatus, name="day_trade_signal_status"),
        default=DayTradeSignalStatus.open,
        nullable=False,
        index=True,
    )
    simulated_pnl_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    account: Mapped["InvestmentAccount"] = relationship()


class DayTradeBar(Base):
    """Durable intraday bar store (learn loop foundation; not just rolling cache)."""

    __tablename__ = "day_trade_bars"
    __table_args__ = (UniqueConstraint("ticker", "ts", name="uq_day_trade_bar_ticker_ts"),)

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    ticker: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    session_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    open: Mapped[float] = mapped_column(Float, nullable=False)
    high: Mapped[float] = mapped_column(Float, nullable=False)
    low: Mapped[float] = mapped_column(Float, nullable=False)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    volume: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)


class DayTradeConfig(Base):
    """Singleton (one active row) param set for day trade rules."""

    __tablename__ = "day_trade_config"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    origin: Mapped[str] = mapped_column(String(16), default="manual", nullable=False)
    validation: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DayTradeConfigHistory(Base):
    """Append-only audit of every param change (rollback + observability)."""

    __tablename__ = "day_trade_config_history"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    config_id: Mapped[str] = mapped_column(ForeignKey("day_trade_config.id"), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    origin: Mapped[str] = mapped_column(String(16), default="manual", nullable=False)
    reason: Mapped[str] = mapped_column(Text, default="", nullable=False)
    validation: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class HvDipConfig(Base):
    """Singleton (one active row) param set for the hv_dip learn loop."""

    __tablename__ = "hv_dip_config"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    origin: Mapped[str] = mapped_column(String(16), default="manual", nullable=False)
    validation: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class HvDipConfigHistory(Base):
    """Append-only audit of every hv_dip param change (rollback + observability)."""

    __tablename__ = "hv_dip_config_history"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    config_id: Mapped[str] = mapped_column(ForeignKey("hv_dip_config.id"), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    origin: Mapped[str] = mapped_column(String(16), default="manual", nullable=False)
    reason: Mapped[str] = mapped_column(Text, default="", nullable=False)
    validation: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class NewsEvent(Base):
    """Structured US news catalyst (Finnhub → LLM classification)."""

    __tablename__ = "news_events"
    __table_args__ = (UniqueConstraint("url", name="uq_news_event_url"),)

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    ticker: Mapped[str | None] = mapped_column(String(16), index=True, nullable=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    url: Mapped[str] = mapped_column(String(1000), nullable=False)
    source: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    event_type: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)
    sentiment: Mapped[str | None] = mapped_column(String(16), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    impact_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    catalyst_strength: Mapped[str | None] = mapped_column(String(16), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    used_in_suggestion: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    raw: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class HvDipObservation(Base):
    """Persistent watch state for structural-decline large-caps (Fase 5b).

    A falling-knife name is not rejected: it is watched here across cycles until
    a confluence of technical recovery + statistical probability + recovery news
    justifies a "risky recovery A" auto-buy, or it is dismissed.
    """

    __tablename__ = "hv_dip_observations"
    __table_args__ = (UniqueConstraint("account_id", "ticker", name="uq_hv_dip_obs_account_ticker"),)

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    account_id: Mapped[str] = mapped_column(
        ForeignKey("investment_accounts.id"), nullable=False, index=True
    )
    ticker: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), default="observing", nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_evaluated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    recovery_probability: Mapped[float | None] = mapped_column(Float, nullable=True)
    recovery_in_progress: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    active_catalyst: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_decision: Mapped[str | None] = mapped_column(String(64), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class DeskDecision(Base):
    """Capital-orchestrator audit: allow / deny / pending intents (no Order on deny)."""

    __tablename__ = "desk_decisions"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    account_id: Mapped[str] = mapped_column(
        ForeignKey("investment_accounts.id"), nullable=False, index=True
    )
    strategy_kind: Mapped[StrategyKind] = mapped_column(
        SAEnum(StrategyKind, name="strategy_kind", create_constraint=False),
        nullable=False,
        index=True,
    )
    ticker: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    verdict: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    reason: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    notional: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    price: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    cash_before: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    r_multiple: Mapped[float | None] = mapped_column(Float, nullable=True)
    enforce: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    suggestion_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DeskBudgetConfig(Base):
    """Learned USD budget slices for the desk gate (one active row)."""

    __tablename__ = "desk_budget_config"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    slices: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    peak_equity_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    origin: Mapped[str] = mapped_column(String(16), default="manual", nullable=False)
    validation: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WatchlistItem(Base):
    """User-curated watchlist (observação) of tickers to follow at market open.

    Synced across Windows/Android and enriched with live quotes on read.
    """

    __tablename__ = "watchlist_items"
    __table_args__ = (UniqueConstraint("account_id", "ticker", name="uq_watchlist_account_ticker"),)

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    account_id: Mapped[str] = mapped_column(
        ForeignKey("investment_accounts.id"), nullable=False, index=True
    )
    ticker: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    added_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ForecastLedger(Base):
    """Every probability the desk asserts, scored against what actually happened.

    This is the measurement spine: without it, "getting smarter" is unfalsifiable
    because nothing ever records what was predicted before the outcome was known.
    ``p_pred`` is written at decision time and never edited; ``outcome`` and
    ``brier`` are filled once ``resolve_after`` has passed.
    """

    __tablename__ = "forecast_ledger"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    source: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    ticker: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    ref_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    p_pred: Mapped[float] = mapped_column(Float, nullable=False)
    horizon_days: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    features: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    resolve_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    outcome: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    outcome_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    brier: Mapped[float | None] = mapped_column(Float, nullable=True)
