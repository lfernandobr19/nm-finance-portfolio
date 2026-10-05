"""Position open/close and P&L math."""

from datetime import datetime, timezone

from app.domain.models import (
    InvestmentAccount,
    Order,
    OrderSide,
    OrderStatus,
    ExecutionMode,
    Position,
    PositionExitReason,
    PositionStatus,
    StrategyKind,
    Suggestion,
    SuggestionStatus,
)
from app.services.positions import close_position, open_position_from_fill, pnl_report


class _Store:
    def __init__(self):
        self.positions: list[Position] = []
        self.accounts: dict[str, InvestmentAccount] = {}
        self.suggestions: dict[str, Suggestion] = {}
        self.orders: dict[str, Order] = {}

    def add(self, obj):
        if isinstance(obj, Position):
            self.positions.append(obj)
        elif isinstance(obj, InvestmentAccount):
            self.accounts[obj.id] = obj
        elif isinstance(obj, Suggestion):
            self.suggestions[obj.id] = obj
        elif isinstance(obj, Order):
            self.orders[obj.id] = obj

    def get(self, model, id_):
        if model is InvestmentAccount:
            return self.accounts.get(id_)
        if model is Suggestion:
            return self.suggestions.get(id_)
        if model is Order:
            return self.orders.get(id_)
        return None

    def query(self, model):
        rows = self.positions if model is Position else []
        return _Q(rows)

    def flush(self):
        pass


class _Q:
    def __init__(self, rows):
        self._rows = list(rows)

    def filter(self, *args, **kwargs):
        # naive: keep all; tests set up only matching rows
        return self

    def order_by(self, *a):
        return self

    def all(self):
        return self._rows

    def one_or_none(self):
        return self._rows[0] if self._rows else None

    def count(self):
        return len(self._rows)


def _account(cash=10000.0) -> InvestmentAccount:
    return InvestmentAccount(
        id="acc",
        name="t",
        owner_user_id="u",
        cash_brl=cash,
        swing_equity_brl=cash,
    )


def test_open_and_close_stop_pnl():
    db = _Store()
    acc = _account(5000)
    db.add(acc)
    sug = Suggestion(
        id="sug",
        account_id="acc",
        ticker="VALE3",
        strategy_kind=StrategyKind.swing,
        score=68,
        status=SuggestionStatus.approved,
        reasons=[],
        metrics={},
        price_explanation="",
        expires_at=datetime.now(timezone.utc),
        entry_price=100.0,
        stop_price=95.0,
        target_price=110.0,
        proposed_amount_brl=1000,
    )
    db.add(sug)
    order = Order(
        id="ord",
        account_id="acc",
        suggestion_id="sug",
        ticker="VALE3",
        strategy_kind=StrategyKind.swing,
        side=OrderSide.buy,
        quantity=10,
        amount_brl=1000.0,
        limit_price=100.0,
        status=OrderStatus.filled,
        broker="inter",
        execution_mode=ExecutionMode.paper,
        filled_price=100.0,
        filled_at=datetime.now(timezone.utc),
        execution_payload={},
    )
    db.add(order)

    pos = open_position_from_fill(db, order, sug)
    assert pos.status == PositionStatus.open
    assert acc.cash_brl == 4000.0

    closed = close_position(db, pos, reason=PositionExitReason.stop)
    assert closed.realized_pnl_brl == -50.0  # (95-100)*10
    assert closed.exit_reason == PositionExitReason.stop
    assert acc.cash_brl == 4950.0  # 4000 + 10*95


def test_close_target_positive():
    db = _Store()
    acc = _account(2000)
    db.add(acc)
    pos = Position(
        id="p",
        account_id="acc",
        order_id="o",
        suggestion_id="s",
        ticker="PETR4",
        strategy_kind=StrategyKind.swing,
        quantity=5,
        entry_price=40.0,
        stop_price=38.0,
        target_price=44.0,
        status=PositionStatus.open,
    )
    # cash already debited conceptually
    acc.cash_brl = 1800.0
    closed = close_position(db, pos, reason="target")
    assert closed.realized_pnl_brl == 20.0
    assert acc.cash_brl == 2020.0


def test_income_requires_manual():
    db = _Store()
    acc = _account()
    db.add(acc)
    pos = Position(
        id="p",
        account_id="acc",
        order_id="o",
        suggestion_id="s",
        ticker="HGLG11",
        strategy_kind=StrategyKind.income,
        quantity=10,
        entry_price=160.0,
        stop_price=None,
        target_price=None,
        status=PositionStatus.open,
    )
    try:
        close_position(db, pos, reason=PositionExitReason.stop)
        assert False
    except ValueError as e:
        assert "stop" in str(e).lower()
    closed = close_position(db, pos, reason=PositionExitReason.manual, manual_price=165.0)
    assert closed.realized_pnl_brl == 50.0
