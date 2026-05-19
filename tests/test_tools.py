"""Direct tool invocation tests (no agent in the loop)."""

from __future__ import annotations

import time

from .common import Report


def run() -> Report:
    r = Report("tools (direct)")

    # Import the backend package
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
    from app.store import get_store
    from app.tools import TOOL_IMPLS

    store = get_store()
    if not store.exhibitors:
        store.load()
    uid = f"toolstest_{int(time.time())}"

    # search_entities
    out = TOOL_IMPLS["search_entities"](uid, query="LoRa IoT", k=4)
    if out.get("results"):
        r.ok(f"search_entities returns {len(out['results'])} results")
    else:
        r.fail("search_entities empty", str(out)[:140])

    # set_user_location (by booth number)
    out = TOOL_IMPLS["set_user_location"](uid, reference="272")
    if out.get("booth_number") == "272":
        r.ok("set_user_location 272 → Deloitte")
    else:
        r.fail("set_user_location 272 failed", str(out)[:140])
    if out.get("_ui", {}).get("you_are_here") == "272":
        r.ok("set_user_location emits _ui.you_are_here")
    else:
        r.fail("set_user_location missing _ui.you_are_here")

    # set_user_location (by company)
    out = TOOL_IMPLS["set_user_location"](uid, reference="Deloitte")
    if out.get("exhibitor", "").startswith("Deloitte"):
        r.ok("set_user_location resolves company name")
    else:
        r.fail("company resolution failed", str(out)[:140])

    # set_user_location (idempotent)
    a = TOOL_IMPLS["set_user_location"](uid, reference="272")
    b = TOOL_IMPLS["set_user_location"](uid, reference="272")
    if a.get("booth_number") == b.get("booth_number"):
        r.ok("set_user_location idempotent")

    # set_user_location (unknown)
    out = TOOL_IMPLS["set_user_location"](uid, reference="zzz-not-a-booth")
    if out.get("error") == "could_not_resolve":
        r.ok("set_user_location handles unknown gracefully")
    else:
        r.fail("unknown booth should error", str(out)[:140])

    # query_nearby
    TOOL_IMPLS["set_user_location"](uid, reference="272")
    out = TOOL_IMPLS["query_nearby"](uid, radius_meters=80)
    if isinstance(out.get("results"), list) and len(out["results"]) > 3:
        r.ok(f"query_nearby returns {len(out['results'])} nearby booths")
    else:
        r.fail("query_nearby too few results", str(out)[:140])
    if out.get("_ui", {}).get("highlights"):
        r.ok("query_nearby emits _ui.highlights")

    # query_nearby with time budget
    out = TOOL_IMPLS["query_nearby"](uid, time_budget_minutes=15)
    if isinstance(out.get("results"), list):
        r.ok("query_nearby with time_budget_minutes works")

    # query_nearby distances are sorted ascending
    if len(out.get("results", [])) >= 2:
        ds = [x["distance_px"] for x in out["results"]]
        if ds == sorted(ds):
            r.ok("query_nearby sorts by distance")
        else:
            r.fail("query_nearby unsorted", str(ds[:6]))

    # build_or_revise_plan (no LLM — direct algo)
    out = TOOL_IMPLS["build_or_revise_plan"](uid, goals="LoRa IoT and edge inference")
    plan = out.get("plan", [])
    if 1 <= len(plan) <= 8:
        r.ok(f"build_or_revise_plan -> {len(plan)} sessions")
    else:
        r.fail("plan size unexpected", str(len(plan)))

    # No time conflicts in the plan
    by_day = {}
    for p in plan:
        by_day.setdefault(p["day"], []).append((p["start"], p["end"], p["title"]))
    conflict = False
    for day, items in by_day.items():
        items.sort()
        for i in range(1, len(items)):
            if items[i][0] < items[i-1][1]:
                conflict = True
    if not conflict:
        r.ok("plan has no time conflicts")
    else:
        r.fail("plan has time conflicts")

    # update_schedule add/remove
    if plan:
        eid = plan[0]["id"]
        out = TOOL_IMPLS["update_schedule"](uid, remove=[eid])
        if eid in out.get("removed", []):
            r.ok("update_schedule remove works")
        out = TOOL_IMPLS["update_schedule"](uid, add=[eid])
        if eid in out.get("added", []):
            r.ok("update_schedule add works")

    # highlight_on_map
    out = TOOL_IMPLS["highlight_on_map"](uid, entity_ids=["272", "270", "269"])
    if "272" in out.get("booths", []):
        r.ok("highlight_on_map accepts booth numbers")

    # mark_visited / save_for_later
    out = TOOL_IMPLS["mark_visited"](uid, entity_id="272")
    if out.get("entity_id") == "272":
        r.ok("mark_visited works")
    out = TOOL_IMPLS["save_for_later"](uid, entity_id="272")
    if out.get("entity_id") == "272":
        r.ok("save_for_later works")

    # submit_annotation good + bad type
    ex_id = next(iter(store.exhibitors.keys()))
    out = TOOL_IMPLS["submit_annotation"](uid, entity_id=ex_id, ann_type="free_drinks", payload={})
    if not out.get("error"):
        r.ok("submit_annotation free_drinks accepted")
    out = TOOL_IMPLS["submit_annotation"](uid, entity_id=ex_id, ann_type="bogus_type", payload={})
    if out.get("error") == "bad_type":
        r.ok("submit_annotation rejects unknown type")

    # who_do_i_know_at — no connections imported
    out = TOOL_IMPLS["who_do_i_know_at"](uid, company="Semtech")
    if out.get("imported") is False:
        r.ok("who_do_i_know_at returns imported=false when empty")

    # summarize_day
    out = TOOL_IMPLS["summarize_day"](uid)
    if "attended_count" in out:
        r.ok("summarize_day returns counts")

    # get_entity
    out = TOOL_IMPLS["get_entity"](uid, entity_id="272")
    if out.get("entity", {}).get("type") == "booth":
        r.ok("get_entity('272') -> booth")
    out = TOOL_IMPLS["get_entity"](uid, entity_id="not-real")
    if out.get("error") == "not_found":
        r.ok("get_entity unknown -> not_found")

    return r


if __name__ == "__main__":
    run().print_summary()
