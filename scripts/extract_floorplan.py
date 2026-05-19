"""Extract a structured layout from the official TechEx PDF.

We pull *every* vector shape from the PDF, classify each by its fill color
(booth, zone, wall, amenity, etc.), and pair booth rectangles with their text
labels (number + sqft). Output: a JSON layout the frontend renders as SVG —
geometry is preserved exactly, but each class of shape has a semantic tag so
the frontend can apply its own color palette.

Output: backend/app/data/floorplan_layout.json
Also: backend/app/data/floorplan.png (3x raster for visual reference)
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parent.parent
PDF_PATH = ROOT / "backend" / "app" / "data" / "real" / "floorplan.pdf"
OUT_DIR = ROOT / "backend" / "app" / "data"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Color palette (RGB 0..1) discovered in the PDF. Classifying each shape against
# these centroids keeps the SVG geometry exact but lets us swap colors freely.
PALETTE = {
    "booth":        (0.954, 0.958, 0.961),   # ~white-gray booth fill
    "floor":        (0.864, 0.868, 0.871),   # building interior fill
    "wall_dark":    (0.011, 0.016, 0.018),   # near-black walls/outlines
    "wall_outer":   (0.641, 0.649, 0.658),   # building outer wall
    "navy":         (0.056, 0.083, 0.160),   # accent dark blue (entrance overlays, etc.)
    "yellow":       (0.995, 0.752, 0.058),   # catering / lounges / startup / featured
    "zone_ai":      (0.907, 0.109, 0.449),   # AI & Big Data pink
    "zone_cyber":   (0.927, 0.403, 0.137),   # Cyber Security orange
    "zone_iot":     (0.201, 0.775, 0.957),   # IoT Tech cyan
    "zone_edge":    (0.244, 0.725, 0.569),   # Edge Computing green
    "zone_edge2":   (0.174, 0.509, 0.517),   # Edge Computing teal
    "zone_dt":      (0.127, 0.283, 0.596),   # Digital Transformation dark blue
    "zone_dc":      (0.128, 0.283, 0.596),   # Data Center (re-used)
    "zone_ia":      (0.547, 0.266, 0.603),   # Intelligent Automation purple
    "zone_phys":    (0.902, 0.333, 0.312),   # Physical AI / AI Dev pink-red
    "white":        (1.0, 1.0, 1.0),
}

# Map color classes → semantic tags. Both "floor" (light gray) and "wall_outer"
# (slightly-darker gray) are actually building-floor fills in the PDF — the
# darker tone is just visual separation between the main hall and the entrance/
# meeting-rooms wing.  We treat both as floor.
COLOR_TO_TAG = {
    "booth": "booth",
    "floor": "floor",
    "wall_dark": "wall",
    "wall_outer": "floor",       # was "outer_wall" — these are floor extensions
    "navy": "accent_dark",
    "yellow": "amenity_yellow",
    "zone_ai": "zone_ai",
    "zone_cyber": "zone_cyber",
    "zone_iot": "zone_iot",
    "zone_edge": "zone_edge",
    "zone_edge2": "zone_edge",
    "zone_dt": "zone_dt",
    "zone_dc": "zone_dt",
    "zone_ia": "zone_ia",
    "zone_phys": "zone_phys",
    "white": "white",
}

# Zone label classification — when a text label sits inside a colored shape, use this
ZONE_LABEL_TO_TAG = [
    ("AI Developer",            "zone_phys"),
    ("AI & Big Data",           "zone_ai"),
    ("Cyber Security",          "zone_cyber"),
    ("IoT Tech",                "zone_iot"),
    ("Edge Computing",          "zone_edge"),
    ("Digital Transformation",  "zone_dt"),
    ("Data Center",             "zone_dt"),
    ("Intelligent Automation",  "zone_ia"),
    ("Physical AI",             "zone_phys"),
]

AMENITY_KEYWORDS = {
    "Catering": "catering",
    "Networking Lounge": "lounge",
    "Networking": "lounge",          # PDF wraps "Networking\nLounge"
    "Meeting Room": "meeting_room",
    "Meet Up Zone": "meetup",
    "Start Up Area": "startup",
    "Learning Lab": "learning_lab",
    "Registration": "registration",
    "ENTRANCE": "entrance",
    "Featured Exhibitors": "featured_strip",
}

BOOTH_NUMBER_RE = re.compile(r"^\d{1,3}(?:\s*/\s*\d{1,3})*$")  # 232 or 232/204/194
SQFT_RE = re.compile(r"^\d{1,4}ft²?$")


def color_distance(a, b):
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def classify_color(rgb):
    if rgb is None:
        return None
    best, best_d = None, 0.1
    for name, c in PALETTE.items():
        d = color_distance(rgb, c)
        if d < best_d:
            best_d = d
            best = name
    return best


def rect_area(r):
    return max(0, r[2] - r[0]) * max(0, r[3] - r[1])


def rect_contains(outer, inner_center):
    return outer[0] <= inner_center[0] <= outer[2] and outer[1] <= inner_center[1] <= outer[3]


def main():
    doc = pymupdf.open(PDF_PATH)
    page = doc[0]
    page_w, page_h = page.rect.width, page.rect.height
    print(f"PDF page size: {page_w:.1f} x {page_h:.1f} pt")

    # Render high-res PNG for fallback / visual reference
    pix = page.get_pixmap(matrix=pymupdf.Matrix(3, 3))
    png_path = OUT_DIR / "floorplan.png"
    pix.save(str(png_path))
    print(f"Rendered PNG -> {png_path} ({pix.width}x{pix.height})")

    # ── Vector shapes ────────────────────────────────────────────────────
    raw_shapes = []
    for d in page.get_drawings():
        rect = d.get("rect")
        if not rect:
            continue
        bbox = [rect.x0, rect.y0, rect.x1, rect.y1]
        if rect_area(bbox) < 4:
            continue
        fill = d.get("fill")
        cls = classify_color(fill) if fill else None
        items = d.get("items") or []
        # If the shape has only a single rectangle path, store as rect.
        # Otherwise serialize the path so we can render arbitrary outlines
        # (the building footprint has a complex outline).
        path = None
        if items and len(items) > 1:
            cmds = []
            for it in items:
                op = it[0]
                pts = it[1:]
                # PyMuPDF tuples: ("l", p1, p2), ("c", p1, p2, p3, p4), ("re", rect)
                if op == "re":
                    r = pts[0]
                    cmds.append({"op": "re", "rect": [r.x0, r.y0, r.x1, r.y1]})
                elif op == "l":
                    cmds.append({"op": "l", "pts": [[p.x, p.y] for p in pts]})
                elif op == "c":
                    cmds.append({"op": "c", "pts": [[p.x, p.y] for p in pts]})
                elif op == "qu":
                    cmds.append({"op": "qu", "pts": [[p.x, p.y] for p in pts]})
            path = cmds
        raw_shapes.append({
            "bbox": bbox,
            "rgb": list(fill) if fill else None,
            "tag": COLOR_TO_TAG.get(cls),
            "color_class": cls,
            "n_items": len(items),
            "path": path,
            "type": d.get("type"),
        })

    print(f"Vector shapes: {len(raw_shapes)}")
    by_tag = {}
    for s in raw_shapes:
        by_tag.setdefault(s["tag"], 0)
        by_tag[s["tag"]] += 1
    print(" by tag:", by_tag)

    # ── Text spans ───────────────────────────────────────────────────────
    raw = page.get_text("dict")
    spans = []
    for block in raw.get("blocks", []):
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                txt = span["text"].strip()
                if not txt:
                    continue
                bbox = list(span["bbox"])
                spans.append({
                    "text": txt,
                    "bbox": bbox,
                    "center": [(bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2],
                    "size": span.get("size", 0),
                })

    # ── Snap each booth-number text span directly to the gray rectangle it sits in.
    # This is more robust than pairing number+sqft (some big-booth labels live in
    # different relative positions within the rect).
    numbers = [s for s in spans if BOOTH_NUMBER_RE.match(s["text"])]
    sqfts = [s for s in spans if SQFT_RE.match(s["text"])]
    booth_rects = [s for s in raw_shapes if s["tag"] == "booth" and rect_area(s["bbox"]) < 100000]

    # Each rect can hold at most one booth-number label.
    rect_assignments: dict[int, dict] = {}
    booths = []
    for n in numbers:
        cx, cy = n["center"]
        candidates = []
        for ri, r in enumerate(booth_rects):
            if rect_contains(r["bbox"], (cx, cy)):
                candidates.append((rect_area(r["bbox"]), ri, r))
        candidates.sort()
        if not candidates:
            continue
        _, ri, r = candidates[0]
        if ri in rect_assignments:
            # already has a number — keep the longer/larger one? skip duplicate
            continue
        # find nearest sqft inside that rect, if any
        sqft_val = None
        sqft_span = None
        for sq in sqfts:
            sx, sy = sq["center"]
            if rect_contains(r["bbox"], (sx, sy)):
                sqft_span = sq
                m = re.match(r"(\d+)ft", sq["text"])
                if m: sqft_val = int(m.group(1))
                break
        b = {
            "booth_number": n["text"].replace(" ", ""),
            "bbox": list(r["bbox"]),
            "center": [(r["bbox"][0] + r["bbox"][2]) / 2, (r["bbox"][1] + r["bbox"][3]) / 2],
            "label_center": [cx, cy],
            "sqft": sqft_val,
        }
        booths.append(b)
        rect_assignments[ri] = b
        r["assigned"] = b["booth_number"]

    snapped = len(rect_assignments)
    print(f"Booth labels: {len(numbers)} -> {snapped} unique rect-snapped booths (of {len(booth_rects)} rects)")

    # ── Identify zone rectangles + their text labels ─────────────────────
    # A zone is a large colored shape with a tag starting with 'zone_'.
    zones = []
    for s in raw_shapes:
        tag = s.get("tag")
        if tag and tag.startswith("zone_") and rect_area(s["bbox"]) > 5000:
            zones.append({
                "tag": tag,
                "bbox": list(s["bbox"]),
                "rgb": s["rgb"],
                "path": s.get("path"),
                "label": None,
            })

    # Match zone labels to zone rects: find text spans whose center is inside
    for s in spans:
        for prefix, label_tag in ZONE_LABEL_TO_TAG:
            if prefix.lower() not in s["text"].lower():
                continue
            cx, cy = s["center"]
            # find the zone rect containing this label center (or closest)
            best = None
            best_d = 1e9
            for z in zones:
                if rect_contains(z["bbox"], (cx, cy)):
                    d = 0
                else:
                    zcx = (z["bbox"][0] + z["bbox"][2]) / 2
                    zcy = (z["bbox"][1] + z["bbox"][3]) / 2
                    d = (zcx - cx) ** 2 + (zcy - cy) ** 2
                if d < best_d:
                    best_d = d; best = z
            if best and (best["label"] is None or len(s["text"]) > len(best["label"])):
                best["label"] = s["text"]
                best["key"] = prefix
            break

    # ── Yellow amenity rects + their labels ──────────────────────────────
    yellow_rects = [s for s in raw_shapes if s["tag"] == "amenity_yellow"]
    amenities = []
    for s in spans:
        for kw, kind in AMENITY_KEYWORDS.items():
            if kw.lower() in s["text"].lower():
                amenities.append({
                    "kind": kind,
                    "label": s["text"],
                    "bbox": list(s["bbox"]),
                    "center": list(s["center"]),
                })
                break

    # Walls — small near-black partitions (booth dividers, room walls). We keep
    # them small (< 8000) so we don't accidentally drown the floor in a giant
    # dark fill from an outer-frame rect.
    walls = [
        {"bbox": list(s["bbox"]), "path": s.get("path")}
        for s in raw_shapes
        if s["tag"] == "wall" and 200 < rect_area(s["bbox"]) < 8000
    ]
    # Floor (big interior fills) — both light-gray and mid-gray pdf classes
    # count as floor. We unify them into the same render layer.
    floors = [
        {"bbox": list(s["bbox"]), "path": s.get("path")}
        for s in raw_shapes
        if s["tag"] == "floor" and rect_area(s["bbox"]) > 30000
    ]

    # Compute a single unified building bbox (union of all floors)
    if floors:
        bx0 = min(f["bbox"][0] for f in floors)
        by0 = min(f["bbox"][1] for f in floors)
        bx1 = max(f["bbox"][2] for f in floors)
        by1 = max(f["bbox"][3] for f in floors)
        building_bbox = [bx0, by0, bx1, by1]
    else:
        building_bbox = [0, 0, page_w, page_h]

    # Filter amenities to those actually on the floor plan. The "Featured
    # Exhibitors:" callout panel sits to the left of the building footprint and
    # is a marketing legend, not part of the navigable map — we drop it.
    def amenity_on_floor(a):
        cx, cy = a["center"]
        return (building_bbox[0] - 10 <= cx <= building_bbox[2] + 10
                and building_bbox[1] - 10 <= cy <= building_bbox[3] + 150)
    on_floor_amenities = [a for a in amenities if a["kind"] != "featured_strip" and amenity_on_floor(a)]

    # Compute a tight viewbox around just the building so the SVG doesn't have
    # huge empty margins. Add ~40pt padding.
    pad = 40
    vb = [
        max(0, building_bbox[0] - pad),
        max(0, building_bbox[1] - pad),
        min(page_w, building_bbox[2] + pad) - max(0, building_bbox[0] - pad),
        min(page_h, building_bbox[3] + pad + 80) - max(0, building_bbox[1] - pad),  # extra 80 for entrance arrows
    ]

    layout = {
        "page_size": [page_w, page_h],
        "viewbox": vb,
        "building_bbox": building_bbox,
        "booths": booths,
        "zones": zones,
        "yellow_rects": [
            {"bbox": list(s["bbox"]), "path": s.get("path")}
            for s in yellow_rects
        ],
        "amenities": on_floor_amenities,
        "walls": walls,
        "floors": floors,
        # Optional: dump all booth rects (white shapes) so the frontend can
        # draw the booth grid even for booths that don't have a number
        # (e.g. partitions or empty pods).
        "booth_rects": [
            {"bbox": list(r["bbox"]), "assigned": r.get("assigned")}
            for r in booth_rects
        ],
    }

    out = OUT_DIR / "floorplan_layout.json"
    out.write_text(json.dumps(layout, indent=2))
    print(f"Wrote -> {out}")
    print(f"  booths: {len(booths)}  zones: {len(zones)}  amenities: {len(amenities)}  walls: {len(walls)}  floors: {len(floors)}  booth_rects: {len(booth_rects)}")
    for z in zones:
        print(f"  zone[{z['tag']}] '{z.get('label')}' bbox={z['bbox']}")


if __name__ == "__main__":
    main()
