"""FastAPI app — REST + WebSocket surface for the Expo Concierge."""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .agent import Conversation, reset_conversation, run_turn
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
)


# ─── REST: corpus + floorplan ────────────────────────────────────────────

@app.get("/api/floorplan.png")
async def floorplan_image():
    p = DATA_DIR / "floorplan.png"
    if not p.exists():
        raise HTTPException(404, "floorplan not rendered")
    return FileResponse(p)


@app.get("/api/booths")
async def list_booths():
    return [b.model_dump(mode="json") for b in get_store().booths.values()]


@app.get("/api/exhibitors")
async def list_exhibitors():
    return [e.model_dump(mode="json") for e in get_store().exhibitors.values()]


@app.get("/api/sessions")
async def list_sessions():
    return [s.model_dump(mode="json") for s in get_store().sessions.values()]


@app.get("/api/annotations/summary")
async def annotations_summary():
    return get_store().annotations_summary()


@app.get("/api/profile/{user_id}")
async def get_profile(user_id: str):
    return get_store().get_profile(user_id).model_dump(mode="json")


@app.post("/api/profile/{user_id}")
async def update_profile(user_id: str, payload: dict):
    p = get_store().update_profile(user_id, **payload)
    return p.model_dump(mode="json")


@app.get("/api/plan/{user_id}")
async def get_plan(user_id: str):
    return get_store().get_plan(user_id)


@app.post("/api/linkedin/{user_id}")
async def upload_linkedin(user_id: str, payload: dict):
    """Accept LinkedIn Connections.csv content as text."""
    raw = payload.get("csv", "")
    conns = parse_connections_csv(raw)
    store = get_store()
    store.update_profile(user_id, connections=conns)
    return {"imported": len(conns), "companies": len({c['company'] for c in conns if c.get('company')})}


@app.post("/api/tool/{name}")
async def call_tool(name: str, payload: dict):
    impl = TOOL_IMPLS.get(name)
    if not impl:
        raise HTTPException(404, "unknown tool")
    user_id = payload.pop("user_id", "demo")
    try:
        return impl(user_id, **payload)
    except TypeError as e:
        raise HTTPException(400, f"bad args: {e}")


# ─── WebSocket: streaming agent chat ─────────────────────────────────────

CONVERSATIONS: dict[str, Conversation] = {}


@app.websocket("/ws/chat/{user_id}")
async def chat_socket(ws: WebSocket, user_id: str):
    await ws.accept()
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
    store = get_store()
    # if embeddings missing, build (pseudo if no API key)
    if not (DATA_DIR / "embeddings.npy").exists():
        build_index()
    store.load()
    print(f"[store] {len(store.sessions)} sessions, {len(store.speakers)} speakers, {len(store.exhibitors)} exhibitors, {len(store.booths)} booths")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=False)
