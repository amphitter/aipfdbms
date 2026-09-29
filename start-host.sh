#!/usr/bin/env bash
# Starts the hospital API and the desk. Run on the host computer, not on each client PC.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
if [[ "${AIPF_ENV:-}" == "production" && -z "${AIPF_DATABASE_URL:-}" ]]; then
  echo "AIPF_ENV=production requires AIPF_DATABASE_URL. Refusing to start." >&2
  exit 1
fi
if [[ -z "${AIPF_DATABASE_URL:-}" ]]; then
  export AIPF_DATABASE_URL="sqlite:///${ROOT}/data/hospital.db"
  echo "Development database explicitly set to the local SQLite file."
fi
cd "$ROOT/backend"
python3 -m aipf.server &
API_PID=$!
echo "$API_PID" > "$ROOT/data/api.pid"
trap 'kill $API_PID' EXIT
cd "$ROOT/frontend"
exec npm run dev -- --host 0.0.0.0 --port 5173
