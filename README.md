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
# 1. Backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export GEMINI_API_KEY=...           # required for live agent
python -m app.main                  # FastAPI on :8000

# 2. Frontend (any static server)
cd ../frontend
python -m http.server 5173          # open http://localhost:5173
```

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
