"""Apply studies to err less (never to trade more). No LLM.

When a universe study shows weak recovery odds — P(close above entry after the
horizon, i.e. "does it appreciate again in ~2 weeks") — with enough samples
(n >= floor), the desk *suppresses* that pattern on its own — it does not ask a
human and it does not loosen anything. Loosening stays owned by the walk-forward
learn loops (hv_dip/day_trade) under their own DSR/PBO gates.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from app.services.stats import benjamini_hochberg, binomial_test_less
from app.services.studies.models import StudyResult

logger = logging.getLogger("fiidesk.studies.apply")

GUARD_PATH = Path(".cache/fiidesk/study_guard.json")
# The user's ruler: a buyable dip is one with more than even odds of appreciating
# again in ~2 weeks. The guard flags a pattern only when its *recovery* odds are
# demonstrated below this null — not when a tight target-before-stop is rare.
WEAK_P_RECOVER_NULL = 0.50
FDR_ALPHA = 0.10
DEFAULT_FLOOR = 30
# Held-out samples needed before the confirmation step can speak at all.
OOS_FLOOR = 10


def _p_recover(r: StudyResult) -> float | None:
    """P(close above entry after the horizon) — the ruler the desk actually uses."""
    if r.n == 0 or r.p_recover is None:
        return None
    return float(r.p_recover)


def _oos_p_recover(r: StudyResult) -> float | None:
    """Same recovery odds over the held-out tail, or None when it is too thin."""
    if r.oos_n < OOS_FLOOR or r.oos_p_recover is None:
        return None
    return float(r.oos_p_recover)


def evaluate(
    results: list[StudyResult],
    *,
    floor: int = DEFAULT_FLOOR,
    alpha: float = FDR_ALPHA,
) -> dict[str, Any]:
    """Return decisions (per universe study) + guards keyed by 'channel:fingerprint'.

    A pattern only becomes a guard when its recovery odds — P(close above entry
    after the horizon) — are demonstrated below even odds (the user's 50% ruler),
    and that weakness survives a Benjamini-Hochberg correction across every
    pattern evaluated in the same run. A rare target-before-stop no longer
    suppresses: it is a tighter, different bet than "will it recover in 2 weeks".
    """
    decisions: list[dict[str, Any]] = []
    guards: dict[str, Any] = {}

    # Pass 1: everything testable, with an exact binomial p-value for the
    # hypothesis "this pattern recovers no better than even odds".
    candidates: list[dict[str, Any]] = []
    for r in results:
        if r.ticker != "UNIVERSE":
            continue
        key = f"{r.channel}:{r.fingerprint}"
        base = {"query_id": r.query_id, "key": key, "n": r.n}
        if r.n < floor:
            decisions.append({**base, "action": "skipped", "reason": f"n={r.n} < {floor}"})
            continue
        p = _p_recover(r)
        if p is None:
            decisions.append({**base, "action": "hold", "reason": "sem desfecho de recuperação"})
            continue

        resolved = int(r.n)
        hits = int(round(p * resolved))
        p_value = binomial_test_less(hits, resolved, WEAK_P_RECOVER_NULL)
        oos_p = _oos_p_recover(r)
        candidates.append({**base, "p_recover": round(p, 4), "p_value": p_value,
                           "hits": hits, "resolved": resolved,
                           "oos_n": r.oos_n,
                           "oos_p_recover": None if oos_p is None else round(oos_p, 4)})

    # Pass 2: FDR across the whole family evaluated together.
    mask = benjamini_hochberg([c["p_value"] for c in candidates], alpha=alpha)
    for c, survived in zip(candidates, mask):
        p, pv, oos_p = c["p_recover"], c["p_value"], c["oos_p_recover"]
        if survived:
            # Confirmation on bars the pattern was never measured on. Absent a
            # usable tail the finding stands on the full sample alone, which is
            # the pre-existing behaviour; a tail that contradicts it does not.
            if oos_p is not None and oos_p >= WEAK_P_RECOVER_NULL:
                decisions.append({
                    **c,
                    "p_value": round(pv, 6),
                    "action": "hold",
                    "reason": (
                        f"P(recupera em ~2 semanas)={p:.2f} fraca no total mas "
                        f"{oos_p:.2f} fora da amostra (n={c['oos_n']}) — não confirmada"
                    ),
                })
                continue
            oos_note = (
                f", confirmada fora da amostra em {oos_p:.2f} (n={c['oos_n']})"
                if oos_p is not None else ", sem amostra de confirmação"
            )
            reason = (
                f"P(recupera em ~2 semanas)={p:.2f} fraca (p={pv:.4f}, FDR {alpha:.0%}"
                f"{oos_note}) — desk decide"
            )
            guards[c["key"]] = {
                "force_review": True,  # legacy key; engines treat it as suppress
                "suppress": True,
                "p_recover": p,
                "p_value": round(pv, 6),
                "n": c["n"],
                "oos_p_recover": oos_p,
                "oos_n": c["oos_n"],
                "reason": reason,
            }
            decisions.append({**c, "p_value": round(pv, 6), "action": "suppress",
                              "reason": reason})
        else:
            decisions.append({
                **c,
                "p_value": round(pv, 6),
                "action": "hold",
                "reason": (
                    f"P(recupera em ~2 semanas)={p:.2f} não sobrevive ao FDR "
                    f"(p={pv:.4f}, {len(candidates)} testes)"
                ),
            })
    return {"decisions": decisions, "guards": guards, "n_tested": len(candidates)}


def write_guards(guards: dict[str, Any]) -> None:
    GUARD_PATH.parent.mkdir(parents=True, exist_ok=True)
    GUARD_PATH.write_text(json.dumps(guards, indent=2), encoding="utf-8")


def read_guards() -> dict[str, Any]:
    try:
        data = json.loads(GUARD_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def guard_for(channel: str, fingerprint: str) -> tuple[bool, str | None]:
    """Whether the study for one pattern is suppressed, and why."""
    g = read_guards().get(f"{channel}:{fingerprint}")
    if isinstance(g, dict) and (g.get("suppress") or g.get("force_review")):
        return True, str(g.get("reason") or "estudo ativo: padrão fraco")
    return False, None


def _studies_advisory() -> bool:
    """Whether study guards annotate instead of hard-block (the desk decides)."""
    try:
        from app.config import get_settings

        return bool(getattr(get_settings(), "desk_studies_advisory", True))
    except Exception:
        return True


def hv_dip_force_review() -> tuple[bool, str | None]:
    """Consumed by hv_dip engine: skip the setup when deep-dip is refuted.

    In advisory mode (default) a refuted pattern is a note, not a lock — the
    engine annotates the trade and keeps going, so the desk decides from
    evidence instead of obeying a frozen verdict.
    """
    force, reason = guard_for("hv_dip", "deep_dip")
    if force and _studies_advisory():
        return False, reason
    return force, reason


def swing_force_review() -> tuple[bool, str | None]:
    """Consumed by the swing engine: skip when breakout+H1 is refuted.

    Same advisory semantics as ``hv_dip_force_review``.
    """
    force, reason = guard_for("swing", "breakout_h1")
    if force and _studies_advisory():
        return False, reason
    return force, reason


# Study fingerprints and day-trade rule ids name the same patterns differently.
FINGERPRINT_TO_RULE_ID = {
    "orb": "opening_range_break",
    "vwap_reclaim": "vwap_reclaim",
}


def day_trade_rule_notes() -> dict[str, str]:
    """Intraday rule ids whose study went weak, mapped to the reason.

    This annotates rather than suppresses, for two reasons. Day trade is fully
    simulated — a signal never becomes an order — so blocking it buys no safety
    and costs the samples the learn loop runs on. And the study measures a
    *proxy* of the rule (``analog._orb`` has none of the real volume filters),
    so its weakness is evidence about the pattern family, not a verdict on the
    rule. Genuine underperformance of the rule itself is already handled by
    ``day_trade.gating.rule_is_gated``, which measures closed signals.
    """
    notes: dict[str, str] = {}
    for fingerprint, rule_id in FINGERPRINT_TO_RULE_ID.items():
        force, reason = guard_for("day_trade", fingerprint)
        if force and reason:
            notes[rule_id] = reason
    return notes


__all__ = [
    "GUARD_PATH",
    "WEAK_P_RECOVER_NULL",
    "FDR_ALPHA",
    "DEFAULT_FLOOR",
    "OOS_FLOOR",
    "evaluate",
    "write_guards",
    "read_guards",
    "guard_for",
    "hv_dip_force_review",
    "swing_force_review",
    "day_trade_rule_notes",
    "FINGERPRINT_TO_RULE_ID",
]
