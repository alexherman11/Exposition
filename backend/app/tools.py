"""Agent tools (§4.5). All tools are idempotent where possible (§4.5 closing).

Each tool returns a plain dict — the same one that goes to both the LLM
and the frontend as a "tool result" pill (§4.6). The frontend uses the
`_ui` field to drive map highlights and schedule animations.
"""

from __future__ import annotations

import os
import re
from typing import Optional

from .ingest.embed import embed_query
from .linkedin import who_at
from .store import get_store


def _entity_summary(eid: str) -> dict:
    s = get_store().get(eid)
    if not s:
        return {"id": eid, "type": "unknown"}
    t = s["type"]
    if t == "session":
        return {"id": s["id"], "type": "session", "title": s["title"], "room": s["room"], "day": s["day"], "start": s["start"], "end": s["end"], "tags": s["tags"]}
    if t == "speaker":
        return {"id": s["id"], "type": "speaker", "name": s["name"], "title": s["title"], "company": s["company"]}
    if t == "exhibitor":
        return {"id": s["id"], "type": "exhibitor", "company": s["company"], "booth_number": s["booth_number"], "hall_zone": s["hall_zone"], "tags": s["tags"]}
    return s


# ─── search ───────────────────────────────────────────────────────────────

def search_entities(query: str, type: Optional[str] = None, k: int = 6) -> dict:
    """Semantic search over sessions/speakers/exhibitors. Returns top-k."""
    store = get_store()
    qv = embed_query(query)
    raw = store.search(qv, type_filter=type, k=k)
    results = [{"score": round(score, 3), **_entity_summary(eid)} for eid, _t, score in raw]
    return {
        "tool": "search_entities",
        "query": query,
        "type": type,
        "results": results,
        "_ui": {"highlights": [r["id"] for r in results if r.get("type") == "exhibitor"][:6]},
    }


def get_entity(entity_id: str) -> dict:
    store = get_store()
    raw = store.get(entity_id)
    if not raw:
        return {"tool": "get_entity", "error": "not_found", "id": entity_id}
    raw["annotations"] = store.annotations_for(entity_id)
    return {"tool": "get_entity", "entity": raw}


# ─── spatial ──────────────────────────────────────────────────────────────

def set_user_location(user_id: str, reference: str) -> dict:
    """Resolve a booth/company reference to a booth, update profile."""
    store = get_store()
    booth = store.find_booth_for_reference(reference)
    if not booth:
        return {"tool": "set_user_location", "error": "could_not_resolve", "reference": reference}
    store.update_profile(user_id, location_reference=booth.booth_number)
    ex = store.exhibitors.get(booth.exhibitor_id) if booth.exhibitor_id else None
    return {
        "tool": "set_user_location",
        "booth_number": booth.booth_number,
        "hall_zone": booth.hall_zone,
        "exhibitor": ex.company if ex else None,
        "_ui": {"you_are_here": booth.booth_number},
    }


def query_nearby(user_id: str, radius_meters: float = 50, filter_tags: Optional[list[str]] = None, time_budget_minutes: Optional[float] = None) -> dict:
    """Find booths near the user, optionally filtered. If a time budget is
    given, radius is computed from walking-speed × budget (§2.4)."""
    store = get_store()
    p = store.get_profile(user_id)
    if not p.location_reference:
        return {"tool": "query_nearby", "error": "no_location_set"}
    me = store.booths.get(p.location_reference)
    if not me:
        return {"tool": "query_nearby", "error": "stale_location"}

    if time_budget_minutes:
        # walking 1.2 m/s through a hall ≈ 72 m/min. Halve to allow time at booth.
        radius_meters = max(20, min(120, time_budget_minutes * 72 * 0.5))

    # pixel radius — our floorplan is 1600x1000 ≈ 100m × 60m so 1m ≈ 16px
    radius_px = radius_meters * 16

    results = store.query_nearby((me.center[0], me.center[1]), radius_px, filter_tags)
    # filter out the booth the user is currently at
    results = [r for r in results if r["booth_number"] != me.booth_number]
    return {
        "tool": "query_nearby",
        "from_booth": me.booth_number,
        "radius_meters": radius_meters,
        "results": results[:12],
        "_ui": {"highlights": [r["booth_number"] for r in results[:12]], "from": me.booth_number},
    }


# ─── planning ─────────────────────────────────────────────────────────────

def build_or_revise_plan(user_id: str, goals: str, day: Optional[str] = None, existing_plan_ids: Optional[list[str]] = None) -> dict:
    """Calls Gemini 2.5 Pro to construct/restructure an itinerary (§4.1).

    For the prototype we use a constrained semantic-search + greedy packer
    that respects time conflicts. This is the deterministic kernel; the
    Pro model is wrapped around it as a reasoning step in agent.py.
    """
    store = get_store()
    qv = embed_query(goals)
    candidates = store.search(qv, type_filter="session", k=40)
    chosen: list[dict] = []
    taken_intervals: list[tuple[str, int, int]] = []

    def to_min(s: str) -> int:
        h, m = s.split(":")
        return int(h) * 60 + int(m)

    for eid, _t, score in candidates:
        sess = store.sessions[eid]
        if day and sess.day != day:
            continue
        start, end = to_min(sess.start), to_min(sess.end)
        conflict = any(d == sess.day and not (end <= s or start >= e) for d, s, e in taken_intervals)
        if conflict:
            continue
        taken_intervals.append((sess.day, start, end))
        chosen.append({**_entity_summary(eid), "score": round(score, 3)})
        if len(chosen) >= 8:
            break

    chosen.sort(key=lambda c: (c["day"], c["start"]))
    for c in chosen:
        store.add_to_plan(user_id, c["id"], "planned", "session")
    return {
        "tool": "build_or_revise_plan",
        "goals": goals,
        "day": day,
        "plan": chosen,
        "_ui": {"plan_changed": True},
    }


def update_schedule(user_id: str, add: Optional[list[str]] = None, remove: Optional[list[str]] = None) -> dict:
    store = get_store()
    added, removed = [], []
    for eid in (add or []):
        item = store.add_to_plan(user_id, eid, "planned", "session")
        added.append(item.entity_id)
    for eid in (remove or []):
        if store.remove_from_plan(user_id, eid):
            removed.append(eid)
    return {"tool": "update_schedule", "added": added, "removed": removed, "_ui": {"plan_changed": True}}


# ─── map highlight ────────────────────────────────────────────────────────

def highlight_on_map(entity_ids: list[str], label: Optional[str] = None) -> dict:
    store = get_store()
    booths = []
    for eid in entity_ids:
        if eid in store.exhibitors:
            booths.append(store.exhibitors[eid].booth_number)
        elif eid in store.booths:
            booths.append(eid)
    return {"tool": "highlight_on_map", "booths": booths, "label": label, "_ui": {"highlights": booths}}


# ─── behavioral state ─────────────────────────────────────────────────────

def mark_visited(user_id: str, entity_id: str) -> dict:
    store = get_store()
    store.add_to_plan(user_id, entity_id, "attended")
    store.log_behavior(user_id, "visited", entity_id)
    return {"tool": "mark_visited", "entity_id": entity_id, "_ui": {"plan_changed": True}}


def save_for_later(user_id: str, entity_id: str) -> dict:
    store = get_store()
    store.add_to_plan(user_id, entity_id, "saved")
    store.log_behavior(user_id, "saved", entity_id)
    return {"tool": "save_for_later", "entity_id": entity_id, "_ui": {"plan_changed": True}}


# ─── community annotations ────────────────────────────────────────────────

def submit_annotation(user_id: str, entity_id: str, ann_type: str, payload: dict) -> dict:
    if ann_type not in ("free_drinks", "good_swag", "rating", "comment", "presenter_contact"):
        return {"tool": "submit_annotation", "error": "bad_type", "type": ann_type}
    a = get_store().add_annotation(user_id, entity_id, ann_type, payload or {})
    return {"tool": "submit_annotation", "annotation": a.model_dump(mode="json"), "_ui": {"annotation_updated": entity_id}}


# ─── summary ──────────────────────────────────────────────────────────────

def summarize_day(user_id: str, scope: str = "today") -> dict:
    store = get_store()
    p = store.get_profile(user_id)
    plan = store.get_plan(user_id)
    attended = [p for p in plan if p["layer"] == "attended"]
    saved = [p for p in plan if p["layer"] == "saved"]
    contacts = [b for b in p.behavioral_log if b.get("action") == "presenter_contact"]
    return {
        "tool": "summarize_day",
        "scope": scope,
        "attended_count": len(attended),
        "saved_count": len(saved),
        "contacts": contacts,
        "log_tail": p.behavioral_log[-12:],
    }


# ─── linkedin connections (§4.8) ──────────────────────────────────────────

def who_do_i_know_at(user_id: str, company: str) -> dict:
    p = get_store().get_profile(user_id)
    if not p.connections:
        return {"tool": "who_do_i_know_at", "imported": False, "message": "No LinkedIn connections imported. Drag your Connections.csv into Settings to enable this."}
    hits = who_at(p.connections, company)
    return {"tool": "who_do_i_know_at", "imported": True, "company": company, "matches": hits[:8], "count": len(hits)}


# ─── web search fallback ──────────────────────────────────────────────────

def web_search(query: str) -> dict:
    """§4.2 — only used when local corpus is thin."""
    if not os.getenv("GEMINI_API_KEY"):
        return {"tool": "web_search", "error": "no_api_key", "query": query}
    from google import genai
    from google.genai import types
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    try:
        resp = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[f"Answer concisely with cited sources: {query}"],
            config=types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())],
                temperature=0.1,
            ),
        )
        return {"tool": "web_search", "query": query, "answer": resp.text}
    except Exception as e:
        return {"tool": "web_search", "error": str(e), "query": query}


# ─── tool registry exposed to the model ───────────────────────────────────

TOOL_SCHEMAS = [
    {
        "name": "search_entities",
        "description": "Semantic search over conference sessions, speakers, and exhibitors. Use FIRST whenever the user mentions a named entity, topic, or interest.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "type": {"type": "string", "enum": ["session", "speaker", "exhibitor"]},
                "k": {"type": "integer"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_entity",
        "description": "Fetch full record for a specific entity id (se_*, sp_*, ex_*, or booth number).",
        "parameters": {"type": "object", "properties": {"entity_id": {"type": "string"}}, "required": ["entity_id"]},
    },
    {
        "name": "set_user_location",
        "description": "Update the user's declared location. The 'reference' is a booth number (e.g. 'A14') OR a company name (e.g. 'Semtech'). MUST be called before query_nearby when the user mentions where they are.",
        "parameters": {"type": "object", "properties": {"reference": {"type": "string"}}, "required": ["reference"]},
    },
    {
        "name": "query_nearby",
        "description": "Find booths near the user's declared location. Pass time_budget_minutes when the user says 'I have X minutes'.",
        "parameters": {
            "type": "object",
            "properties": {
                "radius_meters": {"type": "number"},
                "filter_tags": {"type": "array", "items": {"type": "string"}},
                "time_budget_minutes": {"type": "number"},
            },
        },
    },
    {
        "name": "build_or_revise_plan",
        "description": "Construct a day-plan from goals. Use when the user asks to plan, schedule, or itinerary their day.",
        "parameters": {
            "type": "object",
            "properties": {
                "goals": {"type": "string", "description": "Natural-language description of interests/goals."},
                "day": {"type": "string", "description": "YYYY-MM-DD; default today (2026-05-19)"},
            },
            "required": ["goals"],
        },
    },
    {
        "name": "update_schedule",
        "description": "Add or remove items from the user's planned schedule.",
        "parameters": {
            "type": "object",
            "properties": {
                "add": {"type": "array", "items": {"type": "string"}},
                "remove": {"type": "array", "items": {"type": "string"}},
            },
        },
    },
    {
        "name": "highlight_on_map",
        "description": "Light up specific booths on the floorplan. Pass exhibitor ids or booth numbers.",
        "parameters": {
            "type": "object",
            "properties": {
                "entity_ids": {"type": "array", "items": {"type": "string"}},
                "label": {"type": "string"},
            },
            "required": ["entity_ids"],
        },
    },
    {
        "name": "mark_visited",
        "description": "Record that the user visited an entity (booth/session). Idempotent.",
        "parameters": {"type": "object", "properties": {"entity_id": {"type": "string"}}, "required": ["entity_id"]},
    },
    {
        "name": "save_for_later",
        "description": "Bookmark an entity to the user's saved pile.",
        "parameters": {"type": "object", "properties": {"entity_id": {"type": "string"}}, "required": ["entity_id"]},
    },
    {
        "name": "submit_annotation",
        "description": "Add a community annotation (free_drinks flag, good_swag flag, rating 1-5, comment text).",
        "parameters": {
            "type": "object",
            "properties": {
                "entity_id": {"type": "string"},
                "type": {"type": "string", "enum": ["free_drinks", "good_swag", "rating", "comment", "presenter_contact"]},
                "payload": {"type": "object"},
            },
            "required": ["entity_id", "type"],
        },
    },
    {
        "name": "summarize_day",
        "description": "Produce the end-of-day recap.",
        "parameters": {"type": "object", "properties": {"scope": {"type": "string"}}},
    },
    {
        "name": "who_do_i_know_at",
        "description": "Look up the user's LinkedIn connections at a given company. Use when the user asks 'who do I know at X?'",
        "parameters": {"type": "object", "properties": {"company": {"type": "string"}}, "required": ["company"]},
    },
    {
        "name": "web_search",
        "description": "Fallback when an entity is not in the conference corpus. Use sparingly.",
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
    },
]


TOOL_IMPLS = {
    "search_entities": lambda user_id, **kw: search_entities(**kw),
    "get_entity": lambda user_id, **kw: get_entity(**kw),
    "set_user_location": lambda user_id, **kw: set_user_location(user_id, **kw),
    "query_nearby": lambda user_id, **kw: query_nearby(user_id, **kw),
    "build_or_revise_plan": lambda user_id, **kw: build_or_revise_plan(user_id, **kw),
    "update_schedule": lambda user_id, **kw: update_schedule(user_id, **kw),
    "highlight_on_map": lambda user_id, **kw: highlight_on_map(**kw),
    "mark_visited": lambda user_id, **kw: mark_visited(user_id, **kw),
    "save_for_later": lambda user_id, **kw: save_for_later(user_id, **kw),
    "submit_annotation": lambda user_id, **kw: submit_annotation(user_id, **kw),
    "summarize_day": lambda user_id, **kw: summarize_day(user_id, **kw),
    "who_do_i_know_at": lambda user_id, **kw: who_do_i_know_at(user_id, **kw),
    "web_search": lambda user_id, **kw: web_search(**kw),
}
