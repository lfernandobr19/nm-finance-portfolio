from app.db import SessionLocal
from app.domain.models import DeviceToken

db = SessionLocal()
rows = db.query(DeviceToken).order_by(DeviceToken.updated_at.desc()).all() if hasattr(DeviceToken, "updated_at") else db.query(DeviceToken).all()
print("DeviceToken count:", len(rows))
for r in rows[:10]:
    created = getattr(r, "created_at", None)
    updated = getattr(r, "updated_at", None)
    print(
        f"  user={r.user_id} platform={r.platform} "
        f"token={r.token[:24]}... created={created} updated={updated}"
    )
