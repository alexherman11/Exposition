"""FastAPI app — REST + WebSocket surface for the Expo Concierge."""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .agent import Conversation, reset_conversation, run_turn
from .auth import (
    SESSION_COOKIE,
    get_or_create_user_id,
    linkedin_configured,
    router as auth_router,
    _read_session_cookie,
)
from .db import init_db
from .ingest.embed import build_index
from .linkedin import parse_connections_csv
from .store import get_store
from .tools import TOOL_IMPLS

DATA_DIR = Path(__file__).resolve().parent / "data"
FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend"


app = FastAPI(title="Expo Concierge")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)


# auth routes (login, callback, logout, /api/me)
app.include_router(auth_router)


# ─── current-user dependency ─────────────────────────────────────────────

def current_user_id(request: Request, response: Response) -> str:
    """Resolve user from signed session cookie; mint a guest if none."""
    return get_or_create_user_id(request, response)


# ─── REST: corpus + floorplan ────────────────────────────────────────────

@app.get("/api/floorplan.png")
async def floorplan_image():
    p = DATA_DIR / "floorplan.png"
    if not p.exists():
        raise HTTPException(404, "floorplan not rendered")
    return FileResponse(p)


@app.get("/api/floorplan_layout.json")
async def floorplan_layout():
    p = DATA_DIR / "floorplan_layout.json"
    if not p.exists():
        raise HTTPException(404, "floorplan layout not extracted — run scripts/extract_floorplan.py")
    return FileResponse(p, media_type="application/json")


@app.get("/api/booths")
async def list_booths():
    return [b.model_dump(mode="json") for b in get_store().booths.values()]


@app.get("/api/exhibitors")
async def list_exhibitors():
    return [e.model_dump(mode="json") for e in get_store().exhibitors.values()]


@app.get("/api/sessions")
async def list_sessions():
    return [s.model_dump(mode="json") for s in get_store().sessions.values()]


@app.get("/api/speakers")
async def list_speakers():
    return [s.model_dump(mode="json") for s in get_store().speakers.values()]


@app.get("/api/annotations/summary")
async def annotations_summary():
    return get_store().annotations_summary()


# ─── current-user-scoped endpoints (cookie-derived) ──────────────────────

@app.get("/api/profile")
async def get_my_profile(user_id: str = Depends(current_user_id)):
    return get_store().get_profile(user_id).model_dump(mode="json")


@app.post("/api/profile")
async def update_my_profile(payload: dict, user_id: str = Depends(current_user_id)):
    return get_store().update_profile(user_id, **payload).model_dump(mode="json")


@app.get("/api/plan")
async def get_my_plan(user_id: str = Depends(current_user_id)):
    return get_store().get_plan(user_id)


@app.post("/api/linkedin")
async def upload_my_linkedin(payload: dict, user_id: str = Depends(current_user_id)):
    """Accept LinkedIn Connections.csv content as text. OAuth gets identity;
    this is the only way to actually load the user's connections graph since
    LinkedIn does not expose it via API."""
    raw = payload.get("csv", "")
    conns = parse_connections_csv(raw)
    store = get_store()
    store.update_profile(user_id, connections=conns)
    return {"imported": len(conns), "companies": len({c['company'] for c in conns if c.get('company')})}


# Legacy compatibility — pre-auth callers passed user_id in the path.
# We accept it but ignore in favor of the cookie, except for tests / curl
# which can still pin to a specific id by passing user_id=<...>.

@app.get("/api/profile/{user_id}")
async def get_profile_legacy(user_id: str):
    return get_store().get_profile(user_id).model_dump(mode="json")


@app.post("/api/profile/{user_id}")
async def update_profile_legacy(user_id: str, payload: dict):
    return get_store().update_profile(user_id, **payload).model_dump(mode="json")


@app.get("/api/plan/{user_id}")
async def get_plan_legacy(user_id: str):
    return get_store().get_plan(user_id)


@app.post("/api/linkedin/{user_id}")
async def upload_linkedin_legacy(user_id: str, payload: dict):
    raw = payload.get("csv", "")
    conns = parse_connections_csv(raw)
    get_store().update_profile(user_id, connections=conns)
    return {"imported": len(conns), "companies": len({c['company'] for c in conns if c.get('company')})}


@app.post("/api/tool/{name}")
async def call_tool(name: str, payload: dict, user_id: str = Depends(current_user_id)):
    impl = TOOL_IMPLS.get(name)
    if not impl:
        raise HTTPException(404, "unknown tool")
    # Allow tests to override user_id explicitly; otherwise use cookie session.
    uid = payload.pop("user_id", None) or user_id
    try:
        return impl(uid, **payload)
    except TypeError as e:
        raise HTTPException(400, f"bad args: {e}")


# ─── WebSocket: streaming agent chat ─────────────────────────────────────

CONVERSATIONS: dict[str, Conversation] = {}


@app.websocket("/ws/chat/{user_id}")
async def chat_socket(ws: WebSocket, user_id: str):
    await ws.accept()
    # If the path id is "me", read it from the cookie instead.
    if user_id == "me":
        cookie_uid = _read_session_cookie(ws)  # type: ignore[arg-type]
        if cookie_uid:
            user_id = cookie_uid
        else:
            user_id = f"guest:{uuid.uuid4().hex[:16]}"
    conv = CONVERSATIONS.setdefault(user_id, reset_conversation(user_id))

    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except Exception:
                msg = {"text": raw}
            if msg.get("type") == "reset":
                CONVERSATIONS[user_id] = reset_conversation(user_id)
                await ws.send_text(json.dumps({"type": "reset_ack"}))
                continue
            text = msg.get("text", "").strip()
            if not text:
                continue
            try:
                async for ev in run_turn(conv, text):
                    await ws.send_text(json.dumps(ev))
            except Exception as e:
                await ws.send_text(json.dumps({"type": "error", "message": str(e)}))
    except WebSocketDisconnect:
        return


# ─── frontend mount ──────────────────────────────────────────────────────

if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")


# ─── startup ─────────────────────────────────────────────────────────────

@app.on_event("startup")
async def _startup():
    # DB: bootstrap tables (idempotent)
    init_db()

    store = get_store()
    required = ["exhibitors.json", "booths.json", "sessions.json", "speakers.json"]
    missing = [f for f in required if not (DATA_DIR / f).exists()]
    if missing:
        print(f"[store] WARNING: missing data files {missing}. Run scripts/scrape_agenda.py and scripts/extract_floorplan.py.")
        return

    if not (DATA_DIR / "embeddings.npy").exists():
        if not os.getenv("GEMINI_API_KEY"):
            print("[store] WARNING: GEMINI_API_KEY not set; building pseudo-embeddings. Semantic search quality will be poor.")
        build_index()

    store.load()
    print(
        f"[store] {len(store.sessions)} sessions, {len(store.speakers)} speakers, "
        f"{len(store.exhibitors)} exhibitors, {len(store.booths)} booths"
    )
    print(f"[auth] linkedin sign-in: {'enabled' if linkedin_configured() else 'DISABLED (guest mode only)'}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=False)
