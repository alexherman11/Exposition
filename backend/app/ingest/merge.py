"""Merge real-scraped data into the snapshot.

Strategy:
  - The real exhibitor list scraped from ai-expo.net (246 records) is the
    source of truth for exhibitors and booth numbers.
  - We synthesise booth coordinates by mapping the real booth numbers onto
    a generated floorplan grid (since the actual PDF floorplan is gated
    behind a download we can't reach from the sandbox).
  - Sessions and speakers are best-effort scraped; where scraping failed
    we keep the synthetic ones (so the agent has plenty to plan with) and
    label them as `is_synthetic: true` for transparency.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def _booth_sort_key(b: str) -> tuple:
    """Order booth numbers so adjacent numbers end up adjacent on the grid."""
    m = re.match(r"([A-Za-z]*)(\d+)", b or "")
    if not m:
        return ("zz", 9999)
    return (m.group(1).upper(), int(m.group(2)))


def _layout_booths(booth_numbers: list[str]) -> dict[str, dict]:
    """Place booths on a 1600x1000 grid, 4 hall zones.

    Sort booth numbers and chunk into halls so similar numbers stay near
    each other (matches how exhibition halls assign numeric ranges).
    """
    booth_numbers = sorted(set(booth_numbers), key=_booth_sort_key)
    n = len(booth_numbers)
    # 4 halls × ~ceil(n/4) booths per hall
    per_hall = math.ceil(n / 4)
    zones = ["Hall A — AI", "Hall B — IoT/Edge", "Hall D — Data Center", "Hall C — Cyber"]

    out = {}
    for hall_idx, zone in enumerate(zones):
        chunk = booth_numbers[hall_idx * per_hall : (hall_idx + 1) * per_hall]
        if not chunk:
            continue
        cols = math.ceil(math.sqrt(len(chunk) * 1.4))  # wider than tall
        rows = math.ceil(len(chunk) / cols)
        # Hall placement on canvas
        hx = 40 if hall_idx % 2 == 0 else 820
        hy = 60 if hall_idx < 2 else 540
        hw, hh = 740, 420
        cell_w = (hw - 16) / cols
        cell_h = (hh - 16) / rows
        for i, num in enumerate(chunk):
            r = i // cols
            c = i % cols
            x1 = hx + 8 + c * cell_w + 2
            y1 = hy + 8 + r * cell_h + 2
            x2 = x1 + cell_w - 6
            y2 = y1 + cell_h - 6
            cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
            out[num] = {
                "booth_number": num,
                "bbox": [x1, y1, x2, y2],
                "center": [cx, cy],
                "hall_zone": zone,
                "exhibitor_id": None,
            }
    return out


def _infer_tags(description: str) -> list[str]:
    """Extract tags by keyword spotting. Cheap but useful."""
    text = (description or "").lower()
    keywords = {
        "iot": ["iot", "internet of things", "connected device"],
        "lora": ["lora", "lorawan"],
        "5g": ["5g", "private network"],
        "edge ai": ["edge ai", "edge inference", "edge compute", "on-device"],
        "llm": ["llm", "large language model", "generative ai", "genai"],
        "agents": ["agent", "agentic", "copilot"],
        "rag": ["rag", "retrieval augmented", "vector"],
        "ml platform": ["mlops", "ml platform", "feature store"],
        "data platform": ["lakehouse", "warehouse", "data platform"],
        "cybersecurity": ["security", "threat", "endpoint", "zero trust", "siem"],
        "post-quantum": ["post-quantum", "pqc", "quantum-safe", "quantum safe"],
        "cooling": ["cooling", "thermal", "immersion"],
        "power": ["power", "ups", "pdu", "energy"],
        "robotics": ["robot", "robotics"],
        "vision": ["computer vision", "vision", "perception"],
        "smart factory": ["smart factory", "manufacturing", "scada", "industrial"],
        "automation": ["rpa", "automation", "workflow"],
        "cloud": ["aws", "azure", "gcp", "cloud"],
        "networking": ["network", "sd-wan", "5g network"],
        "sustainability": ["sustainab", "carbon", "green"],
    }
    tags = []
    for k, terms in keywords.items():
        if any(t in text for t in terms):
            tags.append(k)
    return tags[:6]


def merge_real_data() -> dict:
    """Produce a unified snapshot using real exhibitors when available."""
    real_path = DATA_DIR / "exhibitors_real.json"
    synth_path = DATA_DIR / "exhibitors.json"

    real_exhibitors = json.loads(real_path.read_text()) if real_path.exists() else []
    print(f"[merge] real exhibitors: {len(real_exhibitors)}")

    # tag-enrich
    for ex in real_exhibitors:
        if not ex.get("tags"):
            ex["tags"] = _infer_tags(ex.get("description", ""))
        # truncate descriptions ending with '[…]'
        d = ex.get("description") or ""
        if d.endswith("[…]") or d.endswith("[...]"):
            ex["description"] = d.rstrip(" […] .[..]")

    booth_numbers = [ex["booth_number"] for ex in real_exhibitors if ex.get("booth_number")]
    layout = _layout_booths(booth_numbers)

    # Build final booth list
    booths = []
    for ex in real_exhibitors:
        bn = ex.get("booth_number")
        if not bn:
            continue
        b = layout.get(bn)
        if b is None:
            continue
        b = dict(b)
        b["exhibitor_id"] = ex["id"]
        booths.append(b)
        # also attach hall_zone to exhibitor
        ex["hall_zone"] = b["hall_zone"]

    # For any booths in layout without exhibitors (shouldn't happen here), include them
    used = {b["booth_number"] for b in booths}
    for bn, b in layout.items():
        if bn not in used:
            booths.append(b)

    # Sessions / speakers: prefer scraped, fall back to synthetic
    real_sessions = json.loads((DATA_DIR / "sessions_real.json").read_text()) if (DATA_DIR / "sessions_real.json").exists() else []
    real_speakers = json.loads((DATA_DIR / "speakers_real.json").read_text()) if (DATA_DIR / "speakers_real.json").exists() else []

    synth_sessions = json.loads((DATA_DIR / "sessions.json").read_text()) if synth_path.exists() else []
    synth_speakers = json.loads((DATA_DIR / "speakers.json").read_text()) if (DATA_DIR / "speakers.json").exists() else []

    if real_sessions:
        sessions = real_sessions
        speakers = real_speakers
    else:
        # mark synthetic
        for s in synth_sessions: s["is_synthetic"] = True
        for s in synth_speakers: s["is_synthetic"] = True
        # re-anchor synthetic sessions to use real companies where possible
        company_pool = [ex["company"] for ex in real_exhibitors]
        for s in synth_speakers:
            if s["company"] not in company_pool and company_pool:
                # leave as-is — synthetic speakers retain synthetic affiliations
                pass
        sessions = synth_sessions
        speakers = synth_speakers

    return {
        "exhibitors": real_exhibitors,
        "booths": booths,
        "sessions": sessions,
        "speakers": speakers,
    }


def write_merged_snapshot() -> dict:
    snap = merge_real_data()
    # Backup synthetic if present
    for k in ("exhibitors", "booths", "sessions", "speakers"):
        p = DATA_DIR / f"{k}.json"
        if p.exists():
            backup = DATA_DIR / f"{k}.synth.json"
            if not backup.exists():
                backup.write_text(p.read_text())
    for k, rows in snap.items():
        (DATA_DIR / f"{k}.json").write_text(json.dumps(rows, indent=2))
        print(f"[merge] wrote {k}.json ({len(rows)})")
    return snap


if __name__ == "__main__":
    write_merged_snapshot()
