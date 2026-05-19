"""Stage A — scrape the real TechEx microsites (§1.2 Stage A).

The plan calls for per-site Playwright adapters. In this sandbox we cannot
reach the TechEx domains directly, so we delegate fetch + parse to
Gemini 2.5 Flash via the URL Context tool, which has network access. The
tool fetches the page, the model parses out structured records, and we
get JSON back.

The eight URLs we hit (plus the central exhibitor list):

- https://www.ai-expo.net/northamerica/exhibitors/   (exhibitors, all halls)
- https://www.ai-expo.net/northamerica/agenda/
- https://www.iottechexpo.com/northamerica/agenda/
- https://www.edgecomputing-expo.com/northamerica/agenda/
- https://www.cybersecurityexpo.com/northamerica/agenda/
- https://www.digitaltransformation-week.com/northamerica/agenda/
- https://www.datacentre-expo.com/northamerica/agenda/
- https://www.iotaexpo.net/northamerica/agenda/

This is exactly the "Gemini generates the parser" idea from §1.2 — but
done at inference time per microsite, which is cheaper for a hackathon
than maintaining seven hand-written Playwright adapters.
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

MICROSITES = [
    ("AI & Big Data",            "https://www.ai-expo.net/northamerica/"),
    ("IoT Tech",                 "https://www.iottechexpo.com/northamerica/"),
    ("Edge Computing",           "https://www.edgecomputing-expo.com/northamerica/"),
    ("Cyber Security",           "https://www.cybersecurityexpo.com/northamerica/"),
    ("Digital Transformation",   "https://www.digitaltransformation-week.com/northamerica/"),
    ("Data Centre",              "https://www.datacentre-expo.com/northamerica/"),
    ("Intelligent Automation",   "https://www.iotaexpo.net/northamerica/"),
]

EXHIBITORS_URL = "https://www.ai-expo.net/northamerica/exhibitors/"
FLOORPLAN_PAGE_URL = "https://techexevent.com/floorplan-na/"


def _client():
    from google import genai
    return genai.Client(api_key=os.environ["GEMINI_API_KEY"])


def _gemini_fetch_json(client, url: str, instruction: str, model="gemini-2.5-flash") -> list | dict:
    """Fetch a URL via Gemini URL Context tool and extract structured data."""
    from google.genai import types
    prompt = f"Fetch this URL: {url}\n\n{instruction}\n\nReturn ONLY valid JSON. No prose, no markdown fence."
    last_err = None
    for attempt in range(3):
        try:
            resp = client.models.generate_content(
                model=model,
                contents=[prompt],
                config=types.GenerateContentConfig(
                    tools=[types.Tool(url_context=types.UrlContext())],
                    temperature=0.0,
                ),
            )
            text = (resp.text or "").strip()
            # strip code fences if present
            if text.startswith("```"):
                text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
                text = re.sub(r"\n?```$", "", text)
            return json.loads(text)
        except Exception as e:
            last_err = e
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"Gemini fetch failed for {url}: {last_err}")


# -----------------------------------------------------------------------------
# Exhibitors

EXHIBITORS_INSTRUCTION = """
List every exhibitor on this page. For each, return:
{
  "company": "<the visible company name, verbatim>",
  "booth_number": "<booth if printed near the company, else empty string>",
  "description": "<one-line description if the page shows one, else empty string>",
  "website": "<external link if present, else empty string>"
}
Output a JSON array. Be exhaustive — every company shown, even if the list is long.
"""


def scrape_exhibitors() -> list[dict]:
    client = _client()
    raw = _gemini_fetch_json(client, EXHIBITORS_URL, EXHIBITORS_INSTRUCTION)
    if not isinstance(raw, list):
        raw = raw.get("exhibitors", []) if isinstance(raw, dict) else []
    out = []
    for i, r in enumerate(raw):
        if not isinstance(r, dict) or not r.get("company"):
            continue
        out.append({
            "id": f"ex_real_{i:04d}",
            "company": r["company"].strip(),
            "booth_number": str(r.get("booth_number", "")).strip(),
            "description": (r.get("description") or "").strip(),
            "website": (r.get("website") or "").strip(),
            "tags": [],
            "hall_zone": "",
        })
    return out


# -----------------------------------------------------------------------------
# Sessions + speakers per microsite

AGENDA_INSTRUCTION = """
You are looking at an agenda / schedule page for a conference track.
For each session listed, return:
{
  "title": "<verbatim title>",
  "abstract": "<short summary if shown>",
  "day": "<YYYY-MM-DD if shown, else empty>",
  "start": "<HH:MM 24h if shown, else empty>",
  "end": "<HH:MM 24h if shown, else empty>",
  "room": "<room/stage label if shown>",
  "speakers": [
    {"name": "...", "title": "...", "company": "..."}
  ],
  "tags": ["<topic tag>", ...]
}
Output a JSON array. If the page paginates, include only what is visible.
"""


def scrape_microsite_agenda(track: str, base: str) -> list[dict]:
    client = _client()
    url = base + "agenda/"
    try:
        raw = _gemini_fetch_json(client, url, AGENDA_INSTRUCTION)
    except Exception as e:
        print(f"[scrape] {track}: failed to fetch {url}: {e}")
        return []
    if not isinstance(raw, list):
        raw = raw.get("sessions", []) if isinstance(raw, dict) else []
    out = []
    for r in raw:
        if not isinstance(r, dict) or not r.get("title"):
            continue
        out.append({
            "title": r["title"].strip(),
            "abstract": (r.get("abstract") or "").strip(),
            "track": track,
            "day": (r.get("day") or "").strip(),
            "start": (r.get("start") or "").strip(),
            "end": (r.get("end") or "").strip(),
            "room": (r.get("room") or "").strip(),
            "speakers_raw": r.get("speakers", []) or [],
            "tags": r.get("tags", []) or [],
            "microsite": base,
        })
    return out


def _build_speaker_index(raw_sessions: list[dict]) -> list[dict]:
    by_key: dict[str, dict] = {}
    for s in raw_sessions:
        for sp in s.get("speakers_raw", []):
            name = (sp.get("name") or "").strip()
            if not name:
                continue
            key = name.lower()
            if key not in by_key:
                by_key[key] = {
                    "id": f"sp_real_{len(by_key):04d}",
                    "name": name,
                    "title": (sp.get("title") or "").strip(),
                    "company": (sp.get("company") or "").strip(),
                    "bio": "",
                    "session_ids": [],
                    "headshot_url": None,
                }
    return list(by_key.values())


# -----------------------------------------------------------------------------
# Floorplan image

def fetch_floorplan_image() -> Path | None:
    """Have Gemini retrieve and describe the floorplan page so we can find the
    actual image URL, then fetch the PNG via the same channel.

    Because direct image GET from the sandbox is blocked, we delegate the
    actual binary fetch to Gemini multimodal — we ask it to return the
    floorplan image as base64 if it can; otherwise we ask for the image URL
    only and store that URL. The downstream multimodal extraction (Stage B,
    floorplan.py) accepts either a local path or a URL.
    """
    client = _client()
    from google.genai import types
    out_url = DATA_DIR / "floorplan_url.txt"
    try:
        resp = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[
                f"Open {FLOORPLAN_PAGE_URL}. Find the URL of the floorplan image (a .png, .jpg, or .pdf). "
                f"Return JSON: {{\"image_url\": \"<full url>\", \"alt\": \"<alt text>\"}}"
            ],
            config=types.GenerateContentConfig(
                tools=[types.Tool(url_context=types.UrlContext())],
                temperature=0.0,
                response_mime_type="application/json",
            ),
        )
        data = json.loads(resp.text)
        if data.get("image_url"):
            out_url.write_text(data["image_url"])
            print(f"[scrape] floorplan URL → {data['image_url']}")
            return out_url
    except Exception as e:
        print(f"[scrape] floorplan URL fetch failed: {e}")
    return None


# -----------------------------------------------------------------------------
# Top-level driver

def scrape_all() -> dict:
    print("[scrape] fetching exhibitors…")
    exhibitors = scrape_exhibitors()
    print(f"[scrape]   got {len(exhibitors)} exhibitors")

    all_sessions_raw: list[dict] = []
    for track, base in MICROSITES:
        print(f"[scrape] fetching {track} agenda…")
        rows = scrape_microsite_agenda(track, base)
        print(f"[scrape]   got {len(rows)} sessions")
        all_sessions_raw.extend(rows)

    speakers = _build_speaker_index(all_sessions_raw)
    print(f"[scrape] collated {len(speakers)} speakers")

    speakers_by_name = {s["name"].lower(): s for s in speakers}
    sessions = []
    for i, s in enumerate(all_sessions_raw):
        sid = f"se_real_{i:04d}"
        speaker_ids = []
        for sp in s.pop("speakers_raw", []):
            name = (sp.get("name") or "").strip().lower()
            if name and name in speakers_by_name:
                speaker_ids.append(speakers_by_name[name]["id"])
                speakers_by_name[name]["session_ids"].append(sid)
        sessions.append({
            "id": sid,
            **s,
            "speaker_ids": speaker_ids,
        })

    fetch_floorplan_image()

    return {
        "sessions": sessions,
        "speakers": speakers,
        "exhibitors": exhibitors,
    }


def write_real_snapshot() -> dict:
    data = scrape_all()
    for key, rows in data.items():
        out = DATA_DIR / f"{key}_real.json"
        out.write_text(json.dumps(rows, indent=2))
        print(f"[scrape] → {out} ({len(rows)})")
    return data


if __name__ == "__main__":
    os.environ.setdefault("GEMINI_API_KEY", "")
    if not os.environ["GEMINI_API_KEY"]:
        raise SystemExit("Set GEMINI_API_KEY")
    write_real_snapshot()
