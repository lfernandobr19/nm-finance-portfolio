#!/usr/bin/env bash
set -euo pipefail
ROOT="${HOME}/Projects/fiidesk"
BACKEND="${ROOT}/backend"
UNIT_DIR="${HOME}/.config/systemd/user"

cd "${BACKEND}"
. .venv/bin/activate
alembic upgrade head
systemctl --user restart fiidesk-api
sleep 2
curl -s -o /dev/null -w "api:%{http_code}\n" http://127.0.0.1:8010/openapi.json
python scripts/day_trade_smoke.py --skip-stream

mkdir -p "${UNIT_DIR}"
cat > "${UNIT_DIR}/fiidesk-day-trade-streamer.service" <<EOF
[Unit]
Description=NM Finance day trade DXLink streamer (US session)
After=network.target

[Service]
Type=simple
WorkingDirectory=${BACKEND}
EnvironmentFile=${BACKEND}/.env
ExecStart=${BACKEND}/.venv/bin/python -m app.workers.day_trade_streamer
Restart=always
RestartSec=30

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable fiidesk-day-trade-streamer
systemctl --user restart fiidesk-day-trade-streamer || true
systemctl --user --no-pager status fiidesk-day-trade-streamer | head -15
