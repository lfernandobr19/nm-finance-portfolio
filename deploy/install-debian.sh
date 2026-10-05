#!/usr/bin/env bash
# Install NM Finance services on Debian/Ravenna (run as root).
set -euo pipefail
ROOT="${1:-/opt/fiidesk}"
mkdir -p /etc/fiidesk /var/backups/fiidesk
if [[ ! -f /etc/fiidesk/env ]]; then
  cp "$ROOT/deploy/env.example" /etc/fiidesk/env
  echo "Edit /etc/fiidesk/env before starting services."
fi
cp "$ROOT/deploy/systemd/fiidesk-api.service" /etc/systemd/system/
cp "$ROOT/deploy/systemd/fiidesk-worker.service" /etc/systemd/system/
cp "$ROOT/deploy/systemd/fiidesk-day-trade-streamer.service" /etc/systemd/system/
cp "$ROOT/deploy/nginx.conf" /etc/nginx/sites-available/fiidesk
ln -sf /etc/nginx/sites-available/fiidesk /etc/nginx/sites-enabled/fiidesk
systemctl daemon-reload
systemctl enable --now fiidesk-api fiidesk-worker
# After `alembic upgrade head` and DAY_TRADE_ENABLED=true:
# systemctl enable --now fiidesk-day-trade-streamer
nginx -t && systemctl reload nginx
echo "Installed. Remember: alembic upgrade head, SECRET_KEY, and TLS."
