# Expo Concierge

A conversational agent for navigating large enterprise conferences. Built for the
TechEx "Transforming Enterprise Through AI" hackathon (Track 2 — AI Agents with
Google AI Studio), demoed at TechEx North America 2026.

> See [`expo_concierge_gameplan.md`](./expo_concierge_gameplan.md) for the
> full design doc.

## What you get

- **Conversational concierge** powered by Gemini 2.5 Flash (chat front) and
  Gemini 2.5 Pro (planning), with a tight tool surface (search, locate, plan,
  highlight, summarize).
- **Floorplan + live overlay**: a static base image with an SVG pin layer that
  the agent operates directly.
- **Schedule timeline** with proportional time spacing, Saved / Planned /
  Attended state, and animated agent-driven edits.
- **Ingestion pipeline** that fetches sessions / speakers / exhibitors,
  embeds them with Gemini `text-embedding-004`, and extracts booth
  coordinates from the floorplan image via Gemini 2.5 Pro multimodal.
- **Test bench** with deterministic unit tests, scripted scenario tests, and
  an LLM-as-judge layer — the loop that `/goal iterate till done` rides on.

## Running locally

```bash
# 1. Install backend deps
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install pymupdf                 # used by the floorplan extractor

# 2. Ingest real data (one-shot; commit the JSON outputs)
cd ..
python scripts/extract_floorplan.py        # parses real PDF -> booth coords + zones
python scripts/scrape_agenda.py            # scrapes public agenda pages -> sessions/speakers
python scripts/link_exhibitors_to_booths.py  # joins real exhibitors to real booth coords

# 3. (Optional) real Gemini embeddings + agent
export GEMINI_API_KEY=...           # without this, pseudo-embeddings + chat disabled

# 4. Run the server (also serves the frontend)
cd backend
PYTHONIOENCODING=utf-8 python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
# open http://localhost:8000
```

### Tests

```bash
# Full suite (data, API, tools, chat scenarios, browser visual)
python scripts/run_tests.py

# Fast subset (no live Gemini, no headless browser)
python scripts/run_tests.py --skip chat --skip visual
```

The visual layer uses Playwright. Once-per-machine setup:
```bash
python -m pip install playwright httpx websockets
python -m playwright install chromium
```

The suite covers ~150 checks across five layers: data integrity, REST/WebSocket
endpoints, direct tool calls, real-Gemini chat scenarios, and headless-browser
visual + click coverage at five viewport widths (320 → 1920).

### Data sources (real, not synthetic)

The app refuses to fabricate data. Everything you see comes from:

| Entity      | Source                                                  | Script                          |
|-------------|---------------------------------------------------------|---------------------------------|
| Booths      | Official TechEx NA 2026 floorplan PDF                   | `scripts/extract_floorplan.py`  |
| Exhibitors  | `ai-expo.net/northamerica/exhibitors/` (one-shot)       | `backend/app/ingest/scrape.py`  |
| Sessions    | Per-track agenda pages on the 7 TechEx microsites       | `scripts/scrape_agenda.py`      |
| Speakers    | Derived from session agenda blocks                      | `scripts/scrape_agenda.py`      |

If any of those JSON files are missing, the backend starts with a warning
(`[store] WARNING: missing data files…`) and shows empty states in the UI
rather than synthesizing. Re-run the ingest scripts to refresh.

The frontend is a single-page PWA — installable on mobile, works offline for
already-loaded data, no build step.

## Repo layout

```
backend/
  app/
    main.py              FastAPI app + WebSocket chat
    agent.py             Gemini agent loop + tool dispatch
    tools.py             The agent's tool implementations
    models.py            Pydantic schemas
    store.py             In-memory store (sessions/speakers/exhibitors/booths)
    ingest/
      scrape.py          Per-microsite scrapers (Playwright scaffold)
      floorplan.py       Gemini 2.5 Pro multimodal booth extraction
      embed.py           text-embedding-004 batched embeddings
      synth.py           Synthetic TechEx snapshot generator (demo fallback)
    data/                Frozen demo snapshot (sessions, speakers, exhibitors,
                         booths, floorplan.png, embeddings.npy)
frontend/
  index.html             Single-page PWA shell
  manifest.json
  service-worker.js
  css/app.css            Design tokens, dark theme, mobile-first
  js/
    app.js               Top-level state, view router
    map.js               SVG overlay, pin protocol
    schedule.js          Timeline, card animation
    chat.js              Streaming chat + tool-pill UI
tests/
  scenarios/             YAML canonical scenarios (§5.2)
  test_bench.py          Runner — emits structured JSON report
  test_pipeline.py       Deterministic unit tests
scripts/
  run.sh                 Convenience runner
```

## License

MIT. See `LICENSE`.
