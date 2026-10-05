from app.config import get_settings
from app.services.notify import _fcm_v1_configured, _fcm_access_token

s = get_settings()
print("project_id:", s.fcm_project_id)
print("sa_json set:", bool(s.fcm_service_account_json))
print("v1_configured:", _fcm_v1_configured())
tok = _fcm_access_token()
print("access_token ok:", bool(tok))
print("token_len:", len(tok) if tok else 0)
