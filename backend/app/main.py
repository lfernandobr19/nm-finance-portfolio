import json
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api import api_router
from app.config import get_settings
from app.db import SessionLocal
from app.services.worker_heartbeat import HEARTBEAT_PATH

settings = get_settings()

app = FastAPI(title=settings.app_name, version="0.1.0")

# Worker heartbeat file (shared with ARQ / runner, same WorkingDirectory).
# Bearer tokens, not cookies. Wildcard + credentials=True is rejected by browsers
# (Failed to fetch on Flutter web).
origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
allow_all = origins == ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if allow_all else origins,
    allow_credentials=False if allow_all else True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_router)


@app.middleware("http")
async def allow_private_network(request, call_next):
    response = await call_next(request)
    if request.headers.get("access-control-request-private-network"):
        response.headers["Access-Control-Allow-Private-Network"] = "true"
    return response


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "app": settings.app_name}


@app.get("/health/live")
def health_live() -> dict:
    """Process is up (no dependency check)."""
    return {"status": "ok", "app": settings.app_name}


@app.get("/health/ready")
def health_ready():
    """Readiness: checks the database is reachable."""
    try:
        db = SessionLocal()
        try:
            db.execute(text("SELECT 1"))
        finally:
            db.close()
        return {"status": "ok", "database": "up"}
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            status_code=503,
            content={"status": "degraded", "database": "down", "error": str(exc)[:200]},
        )


@app.get("/health/worker")
def health_worker():
    """Liveness of the background worker (auto-sell / alerts)."""
    stale_after = timedelta(seconds=settings.worker_interval_seconds * 3 + 60)
    try:
        data = json.loads(HEARTBEAT_PATH.read_text(encoding="utf-8"))
        last_raw = data.get("last_run_at")
        last = datetime.fromisoformat(last_raw)
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        if now - last > stale_after:
            return JSONResponse(
                status_code=503,
                content={"status": "stale", "last_run_at": last_raw},
            )
        if data.get("db") != "ok":
            return JSONResponse(
                status_code=503,
                content={"status": "db_error", "last_run_at": last_raw},
            )
        return {
            "status": "ok",
            "last_run_at": last_raw,
            "ollama": data.get("ollama"),
            "ollama_model": data.get("ollama_model"),
            "groq_cooldown": bool(data.get("groq_cooldown")),
            "last_llm_source": data.get("last_llm_source"),
            "ollama_expires_at": data.get("ollama_expires_at"),
        }
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            status_code=503,
            content={"status": "unknown", "error": str(exc)[:200]},
        )
