from app.db import SessionLocal
from app.domain.models import DeviceToken
from app.services.notify import _fcm_send_v1

db = SessionLocal()
r = db.query(DeviceToken).order_by(DeviceToken.created_at.desc()).first()
if r is None:
    print("NO_DEVICE_TOKEN")
    raise SystemExit(2)

print(f"target user={r.user_id} platform={r.platform}")
print(f"token={r.token[:24]}...")

ok, err = _fcm_send_v1(
    r.token,
    "NM Finance · push OK",
    "FCM v1 funcionando de ponta a ponta — notificação real chegou.",
    {"kind": "smoke", "account_id": "smoke", "suggestion_id": "smoke"},
)
if ok:
    print("SENT_OK: FCM v1 aceitou a mensagem para o token do M55")
else:
    print(f"SENT_FAIL: error_code={err}")
