"""Trader judgment: numeric gates are priors, not laws.

A $300 desk that only obeys frozen percentages never buys NVDA and never
refuses a scandal dump. This module decides, from cash + news + memory:

- courage: 1 share still fits; leftover misses a floor/budget by a rounding
  gap; thesis is intact → size to 1 share and act
- observe: deep dislocation with bearish structural news → do not buy, keep
  watching
- deny: cannot express the idea even with 1 share (no cash)

Hard stops (paused, invalid, kill switch) never reach this module.

Exits use the same basis: giveback / stop / target / time-stop are priors.
Scandal or a failed thesis → sell. A numeric nick with the thesis intact → hold.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from sqlalchemy.orm import Session

from app.config import get_settings
from app.domain.models import NewsEvent

logger = logging.getLogger("fiidesk.desk_judgment")

Action = Literal["allow", "resize", "observe", "deny", "sell", "hold"]

_SOFT_DENIES = frozenset({"cash_floor", "budget", "unaffordable", "regime_lock"})
_STRUCTURAL_EVENTS = frozenset(
    {
        "litigation",
        "downgrade",
        "guidance_down",
        "regulation",
        "restructuring",
    }
)
_SCANDAL_MARKERS = (
    "fraud",
    "bankrupt",
    "bankruptcy",
    "escândalo",
    "escandalo",
    "going concern",
    "investigation",
    "investigação",
    "falência",
    "falencia",
    "quebra estrutural",
    "restatement",
)


@dataclass
class Judgment:
    action: Action
    reason: str
    thesis: str
    notional: float | None = None
    confidence: float = 0.6

    def as_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "reason": self.reason,
            "thesis": self.thesis,
            "notional": self.notional,
            "confidence": self.confidence,
        }


def structural_risk(
    news: list[Any],
    memories: list[dict[str, Any]] | None = None,
) -> tuple[bool, str]:
    """True when the tape looks like a company breaking, not a buyable dip."""
    for ev in news:
        sentiment = str(getattr(ev, "sentiment", None) or "").lower()
        event_type = str(getattr(ev, "event_type", None) or "").lower()
        conf = float(getattr(ev, "confidence", None) or 0.0)
        title = str(getattr(ev, "title", None) or "").lower()
        if any(m in title for m in _SCANDAL_MARKERS):
            return True, f"headline:{title[:80]}"
        if (
            sentiment == "bearish"
            and event_type in _STRUCTURAL_EVENTS
            and conf >= 0.55
        ):
            return True, f"{event_type} bearish conf={conf:.2f}"
    for item in memories or []:
        if item.get("refuted"):
            continue
        text = str(item.get("text") or "").lower()
        if any(m in text for m in _SCANDAL_MARKERS):
            return True, "memory:structural"
    return False, ""


def load_news(db: Session, ticker: str, *, days: int = 7) -> list[NewsEvent]:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    try:
        return (
            db.query(NewsEvent)
            .filter(
                NewsEvent.ticker == ticker.upper(),
                NewsEvent.published_at.is_not(None),
                NewsEvent.published_at >= since,
            )
            .order_by(NewsEvent.published_at.desc())
            .limit(20)
            .all()
        )
    except Exception:
        logger.exception("desk_judgment news load failed for %s", ticker)
        return []


def load_memories(ticker: str) -> list[dict[str, Any]]:
    try:
        from app.services.learn.memory import search

        return search(f"{ticker} risco estrutural escândalo fraude falência", limit=4)
    except Exception:
        logger.exception("desk_judgment memory search failed for %s", ticker)
        return []


def consider(
    *,
    ticker: str,
    price: float,
    cash: float,
    deny_reason: str,
    news: list[Any] | None = None,
    memories: list[dict[str, Any]] | None = None,
    dip_pct: float | None = None,
) -> Judgment | None:
    """Decide after a numeric deny (or a thesis skip). None = keep the prior."""
    settings = get_settings()
    if not bool(getattr(settings, "desk_judgment_enabled", True)):
        return None

    px = float(price)
    cash_now = float(cash)
    if not isinstance(news, (list, tuple)):
        news = []
    if not isinstance(memories, (list, tuple)):
        memories = []
    structural, why = structural_risk(news, memories)

    if structural:
        dip_txt = f" dip {dip_pct:.1f}%" if dip_pct is not None else ""
        return Judgment(
            action="observe",
            reason="observe_structural",
            thesis=(
                f"{ticker}: queda{dip_txt} parece quebra/escândalo ({why}). "
                "Não compro; continuo observando."
            ),
            confidence=0.75,
        )

    # The desk decides, it does not obey frozen locks. Every numeric gate
    # (cash floor, budget, cooldown, drawdown, stoploss count, regime, even
    # miscalibration) is a prior the personality may lift with courage — as long
    # as one share fits. Only the operational dedup (a working order to replace,
    # a busy allocate window) keeps the prior, so we never double-buy.
    if deny_reason in ("working_order", "window_busy"):
        return None

    if px <= 0 or cash_now + 1e-6 < px:
        return Judgment(
            action="deny",
            reason="no_share",
            thesis=f"{ticker}: 1 ação a US$ {px:.2f} não cabe no caixa US$ {cash_now:.2f}.",
            confidence=0.9,
        )

    leftover = cash_now - px
    dip_txt = f", {dip_pct:.1f}% abaixo da máxima recente" if dip_pct is not None else ""
    if deny_reason == "fresh_high":
        thesis = (
            f"{ticker}: a máxima recente já é a origem da queda{dip_txt}. "
            f"1 ação (US$ {px:.2f}) cabe; sem notícia estrutural. Compro."
        )
        return Judgment(
            action="allow",
            reason="judgment_courage",
            thesis=thesis,
            notional=round(px, 2),
            confidence=0.65,
        )

    thesis = (
        f"{ticker}{dip_txt}: a trava {deny_reason} impediria a única forma de "
        f"participar (1 ação a US$ {px:.2f}, sobra US$ {leftover:.2f}). "
        "Sem evidência de quebra. Assumo o risco."
    )
    return Judgment(
        action="resize",
        reason="judgment_courage",
        thesis=thesis,
        notional=round(px, 2),
        confidence=0.7,
    )


def consider_exit(
    *,
    ticker: str,
    entry: float,
    price: float,
    peak: float | None = None,
    trigger: str = "none",
    news: list[Any] | None = None,
    memories: list[dict[str, Any]] | None = None,
    pnl_pct: float | None = None,
) -> Judgment | None:
    """Decide whether a numeric exit prior should fire.

    Returns sell / hold, or None to keep the numeric prior as-is.
    """
    settings = get_settings()
    if not bool(getattr(settings, "desk_judgment_enabled", True)):
        return None

    px = float(price)
    cost = float(entry)
    if not isinstance(news, (list, tuple)):
        news = []
    if not isinstance(memories, (list, tuple)):
        memories = []
    structural, why = structural_risk(news, memories)

    if pnl_pct is None and cost > 0:
        pnl_pct = (px - cost) / cost * 100.0
    giveback_pct = None
    if peak is not None and float(peak) > 0:
        giveback_pct = (float(peak) - px) / float(peak) * 100.0

    # Thesis is dead: the bounce failed or the runner gave the move back.
    collapsed = (pnl_pct is not None and pnl_pct <= -8.0) or (
        giveback_pct is not None and giveback_pct >= 8.0
    )

    if structural:
        return Judgment(
            action="sell",
            reason="judgment_cut",
            thesis=(
                f"{ticker}: risco estrutural ({why}). "
                "Não espero a trava numérica — saio."
            ),
            confidence=0.8,
        )

    if collapsed:
        gb = f", {giveback_pct:.1f}% abaixo do pico" if giveback_pct is not None else ""
        pnl_txt = f"{pnl_pct:.1f}%" if pnl_pct is not None else "?"
        return Judgment(
            action="sell",
            reason="judgment_cut",
            thesis=(f"{ticker}: a tese não segurou (PnL {pnl_txt}{gb}). Vendo."),
            confidence=0.75,
        )

    trig = (trigger or "none").lower()
    if trig in {"", "none", "ok"}:
        return None

    if trig == "target":
        return Judgment(
            action="hold",
            reason="judgment_hold",
            thesis=(
                f"{ticker}: o alvo numérico é prior. Tese intacta, deixo correr."
            ),
            confidence=0.65,
        )
    if trig == "time_stop" and (pnl_pct is None or pnl_pct < -2.0):
        return Judgment(
            action="sell",
            reason="judgment_cut",
            thesis=(
                f"{ticker}: o prazo esgotou e a tese não pagou "
                f"(PnL {pnl_pct:.1f}%). Saio."
            ),
            confidence=0.7,
        )
    return Judgment(
        action="hold",
        reason="judgment_hold",
        thesis=(
            f"{ticker}: a trava {trig} disparou, mas não há quebra nem colapso. "
            "Mantenho."
        ),
        confidence=0.7,
    )


def judge_intent(db: Session, intent: Any, deny_reason: str) -> Judgment | None:
    """Load context and judge a live DeskIntent after a numeric deny."""
    cash = float(getattr(intent.account, "cash_usd", None) or 0)
    dip = None
    metrics = getattr(intent, "metrics", None) or {}
    if isinstance(metrics, dict) and metrics.get("dip_pct") is not None:
        try:
            dip = float(metrics["dip_pct"])
        except (TypeError, ValueError):
            dip = None
    news = load_news(db, intent.ticker)
    memories = load_memories(intent.ticker)
    return consider(
        ticker=str(intent.ticker).upper(),
        price=float(intent.price),
        cash=cash,
        deny_reason=deny_reason,
        news=news,
        memories=memories,
        dip_pct=dip,
    )


def record_exit_forecast(db: Session, position: Any, judged: Judgment) -> None:
    """Write hold/cut as a probability before the close grades it."""
    if judged is None:
        return
    pos_id = getattr(position, "id", None)
    ticker = getattr(position, "ticker", None)
    if not pos_id or not ticker:
        return
    try:
        from app.services.learn.ledger import record_forecast_once
    except Exception:
        return
    direction = "down" if judged.action == "sell" else "up"
    try:
        record_forecast_once(
            db,
            ref_id=str(pos_id),
            source="judgment",
            kind=str(judged.reason or judged.action),
            ticker=str(ticker),
            p_pred=float(judged.confidence or 0.6),
            horizon_days=5,
            features={"direction": direction, "action": judged.action},
        )
    except Exception:
        logger.debug("judgment exit forecast skipped", exc_info=True)
