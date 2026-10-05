"""Fase A smoke: verify the app imports and the new routes are registered."""

from app.main import app

paths = [getattr(r, "path", "") for r in app.routes]

checks = {
    "hv-dip/observations": "/hv-dip/observations",
    "hv-dip/config": "/hv-dip/config",
    "hv-dip/config/history": "/hv-dip/config/history",
    "hv-dip/config/rollback": "/hv-dip/config/rollback",
    "news-events": "/news-events",
    "day-trade/state": "/day-trade/state",
}

ok = True
for label, frag in checks.items():
    found = any(frag in p for p in paths)
    print(f"{label}: {'OK' if found else 'MISSING'}")
    ok = ok and found

print(f"total_routes={len(paths)}")
print("SMOKE_OK" if ok else "SMOKE_FAIL")
