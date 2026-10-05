#!/usr/bin/env bash
cd /home/<USER>/Projects/fiidesk/backend || exit 1
echo "--- FCM/Finnhub keys presence (bool only) ---"
for k in FCM_PROJECT_ID FCM_SERVICE_ACCOUNT_JSON FCM_SERVER_KEY FINNHUB_API_KEY LLM_API_KEY; do
  v=$(grep -E "^${k}=" .env 2>/dev/null | cut -d= -f2-)
  if [ -n "$v" ]; then
    echo "$k: SET"
  else
    echo "$k: EMPTY"
  fi
done
