# NM Finance (portfolio / sanitized)

**NM Finance** is a personal finance + markets desk: Flutter client, FastAPI backend, Redis/SQLite, optional broker paper trading (Tastytrade), B3 market data (brapi), news/LLM helpers, and Docker-friendly deploy docs.

This repository is a **sanitized structure-complete skeleton** for portfolio review:

- Flutter app (`app/`) + FastAPI backend (`backend/`) + `deploy/` + `scripts/` + `docs/`
- **No** production `.env`, databases, caches, build artifacts, keystores, or live Tailscale IPs
- Secrets via `backend/.env.example` (empty/placeholder values only)
- Firebase `google-services.json` is a **placeholder** — replace for real builds

> The live NM Finance deployment on the author’s home server and the working trees used in production are **not** this copy.

## Stack

- Flutter (Android / desktop / web targets as configured in `app/`)
- Python FastAPI workers (market refresh, HV-dip, day-trade streamer hooks)
- Redis + SQLite (configurable via env)
- Optional: Tastytrade paper API, brapi, Finnhub, OpenAI-compatible LLM, FCM

## Quick start (local)

```bash
# Backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill tokens locally; never commit .env
uvicorn app.main:app --reload --port 8010

# Flutter
cd ../app
flutter pub get
# point API base URL at localhost / your LAN (see lib/core/api_client.dart placeholders)
flutter run
```

See `deploy/env.example` for additional ops-oriented variables.

## Layout

- `app/` — Flutter client (display name: NM Finance)
- `backend/` — FastAPI API + workers + tests
- `deploy/` — compose / env examples
- `scripts/` — install/helpers (sanitized)
- `docs/` — notes

## Demo seed / brokers

Broker and market integrations read credentials from environment only. Leave tokens empty for a compile/run of the API shell; enable paper sandbox flags when experimenting.
