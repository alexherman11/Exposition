"""Produce visual reference mockups of each app pane using the live data.

We can't run a headless browser in this sandbox, so this is a server-side
faithful render: same data, same color tokens, same layout proportions
as the real PWA. Saves PNGs to /home/user/Exposition/screenshots/.
"""

from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "backend" / "app" / "data"
OUT_DIR = ROOT / "screenshots"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Color tokens — same as css/app.css :root
C = {
    "bg_0": "#060818",
    "bg_1": "#0a0e1f",
    "bg_2": "#11162e",
    "bg_3": "#1a2042",
    "line": "#1f2547",
    "line2": "#2a3164",
    "text": "#e6e8f5",
    "text_mute": "#8e95b8",
    "text_dim": "#5a608a",
    "accent": "#38e1c4",
    "accent2": "#6f6cff",
    "warm": "#f7c66a",
    "pink": "#f472b6",
    "green": "#34d399",
    "you": "#4cc4ff",
    "plan": "#a78bfa",
    "match": "#5ee2c7",
}


def font(size, bold=False):
    path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default()


def text_w(d, s, f):
    bbox = d.textbbox((0, 0), s, font=f)
    return bbox[2] - bbox[0]


def gradient_bg(w, h):
    img = Image.new("RGB", (w, h), C["bg_0"])
    d = ImageDraw.Draw(img, "RGBA")
    d.ellipse([-300, -300, 700, 500], fill=(56, 225, 196, 22))
    d.ellipse([w-700, -200, w+200, 500], fill=(111, 108, 255, 28))
    d.ellipse([w/2-500, h-200, w/2+500, h+300], fill=(247, 198, 106, 14))
    return img


def draw_topbar(d, w, h=64):
    d.rectangle([0, 0, w, h], fill=C["bg_1"])
    d.line([0, h, w, h], fill=C["line"])
    # brand
    d.rounded_rectangle([20, 14, 56, 50], radius=10, fill=(0, 0, 0))
    g = ImageDraw.Draw(Image.new("RGB", (50, 50), C["bg_1"]))
    d.rounded_rectangle([22, 16, 54, 48], radius=8, fill=C["accent"])
    d.rounded_rectangle([28, 24, 52, 46], radius=6, fill=C["accent2"])
    d.rounded_rectangle([34, 30, 50, 44], radius=4, fill=C["warm"])
    d.text((68, 16), "Expo Concierge", fill=C["text"], font=font(14, bold=True))
    d.text((68, 36), "TechEx NA 2026 · San Jose · May 18–19", fill=C["text_mute"], font=font(10))
    # view pill (center)
    pill_w = 300
    px = (w - pill_w) // 2
    d.rounded_rectangle([px, 16, px + pill_w, 48], radius=16, fill=C["bg_2"], outline=C["line"])
    seg = pill_w // 3
    return px, seg


def draw_topbar_with_active(d, w, active="chat"):
    px, seg = draw_topbar(d, w)
    labels = ["Chat", "Map", "Schedule"]
    for i, lab in enumerate(labels):
        x0 = px + i * seg + 4
        y0 = 20
        x1 = x0 + seg - 8
        y1 = 44
        if lab.lower() == active:
            d.rounded_rectangle([x0, y0, x1, y1], radius=12, fill=C["bg_3"], outline=C["line2"])
            fill = C["text"]
        else:
            fill = C["text_mute"]
        tw = text_w(d, lab, font(12, bold=True))
        d.text((x0 + (seg - 8 - tw) / 2, 24), lab, fill=fill, font=font(12, bold=True))
    # user pill (right)
    d.ellipse([w - 220, 18, w - 188, 50], fill=C["accent2"])
    d.text((w - 213, 26), "A", fill=C["bg_0"], font=font(13, bold=True))
    d.text((w - 178, 18), "Alex Park", fill=C["text"], font=font(12, bold=True))
    d.text((w - 178, 34), "LoRa IoT · edge compute · cooling ✏", fill=C["text_mute"], font=font(10))


# ─── Chat view ─────────────────────────────────────────────────────────
def render_chat_view(w=1280, h=820):
    img = gradient_bg(w, h)
    d = ImageDraw.Draw(img, "RGBA")
    draw_topbar_with_active(d, w, active="chat")

    # Chat column (left, 460 wide) + content placeholder on right
    chat_w = 460
    d.rectangle([0, 64, chat_w, h], fill=(10, 14, 31, 220))
    d.rectangle([chat_w, 64, w, h], fill=(8, 12, 26, 200))
    d.line([chat_w, 64, chat_w, h], fill=C["line"])

    # WELCOME CARD (in left column)
    cy = 90
    d.rounded_rectangle([18, cy, chat_w-18, cy+200], radius=18, fill=C["bg_2"], outline=C["line"])
    d.text((34, cy+18), "Hi Alex — welcome to TechEx", fill=C["text"], font=font(18, bold=True))
    msg = "I'm your concierge. I keep your map, schedule, and conversation in sync. Try:"
    yy = cy + 50
    for line in textwrap.wrap(msg, width=46):
        d.text((34, yy), line, fill=C["text_mute"], font=font(12))
        yy += 18
    chips = ["Plan my day for LoRa IoT", "I just talked to Semtech — who's similar?", "I'm at booth B14, what's nearby?", "Recap my day"]
    cx, cy2 = 30, yy + 8
    for c in chips:
        w_c = text_w(d, c, font(11)) + 24
        if cx + w_c > chat_w - 22:
            cx = 30; cy2 += 30
        d.rounded_rectangle([cx, cy2, cx + w_c, cy2 + 26], radius=13, fill=C["bg_3"], outline=C["line2"])
        d.text((cx + 12, cy2 + 6), c, fill=C["text"], font=font(11))
        cx += w_c + 8

    # USER MESSAGE
    msg_y = cy + 240
    txt = "I'm at the IBM booth — what's nearby that's about LLMs?"
    tw = max(text_w(d, txt, font(13)) + 28, 200)
    d.rounded_rectangle([chat_w - 30 - tw, msg_y, chat_w - 18, msg_y + 36], radius=14, fill=C["bg_3"], outline=C["line2"])
    d.text((chat_w - 30 - tw + 14, msg_y + 10), txt, fill=C["text"], font=font(13))

    # AGENT BUBBLE (with tool pills)
    msg_y += 56
    # tool pills
    pills = [
        ("✓ You're at 297 · IBM", "done"),
        ("✓ 4 nearby matched", "done"),
    ]
    px = 18
    for label, state in pills:
        w_p = text_w(d, label, font(11)) + 28
        d.rounded_rectangle([px, msg_y, px + w_p, msg_y + 24], radius=12, fill=(56, 225, 196, 30), outline=(56, 225, 196, 80))
        d.ellipse([px + 8, msg_y + 9, px + 14, msg_y + 15], fill=C["green"])
        d.text((px + 18, msg_y + 6), label[2:], fill=C["text"], font=font(11))
        px += w_p + 6
    msg_y += 32
    bubble_h = 130
    d.rounded_rectangle([18, msg_y, chat_w - 50, msg_y + bubble_h], radius=14, fill=C["bg_2"], outline=C["line"])
    agent_text = "You're at IBM (Booth 297, Hall D). Two LLM-adjacent booths are within a 5-min walk:\n\n• Workato (Booth 230) — agent workflows\n• Pinecone (Booth 268) — vector DB + RAG\n\nI've highlighted them on the map and drawn a walking line. Want me to add one to your schedule?"
    yy = msg_y + 12
    for line in textwrap.wrap(agent_text, width=42):
        if line == "":
            yy += 6; continue
        d.text((34, yy), line, fill=C["text"], font=font(12))
        yy += 16

    # input
    d.line([0, h - 60, chat_w, h - 60], fill=C["line"])
    d.rounded_rectangle([18, h - 48, chat_w - 60, h - 16], radius=16, fill=C["bg_2"], outline=C["line2"])
    d.text((34, h - 38), "Ask anything about the show…", fill=C["text_dim"], font=font(12))
    d.ellipse([chat_w - 48, h - 48, chat_w - 16, h - 16], fill=C["accent"])
    d.polygon([(chat_w - 38, h - 38), (chat_w - 24, h - 32), (chat_w - 38, h - 26)], fill=C["bg_0"])

    # RIGHT side: map preview
    draw_minimap(d, chat_w + 14, 90, w - chat_w - 28, h - 130)
    return img


def draw_minimap(d, x, y, w, h):
    """Compact map with you-are-here + nearby highlights at IBM."""
    booths = json.loads((DATA_DIR / "booths.json").read_text())
    exhibitors = {e["id"]: e for e in json.loads((DATA_DIR / "exhibitors.json").read_text())}

    d.rounded_rectangle([x, y, x + w, y + h], radius=16, fill=C["bg_1"], outline=C["line"])
    d.text((x + 16, y + 14), "Live map", fill=C["text"], font=font(14, bold=True))
    d.text((x + 16, y + 32), "agent-driven highlights", fill=C["text_mute"], font=font(10))

    # legend
    items = [("● You", C["you"]), ("○ Plan", C["plan"]), ("● Focus", C["accent"]), ("● Match", C["match"])]
    lx = x + w - 270
    for label, color in items:
        d.ellipse([lx, y + 22, lx + 10, y + 32], fill=color)
        d.text((lx + 14, y + 22), label[2:], fill=C["text_mute"], font=font(10))
        lx += 66

    inner_y = y + 56
    inner_h = h - 72
    # scale 1600x1000 to inner box
    sx = w / 1600
    sy = inner_h / 1000

    # hall backdrops simplified
    halls = {}
    for b in booths:
        halls.setdefault(b["hall_zone"], []).append(b)
    hall_colors = {"Hall A — AI": "#0c1430", "Hall B — IoT/Edge": "#0b1d2e", "Hall D — Data Center": "#1f1505", "Hall C — Cyber": "#1d0b21"}
    hall_edges = {"Hall A — AI": "#3a8df0", "Hall B — IoT/Edge": "#22d3a6", "Hall D — Data Center": "#f0a050", "Hall C — Cyber": "#e879b3"}
    for hz, rows in halls.items():
        xs = [r["bbox"][0] for r in rows] + [r["bbox"][2] for r in rows]
        ys = [r["bbox"][1] for r in rows] + [r["bbox"][3] for r in rows]
        pad = 8
        rect = [x + (min(xs) - pad) * sx, inner_y + (min(ys) - pad) * sy, x + (max(xs) + pad) * sx, inner_y + (max(ys) + pad) * sy]
        d.rounded_rectangle(rect, radius=8, fill=hall_colors.get(hz, "#0a0e1f"), outline=hall_edges.get(hz, "#445"))

    # Pick "IBM" as you-are-here
    you_booth = next((b for b in booths if exhibitors.get(b["exhibitor_id"], {}).get("company") == "IBM"), None)
    # focus = a couple nearby booths
    focus = []
    if you_booth:
        cx, cy = you_booth["center"]
        cands = sorted(booths, key=lambda b: (b["center"][0] - cx) ** 2 + (b["center"][1] - cy) ** 2)
        focus = [b for b in cands[1:4]]

    # Match interest
    interest_kw = ["llm", "agent", "iot", "lora", "edge", "rag", "vector"]
    def is_match(b):
        ex = exhibitors.get(b["exhibitor_id"])
        if not ex: return False
        t = (ex["company"] + " " + (ex.get("description") or "")).lower()
        return any(k in t for k in interest_kw)

    for b in booths:
        cx, cy = b["center"]
        px, py = x + cx * sx, inner_y + cy * sy
        if b is you_booth:
            d.ellipse([px-12, py-12, px+12, py+12], fill=(76, 196, 255, 50))
            d.ellipse([px-6, py-6, px+6, py+6], fill=C["you"], outline=C["bg_0"], width=1)
        elif b in focus:
            d.ellipse([px-10, py-10, px+10, py+10], fill=(56, 225, 196, 60))
            d.ellipse([px-5, py-5, px+5, py+5], fill=C["accent"])
        elif is_match(b):
            d.ellipse([px-4, py-4, px+4, py+4], fill=(94, 226, 199, 110))
        else:
            d.ellipse([px-2.5, py-2.5, px+2.5, py+2.5], fill=(80, 100, 150, 180))

    # walking line from you to first focus
    if you_booth and focus:
        a = you_booth["center"]; b = focus[0]["center"]
        ax, ay = x + a[0] * sx, inner_y + a[1] * sy
        bx, by = x + b[0] * sx, inner_y + b[1] * sy
        for i in range(0, 30, 3):
            t = i / 30; t2 = (i + 1.4) / 30
            d.line([ax + (bx-ax)*t, ay + (by-ay)*t, ax + (bx-ax)*t2, ay + (by-ay)*t2], fill=C["accent"], width=2)


# ─── Map view (full) ────────────────────────────────────────────────────
def render_map_view(w=1280, h=820):
    img = gradient_bg(w, h)
    d = ImageDraw.Draw(img, "RGBA")
    draw_topbar_with_active(d, w, active="map")

    chat_w = 460
    d.rectangle([0, 64, chat_w, h], fill=(10, 14, 31, 220))
    d.rectangle([chat_w, 64, w, h], fill=(8, 12, 26, 200))
    d.line([chat_w, 64, chat_w, h], fill=C["line"])

    # Tiny chat strip
    d.text((20, 80), "CONVERSATION", fill=C["text_mute"], font=font(10, bold=True))
    bubbles = [
        ("user", "I just talked to IBM — what's similar nearby with 15 minutes?"),
        ("agent_pills", "✓ Set location: 297 IBM   ✓ 6 matches"),
        ("agent", "I've put you at IBM (Booth 297, Hall D — Data Center). Within a 15-min walk I see six relevant booths. Top three: Pinecone (RAG/vectors, 268), Workato (agent workflows, 230), and Deloitte AI (cross-track AI consulting, 272). All highlighted with a walking line."),
    ]
    yy = 104
    for role, text in bubbles:
        if role == "user":
            tw = text_w(d, text, font(12)) + 28
            d.rounded_rectangle([chat_w - 18 - min(tw, 380), yy, chat_w - 18, yy + 60], radius=14, fill=C["bg_3"], outline=C["line2"])
            for line in textwrap.wrap(text, width=38)[:3]:
                d.text((chat_w - 18 - min(tw, 380) + 12, yy + 8), line, fill=C["text"], font=font(12)); yy += 18
            yy += 14
        elif role == "agent_pills":
            px = 18
            for piece in text.split("   "):
                w_p = text_w(d, piece, font(11)) + 28
                d.rounded_rectangle([px, yy, px + w_p, yy + 24], radius=12, fill=(56, 225, 196, 30), outline=(56, 225, 196, 80))
                d.ellipse([px + 8, yy + 9, px + 14, yy + 15], fill=C["green"])
                d.text((px + 18, yy + 6), piece[2:], fill=C["text"], font=font(11))
                px += w_p + 6
            yy += 32
        else:
            box_h = 8
            wrapped = textwrap.wrap(text, width=42)
            d.rounded_rectangle([18, yy, chat_w - 50, yy + 22 + 16 * len(wrapped)], radius=14, fill=C["bg_2"], outline=C["line"])
            iy = yy + 12
            for line in wrapped:
                d.text((34, iy), line, fill=C["text"], font=font(12)); iy += 16
            yy = iy + 14

    # MAP (right)
    map_x, map_y = chat_w + 1, 64
    map_w, map_h = w - chat_w - 1, h - 64
    # toolbar
    d.rectangle([map_x, map_y, w, map_y + 44], fill=C["bg_1"])
    d.line([map_x, map_y + 44, w, map_y + 44], fill=C["line"])
    items = [("● You", C["you"]), ("○ Plan", C["plan"]), ("● Focus", C["accent"]), ("● Match", C["match"]), ("● Visited", "#94a3b8")]
    lx = map_x + 20
    for label, color in items:
        d.ellipse([lx, map_y + 16, lx + 10, map_y + 26], fill=color)
        d.text((lx + 14, map_y + 14), label[2:], fill=C["text_mute"], font=font(11))
        lx += 86
    d.rounded_rectangle([w - 110, map_y + 12, w - 20, map_y + 36], radius=8, fill=C["bg_3"], outline=C["line2"])
    d.text((w - 96, map_y + 18), "Reset view", fill=C["text_mute"], font=font(11))

    # main map (use the floorplan with overlays drawn on top)
    fp = Image.open(DATA_DIR / "floorplan.png").convert("RGB")
    target_w = map_w - 40
    target_h = map_h - 80
    ratio = min(target_w / fp.width, target_h / fp.height)
    new_w, new_h = int(fp.width * ratio), int(fp.height * ratio)
    fp_resized = fp.resize((new_w, new_h), Image.LANCZOS)
    img.paste(fp_resized, (map_x + (map_w - new_w) // 2, map_y + 60))

    # overlay highlights
    ox = map_x + (map_w - new_w) // 2
    oy = map_y + 60
    booths = json.loads((DATA_DIR / "booths.json").read_text())
    exhibitors = {e["id"]: e for e in json.loads((DATA_DIR / "exhibitors.json").read_text())}
    you_booth = next((b for b in booths if exhibitors.get(b["exhibitor_id"], {}).get("company") == "IBM"), None)
    if you_booth:
        scale = new_w / 1600
        bx, by = you_booth["center"]
        px, py = ox + bx * scale, oy + by * scale
        d.ellipse([px-26, py-26, px+26, py+26], fill=(76, 196, 255, 60))
        d.ellipse([px-14, py-14, px+14, py+14], fill=(76, 196, 255, 100))
        d.ellipse([px-7, py-7, px+7, py+7], fill=C["you"], outline=C["bg_0"], width=2)
        d.text((px + 14, py - 30), "YOU · IBM", fill=C["you"], font=font(11, bold=True))
        # focus nearby
        cand = sorted([b for b in booths if b is not you_booth], key=lambda b: (b["center"][0]-bx)**2 + (b["center"][1]-by)**2)
        focus_companies = []
        for fbooth in cand[:3]:
            fx, fy = fbooth["center"]
            tx, ty = ox + fx * scale, oy + fy * scale
            # dashed line
            for i in range(0, 40, 3):
                t1 = i / 40; t2 = (i + 1.6) / 40
                d.line([px + (tx-px)*t1, py + (ty-py)*t1, px + (tx-px)*t2, py + (ty-py)*t2], fill=C["accent"], width=3)
            d.ellipse([tx-14, ty-14, tx+14, ty+14], fill=(56, 225, 196, 70))
            d.ellipse([tx-7, ty-7, tx+7, ty+7], fill=C["accent"])
            ex = exhibitors.get(fbooth["exhibitor_id"])
            if ex: focus_companies.append(ex["company"])
            d.text((tx + 14, ty - 30), (ex["company"][:18] if ex else fbooth["booth_number"]), fill=C["accent"], font=font(11, bold=True))

    return img


# ─── Schedule view ─────────────────────────────────────────────────────
def render_schedule_view(w=1280, h=820):
    img = gradient_bg(w, h)
    d = ImageDraw.Draw(img, "RGBA")
    draw_topbar_with_active(d, w, active="schedule")
    chat_w = 460
    d.rectangle([0, 64, chat_w, h], fill=(10, 14, 31, 220))
    d.rectangle([chat_w, 64, w, h], fill=(8, 12, 26, 200))
    d.line([chat_w, 64, chat_w, h], fill=C["line"])

    # left mini conversation
    d.text((20, 80), "CONVERSATION", fill=C["text_mute"], font=font(10, bold=True))
    bubbles = [
        ("user", "Plan my day for LoRa IoT"),
        ("agent_pills", "✓ Built 6-stop plan"),
        ("agent", "Here's your day across both Halls A and B. The first three sessions cluster around LoRaWAN deployment and asset tracking, and I've squeezed in a lunchtime stop at Senet's booth so you can ask about their network server. Tap any card to jump to the map."),
    ]
    yy = 104
    for role, text in bubbles:
        if role == "user":
            tw = text_w(d, text, font(12)) + 28
            d.rounded_rectangle([chat_w - 18 - tw, yy, chat_w - 18, yy + 36], radius=14, fill=C["bg_3"], outline=C["line2"])
            d.text((chat_w - 18 - tw + 14, yy + 10), text, fill=C["text"], font=font(12))
            yy += 50
        elif role == "agent_pills":
            w_p = text_w(d, text[2:], font(11)) + 28
            d.rounded_rectangle([18, yy, 18 + w_p, yy + 24], radius=12, fill=(56, 225, 196, 30), outline=(56, 225, 196, 80))
            d.ellipse([26, yy + 9, 32, yy + 15], fill=C["green"])
            d.text((36, yy + 6), text[2:], fill=C["text"], font=font(11))
            yy += 32
        else:
            wrapped = textwrap.wrap(text, width=42)
            d.rounded_rectangle([18, yy, chat_w - 50, yy + 14 + 16 * len(wrapped)], radius=14, fill=C["bg_2"], outline=C["line"])
            iy = yy + 8
            for line in wrapped:
                d.text((34, iy), line, fill=C["text"], font=font(12)); iy += 16
            yy = iy + 14

    # RIGHT: schedule timeline
    sx, sy = chat_w + 30, 100
    sw = w - chat_w - 60
    # tabs
    tabs = ["Planned", "Saved", "Attended"]
    tx = sx
    for i, t in enumerate(tabs):
        active = (i == 0)
        bg = C["bg_3"] if active else "transparent"
        border = C["line2"] if active else None
        if active:
            d.rounded_rectangle([tx, sy, tx + 90, sy + 28], radius=14, fill=bg, outline=border)
        d.text((tx + 22 + (4 if not active else 0), sy + 8), t, fill=(C["text"] if active else C["text_mute"]), font=font(11, bold=active))
        tx += 100
    sy += 50
    d.text((sx, sy), "MAY 19", fill=C["text_mute"], font=font(11, bold=True))
    sy += 22

    # cards
    cards = [
        ("09:00", "09:25", "Building agentic workflows that actually ship", "Theatre A · AI & Big Data", ["agents", "LLM"], "ai", 92),
        ("09:45", "10:25", "LoRa-based IoT at industrial scale — panel", "Hall B Stage · IoT Tech", ["LoRa", "IoT"], "iot", 97),
        ("10:45", "11:25", "TinyML on Cortex-M: a maker's tour", "Theatre B · Edge Computing", ["TinyML"], "edge", 84),
        ("12:30", "13:10", "The asset-tracking stack in 2026", "Hall B Stage · IoT Tech", ["asset tracking"], "iot", 91),
        ("14:00", "14:40", "Function-calling at scale: tool routing in agents", "Demo Stage · AI & Big Data", ["agents", "function calling"], "ai", 87),
        ("15:00", "15:25", "Liquid cooling architectures for AI training clusters", "Theatre C · Data Centre", ["cooling", "HPC"], "data", 76),
    ]
    track_color = {"ai": C["accent"], "iot": C["green"], "edge": C["warm"], "cyber": C["pink"], "data": C["accent2"]}
    prev_end = None
    for start, end, title, meta, tags, track, match in cards:
        # gap?
        if prev_end and prev_end != start:
            gap_min = (int(start[:2])*60 + int(start[3:])) - (int(prev_end[:2])*60 + int(prev_end[3:]))
            if gap_min > 8:
                d.text((sx + 72, sy + 6), f"{gap_min} min — {'fillable' if gap_min>=25 else 'tight'}", fill=C["text_dim"], font=font(11))
                sy += 24
        # time column
        d.text((sx, sy + 8), start, fill=C["text_mute"], font=font(11))
        d.text((sx, sy + 24), end, fill=C["text_dim"], font=font(9))
        # vertical line
        d.line([sx + 60, sy, sx + 60, sy + 60], fill=C["line"], width=1)
        d.ellipse([sx + 56, sy + 8, sx + 64, sy + 16], fill=track_color.get(track), outline=C["bg_0"])
        # card
        card_x = sx + 84
        card_w = sw - 100
        d.rounded_rectangle([card_x, sy, card_x + card_w, sy + 64], radius=10, fill=C["bg_2"], outline=C["line"])
        d.line([card_x, sy, card_x, sy + 64], fill=track_color.get(track), width=3)
        d.text((card_x + 14, sy + 8), title, fill=C["text"], font=font(13, bold=True))
        d.text((card_x + 14, sy + 30), meta, fill=C["text_mute"], font=font(11))
        # match badge
        m_text = f"{match}%"
        m_w = text_w(d, m_text, font(11, bold=True)) + 14
        d.rounded_rectangle([card_x + card_w - m_w - 8, sy + 8, card_x + card_w - 8, sy + 26], radius=9, fill=(56, 225, 196, 60))
        d.text((card_x + card_w - m_w - 1, sy + 10), m_text, fill=C["accent"], font=font(11, bold=True))
        # tags
        tx = card_x + 14
        for tag in tags[:3]:
            tw = text_w(d, tag, font(10)) + 16
            d.rounded_rectangle([tx, sy + 46, tx + tw, sy + 60], radius=7, fill=C["bg_3"])
            d.text((tx + 8, sy + 48), tag, fill=C["text_mute"], font=font(10))
            tx += tw + 6
        # map pin link
        d.text((card_x + card_w - 70, sy + 46), "📍 Map", fill=C["accent"], font=font(11, bold=True))
        sy += 78
        prev_end = end

    return img


def render_mobile_view(w=420, h=900):
    """Mobile (PWA) view of the chat."""
    img = gradient_bg(w, h)
    d = ImageDraw.Draw(img, "RGBA")
    # device frame
    d.rounded_rectangle([0, 0, w, h], radius=36, outline=C["line"], width=2)
    # status bar
    d.text((24, 18), "9:41", fill=C["text"], font=font(13, bold=True))
    d.text((w-70, 18), "■■■■", fill=C["text"], font=font(10))
    # top brand
    d.text((24, 50), "Expo Concierge", fill=C["text"], font=font(16, bold=True))
    d.text((24, 70), "TechEx · Day 2", fill=C["text_mute"], font=font(11))
    # view switch
    d.rounded_rectangle([24, 100, w-24, 134], radius=18, fill=C["bg_2"], outline=C["line"])
    seg = (w - 48) // 3
    for i, lab in enumerate(["Chat", "Map", "Schedule"]):
        x0 = 24 + i*seg + 4
        if i == 0:
            d.rounded_rectangle([x0, 104, x0 + seg - 8, 130], radius=14, fill=C["bg_3"], outline=C["line2"])
            d.text((x0 + (seg-8)/2 - 12, 110), lab, fill=C["text"], font=font(12, bold=True))
        else:
            d.text((x0 + (seg-8)/2 - 14, 110), lab, fill=C["text_mute"], font=font(12))

    # chat
    yy = 170
    msg_pairs = [
        ("user", "I have 30 min before my next talk"),
        ("agent_pills", "✓ Found 5 nearby"),
        ("agent", "Three matches close by: Pinecone (vector DB, 4-min walk), Workato (agents, 6-min), and Hailo (edge NPUs, 8-min). Want me to highlight a path?"),
        ("user", "yes, and add Pinecone to my schedule"),
        ("agent_pills", "✓ Highlighted path   ✓ Added Pinecone"),
        ("agent", "Done — Pinecone is on your schedule at 15:00, and I've drawn the route. Their booth has free coffee per a community note 5 min ago."),
    ]
    for role, text in msg_pairs:
        if role == "user":
            wrapped = textwrap.wrap(text, width=28)
            box_h = 16 + 16 * len(wrapped)
            tw = max(text_w(d, line, font(12)) for line in wrapped) + 24
            d.rounded_rectangle([w - 24 - tw, yy, w - 24, yy + box_h], radius=12, fill=C["bg_3"], outline=C["line2"])
            iy = yy + 8
            for line in wrapped:
                d.text((w - 24 - tw + 12, iy), line, fill=C["text"], font=font(12)); iy += 16
            yy = iy + 10
        elif role == "agent_pills":
            px = 24
            for piece in text.split("   "):
                w_p = text_w(d, piece, font(10)) + 24
                if px + w_p > w - 24:
                    px = 24; yy += 26
                d.rounded_rectangle([px, yy, px + w_p, yy + 22], radius=11, fill=(56, 225, 196, 30), outline=(56, 225, 196, 80))
                d.ellipse([px + 7, yy + 8, px + 13, yy + 14], fill=C["green"])
                d.text((px + 16, yy + 5), piece[2:], fill=C["text"], font=font(10))
                px += w_p + 5
            yy += 30
        else:
            wrapped = textwrap.wrap(text, width=30)
            box_h = 14 + 16 * len(wrapped)
            d.rounded_rectangle([24, yy, w - 50, yy + box_h], radius=12, fill=C["bg_2"], outline=C["line"])
            iy = yy + 8
            for line in wrapped:
                d.text((36, iy), line, fill=C["text"], font=font(12)); iy += 16
            yy = iy + 10

    # input
    d.rounded_rectangle([24, h - 60, w - 70, h - 28], radius=16, fill=C["bg_2"], outline=C["line2"])
    d.text((36, h - 50), "Ask anything…", fill=C["text_dim"], font=font(11))
    d.ellipse([w - 60, h - 60, w - 28, h - 28], fill=C["accent"])
    d.polygon([(w-50, h-50), (w-36, h-44), (w-50, h-38)], fill=C["bg_0"])
    return img


def main():
    chat = render_chat_view()
    chat.save(OUT_DIR / "01_chat.png", optimize=True)
    print("→ 01_chat.png")
    mp = render_map_view()
    mp.save(OUT_DIR / "02_map.png", optimize=True)
    print("→ 02_map.png")
    sc = render_schedule_view()
    sc.save(OUT_DIR / "03_schedule.png", optimize=True)
    print("→ 03_schedule.png")
    mob = render_mobile_view()
    mob.save(OUT_DIR / "04_mobile.png", optimize=True)
    print("→ 04_mobile.png")


if __name__ == "__main__":
    main()
