#!/usr/bin/env bash
# Restart the fiidesk ARQ worker: kill stale loops, restart the systemd unit.
set -u

BACKEND_DIR="/home/<USER>/Projects/fiidesk/backend"
LOG_DIR="$BACKEND_DIR/.cache/fiidesk"
mkdir -p "$LOG_DIR"

echo "=== before ==="
ps -eo pid,lstart,cmd | grep -E 'app.workers.runner|arq app.workers.arq_settings' | grep -v grep || echo "(none)"

pids=$(pgrep -f 'app.workers.runner' || true)
if [ -n "$pids" ]; then
  echo "killing leftover runner pids: $pids"
  kill $pids 2>/dev/null || true
  sleep 2
  pkill -9 -f 'app.workers.runner' 2>/dev/null || true
fi

systemctl --user daemon-reload
systemctl --user restart fiidesk-worker
sleep 5

echo "=== after ==="
systemctl --user is-active fiidesk-worker || true
ps -eo pid,lstart,cmd | grep -E 'app.workers.runner|arq app.workers.arq_settings' | grep -v grep || echo "(none)"
echo "--- heartbeat ---"
cat "$LOG_DIR/worker_heartbeat.json" 2>/dev/null || echo "(no heartbeat yet)"
echo "RESTART_DONE"
