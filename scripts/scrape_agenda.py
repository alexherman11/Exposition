"""Scrape real TechEx NA 2026 sessions + speakers from the public agenda pages.

No Gemini key required — pages are server-rendered Elementor blocks that we
parse with httpx + BeautifulSoup directly.

Strategy:
  - Walk a known list of per-track agenda URLs (also discoverable from any
    agenda page's sidebar nav).
  - On each page, scan elementor heading widgets in document order. A session
    starts at every "HH:MM - HH:MM" heading and continues until the next time
    heading or page end. Within the session block we collect:
        * title (first heading after the time)
        * abstract (first text-editor widget, if any)
        * speakers (each post-title heading is a speaker name; the next two
          headings after it are typically their job-title and company)

Outputs:
  backend/app/data/sessions.json
  backend/app/data/speakers.json

Backs up the synthetic versions to *.synth.json on first run.

Run:
  python scripts/scrape_agenda.py            # scrape everything
  python scripts/scrape_agenda.py --quick    # just the AI Strategy track (smoke test)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "backend" / "app" / "data"

TRACK_URLS = [
    # AI & Big Data Expo — both days
    ("AI & Big Data", "2026-05-18", "https://www.ai-expo.net/northamerica/agenda/ai-strategy-autonomous-intelligence-enterprise-transformation/"),
    ("AI & Big Data", "2026-05-18", "https://www.ai-expo.net/northamerica/agenda/data-at-scale-platforms-pipelines-value-extraction/"),
    ("AI & Big Data", "2026-05-18", "https://www.ai-expo.net/northamerica/agenda/data-platforms-systems/"),
    ("AI & Big Data", "2026-05-18", "https://www.ai-expo.net/northamerica/agenda/ai-big-data-headliners/"),
    ("AI & Big Data", "2026-05-19", "https://www.ai-expo.net/northamerica/agenda/enterprise-ai-implementation-roi/"),
    ("AI & Big Data", "2026-05-19", "https://www.ai-expo.net/northamerica/agenda/future-of-ai/"),
    ("AI Developer",  "2026-05-19", "https://www.ai-expo.net/northamerica/agenda/ai-developer-conference-from-prototype-to-production/"),
    ("Physical AI",   "2026-05-19", "https://www.ai-expo.net/northamerica/agenda/physical-ai/"),
    # IoT Tech
    ("IoT Tech",      "2026-05-18", "https://www.iottechexpo.com/northamerica/agenda/edge-computing-iot/"),
    ("IoT Tech",      "2026-05-18", "https://www.iottechexpo.com/northamerica/agenda/embedded-systems-in-action/"),
    ("IoT Tech",      "2026-05-19", "https://www.iottechexpo.com/northamerica/agenda/industrial-iot-industry-4-0/"),
    ("IoT Tech",      "2026-05-19", "https://www.iottechexpo.com/northamerica/agenda/iot-security-digital-twins/"),
    ("IoT Tech",      "2026-05-19", "https://www.iottechexpo.com/northamerica/agenda/physical-ai/"),
    # Edge Computing
    ("Edge Computing","2026-05-18", "https://edgecomputing-expo.com/northamerica/agenda/edge-computing-and-aiot/"),
    ("Edge Computing","2026-05-18", "https://edgecomputing-expo.com/northamerica/agenda/connectivity-infrastructure-and-iot-security/"),
    ("Edge Computing","2026-05-19", "https://edgecomputing-expo.com/northamerica/agenda/industrial-iot-and-digital-twins/"),
    ("Edge Computing","2026-05-19", "https://edgecomputing-expo.com/northamerica/agenda/embedded-systems-in-action/"),
    # Cyber Security & Cloud
    ("Cyber Security","2026-05-18", "https://www.cybersecuritycloudexpo.com/northamerica/agenda/agenda-north-america-2026-cloud-ai-the-future-of-cyber-defense/"),
    ("Cyber Security","2026-05-19", "https://www.cybersecuritycloudexpo.com/northamerica/agenda/agenda-north-america-2026-cybersecurity-leadership-enterprise-risk/"),
    # Digital Transformation
    ("Digital Transformation","2026-05-18","https://www.digitaltransformation-week.com/northamerica/agenda/digital-transformation-in-action/"),
    ("Digital Transformation","2026-05-19","https://www.digitaltransformation-week.com/northamerica/agenda/human-centered-approaches-to-dtx/"),
    # Intelligent Automation
    ("Intelligent Automation","2026-05-18","https://intelligentautomation-conference.com/northamerica/agenda/intelligent-automation-efficiency-human-ia-collaboration/"),
    ("Intelligent Automation","2026-05-19","https://intelligentautomation-conference.com/northamerica/agenda/physical-ai/"),
    # Data Centre
    ("Data Centre",   "2026-05-18", "https://datacentrecongress.com/northamerica/agenda/green-investment-digital-innovation-and-physical-infrastructure/"),
    ("Data Centre",   "2026-05-19", "https://datacentrecongress.com/northamerica/agenda/techex-north-america-expo-center/"),
    # Learning Hub
    ("Learning Hub",  "2026-05-18", "https://techexevent.com/agenda/techex-learning-hub-day-one-day-two/"),
]

TIME_RE = re.compile(r"^\s*(\d{1,2}):(\d{2})\s*[-–—]\s*(\d{1,2}):(\d{2})\s*$")
ROOM_HINT_RE = re.compile(r"(theatre|theater|hall|stage|room|workshop|lab|lounge)\b", re.I)


def _stable_id(prefix: str, *parts: str) -> str:
    h = hashlib.sha1("|".join(p.strip().lower() for p in parts).encode("utf-8")).hexdigest()[:10]
    return f"{prefix}_{h}"


def _normalize(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").replace("’", "'").replace("—", "—")).strip()


def fetch(url: str) -> BeautifulSoup | None:
    try:
        r = httpx.get(url, timeout=30, headers={"user-agent": "Mozilla/5.0 (compatible; ExpoConcierge/1.0)"}, follow_redirects=True)
        if r.status_code != 200:
            print(f"[scrape] {url}: HTTP {r.status_code}")
            return None
        return BeautifulSoup(r.text, "lxml")
    except Exception as e:
        print(f"[scrape] {url}: {e}")
        return None


def _widgets_in_order(soup: BeautifulSoup) -> list[tuple[str, str]]:
    """Return (kind, text) for every elementor widget in document order.

    kind ∈ {time, heading, text}
    """
    out = []
    for w in soup.select(".elementor-widget"):
        classes = " ".join(w.get("class", []))
        text = _normalize(w.get_text(" ", strip=True))
        if not text:
            continue
        if "elementor-widget-heading" in classes:
            if TIME_RE.match(text):
                out.append(("time", text))
            else:
                out.append(("heading", text))
        elif "elementor-widget-text-editor" in classes:
            out.append(("text", text))
    return out


def parse_track_page(track: str, day: str, url: str) -> tuple[list[dict], list[dict]]:
    soup = fetch(url)
    if not soup:
        return [], []
    page_title = soup.title.string if soup.title else url
    print(f"[scrape] {track} / {urlparse(url).path}: page title = {page_title!r}")

    widgets = _widgets_in_order(soup)

    # Find the "agenda body" by trimming to the first time widget and onward
    first_time = next((i for i, (k, _) in enumerate(widgets) if k == "time"), -1)
    if first_time < 0:
        print(f"  no sessions found on {url}")
        return [], []
    widgets = widgets[first_time:]

    # Split into session blocks by time markers
    sessions_raw = []
    current = None
    for kind, text in widgets:
        if kind == "time":
            if current:
                sessions_raw.append(current)
            current = {"time": text, "headings": [], "texts": []}
        elif current is not None:
            if kind == "heading":
                current["headings"].append(text)
            else:
                current["texts"].append(text)
    if current:
        sessions_raw.append(current)

    sessions: list[dict] = []
    speakers_by_key: dict[str, dict] = {}

    for raw in sessions_raw:
        m = TIME_RE.match(raw["time"])
        if not m:
            continue
        sh, sm, eh, em = (int(g) for g in m.groups())
        # 1pm–5pm sessions are written like "1:20" with no AM/PM. Promote to 24h.
        if sh < 8 and sh != 12:
            sh += 12
        if eh < 8 and eh != 12:
            eh += 12
        start_t = f"{sh:02d}:{sm:02d}"
        end_t = f"{eh:02d}:{em:02d}"

        if not raw["headings"]:
            continue
        title = raw["headings"][0]
        # Skip "Chairperson's Opening Remarks", page-headers etc? keep them — they're real.
        abstract = raw["texts"][0] if raw["texts"] else ""

        # Speakers: any remaining headings come in groups of (name, title, company).
        # We don't always have all three; chunk in 3s but tolerate stragglers.
        speaker_blocks = raw["headings"][1:]
        # Skip room-hint heading if present
        room = ""
        if speaker_blocks and ROOM_HINT_RE.search(speaker_blocks[0]) and len(speaker_blocks[0]) < 60:
            room = speaker_blocks.pop(0)

        speaker_ids = []
        i = 0
        while i < len(speaker_blocks):
            name = speaker_blocks[i]
            job = speaker_blocks[i + 1] if i + 1 < len(speaker_blocks) else ""
            company = speaker_blocks[i + 2] if i + 2 < len(speaker_blocks) else ""
            i += 3
            if not name or len(name) > 80:
                continue
            # Heuristic: real names contain a space and aren't long sentences
            if " " not in name or name.endswith("?") or name.endswith(":"):
                continue
            key = (name + "|" + company).lower()
            if key not in speakers_by_key:
                sid = _stable_id("sp", name, company)
                speakers_by_key[key] = {
                    "id": sid,
                    "name": name,
                    "title": job,
                    "company": company,
                    "bio": "",
                    "session_ids": [],
                    "headshot_url": None,
                }
            speaker_ids.append(speakers_by_key[key]["id"])

        sid_session = _stable_id("se", title, day, start_t, track)
        for spk_id in speaker_ids:
            for sp in speakers_by_key.values():
                if sp["id"] == spk_id:
                    if sid_session not in sp["session_ids"]:
                        sp["session_ids"].append(sid_session)
        sessions.append({
            "id": sid_session,
            "title": title,
            "abstract": abstract,
            "track": track,
            "day": day,
            "start": start_t,
            "end": end_t,
            "room": room,
            "speaker_ids": speaker_ids,
            "tags": _infer_tags(title + " " + abstract),
            "microsite": urlparse(url).netloc,
        })

    print(f"  -> {len(sessions)} sessions, {len(speakers_by_key)} speakers")
    return sessions, list(speakers_by_key.values())


def _infer_tags(text: str) -> list[str]:
    t = (text or "").lower()
    rules = {
        "agents": ["agent", "agentic", "autonom"],
        "llm": ["llm", "large language", "foundation model", "generative ai"],
        "rag": ["rag", "retrieval", "vector"],
        "iot": ["iot", "internet of things"],
        "lora": ["lora", "lorawan"],
        "edge ai": ["edge ai", "edge inference", "on-device", "tinyml"],
        "cybersecurity": ["security", "threat", "zero trust", "siem"],
        "post-quantum": ["post-quantum", "pqc", "quantum-safe"],
        "data center": ["data center", "data centre", "cooling", "hpc"],
        "robotics": ["robot", "physical ai"],
        "data platform": ["data platform", "lakehouse", "warehouse"],
        "automation": ["automation", "rpa", "workflow"],
        "industrial": ["industrial", "manufacturing", "scada"],
        "embedded": ["embedded", "cortex", "microcontroller"],
        "5g": ["5g", "private network"],
    }
    tags = []
    for k, terms in rules.items():
        if any(p in t for p in terms):
            tags.append(k)
    return tags[:6]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="Only scrape the first track (smoke test)")
    args = ap.parse_args()

    targets = TRACK_URLS[:1] if args.quick else TRACK_URLS

    all_sessions: list[dict] = []
    all_speakers: dict[str, dict] = {}

    for track, day, url in targets:
        sessions, speakers = parse_track_page(track, day, url)
        all_sessions.extend(sessions)
        for sp in speakers:
            if sp["id"] not in all_speakers:
                all_speakers[sp["id"]] = sp
            else:
                # merge session_ids
                merged = list({*all_speakers[sp["id"]]["session_ids"], *sp["session_ids"]})
                all_speakers[sp["id"]]["session_ids"] = merged
        time.sleep(0.5)  # be polite

    # Backup synthetic versions
    for k in ("sessions", "speakers"):
        p = DATA / f"{k}.json"
        if p.exists() and not (DATA / f"{k}.synth.json").exists():
            (DATA / f"{k}.synth.json").write_text(p.read_text())

    (DATA / "sessions.json").write_text(json.dumps(all_sessions, indent=2))
    (DATA / "speakers.json").write_text(json.dumps(list(all_speakers.values()), indent=2))
    print()
    print(f"[scrape] DONE. {len(all_sessions)} sessions, {len(all_speakers)} unique speakers across {len(targets)} tracks.")
    print(f"[scrape] Written -> {DATA / 'sessions.json'}")
    print(f"[scrape] Written -> {DATA / 'speakers.json'}")


if __name__ == "__main__":
    main()
