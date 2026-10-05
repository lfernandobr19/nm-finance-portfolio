from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_serializer

from app.domain.models import MembershipRole, SuggestionStatus
from app.services.studies.models import StudySnapshot


def _round2(value: float | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 2)


def _round_metrics(metrics: dict[str, Any] | None) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, val in (metrics or {}).items():
        if isinstance(val, float):
            out[key] = round(val, 2)
        else:
            out[key] = val
    return out


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(default="", max_length=200)


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: EmailStr
    full_name: str
    created_at: datetime


class RefreshRequest(BaseModel):
    refresh_token: str


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetConfirm(BaseModel):
    email: EmailStr
    code: str = Field(min_length=4, max_length=12)
    new_password: str = Field(min_length=8, max_length=128)


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)


class AccountCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    target_capital: float = 0.0
    max_ticket_brl: float = 5000.0


class AccountUpdate(BaseModel):
    name: str | None = None
    target_capital: float | None = None
    max_ticket_brl: float | None = None
    auto_approve_enabled: bool | None = None
    auto_approve_min_score: float | None = None
    daily_auto_approve_limit: int | None = None
    broker_code: str | None = None
    execution_mode: str | None = None
    order_type: str | None = None
    swing_max_positions: int | None = None
    swing_cash_floor_pct: float | None = None
    swing_risk_pct_a: float | None = None
    swing_risk_pct_b: float | None = None
    swing_equity_brl: float | None = None
    cash_brl: float | None = None
    currency: str | None = None
    cash_usd: float | None = None
    hv_dip_max_positions: int | None = None
    hv_dip_cash_floor_pct: float | None = None
    hv_dip_max_ticker_pct: float | None = None
    hv_dip_equity_usd: float | None = None
    automation_paused: bool | None = None


class AccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    owner_user_id: str
    target_capital: float
    auto_approve_enabled: bool
    auto_approve_min_score: float
    daily_auto_approve_limit: int
    max_ticket_brl: float
    broker_code: str = "inter"
    execution_mode: str = "paper"
    order_type: str = "limit"
    swing_max_positions: int = 5
    swing_cash_floor_pct: float = 20.0
    swing_risk_pct_a: float = 1.5
    swing_risk_pct_b: float = 1.0
    swing_equity_brl: float = 10000.0
    cash_brl: float = 10000.0
    currency: str = "BRL"
    cash_usd: float = 0.0
    hv_dip_max_positions: int = 4
    hv_dip_cash_floor_pct: float = 30.0
    hv_dip_max_ticker_pct: float = 80.0
    hv_dip_equity_usd: float = 100.0
    automation_paused: bool = False
    created_at: datetime
    my_role: MembershipRole | None = None


class MembershipOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    account_id: str
    role: MembershipRole
    email: str | None = None
    full_name: str | None = None


class InviteCreate(BaseModel):
    role: MembershipRole = MembershipRole.operator


class InviteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    account_id: str
    code: str
    role: MembershipRole
    expires_at: datetime
    accepted_at: datetime | None


class InviteAccept(BaseModel):
    code: str


class RuleUpdate(BaseModel):
    min_dividend_yield: float | None = None
    min_effective_yield: float | None = None
    max_p_vp: float | None = None
    min_avg_volume: float | None = None
    allowed_sectors: list[str] | None = None
    excluded_tickers: list[str] | None = None
    allowed_asset_classes: list[str] | None = None
    prefer_monthly_dividends: bool | None = None
    score_threshold: float | None = None


class RuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    account_id: str
    version: int
    is_active: bool
    min_dividend_yield: float
    min_effective_yield: float
    max_p_vp: float
    min_avg_volume: float
    allowed_sectors: list[Any]
    excluded_tickers: list[Any]
    allowed_asset_classes: list[Any]
    prefer_monthly_dividends: bool
    score_threshold: float
    created_at: datetime


class ReasonItem(BaseModel):
    rule: str
    passed: bool
    detail: str


class SuggestionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    account_id: str
    ticker: str
    strategy_kind: str = "income"
    asset_class: str
    dividend_frequency: str
    score: float
    swing_score_letter: str | None = None
    entry_price: float | None = None
    stop_price: float | None = None
    target_price: float | None = None
    r_multiple: float | None = None
    status: SuggestionStatus
    reasons: list[Any]
    metrics: dict[str, Any]
    price_explanation: str
    llm_summary: str | None
    rule_version: int
    proposed_amount_brl: float
    setup_low: float | None = None
    tranche_index: int = 1
    review_required: bool = False
    review_reason: str | None = None
    acted_by_user_id: str | None
    action_note: str | None
    acted_at: datetime | None
    expires_at: datetime
    created_at: datetime

    @field_serializer(
        "score",
        "entry_price",
        "stop_price",
        "target_price",
        "r_multiple",
        "proposed_amount_brl",
        "setup_low",
    )
    def _ser_money(self, value: float | None) -> float | None:
        return _round2(value)

    @field_serializer("metrics")
    def _ser_metrics(self, metrics: dict[str, Any]) -> dict[str, Any]:
        return _round_metrics(metrics)


class SuggestionAction(BaseModel):
    note: str | None = None
    amount_usd: float | None = None


class ApproveOptionOut(BaseModel):
    amount_usd: float
    quantity: float | None = None
    label: str
    mode: str


class SuggestionApproveOptionsOut(BaseModel):
    live_price: float
    fractional_allowed: bool
    max_amount_usd: float
    default_amount_usd: float | None = None
    approvable: bool
    block_reason: str | None = None
    options: list[ApproveOptionOut] = Field(default_factory=list)


class SuggestionApproveOut(SuggestionOut):
    """Approve response includes broker order outcome for UI feedback."""

    order_id: str | None = None
    order_status: str | None = None
    order_error: str | None = None
    live_price: float | None = None
    fill_hint: str | None = None


class OrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    account_id: str
    suggestion_id: str
    ticker: str
    strategy_kind: str = "income"
    side: str
    quantity: float
    amount_brl: float
    limit_price: float
    status: str
    broker: str
    execution_mode: str
    broker_order_id: str | None
    filled_price: float | None
    filled_at: datetime | None
    error_message: str | None
    execution_payload: dict[str, Any]
    acted_by_user_id: str | None
    created_at: datetime

    @field_serializer("quantity")
    def _ser_qty(self, value: float) -> float:
        return round(float(value), 6)

    @field_serializer("amount_brl", "limit_price", "filled_price")
    def _ser_order_money(self, value: float | None) -> float | None:
        return _round2(value)


class OrderMarkFilled(BaseModel):
    filled_price: float | None = None
    note: str | None = None


class NewsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    ticker: str | None
    title: str
    url: str
    source: str
    published_at: datetime | None


class DeviceTokenIn(BaseModel):
    token: str
    platform: str = "android"


class PositionCloseIn(BaseModel):
    reason: str = Field(description="stop | target | manual | market | protect")
    price: float | None = None


class RotationDismissIn(BaseModel):
    suggestion_id: str


class PositionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    account_id: str
    order_id: str
    suggestion_id: str
    ticker: str
    strategy_kind: str
    quantity: float
    entry_price: float
    stop_price: float | None = None
    target_price: float | None = None
    setup_low: float | None = None
    tranche_index: int = 1
    avg_entry_price: float | None = None
    status: str
    exit_reason: str | None = None
    exit_price: float | None = None
    realized_pnl_brl: float | None = None
    realized_pnl_pct: float | None = None
    r_multiple_realized: float | None = None
    opened_at: datetime
    closed_at: datetime | None = None
    # Mark-to-market (open positions only; null when closed / unavailable)
    mark_price: float | None = None
    cost_brl: float | None = None
    market_value_brl: float | None = None
    unrealized_pnl_brl: float | None = None
    price_alert: str | None = None
    unrealized_pnl_pct: float | None = None
    peak_unrealized_pct: float | None = None
    exit_state: str | None = None
    latched_5: bool | None = None
    protect_active: bool | None = None
    must_review_by: str | None = None
    days_until_review: int | None = None

    @field_serializer(
        "quantity",
        "entry_price",
        "stop_price",
        "target_price",
        "setup_low",
        "avg_entry_price",
        "exit_price",
        "realized_pnl_brl",
        "realized_pnl_pct",
        "r_multiple_realized",
        "mark_price",
        "cost_brl",
        "market_value_brl",
        "unrealized_pnl_brl",
    )
    def _ser_pos_money(self, value: float | None) -> float | None:
        return _round2(value)


class PortfolioOut(BaseModel):
    cash_brl: float
    invested_open_brl: float
    market_value_open_brl: float = 0.0
    unrealized_pnl_brl: float = 0.0
    equity_brl: float
    equity_cost_brl: float | None = None
    open_positions: int
    open_swing: int
    open_income: int
    open_hv_dip: int = 0
    open_hv_dip_tickers: int = 0
    hv_dip_max_positions: int = 4
    hv_dip_cash_floor_pct: float = 30.0
    hv_dip_max_ticker_pct: float = 80.0
    cash_pct_of_equity: float | None = None
    currency: str = "BRL"
    cash_usd: float | None = None
    realized_pnl_day_brl: float

    @field_serializer(
        "cash_brl",
        "invested_open_brl",
        "market_value_open_brl",
        "unrealized_pnl_brl",
        "equity_brl",
        "equity_cost_brl",
        "realized_pnl_day_brl",
        "hv_dip_cash_floor_pct",
        "hv_dip_max_ticker_pct",
        "cash_pct_of_equity",
        "cash_usd",
    )
    def _ser_pf(self, value: float | None) -> float | None:
        if value is None:
            return None
        return round(float(value), 2)


class CloseAllOut(BaseModel):
    closed: int
    cash_brl: float
    items: list[PositionOut]

    @field_serializer("cash_brl")
    def _ser_cash(self, value: float) -> float:
        return round(float(value), 2)


class PnlGoalsOut(BaseModel):
    daily_target_pct: float = 7.0
    equity_ref: float = 0.0
    days_in_period: int = 1
    period_pnl: float = 0.0
    period_pnl_pct: float = 0.0
    period_target_pnl: float = 0.0
    period_target_pct: float = 0.0
    progress_pct: float = 0.0
    hit: bool = False
    currency: str = "BRL"

    @field_serializer(
        "daily_target_pct",
        "equity_ref",
        "period_pnl",
        "period_pnl_pct",
        "period_target_pnl",
        "period_target_pct",
        "progress_pct",
    )
    def _ser_goals(self, value: float) -> float:
        return round(float(value), 2)


class StretchScorecardOut(BaseModel):
    horizon_trades: int = 40
    horizon_days: int = 60
    closed_trades: int = 0
    equity_now: float = 0.0
    equity_target: float = 130.0
    equity_progress_pct: float = 0.0
    avg_return_pct: float = 0.0
    avg_return_target_pct: float = 11.0
    realized_pnl: float = 0.0
    realized_pnl_target: float = 25.0
    latched_pct: float = 0.0
    latched_target_pct: float = 55.0
    protect_or_2r_pct: float = 0.0
    protect_or_2r_target_pct: float = 40.0
    expectancy_r: float | None = None
    expectancy_r_target: float = 0.45
    win_rate_pct: float = 0.0
    win_rate_target_pct: float = 58.0
    max_drawdown_target_pct: float = 12.0
    wins: int = 0
    losses: int = 0

    @field_serializer(
        "equity_now",
        "equity_target",
        "equity_progress_pct",
        "avg_return_pct",
        "avg_return_target_pct",
        "realized_pnl",
        "realized_pnl_target",
        "latched_pct",
        "latched_target_pct",
        "protect_or_2r_pct",
        "protect_or_2r_target_pct",
        "expectancy_r",
        "expectancy_r_target",
        "win_rate_pct",
        "win_rate_target_pct",
        "max_drawdown_target_pct",
    )
    def _ser_sc(self, value: float | None) -> float | None:
        if value is None:
            return None
        return round(float(value), 2)


class PnlReportOut(BaseModel):
    period: str
    strategy_kind: str | None = None
    from_: str = Field(alias="from")
    total_pnl_brl: float
    trades: int
    wins: int
    losses: int
    items: list[PositionOut]
    goals: PnlGoalsOut | None = None
    scorecard: StretchScorecardOut | None = None

    model_config = ConfigDict(populate_by_name=True)

    @field_serializer("total_pnl_brl")
    def _ser_total(self, value: float) -> float:
        return round(float(value), 2)


class PnlSeriesPointOut(BaseModel):
    date: str
    cumulative_pnl: float
    day_pnl: float = 0.0
    target_cumulative_pnl: float = 0.0
    day_target_pnl: float = 0.0
    day_pnl_pct: float = 0.0
    day_target_pct: float = 7.0

    @field_serializer(
        "cumulative_pnl",
        "day_pnl",
        "target_cumulative_pnl",
        "day_target_pnl",
        "day_pnl_pct",
        "day_target_pct",
    )
    def _ser_pnl(self, value: float) -> float:
        return round(float(value), 2)


class PnlSeriesOut(BaseModel):
    period: str
    strategy_kind: str | None = None
    currency: str = "BRL"
    from_: str = Field(alias="from")
    points: list[PnlSeriesPointOut]
    goals: PnlGoalsOut | None = None
    daily_target_pct: float = 7.0
    equity_ref: float = 0.0

    model_config = ConfigDict(populate_by_name=True)

    @field_serializer("daily_target_pct", "equity_ref")
    def _ser_series_meta(self, value: float) -> float:
        return round(float(value), 2)


class IntradayBarOut(BaseModel):
    ts: str
    open: float
    high: float
    low: float
    close: float
    volume: float


class DayTradeSignalOut(BaseModel):
    id: str
    account_id: str
    session_date: date
    ticker: str
    rule_id: str
    side: str
    entry_price: float
    stop_price: float
    target_price: float
    status: str
    simulated_pnl_usd: float | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    closed_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)

    @field_serializer("session_date")
    def _ser_session_date(self, value: Any) -> str:
        if hasattr(value, "isoformat"):
            return value.isoformat()
        return str(value)

    @field_serializer("entry_price", "stop_price", "target_price", "simulated_pnl_usd")
    def _ser_prices(self, value: float | None) -> float | None:
        if value is None:
            return None
        return round(float(value), 4)


class DayTradeGroupStatOut(BaseModel):
    key: str
    n: int = 0
    wins: int = 0
    losses: int = 0
    win_rate: float = 0.0
    win_rate_lo: float = 0.0
    win_rate_hi: float = 0.0
    expectancy_r: float | None = None
    expectancy_r_lo: float | None = None
    expectancy_r_hi: float | None = None
    profit_factor: float | None = None
    avg_hold_minutes: float | None = None
    total_pnl: float = 0.0
    total_r: float = 0.0


class DayTradeAnalyticsOut(BaseModel):
    total_closed: int = 0
    by_rule: list[DayTradeGroupStatOut] = Field(default_factory=list)
    by_ticker: list[DayTradeGroupStatOut] = Field(default_factory=list)
    by_side: list[DayTradeGroupStatOut] = Field(default_factory=list)


class DayTradeConfigOut(BaseModel):
    version: int
    is_active: bool
    params: dict[str, Any]
    origin: str
    validation: dict[str, Any] = Field(default_factory=dict)
    activated_at: datetime | None = None
    created_at: datetime


class DayTradeConfigHistoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    version: int
    params: dict[str, Any]
    origin: str
    reason: str
    validation: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class DayTradeConfigSetIn(BaseModel):
    params: dict[str, Any] = Field(default_factory=dict)
    reason: str = ""
    origin: str = "manual"


class HvDipObservationOut(BaseModel):
    """Radar de observação (facas caindo) — estado persistido do hv_dip."""

    model_config = ConfigDict(from_attributes=True)

    ticker: str
    status: str
    recovery_probability: float | None = None
    recovery_in_progress: bool = False
    active_catalyst: bool = False
    last_decision: str | None = None
    note: str | None = None
    first_seen_at: datetime | None = None
    last_evaluated_at: datetime | None = None
    updated_at: datetime | None = None

    @field_serializer("recovery_probability")
    def _ser_recovery_probability(self, value: float | None) -> float | None:
        if value is None:
            return None
        return round(float(value), 4)


class HvDipConfigOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    version: int
    is_active: bool
    params: dict[str, Any]
    origin: str
    validation: dict[str, Any] = Field(default_factory=dict)
    activated_at: datetime | None = None
    created_at: datetime | None = None


class HvDipConfigHistoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    version: int
    params: dict[str, Any]
    origin: str
    reason: str
    validation: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class NewsEventOut(BaseModel):
    """Catalisador de notícia classificado pelo LLM (event_type/sentiment/confidence)."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    ticker: str | None = None
    title: str
    url: str
    source: str = ""
    event_type: str | None = None
    sentiment: str | None = None
    confidence: float | None = None
    impact_score: float | None = None
    catalyst_strength: str | None = None
    published_at: datetime | None = None
    processed_at: datetime | None = None
    used_in_suggestion: bool = False

    @field_serializer("confidence", "impact_score")
    def _ser_score(self, value: float | None) -> float | None:
        if value is None:
            return None
        return round(float(value), 4)


class DayTradeRegimeOut(BaseModel):
    ticker: str
    regime: str
    slope: float | None = None

    @field_serializer("slope")
    def _ser_slope(self, value: float | None) -> float | None:
        if value is None:
            return None
        return round(float(value), 4)


class DayTradeStateOut(BaseModel):
    circuit_breaker_tripped: list[str] = Field(default_factory=list)
    regimes: list[DayTradeRegimeOut] = Field(default_factory=list)


class WatchlistAddIn(BaseModel):
    ticker: str = Field(min_length=1, max_length=16)
    note: str | None = None


class WatchlistItemOut(BaseModel):
    """Item da watchlist de observação + cotação ao vivo enriquecida."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    account_id: str
    ticker: str
    note: str | None = None
    created_at: datetime | None = None
    price: float | None = None
    prev_close: float | None = None
    change_pct: float | None = None
    currency: str = "BRL"

    @field_serializer("price", "prev_close", "change_pct")
    def _ser_price(self, value: float | None) -> float | None:
        if value is None:
            return None
        return round(float(value), 4)


class LearnStatusOut(BaseModel):
    status: str = "unknown"
    n: int | None = None


class LlmReviewOut(BaseModel):
    ticker: str
    lesson: str = ""
    would_change: str = ""
    confidence: float | None = None
    source: str | None = None


class IntelligencePulseOut(BaseModel):
    """Nightly intelligence snapshot. Read-only; never places orders."""

    available: bool = True
    ts: str | None = None
    llm_default: str | None = None
    last_source: str | None = None
    news_json_ok: int | None = None
    n_closed_usd: int = 0
    learn: dict[str, LearnStatusOut] = Field(default_factory=dict)
    reviews_n: int = 0
    calibration: dict[str, Any] | None = None
    hv_dip_auto_buy_enabled: bool = False
    recent_reviews: list[LlmReviewOut] = Field(default_factory=list)
    swing_h1: dict[str, Any] | None = None
    studies: StudySnapshot | None = None
    ollama: str | None = None
    groq_cooldown: bool | None = None
    ollama_expires_at: str | None = None
    last_llm_source: str | None = None
    assertiveness: dict[str, Any] | None = None
    research: dict[str, Any] | None = None
    memory: dict[str, Any] | None = None
    platt: dict[str, Any] | None = None
    whitelist: dict[str, Any] | None = None
    trials: dict[str, Any] | None = None
    desk_slices: dict[str, Any] | None = None
    live_promotion: dict[str, Any] | None = None
    hv_dip_live_auto_buy: bool = False


class EvolutionEventOut(BaseModel):
    ts: str | None = None
    kind: str
    title: str
    detail: str = ""


class EvolutionListOut(BaseModel):
    items: list[EvolutionEventOut] = Field(default_factory=list)


class MemoryLessonOut(BaseModel):
    id: str | None = None
    kind: str = ""
    scope: str = ""
    text: str = ""
    provenance: str = ""
    confidence: float | None = None
    n_support: int | None = None
    refuted: bool = False
    created_at: str | None = None


class MemoryListOut(BaseModel):
    items: list[MemoryLessonOut] = Field(default_factory=list)


class LedgerRowOut(BaseModel):
    id: str
    source: str
    kind: str
    ticker: str
    p_pred: float
    horizon_days: int = 1
    outcome: bool | None = None
    brier: float | None = None
    created_at: str | None = None
    resolved_at: str | None = None


class LedgerListOut(BaseModel):
    items: list[LedgerRowOut] = Field(default_factory=list)


class DecisionRowOut(BaseModel):
    id: str
    ticker: str
    strategy_kind: str
    verdict: str
    reason: str = ""
    notional: float = 0.0
    enforce: bool = False
    created_at: str | None = None


class DecisionListOut(BaseModel):
    items: list[DecisionRowOut] = Field(default_factory=list)


class CalibrationViewOut(BaseModel):
    calibrators: dict[str, Any] = Field(default_factory=dict)
    assertiveness: dict[str, Any] = Field(default_factory=dict)
