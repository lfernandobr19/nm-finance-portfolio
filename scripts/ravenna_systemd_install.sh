#!/usr/bin/env bash
# Install user systemd units on Ravenna so API/worker restart after crash or reboot.
set -euo pipefail
ROOT="${1:-$HOME/Projects/fiidesk}"
UNIT_DIR="$HOME/.config/systemd/user"
mkdir -p "$UNIT_DIR"
sed "s|%h|$HOME|g" "$ROOT/deploy/systemd/user/fiidesk-api.service" > "$UNIT_DIR/fiidesk-api.service"
sed "s|%h|$HOME|g" "$ROOT/deploy/systemd/user/fiidesk-worker.service" > "$UNIT_DIR/fiidesk-worker.service"
sed "s|%h|$HOME|g" "$ROOT/deploy/systemd/user/fiidesk-research.service" > "$UNIT_DIR/fiidesk-research.service"
sed "s|%h|$HOME|g" "$ROOT/deploy/systemd/user/fiidesk-account-streamer.service" > "$UNIT_DIR/fiidesk-account-streamer.service"
# Stop manual/nohup instances so we do not duplicate workers.
pkill -f 'uvicorn app.main:app' 2>/dev/null || true
pkill -f 'app.workers.runner' 2>/dev/null || true
pkill -f 'arq app.workers.arq_settings' 2>/dev/null || true
pkill -f 'app.workers.tastytrade_account_streamer' 2>/dev/null || true
sleep 1
systemctl --user daemon-reload
systemctl --user enable fiidesk-api fiidesk-worker fiidesk-research fiidesk-account-streamer
systemctl --user restart fiidesk-api fiidesk-worker fiidesk-research fiidesk-account-streamer
systemctl --user --no-pager status fiidesk-api fiidesk-worker fiidesk-research fiidesk-account-streamer || true
curl -s -o /dev/null -w "openapi:%{http_code}\n" http://127.0.0.1:8010/openapi.json || true
echo "Enable linger (run once with sudo if services stop after logout):"
echo "  sudo loginctl enable-linger $USER"
