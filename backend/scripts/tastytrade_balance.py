"""Quick tastytrade balance probe."""
from app.config import get_settings
from app.services.tastytrade_client import TastytradeClient
import httpx

get_settings.cache_clear()
c = TastytradeClient()
tok = c._ensure_access_token()  # noqa: SLF001
acc = get_settings().tastytrade_account_number
url = f"{c.base_url}/accounts/{acc}/balances"
r = httpx.get(
    url,
    headers={"Authorization": f"Bearer {tok}", "Accept": "application/json"},
    timeout=30,
)
print("balances", r.status_code, r.text[:800])
