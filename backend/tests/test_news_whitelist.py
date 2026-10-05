"""News whitelist derived from outcomes, not from words that sound bullish."""

from __future__ import annotations

from app.domain.models import NewsEvent
from app.services.learn import news_whitelist as wl_mod
from app.services.learn.news_whitelist import (
    allowed_event_types,
    compute_whitelist,
    refresh_whitelist,
)


def _add(db, event_type: str, *, hits: int, misses: int, horizon: int = 1):
    for i in range(hits + misses):
        db.add(
            NewsEvent(
                ticker="AMD",
                event_type=event_type,
                sentiment="bullish",
                confidence=0.8,
                title=f"{event_type}-{i}",
                url=f"https://example.test/{event_type}/{horizon}/{i}",
                raw={f"outcome_ok_{horizon}d": i < hits},
            )
        )


def test_a_type_that_beats_the_base_rate_is_allowed(db_session):
    # Base rate is dragged down by the crowd; the winner sits far above it.
    _add(db_session, "other", hits=150, misses=350)
    _add(db_session, "product_launch", hits=240, misses=160)
    db_session.flush()

    report = compute_whitelist(db_session)
    assert report["status"] == "ok"
    assert report["allowed"] == ["product_launch"]
    assert report["horizon"] == 1


def test_a_type_that_merely_sounds_bullish_is_rejected(db_session):
    """guidance_up is on the shipped list and underperforms the base rate."""
    _add(db_session, "other", hits=400, misses=400)
    _add(db_session, "guidance_up", hits=60, misses=140)
    db_session.flush()

    report = compute_whitelist(db_session)
    assert "guidance_up" not in report["allowed"]
    entry = next(t for t in report["types"] if t["event_type"] == "guidance_up")
    assert entry["hit_rate"] < report["base_rate"]


def test_types_that_all_perform_alike_produce_no_winner(db_session):
    """Nothing may be promoted when no type actually separates from the rest.

    The false-discovery *rate* under real noise is exercised at the Benjamini-
    Hochberg level in test_fdr.py, over enough runs to mean something. Here the
    data is deliberately uniform so the assertion cannot hinge on a lucky seed.
    """
    for i in range(12):
        _add(db_session, f"type_{i}", hits=40, misses=40)
    db_session.flush()

    report = compute_whitelist(db_session)
    assert report["n_tested"] == 12
    assert report["allowed"] == []


def test_a_lone_lucky_streak_does_not_clear_correction(db_session):
    """One type running hot on a small sample is not evidence."""
    for i in range(11):
        _add(db_session, f"type_{i}", hits=40, misses=40)
    _add(db_session, "hot_streak", hits=14, misses=6)  # 70% on n=20
    db_session.flush()

    report = compute_whitelist(db_session)
    assert "hot_streak" not in report["allowed"]


def test_types_below_the_sample_floor_are_not_tested(db_session):
    _add(db_session, "other", hits=400, misses=400)
    _add(db_session, "rare_but_perfect", hits=8, misses=0)
    db_session.flush()

    report = compute_whitelist(db_session)
    assert "rare_but_perfect" not in report["allowed"]
    assert all(t["event_type"] != "rare_but_perfect" for t in report["types"])


def test_thin_corpus_reports_insufficient_data(db_session):
    _add(db_session, "product_launch", hits=20, misses=5)
    db_session.flush()

    report = compute_whitelist(db_session)
    assert report["status"] == "insufficient_data"
    assert report["allowed"] == []


def test_longest_available_horizon_wins(db_session):
    """14 days is what the strategy holds, so it decides once it exists."""
    _add(db_session, "other", hits=200, misses=300, horizon=14)
    _add(db_session, "product_launch", hits=300, misses=200, horizon=14)
    db_session.flush()

    report = compute_whitelist(db_session)
    assert report["horizon"] == 14
    assert report["allowed"] == ["product_launch"]


def test_unlabelled_events_never_count(db_session):
    _add(db_session, "other", hits=400, misses=400)
    for i in range(500):
        db_session.add(
            NewsEvent(
                ticker="AMD", event_type="unlabelled", sentiment="bullish",
                confidence=0.9, title=f"u{i}", url=f"https://example.test/u/{i}",
                raw={},
            )
        )
    db_session.flush()

    report = compute_whitelist(db_session)
    assert report["n"] == 800
    assert "unlabelled" not in report["allowed"]


def test_low_confidence_events_are_excluded(db_session):
    _add(db_session, "other", hits=400, misses=400)
    for i in range(100):
        db_session.add(
            NewsEvent(
                ticker="AMD", event_type="cheap_talk", sentiment="bullish",
                confidence=0.2, title=f"c{i}", url=f"https://example.test/c/{i}",
                raw={"outcome_ok_1d": True},
            )
        )
    db_session.flush()

    report = compute_whitelist(db_session)
    assert "cheap_talk" not in report["allowed"]


def test_allowed_event_types_falls_back_to_no_filter(tmp_path, monkeypatch, db_session):
    """An empty result must not silently switch the catalyst off entirely."""
    monkeypatch.setattr(wl_mod, "_PATH", tmp_path / "news_whitelist.json")
    assert allowed_event_types() is None  # nothing written yet

    for i in range(12):
        _add(db_session, f"t{i}", hits=40, misses=40)
    db_session.flush()

    refresh_whitelist(db_session)
    assert allowed_event_types() is None


def test_allowed_event_types_reads_back_a_real_winner(tmp_path, monkeypatch, db_session):
    monkeypatch.setattr(wl_mod, "_PATH", tmp_path / "news_whitelist.json")
    _add(db_session, "other", hits=150, misses=350)
    _add(db_session, "product_launch", hits=240, misses=160)
    db_session.flush()

    refresh_whitelist(db_session)
    assert allowed_event_types() == {"product_launch"}
