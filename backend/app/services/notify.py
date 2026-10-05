"""Push via FCM when configured. App-local notifications cover Android without FCM."""

from __future__ import annotations

import json
import logging

import httpx
from sqlalchemy.orm import Session

from app.config import get_settings
from app.domain.models import (
    AccountMembership,
    DeviceToken,
    InvestmentAccount,
    MembershipRole,
    Order,
    Position,
    Suggestion,
)

logger = logging.getLogger(__name__)
settings = get_settings()


_EVENT_LABELS = {
    "partnership": "parceria",
    "guidance_up": "guidance positiva",
    "guidance_down": "guidance negativa",
    "upgrade": "upgrade",
    "downgrade": "downgrade",
    "m_and_a": "fusão/aquisição",
    "contract": "contrato",
    "product_launch": "lançamento",
    "earnings": "resultado",
    "litigation": "litígio",
    "regulation": "regulação",
    "buyback": "recompra",
    "restructuring": "reestruturação",
    "new_leadership": "nova liderança",
    "turnaround": "turnaround",
    "other": "notícia",
}


def _factors(suggestion: Suggestion) -> str:
    """Build a human-readable reason string from catalyst + setup metrics."""
    parts: list[str] = []
    catalyst = (suggestion.metrics or {}).get("catalyst") if suggestion.metrics else None
    if catalyst:
        ev_type = str(catalyst.get("event_type") or "").strip()
        label = _EVENT_LABELS.get(ev_type, ev_type or "catalisador")
        seg = label
        sentiment = str(catalyst.get("sentiment") or "").strip()
        if sentiment:
            seg += f" {sentiment}"
        confidence = catalyst.get("confidence")
        if confidence is not None:
            try:
                seg += f" conf {float(confidence) * 100:.0f}%"
            except (TypeError, ValueError):
                pass
        impact = catalyst.get("impact_score")
        if impact is not None:
            try:
                seg += f" imp {float(impact):.0f}"
            except (TypeError, ValueError):
                pass
        parts.append(seg)

    letter = (suggestion.swing_score_letter or "").strip()
    if letter:
        parts.append(f"score {suggestion.score:.0f} {letter}")
    elif suggestion.score is not None:
        parts.append(f"score {suggestion.score:.0f}")

    sm = suggestion.metrics or {}
    dip = sm.get("dip_pct")
    if dip is not None:
        try:
            parts.append(f"dip {float(dip):.1f}%")
        except (TypeError, ValueError):
            pass

    return " · ".join(parts)


def notify_suggestion(db: Session, suggestion: Suggestion) -> int:
    kind = getattr(suggestion.strategy_kind, "value", suggestion.strategy_kind) or "income"
    letter = (suggestion.swing_score_letter or "").strip()
    review = bool(getattr(suggestion, "review_required", False))
    catalyst = (suggestion.metrics or {}).get("catalyst") if suggestion.metrics else None
    factors = _factors(suggestion)

    if suggestion.status.value == "auto_approved":
        if kind == "hv_dip" and catalyst:
            title = f"NM Finance · Compra automática {suggestion.ticker}"
            body = factors or f"Score {suggestion.score:.0f} — registrado automaticamente"
        else:
            title = f"NM Finance · auto {suggestion.ticker}"
            body = f"Score {suggestion.score:.0f} — registrado automaticamente"
    elif kind == "hv_dip":
        tag = f" {letter}" if letter else ""
        rev = " REVIEW" if review else ""
        if catalyst:
            title = f"NM Finance · Compra sugerida · {suggestion.ticker}{tag}"
            body = f"{factors} — confirme no app"
        else:
            title = f"NM Finance · NM High-Vol{tag}{rev}"
            body = f"{suggestion.ticker} score {suggestion.score:.0f} — confirme no app"
    elif kind == "swing":
        tag = f" {letter}" if letter else ""
        title = f"NM Finance · Swing{tag}"
        body = f"{suggestion.ticker} score {suggestion.score:.0f} — abra o app para aprovar"
    else:
        title = f"NM Finance · {suggestion.ticker}"
        body = f"Score {suggestion.score:.0f} — toque para aprovar ou rejeitar"

    return _notify_fcm(db, title, body, account_id=suggestion.account_id, suggestion=suggestion)


def notify_order_filled(
    db: Session,
    order: Order,
    position: Position,
    suggestion: Suggestion | None = None,
) -> int:
    """Notify owners when an auto (news-catalyst) order fills and opens a position."""
    if order.acted_by_user_id is not None:
        return 0
    sug = suggestion or db.get(Suggestion, order.suggestion_id)
    if sug is None:
        return 0
    catalyst = (sug.metrics or {}).get("catalyst") if sug.metrics else None
    if not catalyst:
        return 0

    qty = float(order.quantity or 0)
    price = float(order.filled_price or order.limit_price)
    total = round(qty * price, 2)
    factors = _factors(sug)
    body = f"{qty:g} ações a US$ {price:.2f} (US$ {total:.2f})"
    if factors:
        body += f" · {factors}"

    return _notify_fcm(
        db,
        f"NM Finance · Compra efetuada {order.ticker}",
        body,
        account_id=order.account_id,
        suggestion=sug,
        extra_data={
            "kind": "order_filled",
            "position_id": position.id,
            "suggestion_id": order.suggestion_id,
            "ticker": order.ticker,
            "filled_price": str(price),
            "quantity": str(qty),
        },
    )


def notify_position_alert(
    db: Session,
    *,
    account: InvestmentAccount,
    position: Position,
    alert: str,
    mark_price: float,
) -> int:
    if alert == "stop":
        title = f"NM Finance · STOP {position.ticker}"
        body = f"Cotação {mark_price:.2f} ≤ stop — avalie fechamento manual"
    elif alert == "target":
        title = f"NM Finance · ALVO {position.ticker}"
        body = f"Cotação {mark_price:.2f} ≥ alvo — considere realização"
    elif alert == "recovery":
        title = f"NM Finance · RECUP {position.ticker}"
        body = f"Cotação {mark_price:.2f} ≥ topo do dip — considere saída parcial"
    elif alert == "trailing":
        title = f"NM Finance · TRAIL {position.ticker}"
        body = f"Lucro caiu do pico — proteja ganho ({mark_price:.2f})"
    elif alert == "latched":
        title = f"NM Finance · OBS {position.ticker}"
        body = f"Entrou em observação (+5%) — cotação {mark_price:.2f}"
    elif alert == "protect":
        title = f"NM Finance · PROT {position.ticker}"
        body = f"Proteção acionada — saída em {mark_price:.2f}"
    elif alert == "time_review":
        title = f"NM Finance · D14 {position.ticker}"
        body = f"Dia 14 — avalie saída (cotação {mark_price:.2f})"
    elif alert == "rotation":
        title = f"NM Finance · Rotação?"
        body = f"Oportunidade melhor disponível — {mark_price:.2f}"
    else:
        title = f"NM Finance · {position.ticker}"
        body = f"Alerta {alert} — cotação {mark_price:.2f}"
    return _notify_fcm(
        db,
        title,
        body,
        account_id=account.id,
        extra_data={"position_id": position.id, "alert": alert, "ticker": position.ticker},
    )


def notify_latched(
    db: Session,
    *,
    account: InvestmentAccount,
    position: Position,
    mark_price: float,
    upnl_pct: float,
) -> int:
    title = f"NM Finance · OBS {position.ticker}"
    body = f"Observação +5% · lucro {upnl_pct:.1f}% · cotação {mark_price:.2f}"
    return _notify_fcm(
        db,
        title,
        body,
        account_id=account.id,
        extra_data={
            "kind": "exit",
            "position_id": position.id,
            "suggestion_id": position.suggestion_id,
            "alert": "latched",
            "ticker": position.ticker,
            "upnl_pct": str(round(upnl_pct, 2)),
        },
    )


def notify_time_review(
    db: Session,
    *,
    account: InvestmentAccount,
    position: Position,
    mark_price: float,
    upnl_pct: float,
    exit_state: str,
    days_until_review: int | None,
) -> int:
    title = f"NM Finance · D14 {position.ticker}"
    days_txt = f"{days_until_review}d" if days_until_review is not None else "hoje"
    body = (
        f"Review dia 14 ({days_txt}) · {exit_state} · "
        f"PnL {upnl_pct:+.1f}% · {mark_price:.2f}"
    )
    return _notify_fcm(
        db,
        title,
        body,
        account_id=account.id,
        extra_data={
            "kind": "time_review",
            "position_id": position.id,
            "suggestion_id": position.suggestion_id,
            "alert": "time_review",
            "ticker": position.ticker,
            "upnl_pct": str(round(upnl_pct, 2)),
            "exit_state": exit_state,
        },
    )


def notify_rotation_opportunity(
    db: Session,
    *,
    account: InvestmentAccount,
    open_position: Position,
    new_suggestion: Suggestion,
    open_upnl_pct: float,
    open_mark: float,
) -> int:
    letter = (new_suggestion.swing_score_letter or "").strip()
    tag = f" {letter}" if letter else ""
    title = f"NM Finance · Rotação? {new_suggestion.ticker}{tag}"
    body = (
        f"Nova {new_suggestion.ticker} score {new_suggestion.score:.0f} vs "
        f"{open_position.ticker} ({open_upnl_pct:+.1f}%) · slot NM"
    )
    return _notify_fcm(
        db,
        title,
        body,
        account_id=account.id,
        suggestion=new_suggestion,
        extra_data={
            "kind": "rotation",
            "alert": "rotation",
            "position_id": open_position.id,
            "open_ticker": open_position.ticker,
            "open_upnl_pct": str(round(open_upnl_pct, 2)),
            "open_mark": str(round(open_mark, 2)),
            "new_score": str(round(float(new_suggestion.score), 1)),
            "new_ticker": new_suggestion.ticker,
        },
    )


def notify_day_trade_event(
    db: Session,
    *,
    account_id: str,
    event: str,
    detail: str,
) -> int:
    """Generic day-trade event (circuit breaker trip, learn applied, etc.)."""
    title = f"NM Finance · DT {event}"
    return _notify_fcm(
        db,
        title,
        detail,
        account_id=account_id,
        extra_data={"kind": "day_trade", "event": event, "detail": detail},
    )


def register_device_token(
    db: Session,
    *,
    user_id: str,
    token: str,
    platform: str = "android",
) -> None:
    """Register (or refresh the platform of) an FCM device token for a user."""
    existing = (
        db.query(DeviceToken)
        .filter(DeviceToken.user_id == user_id, DeviceToken.token == token)
        .one_or_none()
    )
    if existing:
        existing.platform = platform
    else:
        db.add(DeviceToken(user_id=user_id, token=token, platform=platform))
    db.commit()


def _fcm_v1_configured() -> bool:
    return bool(
        (settings.fcm_project_id or "").strip()
        and (settings.fcm_service_account_json or "").strip()
    )


def _fcm_credentials():
    """Build Google service-account credentials for the Firebase Messaging scope."""
    raw = (settings.fcm_service_account_json or "").strip()
    if not raw:
        return None
    try:
        from google.oauth2 import service_account

        if raw.startswith("{"):
            info = json.loads(raw)
        else:
            with open(raw, "r", encoding="utf-8") as f:
                info = json.load(f)
        return service_account.Credentials.from_service_account_info(
            info,
            scopes=["https://www.googleapis.com/auth/firebase.messaging"],
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("FCM service account invalid: %s", exc)
        return None


def _fcm_access_token() -> str | None:
    creds = _fcm_credentials()
    if creds is None:
        return None
    try:
        from google.auth.transport.requests import Request

        creds.refresh(Request())
        return creds.token
    except Exception as exc:  # noqa: BLE001
        logger.warning("FCM token refresh failed: %s", exc)
        return None


def _fcm_error_code(text: str) -> str | None:
    """Extract FCM v1 errorCode (e.g. UNREGISTERED) from an error response body."""
    try:
        data = json.loads(text)
        for detail in (data.get("error") or {}).get("details") or []:
            code = detail.get("errorCode")
            if code:
                return code
    except (json.JSONDecodeError, AttributeError, TypeError):
        pass
    return None


def _fcm_send_v1(token: str, title: str, body: str, data: dict) -> tuple[bool, str | None]:
    """Send one message via FCM HTTP v1. Returns (ok, error_code_or_None)."""
    access_token = _fcm_access_token()
    if not access_token:
        return False, "no_access_token"
    project_id = (settings.fcm_project_id or "").strip()
    if not project_id:
        return False, "no_project_id"

    url = f"https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"
    message = {
        "token": token,
        "notification": {"title": title, "body": body},
        "data": data,
    }
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.post(url, json={"message": message}, headers=headers)
            if resp.status_code < 300:
                return True, None
            code = _fcm_error_code(resp.text)
            logger.warning("FCM v1 error %s: %s", resp.status_code, resp.text[:300])
            return False, code
    except httpx.HTTPError as exc:
        logger.warning("FCM v1 request failed: %s", exc)
        return False, "http_error"


def _fcm_send_legacy(
    tokens: list[DeviceToken], title: str, body: str, data: dict
) -> int:
    """Legacy FCM `send` API (FCM_SERVER_KEY). Kept for partial-deploy compatibility."""
    payload_base = {"notification": {"title": title, "body": body}, "data": data}
    headers = {
        "Authorization": f"key={settings.fcm_server_key}",
        "Content-Type": "application/json",
    }
    sent = 0
    with httpx.Client(timeout=15.0) as client:
        for device in tokens:
            payload = {**payload_base, "to": device.token}
            try:
                resp = client.post(
                    "https://fcm.googleapis.com/fcm/send", json=payload, headers=headers
                )
                if resp.status_code < 300:
                    sent += 1
                else:
                    logger.warning("FCM legacy error %s: %s", resp.status_code, resp.text)
            except httpx.HTTPError as exc:
                logger.warning("FCM legacy request failed: %s", exc)
    return sent


def notify_pnl_milestone(
    db: Session,
    *,
    account: InvestmentAccount,
    pnl: float,
    milestone: float,
) -> int:
    """Notify when the daily P&L crosses a loss/gain milestone (USD)."""
    direction = "ganho" if pnl >= 0 else "perda"
    sign = "+" if pnl >= 0 else "-"
    title = f"NM Finance · {direction.title()} de {sign}US$ {milestone:g}"
    body = (
        f"P&L do dia {sign}US$ {abs(pnl):.2f} "
        f"(marco {sign}US$ {milestone:g}) · conta {account.name}"
    )
    return _notify_fcm(
        db,
        title,
        body,
        account_id=account.id,
        extra_data={
            "kind": "pnl_milestone",
            "pnl": str(round(pnl, 2)),
            "milestone": str(milestone),
            "currency": "USD",
        },
    )


def notify_worker_down(
    db: Session,
    *,
    user_ids: list[str],
    stale_minutes: int,
) -> int:
    """Watchdog: notify owners the worker appears offline (stale heartbeat)."""
    tokens = db.query(DeviceToken).filter(DeviceToken.user_id.in_(user_ids)).all()
    if not tokens:
        return 0
    title = "NM Finance · Worker offline"
    body = f"Automação sem heartbeat há {stale_minutes} min — verifique o servidor."
    sent = 0
    data = {"kind": "worker_down", "stale_minutes": str(stale_minutes)}
    for device in tokens:
        ok, err_code = _fcm_send_v1(device.token, title, body, data)
        if ok:
            sent += 1
        elif err_code in {"UNREGISTERED", "INVALID_ARGUMENT"}:
            db.delete(device)
    db.commit()
    return sent


def notify_order_stuck(
    db: Session,
    *,
    order: Order,
    hours: float,
) -> int:
    """Reconciliation anomaly: order stuck in `submitted` for too long."""
    title = f"NM Finance · Ordem presa {order.ticker}"
    body = (
        f"Ordem {order.broker_order_id or order.id[:8]} em 'submitted' "
        f"há {hours:.1f}h — verifique na corretora."
    )
    return _notify_fcm(
        db,
        title,
        body,
        account_id=order.account_id,
        extra_data={
            "kind": "order_stuck",
            "order_id": order.id,
            "ticker": order.ticker,
            "hours": str(round(hours, 1)),
        },
    )


def _notify_fcm(
    db: Session,
    title: str,
    body: str,
    *,
    account_id: str,
    suggestion: Suggestion | None = None,
    extra_data: dict | None = None,
) -> int:
    memberships = (
        db.query(AccountMembership)
        .filter(
            AccountMembership.account_id == account_id,
            AccountMembership.role.in_([MembershipRole.owner, MembershipRole.operator]),
        )
        .all()
    )
    user_ids = [m.user_id for m in memberships]
    if not user_ids:
        return 0
    tokens = db.query(DeviceToken).filter(DeviceToken.user_id.in_(user_ids)).all()
    if not tokens:
        return 0

    data: dict[str, str] = {"account_id": account_id}
    if suggestion:
        data["suggestion_id"] = suggestion.id
        data["ticker"] = suggestion.ticker
        data["status"] = suggestion.status.value
    if extra_data:
        for k, v in extra_data.items():
            data[k] = str(v)

    logger.info(
        "FCM notify title=%r body=%r data=%r",
        title,
        body,
        data,
    )

    # Legacy-only path (FCM_SERVER_KEY) when v1 is not configured.
    if settings.fcm_server_key and not _fcm_v1_configured():
        return _fcm_send_legacy(tokens, title, body, data)

    if not _fcm_v1_configured():
        logger.info("FCM disabled; %d device tokens unused", len(tokens))
        return 0

    sent = 0
    for device in tokens:
        ok, err_code = _fcm_send_v1(device.token, title, body, data)
        if ok:
            sent += 1
        elif err_code in {"UNREGISTERED", "INVALID_ARGUMENT"}:
            logger.info("Removing stale FCM token (%s)", err_code)
            db.delete(device)
    db.commit()
    return sent
