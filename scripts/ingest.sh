#!/usr/bin/env bash
# Full ingestion: scrape → merge → render → embed.
set -euo pipefail
cd "$(dirname "$0")/.."
source backend/.venv/bin/activate
export GEMINI_API_KEY="${GEMINI_API_KEY:?Set GEMINI_API_KEY first}"

(cd backend && python3 -m app.ingest.scrape) || echo "[ingest] scrape errored, continuing with cached data"
(cd backend && python3 -m app.ingest.synth)         # seed sessions/speakers fallback
(cd backend && python3 -m app.ingest.merge)         # merge real exhibitors over synthetic
(cd backend && python3 -m app.ingest.floorplan)     # render base PNG
(cd backend && python3 -m app.ingest.embed)         # build embeddings (real Gemini if API key)
echo "[ingest] done"
