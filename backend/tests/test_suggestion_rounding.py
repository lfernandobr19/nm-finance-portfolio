from datetime import datetime, timezone

from app.domain.models import SuggestionStatus
from app.schemas import SuggestionOut


def test_suggestion_out_rounds_prices():
    out = SuggestionOut(
        id="1",
        account_id="a",
        ticker="VALE3",
        asset_class="fii",
        dividend_frequency="other",
        score=68.0,
        entry_price=78.7,
        stop_price=75.77821428571428,
        target_price=84.54357142857144,
        r_multiple=2,
        status=SuggestionStatus.pending,
        reasons=[],
        metrics={"atr_pct": 2.475040842258125, "strategy": "swing_dw_breakout"},
        price_explanation="x",
        llm_summary=None,
        rule_version=1,
        proposed_amount_brl=2675.8,
        acted_by_user_id=None,
        action_note=None,
        acted_at=None,
        expires_at=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
    )
    dumped = out.model_dump()
    assert dumped["stop_price"] == 75.78
    assert dumped["target_price"] == 84.54
    assert dumped["proposed_amount_brl"] == 2675.8
    assert dumped["metrics"]["atr_pct"] == 2.48
