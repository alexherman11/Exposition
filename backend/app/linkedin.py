"""LinkedIn CSV connections graph (§4.8).

The official LinkedIn API does not expose connections, but the user can
export their `Connections.csv` from linkedin.com/mypreferences/d/download-my-data.

We parse it into a tiny per-user graph keyed on company name. The agent
calls `who_do_i_know_at(company)` to answer "who do I know there?"
"""

from __future__ import annotations

import csv
import io
from typing import Iterable


def parse_connections_csv(raw: bytes | str) -> list[dict]:
    """LinkedIn ships a CSV that starts with a few "Notes:" lines, then the
    real header. Skip until we find the header row."""
    if isinstance(raw, bytes):
        text = raw.decode("utf-8", errors="replace")
    else:
        text = raw
    lines = text.splitlines()
    # find the header
    start = 0
    for i, line in enumerate(lines):
        if "First Name" in line and "Last Name" in line:
            start = i
            break
    reader = csv.DictReader(lines[start:])
    out = []
    for row in reader:
        first = (row.get("First Name") or "").strip()
        last = (row.get("Last Name") or "").strip()
        if not (first or last):
            continue
        out.append({
            "name": f"{first} {last}".strip(),
            "title": (row.get("Position") or "").strip(),
            "company": (row.get("Company") or "").strip(),
            "url": (row.get("URL") or "").strip(),
            "connected_on": (row.get("Connected On") or "").strip(),
        })
    return out


def index_by_company(connections: list[dict]) -> dict[str, list[dict]]:
    by_co: dict[str, list[dict]] = {}
    for c in connections:
        if not c.get("company"):
            continue
        key = c["company"].lower().strip()
        by_co.setdefault(key, []).append(c)
    return by_co


def who_at(connections: list[dict], company: str) -> list[dict]:
    company_lc = company.lower().strip()
    out = []
    for c in connections:
        co = c.get("company", "").lower()
        if not co:
            continue
        if co == company_lc or company_lc in co or co in company_lc:
            out.append(c)
    return out
