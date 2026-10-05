"""Reseed the active hv_dip learn-loop config so wiring it to the engine
does not silently drop the live dip floor from 12% to the historical default 8%.

Must run once on Ravenna at the same deploy that starts reading
`get_active_params()` inside `run_hv_dip_cycle`. Idempotent: if the active
config already has dip_pct=12.0 it is a no-op.

    .venv/bin/python scripts/nm_reseed_hv_dip_config.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import SessionLocal
from app.services.hv_dip.configs import activate_params, ensure_default_config, get_active_params
from app.services.hv_dip.params import default_params


# Matches settings.hv_dip_min_dip_pct (the value the engine used before the
# learn-loop wire-up). Also the upper bound of ParamSpec("dip_pct").
TARGET = {
    "dip_pct": 12.0,
    "min_recovery_rate": 0.6,
    "reject_fresh_high": 1.0,
}


def main() -> int:
    db = SessionLocal()
    try:
        ensure_default_config(db)
        current = get_active_params(db)
        print(f"active before: {current}")

        if (
            float(current.get("dip_pct", 0)) == TARGET["dip_pct"]
            and float(current.get("min_recovery_rate", 0)) == TARGET["min_recovery_rate"]
            and float(current.get("reject_fresh_high", 0)) == TARGET["reject_fresh_high"]
        ):
            print("already at target — no-op")
            return 0

        params = default_params()
        params.update(TARGET)
        row = activate_params(
            db,
            params,
            origin="manual",
            reason=(
                "reseed: align learn-loop dip_pct with settings.hv_dip_min_dip_pct=12 "
                "before the engine starts reading get_active_params()"
            ),
            validation={"source": "nm_reseed_hv_dip_config"},
        )
        db.commit()
        print(f"activated v{row.version}: {get_active_params(db)}")
        return 0
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
