#!/usr/bin/env bash
# Local dev runner.
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -d backend/.venv ]; then
  python3 -m venv backend/.venv
  source backend/.venv/bin/activate
  pip install -r backend/requirements.txt
else
  source backend/.venv/bin/activate
fi

if [ ! -f backend/app/data/embeddings.npy ]; then
  echo "Building embeddings (one-time)…"
  (cd backend && python3 -m app.ingest.embed)
fi

export GEMINI_API_KEY="${GEMINI_API_KEY:-}"
exec python3 -m uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 8000
