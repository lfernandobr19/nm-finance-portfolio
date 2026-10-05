#!/usr/bin/env bash
# Plug tastytrade sandbox OAuth credentials for NM USD paper.
# Run on Ravenna: bash scripts/tastytrade_setup.sh

set -euo pipefail

ENV_FILE="${1:-backend/.env}"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing $ENV_FILE — copy deploy/env.example first"
  exit 1
fi

echo "=== tastytrade sandbox setup (NM Finance) ==="
echo "Need: Client ID, Client Secret, Refresh Token (Create Grant), Account Number"
echo ""

read -rp "Client ID: " CLIENT_ID
read -rsp "Client Secret: " CLIENT_SECRET
echo ""
read -rsp "Refresh Token: " REFRESH
echo ""
read -rp "Account Number (e.g. 3AD45265): " ACCOUNT

upsert() {
  local k="$1" v="$2"
  if grep -q "^${k}=" "$ENV_FILE" 2>/dev/null; then
    sed -i "s|^${k}=.*|${k}=${v}|" "$ENV_FILE"
  else
    echo "${k}=${v}" >> "$ENV_FILE"
  fi
}

upsert TASTYTRADE_CLIENT_ID "$CLIENT_ID"
upsert TASTYTRADE_CLIENT_SECRET "$CLIENT_SECRET"
upsert TASTYTRADE_REFRESH_TOKEN "$REFRESH"
upsert TASTYTRADE_ACCOUNT_NUMBER "$ACCOUNT"
upsert TASTYTRADE_SANDBOX "true"

echo ""
echo "Updated $ENV_FILE. Restart: systemctl --user restart fiidesk-api fiidesk-worker"
echo "Smoke: cd backend && PYTHONPATH=. .venv/bin/python scripts/tastytrade_smoke.py"
