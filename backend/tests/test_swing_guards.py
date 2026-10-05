"""Swing freios: max positions, cash floor, score C live block."""

from app.domain.models import (
    ExecutionMode,
    InvestmentAccount,
    Position,
    PositionStatus,
    StrategyKind,
    Suggestion,
    SuggestionStatus,
)
from app.services.orders import assert_swing_guards, count_open_swing_positions


class _FakeQuery:
    def __init__(self, rows):
        self._rows = list(rows)

    def filter(self, *args, **kwargs):
        return self

    def count(self):
        return len(self._rows)

    def all(self):
        return self._rows

    def one_or_none(self):
        return self._rows[0] if self._rows else None


class _FakeDB:
    def __init__(self, positions: list[Position] | None = None, orders: list | None = None):
        self._positions = positions or []
        self._orders = orders or []

    def query(self, model):
        if model is Position:
            return _FakeQuery(self._positions)
        return _FakeQuery(self._orders)


def _account(**kwargs) -> InvestmentAccount:
    defaults = dict(
        id="acc",
        name="t",
        owner_user_id="u",
        swing_max_positions=5,
        swing_cash_floor_pct=20.0,
        swing_risk_pct_a=1.5,
        swing_risk_pct_b=1.0,
        swing_equity_brl=10_000.0,
        cash_brl=10_000.0,
        execution_mode=ExecutionMode.paper,
        max_ticket_brl=5000.0,
    )
    defaults.update(kwargs)
    return InvestmentAccount(**defaults)


def _suggestion(**kwargs) -> Suggestion:
    defaults = dict(
        id="sug",
        account_id="acc",
        ticker="AAPL34",
        strategy_kind=StrategyKind.swing,
        score=90.0,
        swing_score_letter="A",
        status=SuggestionStatus.pending,
        reasons=[],
        metrics={"price": 50.0},
        price_explanation="",
        expires_at=None,
        entry_price=50.0,
        stop_price=48.0,
        target_price=54.0,
        proposed_amount_brl=1000.0,
    )
    defaults.update(kwargs)
    return Suggestion(**defaults)


def _open_pos(**kwargs) -> Position:
    defaults = dict(
        id="p1",
        account_id="acc",
        order_id="o1",
        suggestion_id="s1",
        ticker="AAPL34",
        strategy_kind=StrategyKind.swing,
        quantity=10,
        entry_price=50.0,
        stop_price=48.0,
        target_price=54.0,
        status=PositionStatus.open,
    )
    defaults.update(kwargs)
    return Position(**defaults)


def test_count_open_swing_positions():
    db = _FakeDB(positions=[_open_pos()])
    assert count_open_swing_positions(db, "acc") == 1


def test_guard_blocks_score_c_live():
    account = _account(execution_mode=ExecutionMode.live)
    sug = _suggestion(swing_score_letter="C")
    db = _FakeDB()
    try:
        assert_swing_guards(db, account, sug, amount_brl=500)
        assert False, "expected ValueError"
    except ValueError as e:
        assert "Score C" in str(e)


def test_guard_max_positions():
    positions = [_open_pos(id=f"p{i}", order_id=f"o{i}", suggestion_id=f"s{i}") for i in range(5)]
    db = _FakeDB(positions=positions)
    try:
        assert_swing_guards(db, _account(), _suggestion(), amount_brl=100)
        assert False, "expected ValueError"
    except ValueError as e:
        assert "posiç" in str(e).lower() or "posic" in str(e).lower()


def test_guard_cash_floor():
    # cash 2500, floor 20% of equity 10k = 2000; order 1000 leaves 1500 < 2000
    db = _FakeDB()
    try:
        assert_swing_guards(db, _account(cash_brl=2500.0), _suggestion(), amount_brl=1000.0)
        assert False, "expected ValueError"
    except ValueError as e:
        assert "caixa" in str(e).lower()
