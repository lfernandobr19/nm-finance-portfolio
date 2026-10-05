"""Check tastytrade live orders and recent fiidesk LCID order."""
import httpx
from app.config import get_settings
from app.db import SessionLocal
from app.domain.models import Order
from app.services.tastytrade_client import TastytradeClient

get_settings.cache_clear()
client = TastytradeClient()
tok = client._ensure_access_token()  # noqa: SLF001
acc = get_settings().tastytrade_account_number
headers = {"Authorization": f"Bearer {tok}", "Accept": "application/json"}
with httpx.Client(timeout=30) as http:
    live = http.get(f"{client.base_url}/accounts/{acc}/orders/live", headers=headers)
    bal = http.get(f"{client.base_url}/accounts/{acc}/balances", headers=headers)
    pos = http.get(f"{client.base_url}/accounts/{acc}/positions", headers=headers)
print("live", live.status_code, live.text[:1500])
print("bal", bal.text[:300])
print("pos", pos.text[:500])

db = SessionLocal()
o = db.query(Order).filter(Order.ticker == "LCID").order_by(Order.created_at.desc()).first()
print("\nfiidesk order", o.id[:8], o.status, o.broker_order_id, o.execution_payload)
db.close()
