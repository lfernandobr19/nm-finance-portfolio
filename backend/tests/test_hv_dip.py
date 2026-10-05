"""Tests for NM High-Vol Dip scoring and market data client."""

from datetime import datetime, timezone

from app.services.hv_dip.score import HvDipSignals, score_hv_dip


def test_score_hv_dip_letter_a():
    scored = score_hv_dip(
        HvDipSignals(
            dip_pct=12.0,
            atr_pct=4.0,
            volume_ratio=1.2,
            entry=100.0,
            stop=88.0,
            target=124.0,
        )
    )
    assert scored is not None
    assert scored.letter == "A"
    assert scored.r_multiple >= 1.5


def test_score_hv_dip_review_is_c():
    scored = score_hv_dip(
        HvDipSignals(
            dip_pct=15.0,
            atr_pct=5.0,
            volume_ratio=1.5,
            entry=90.0,
            stop=80.0,
            target=110.0,
            review_required=True,
            review_reason="52w low",
        )
    )
    assert scored is not None
    assert scored.letter == "C"


def test_market_data_yahoo_daily_bars(monkeypatch):
    from app.config import get_settings

    get_settings.cache_clear()

    ts = int(datetime(2024, 6, 3, tzinfo=timezone.utc).timestamp())
    fake = {
        "chart": {
            "result": [
                {
                    "timestamp": [ts],
                    "indicators": {
                        "quote": [
                            {
                                "open": [100.0],
                                "high": [105.0],
                                "low": [99.0],
                                "close": [104.0],
                                "volume": [1_000_000.0],
                            }
                        ]
                    },
                }
            ]
        }
    }

    class FakeResp:
        status_code = 200

        def json(self):
            return fake

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url, params=None):
            return FakeResp()

    monkeypatch.setattr("app.services.market_data.httpx.Client", FakeClient)
    from app.services.market_data import MarketDataClient

    bars = MarketDataClient().fetch_daily_bars("TSLA", force=True)
    assert len(bars) == 1
    assert bars[0].close == 104.0
    get_settings.cache_clear()
