"""News bonus is continuous in the calibrated probability."""

from __future__ import annotations

from app.services.hv_dip.engine import news_catalyst_bonus


def test_bonus_is_monotonic_in_calibrated_p(monkeypatch):
    monkeypatch.setattr(
        "app.services.learn.calibration.calibrated_probability",
        lambda source, p, fallback=None: p,
    )
    lo = news_catalyst_bonus(0.2)
    mid = news_catalyst_bonus(0.5)
    hi = news_catalyst_bonus(0.9)
    assert lo < mid < hi
    assert hi <= 5.0


def test_miscalibrated_source_shrinks_bonus(monkeypatch):
    monkeypatch.setattr(
        "app.services.learn.calibration.calibrated_probability",
        lambda source, p, fallback=None: 0.05,
    )
    assert news_catalyst_bonus(0.95) < 0.5


def test_bonus_uses_event_type_calibrator(monkeypatch):
    seen: list[tuple[str, str | None]] = []

    def _cal(source, p, fallback=None):
        seen.append((source, fallback))
        return 0.2 if source == "news:product_launch" else p

    monkeypatch.setattr(
        "app.services.learn.calibration.calibrated_probability",
        _cal,
    )
    bonus_typed = news_catalyst_bonus(0.9, "product_launch")
    bonus_other = news_catalyst_bonus(0.9, "guidance_up")
    assert seen[0] == ("news:product_launch", "news")
    assert seen[1] == ("news:guidance_up", "news")
    assert bonus_typed < bonus_other
