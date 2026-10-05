#!/usr/bin/env bash
# Plug Alpaca paper keys when support approves your account (Brazil signup blocked).
# Run on Ravenna from repo root: bash scripts/alpaca_setup.sh

set -euo pipefail

ENV_FILE="${1:-.env}"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing $ENV_FILE — copy deploy/env.example first"
  exit 1
fi

echo "=== Alpaca paper setup (NM High-Vol Dip) ==="
echo "1. Paste ALPACA_API_KEY and ALPACA_SECRET_KEY from https://app.alpaca.markets/paper/dashboard/overview"
echo "2. Ensure ALPACA_PAPER=true"
echo ""

read -rp "Alpaca API Key: " KEY
read -rsp "Alpaca Secret Key: " SECRET
echo ""

upsert() {
  local k="$1" v="$2"
  if grep -q "^${k}=" "$ENV_FILE" 2>/dev/null; then
    sed -i "s|^${k}=.*|${k}=${v}|" "$ENV_FILE"
  else
    echo "${k}=${v}" >> "$ENV_FILE"
  fi
}

upsert ALPACA_API_KEY "$KEY"
upsert ALPACA_SECRET_KEY "$SECRET"
upsert ALPACA_PAPER "true"

echo ""
echo "Updated $ENV_FILE. Restart API + worker:"
echo "  pkill -f 'uvicorn app.main' || true"
echo "  pkill -f 'app.workers.runner' || true"
echo "  cd backend && nohup .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8010 >> ../logs/api.log 2>&1 &"
echo "  nohup .venv/bin/python -m app.workers.runner >> ../logs/worker.log 2>&1 &"
echo ""
echo "Validate:"
echo "  cd backend && PYTHONPATH=. .venv/bin/python scripts/m0_aceite_smoke.py"
echo "Expect mode: alpaca_paper (not alpaca_paper_sim)"
