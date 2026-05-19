"""Deterministic unit tests for the ingestion + tool layer (§5.1 first row)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.store import get_store
from app.ingest.embed import build_index
from app.tools import search_entities, set_user_location, query_nearby, build_or_revise_plan, summarize_day


def setup_module(_):
    store = get_store()
    if not (ROOT / "backend" / "app" / "data" / "embeddings.npy").exists():
        build_index()
    store.load()


def test_corpus_sizes():
    s = get_store()
    assert len(s.sessions) > 100, f"too few sessions: {len(s.sessions)}"
    assert len(s.speakers) > 100
    assert len(s.exhibitors) > 50
    assert len(s.booths) > 50


def test_search_returns_results():
    r = search_entities("LoRa IoT asset tracking", type="exhibitor", k=5)
    assert r["results"], "expected at least one match"
    assert all("id" in x for x in r["results"])


def test_set_location_resolves_company():
    user = "test_user_loc"
    # find a real company to use
    store = get_store()
    sample = next(iter(store.exhibitors.values()))
    r = set_user_location(user, sample.company)
    assert "error" not in r, r
    assert r["booth_number"] == sample.booth_number


def test_query_nearby_requires_location():
    r = query_nearby("test_user_neighbor", radius_meters=50)
    assert r.get("error") == "no_location_set"


def test_query_nearby_after_set():
    user = "test_user_nearby"
    store = get_store()
    sample = next(iter(store.exhibitors.values()))
    set_user_location(user, sample.company)
    r = query_nearby(user, time_budget_minutes=15)
    assert "results" in r


def test_plan_respects_no_time_conflict():
    user = "test_user_plan"
    r = build_or_revise_plan(user, "edge inference and LoRa IoT", day="2026-05-19")
    plan = r["plan"]
    # within day check no overlaps
    by_day = {}
    for p in plan:
        by_day.setdefault(p["day"], []).append(p)
    for items in by_day.values():
        items.sort(key=lambda x: x["start"])
        for a, b in zip(items, items[1:]):
            assert a["end"] <= b["start"], f"overlap: {a} vs {b}"


def test_summarize_day_returns_payload():
    r = summarize_day("test_user_recap")
    assert "attended_count" in r


if __name__ == "__main__":
    setup_module(None)
    funcs = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    for f in funcs:
        try:
            f()
            print(f"ok  {f.__name__}")
        except AssertionError as e:
            print(f"FAIL {f.__name__}: {e}")
        except Exception as e:
            print(f"ERR  {f.__name__}: {e!r}")
