"""Floorplan extraction (§1.2 Stage B).

Two paths:

  1. `render_demo_floorplan(...)` — renders an opinionated SVG/PNG floorplan
     from the booth coordinate table. Used as the canonical base image
     the SVG overlay sits on top of.

  2. `extract_with_gemini(image_path)` — the real multimodal call to
     Gemini 2.5 Pro that reads booth coords out of an arbitrary
     floorplan image. The plan's intended production path.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
WIDTH, HEIGHT = 1600, 1000

# Subtler hall palette — deeper backdrops, vivid edges
HALL_STYLE = {
    "Hall A — AI":         {"fill": "#0c1430", "edge": "#3a8df0", "accent": "#9fbfff", "tag": "AI"},
    "Hall B — IoT/Edge":   {"fill": "#0b1d2e", "edge": "#22d3a6", "accent": "#a5f3da", "tag": "IoT/Edge"},
    "Hall C — Cyber":      {"fill": "#1d0b21", "edge": "#e879b3", "accent": "#f4c1de", "tag": "Cyber"},
    "Hall D — Data Center":{"fill": "#1f1505", "edge": "#f0a050", "accent": "#f7d0a0", "tag": "Data Center"},
}


def _try_font(size: int, bold=False):
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ]
    for c in candidates:
        try:
            return ImageFont.truetype(c, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _truncate(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def render_demo_floorplan(out_path: Path | None = None) -> Path:
    out_path = out_path or (DATA_DIR / "floorplan.png")
    with open(DATA_DIR / "booths.json") as f:
        booths = json.load(f)
    with open(DATA_DIR / "exhibitors.json") as f:
        exhibitors = {e["id"]: e for e in json.load(f)}

    # Background gradient (soft, dark)
    img = Image.new("RGB", (WIDTH, HEIGHT), "#05071a")
    d = ImageDraw.Draw(img, "RGBA")
    # subtle radial glow centers per hall
    for cy, color in [(220, (40, 90, 200, 18)), (220 + 500, (220, 140, 50, 14)), (220, (40, 200, 160, 14)), (720, (220, 100, 180, 12))]:
        d.ellipse([0, cy-220, 1600, cy+220], fill=color)

    # Aisle grid (very subtle)
    for x in range(0, WIDTH, 40):
        d.line([(x, 60), (x, HEIGHT-30)], fill=(20, 28, 60, 80), width=1)
    for y in range(60, HEIGHT-30, 40):
        d.line([(0, y), (WIDTH, y)], fill=(20, 28, 60, 80), width=1)

    f_title = _try_font(28, bold=True)
    f_sub = _try_font(13)
    f_zone = _try_font(18, bold=True)
    f_zone_sub = _try_font(11)
    f_booth = _try_font(10, bold=True)
    f_name = _try_font(10)

    # Title bar
    d.rectangle([0, 0, WIDTH, 52], fill=(8, 10, 28, 240))
    d.text((24, 12), "TechEx North America 2026 · Floorplan", fill="#e6e8f5", font=f_title)
    d.text((24, 38), "San Jose McEnery Convention Center · May 18–19", fill="#8e95b8", font=f_sub)
    # legend on right
    d.text((WIDTH-280, 14), "● populated   ○ open booth", fill="#8e95b8", font=f_sub)
    d.text((WIDTH-280, 32), "─ aisle      ▢ hall zone", fill="#8e95b8", font=f_sub)

    # Hall backdrops (compute from booth groupings)
    by_zone = {}
    for b in booths:
        by_zone.setdefault(b["hall_zone"], []).append(b)
    for zone, rows in by_zone.items():
        xs = [r["bbox"][0] for r in rows] + [r["bbox"][2] for r in rows]
        ys = [r["bbox"][1] for r in rows] + [r["bbox"][3] for r in rows]
        pad = 14
        rect = [min(xs) - pad, min(ys) - pad - 22, max(xs) + pad, max(ys) + pad]
        style = HALL_STYLE.get(zone, {"fill": "#101a36", "edge": "#445", "accent": "#aab"})
        d.rounded_rectangle(rect, radius=14, fill=style["fill"], outline=style["edge"], width=2)
        # zone label tab
        tab = [rect[0] + 10, rect[1] - 18, rect[0] + 220, rect[1] + 4]
        d.rounded_rectangle(tab, radius=6, fill=style["edge"])
        d.text((tab[0] + 10, tab[1] + 3), zone, fill="#0a0e1f", font=f_zone)

    # Booths
    for b in booths:
        x1, y1, x2, y2 = b["bbox"]
        zone = b["hall_zone"]
        style = HALL_STYLE.get(zone, {"fill": "#1f2937", "edge": "#94a3b8", "accent": "#cbd5f5"})
        if b.get("exhibitor_id"):
            d.rounded_rectangle([x1, y1, x2, y2], radius=4, fill=(30, 40, 70, 240), outline=style["accent"], width=1)
            ex = exhibitors[b["exhibitor_id"]]
            d.text((x1 + 4, y1 + 2), b["booth_number"], fill="#cbd5f5", font=f_booth)
            d.text((x1 + 4, y1 + 14), _truncate(ex["company"], 18), fill="#e6e8f5", font=f_name)
        else:
            d.rounded_rectangle([x1, y1, x2, y2], radius=4, fill=(15, 20, 40, 200), outline=(80, 90, 130, 180), width=1)
            d.text((x1 + 4, y1 + 2), b["booth_number"], fill="#5a608a", font=f_booth)

    # Compass + scale
    cx, cy = WIDTH - 80, HEIGHT - 60
    d.ellipse([cx-20, cy-20, cx+20, cy+20], outline="#475569", width=1)
    d.text((cx-5, cy-30), "N", fill="#cbd5f5", font=_try_font(12, bold=True))
    d.line([(cx, cy), (cx, cy-14)], fill="#cbd5f5", width=2)

    img = img.filter(ImageFilter.SMOOTH)
    img.save(out_path, optimize=True)
    print(f"Rendered floorplan → {out_path}")
    return out_path


def extract_with_gemini(image_path: Path | str) -> list[dict]:
    """Call Gemini 2.5 Pro to extract booth coordinates from a floorplan."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("Set GEMINI_API_KEY")
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
    with open(image_path, "rb") as f:
        img_bytes = f.read()

    prompt = """You are looking at a numbered exhibition floorplan.

Return a JSON array. For EVERY numbered booth rectangle, emit:
{
  "booth_number": "<the printed number>",
  "bbox": [x1, y1, x2, y2],
  "center": [cx, cy],
  "hall_zone": "<the hall label this booth sits inside>"
}

Be exhaustive. Use the image's pixel coordinate system.
"""
    response = client.models.generate_content(
        model="gemini-2.5-pro",
        contents=[
            types.Part.from_bytes(data=img_bytes, mime_type="image/png"),
            prompt,
        ],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.0,
        ),
    )
    return json.loads(response.text)


if __name__ == "__main__":
    render_demo_floorplan()
