"""LLM insight generator: the model reads a pre-computed numeric digest and writes
short, grounded PT insights. It never computes probabilities — it only phrases
what the digest already contains, then the JSON is validated against ``Insight``
(``extra='forbid'``) exactly like ``propose.py``.

Cost gate: insights only run when a digest is available (results exist) and the
LLM is configured; callers (``runner``) are already event-driven so this runs on
data change, not on a fixed clock.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import ValidationError
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.domain.models import NewsEvent
from app.services.llm_client import chat, cloud_configured, local_configured
from app.services.studies.models import Insight, InsightEvidence, StudyResult

logger = logging.getLogger("fiidesk.studies.insight")

INSIGHT_CAP = 10
MAX_TICKERS = 5
# The full digest (universe + top tickers) is a large prompt: the local 7B takes
# ~50s on this hardware, so give insights more headroom than the 45s default.
INSIGHT_TIMEOUT_SECONDS = 120.0

_SYSTEM = (
    "Você é o setor de pesquisa de um desk de trading. Recebe um digest numérico "
    "pré-computado (nunca barras cruas) e, às vezes, um bloco de Lições acumuladas. "
    "Cada insight deve citar APENAS números que estão no digest; cite o valor em "
    "``evidence``. Se houver Lições acumuladas, cite pelo menos uma no ``text`` ou "
    "em evidence com fact=\"memória\" — sobretudo as REFUTADAS, para não repropor "
    "o que já foi desmentido. Não invente dados, não proponha operações, não dê "
    "conselhos de investimento. Responda SOMENTE com um objeto JSON "
    "{\"insights\": [ ... ]} onde cada item tem: ticker, kind (universe|ticker), "
    "text, evidence (lista de {fact, value}), confidence (0 a 1), "
    "channel (hv_dip|swing|day_trade)."
)


def _price_stats(bars: list[Any]) -> dict[str, Any]:
    closes = [float(getattr(b, "close", 0.0)) for b in bars if getattr(b, "close", None)]
    if not closes:
        return {}
    last = closes[-1]
    sma20 = sum(closes[-20:]) / min(20, len(closes))
    ret20 = round((last / closes[-21] - 1.0) * 100.0, 2) if len(closes) >= 21 else None
    peak = closes[0]
    mdd = 0.0
    for c in closes:
        peak = max(peak, c)
        if peak > 0:
            mdd = min(mdd, (c - peak) / peak * 100.0)
    return {
        "bars": len(closes),
        "close": round(last, 2),
        "return_20d_pct": ret20,
        "above_sma20": last >= sma20,
        "max_drawdown_pct": round(mdd, 2),
    }


def _ticker_news_stats(db: Session, ticker: str) -> dict[str, Any]:
    rows = db.query(NewsEvent).filter(NewsEvent.ticker == ticker).all()
    bull_ret: list[float] = []
    bear_ret: list[float] = []
    bull = bear = 0
    for ev in rows:
        raw = ev.raw or {}
        r = raw.get("outcome_ret_1d")
        if not isinstance(r, (int, float)):
            r = None
        if ev.sentiment == "bullish":
            bull += 1
            if r is not None:
                bull_ret.append(r * 100.0)
        elif ev.sentiment == "bearish":
            bear += 1
            if r is not None:
                bear_ret.append(r * 100.0)
    return {
        "total": len(rows),
        "bullish": bull,
        "bearish": bear,
        "avg_ret_after_bullish_pct": round(sum(bull_ret) / len(bull_ret), 2) if bull_ret else None,
        "avg_ret_after_bearish_pct": round(sum(bear_ret) / len(bear_ret), 2) if bear_ret else None,
    }


def _universe_news_stats(db: Session) -> dict[str, Any]:
    try:
        total = db.query(func.count()).select_from(NewsEvent).scalar() or 0
        classified = (
            db.query(func.count())
            .select_from(NewsEvent)
            .filter(NewsEvent.processed_at.is_not(None))
            .scalar()
            or 0
        )
    except Exception:
        return {}
    return {"total": int(total), "classified": int(classified)}


def _pick_tickers(results: list[StudyResult], max_tickers: int) -> list[str]:
    per = [r for r in results if r.ticker and r.ticker != "UNIVERSE"]
    per.sort(key=lambda r: abs(r.vs_universe or 0.0), reverse=True)
    out: list[str] = []
    seen: set[str] = set()
    for r in per:
        if r.ticker not in seen:
            seen.add(r.ticker)
            out.append(r.ticker)
        if len(out) >= max_tickers:
            break
    return out


def _round(v: Any, nd: int = 3) -> Any:
    return round(v, nd) if isinstance(v, (int, float)) else v


def build_ticker_digest(
    db: Session,
    ticker: str,
    results: list[StudyResult],
) -> dict[str, Any]:
    """Compact ground-truth digest for one ticker (bars + patterns + news)."""
    from app.services.market_data import MarketDataClient

    bars = MarketDataClient().fetch_daily_bars(ticker)
    patterns = [
        {
            "fingerprint": r.fingerprint,
            "n": r.n,
            "p_higher": _round(r.p_higher),
            "p_stop_first": _round(r.p_stop_first),
            "p_recover": _round(r.p_recover),
            "vs_universe": _round(r.vs_universe),
        }
        for r in results
        if r.ticker == ticker
    ]
    return {
        "ticker": ticker,
        "price": _price_stats(bars),
        "patterns": patterns,
        "news": _ticker_news_stats(db, ticker),
    }


def build_universe_digest(db: Session, results: list[StudyResult]) -> dict[str, Any]:
    patterns = [
        {
            "fingerprint": r.fingerprint,
            "label": r.label,
            "n": r.n,
            "p_higher": _round(r.p_higher),
            "p_stop_first": _round(r.p_stop_first),
            "p_recover": _round(r.p_recover),
        }
        for r in results
        if r.ticker == "UNIVERSE"
    ]
    return {"patterns": patterns, "news": _universe_news_stats(db)}


def generate_insights(
    db: Session,
    *,
    results: list[StudyResult] | None = None,
    max_tickers: int = MAX_TICKERS,
    max_insights: int = INSIGHT_CAP,
) -> list[Insight]:
    """Generate grounded insights from the numeric digest (one capped LLM call)."""
    if not (local_configured() or cloud_configured()):
        return []
    results = results or []
    if not results:
        return []

    universe = build_universe_digest(db, results)
    tickers = [
        build_ticker_digest(db, t, results)
        for t in _pick_tickers(results, max_tickers)
    ]
    digest = {"universe": universe, "tickers": tickers}
    if not universe.get("patterns") and not tickers:
        return []

    memory_bits = ""
    try:
        from app.services.learn.memory import prompt_block

        names = " ".join(t.get("ticker", "") for t in tickers if isinstance(t, dict))
        memory_bits = prompt_block(f"estudos hv_dip {names}".strip())
    except Exception:
        memory_bits = ""
    user = json.dumps(digest, ensure_ascii=False)
    if memory_bits:
        user = memory_bits + "\n\n" + user

    res = chat(
        [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": user},
        ],
        json_mode=True,
        temperature=0.2,
        timeout=INSIGHT_TIMEOUT_SECONDS,
        escalate=False,
    )
    if not res.content:
        return []

    try:
        data = json.loads(res.content)
    except json.JSONDecodeError:
        logger.info("studies insight: non-JSON dropped")
        return []

    items = data.get("insights") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return []

    out: list[Insight] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            ins = Insight.model_validate(item)
        except ValidationError as exc:
            logger.info("studies insight drop (schema): %s", str(exc.errors()[:1]))
            continue
        out.append(ins)
        if len(out) >= max_insights:
            break
    return out


__all__ = [
    "INSIGHT_CAP",
    "MAX_TICKERS",
    "INSIGHT_TIMEOUT_SECONDS",
    "build_ticker_digest",
    "build_universe_digest",
    "generate_insights",
]
