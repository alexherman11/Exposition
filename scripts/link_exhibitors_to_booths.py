"""Replace the synthetic booth grid in `booths.json` with real PDF coords,
joined to real exhibitor data by booth number.

After this runs, every booth in booths.json carries its actual PDF position
and (if a real exhibitor uses that booth) the exhibitor_id link.

Backs up the old synthetic file once to booths.synth.json.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "backend" / "app" / "data"


def zone_for_position(layout, cx, cy):
    """Find which zone (if any) the booth center lies within."""
    for z in layout["zones"]:
        x0, y0, x1, y1 = z["bbox"]
        if x0 <= cx <= x1 and y0 <= cy <= y1:
            return z.get("label") or z.get("tag")
    return ""


def main():
    layout = json.loads((DATA / "floorplan_layout.json").read_text())
    exhibitors = json.loads((DATA / "exhibitors.json").read_text())

    booths_synth = DATA / "booths.json"
    if booths_synth.exists() and not (DATA / "booths.synth.json").exists():
        (DATA / "booths.synth.json").write_text(booths_synth.read_text())

    # Index exhibitors by booth number (and by each component of composite "232 / 204 / 194")
    ex_by_booth: dict[str, dict] = {}
    for ex in exhibitors:
        bn = (ex.get("booth_number") or "").strip()
        if not bn:
            continue
        ex_by_booth[bn] = ex
        for piece in re.split(r"\s*[/,]\s*", bn):
            piece = piece.strip()
            if piece:
                ex_by_booth.setdefault(piece, ex)

    booths_out = []
    matched = 0
    for b in layout["booths"]:
        bn = b["booth_number"]
        cx, cy = b["center"]
        ex = ex_by_booth.get(bn)
        zone_label = zone_for_position(layout, cx, cy)
        # If no zone, fall back to hall classification by position
        if not zone_label:
            if cy < 400:
                zone_label = "Main floor — north"
            elif cy < 700:
                zone_label = "Main floor — center"
            else:
                zone_label = "Main floor — south"
        rec = {
            "booth_number": bn,
            "bbox": b["bbox"],
            "center": b["center"],
            "hall_zone": zone_label,
            "exhibitor_id": ex["id"] if ex else None,
            "sqft": b.get("sqft"),
        }
        booths_out.append(rec)
        if ex:
            matched += 1
            ex["hall_zone"] = zone_label

    # Sort by booth number numerically when possible
    def key(b):
        m = re.match(r"(\d+)", b["booth_number"])
        return (0, int(m.group(1))) if m else (1, b["booth_number"])
    booths_out.sort(key=key)

    (DATA / "booths.json").write_text(json.dumps(booths_out, indent=2))
    (DATA / "exhibitors.json").write_text(json.dumps(exhibitors, indent=2))

    print(f"booths written: {len(booths_out)}")
    print(f"booths linked to a real exhibitor: {matched}")
    print(f"exhibitors total: {len(exhibitors)}")


if __name__ == "__main__":
    main()
