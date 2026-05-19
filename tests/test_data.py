"""Data integrity tests — pure JSON assertions, no server needed."""

from __future__ import annotations

import json
import re
from collections import Counter

from .common import DATA, Report


def run() -> Report:
    r = Report("data integrity")

    exhibitors = json.loads((DATA / "exhibitors.json").read_text())
    booths = json.loads((DATA / "booths.json").read_text())
    sessions = json.loads((DATA / "sessions.json").read_text())
    speakers = json.loads((DATA / "speakers.json").read_text())
    layout = json.loads((DATA / "floorplan_layout.json").read_text())

    # ── Exhibitors ──────────────────────────────────────────────────────
    r.ok(f"exhibitors loaded: {len(exhibitors)}")
    for ex in exhibitors:
        if not ex.get("id"):
            r.fail("exhibitor missing id", json.dumps(ex)[:120])
        if not ex.get("company"):
            r.fail("exhibitor missing company", ex.get("id"))
    if all(e.get("id") and e.get("company") for e in exhibitors):
        r.ok("every exhibitor has id+company")
    ids = [e["id"] for e in exhibitors]
    if len(ids) == len(set(ids)):
        r.ok(f"exhibitor ids unique ({len(ids)})")
    else:
        r.fail("duplicate exhibitor ids", str(Counter(ids).most_common(3)))

    # ── Booths ──────────────────────────────────────────────────────────
    r.ok(f"booths loaded: {len(booths)}")
    bad = [b for b in booths if not (b.get("bbox") and b.get("center") and b.get("booth_number"))]
    if not bad:
        r.ok("every booth has bbox + center + number")
    else:
        r.fail("booth missing geom", ", ".join(b.get("booth_number","?") for b in bad[:5]))

    booth_nums = {b["booth_number"] for b in booths}
    booth_centers_ok = all(
        len(b["center"]) == 2 and isinstance(b["center"][0], (int, float)) for b in booths
    )
    if booth_centers_ok:
        r.ok("booth centers numeric")

    # Booths assigned to a real exhibitor must reference a real id
    ex_ids = {e["id"] for e in exhibitors}
    bad_links = [b for b in booths if b.get("exhibitor_id") and b["exhibitor_id"] not in ex_ids]
    if not bad_links:
        r.ok("booth→exhibitor refs all valid")
    else:
        r.fail("stale booth→exhibitor links", str(len(bad_links)))

    # ── Sessions ────────────────────────────────────────────────────────
    r.ok(f"sessions loaded: {len(sessions)}")
    for s in sessions[:0]: pass  # touch
    spk_ids = {s["id"] for s in speakers}
    time_re = re.compile(r"^\d{2}:\d{2}$")
    day_re = re.compile(r"^2026-05-(18|19)$")
    bad_time = [s for s in sessions if not (time_re.match(s.get("start","")) and time_re.match(s.get("end","")))]
    bad_day = [s for s in sessions if not day_re.match(s.get("day",""))]
    bad_spk = [s for s in sessions for sid in s.get("speaker_ids",[]) if sid not in spk_ids]
    if not bad_time:
        r.ok("every session has HH:MM start+end")
    else:
        r.fail(f"sessions with bad time format: {len(bad_time)}", str([s["title"][:50] for s in bad_time[:3]]))
    if not bad_day:
        r.ok("every session day is 2026-05-18 or 2026-05-19")
    else:
        r.fail(f"sessions with bad day: {len(bad_day)}", str([s["day"] for s in bad_day[:3]]))
    if not bad_spk:
        r.ok("every session speaker_id resolves")
    else:
        r.fail(f"sessions reference missing speakers: {len(bad_spk)}")

    # Sessions where end <= start
    flipped = []
    for s in sessions:
        try:
            sh,sm = map(int, s["start"].split(":")); eh,em = map(int, s["end"].split(":"))
            if (eh*60+em) <= (sh*60+sm):
                flipped.append(s["title"])
        except Exception:
            pass
    if not flipped:
        r.ok("session end > start")
    else:
        r.fail(f"sessions with end<=start: {len(flipped)}", str(flipped[:3]))

    # ── Speakers ────────────────────────────────────────────────────────
    r.ok(f"speakers loaded: {len(speakers)}")
    sess_ids = {s["id"] for s in sessions}
    bad_sess = [sid for sp in speakers for sid in sp.get("session_ids",[]) if sid not in sess_ids]
    if not bad_sess:
        r.ok("every speaker session_id resolves")
    else:
        r.fail(f"speakers reference missing sessions: {len(bad_sess)}")

    # ── Floorplan layout ────────────────────────────────────────────────
    r.ok(f"layout: {len(layout['booths'])} booths, {len(layout['zones'])} zones, {len(layout['amenities'])} amenities")
    if "building_bbox" in layout:
        r.ok("layout has building_bbox")
    if layout.get("viewbox") and len(layout["viewbox"]) == 4:
        r.ok("layout has 4-element viewbox")
    # every layout booth center is inside the building bbox
    bx0, by0, bx1, by1 = layout["building_bbox"]
    outside = [b for b in layout["booths"] if not (bx0-5 <= b["center"][0] <= bx1+5 and by0-5 <= b["center"][1] <= by1+5)]
    if not outside:
        r.ok("all layout booths inside building_bbox")
    else:
        r.fail(f"booths outside building: {len(outside)}", str([b['booth_number'] for b in outside[:5]]))
    if layout.get("amenities") and all(a.get("kind") != "featured_strip" for a in layout["amenities"]):
        r.ok("no 'Featured Exhibitors' callout in amenities")

    # ── Embeddings ──────────────────────────────────────────────────────
    try:
        import numpy as np
        emb = np.load(DATA / "embeddings.npy")
        idx = json.loads((DATA / "embedding_ids.json").read_text())
        if emb.shape[0] == len(idx["ids"]) == len(idx["types"]):
            r.ok(f"embeddings shape {emb.shape} matches index ({len(idx['ids'])})")
        else:
            r.fail("embeddings shape/index mismatch", f"matrix={emb.shape}, ids={len(idx['ids'])}")
        if emb.shape[1] == 768:
            r.ok("embedding dim = 768")
    except Exception as e:
        r.fail("embeddings load failed", str(e))

    return r


if __name__ == "__main__":
    r = run()
    r.print_summary()
