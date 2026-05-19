"""HTTP API endpoint tests against a running backend."""

from __future__ import annotations

import json
import time

import httpx

from .common import BACKEND_URL, Report


def run() -> Report:
    r = Report("API endpoints")
    c = httpx.Client(base_url=BACKEND_URL, timeout=30.0)

    # Core lists
    for path, min_count in [
        ("/api/booths", 200),
        ("/api/exhibitors", 200),
        ("/api/sessions", 100),
        ("/api/speakers", 100),
    ]:
        resp = c.get(path)
        if resp.status_code != 200:
            r.fail(f"GET {path}", f"status={resp.status_code}")
            continue
        d = resp.json()
        if isinstance(d, list) and len(d) >= min_count:
            r.ok(f"GET {path} -> {len(d)} items")
        else:
            r.fail(f"GET {path} too few items", f"got {len(d) if isinstance(d, list) else type(d).__name__}")

    # Floorplan layout
    resp = c.get("/api/floorplan_layout.json")
    if resp.status_code == 200:
        d = resp.json()
        for k in ("booths", "zones", "amenities", "yellow_rects", "viewbox", "building_bbox"):
            if k in d:
                r.ok(f"layout has '{k}'")
            else:
                r.fail(f"layout missing '{k}'")
    else:
        r.fail("GET /api/floorplan_layout.json", f"status={resp.status_code}")

    # Floorplan PNG
    resp = c.get("/api/floorplan.png")
    if resp.status_code == 200 and resp.headers.get("content-type", "").startswith("image/"):
        r.ok(f"GET /api/floorplan.png -> {len(resp.content)//1024}KB image")
    else:
        r.fail("GET /api/floorplan.png", f"status={resp.status_code}")

    # Profile GET (auto-creates)
    uid = f"apitest_{int(time.time())}"
    resp = c.get(f"/api/profile/{uid}")
    if resp.status_code == 200 and "user_id" in resp.json():
        r.ok(f"GET /api/profile/{uid}")
    else:
        r.fail("GET profile", resp.text[:120])

    # Profile POST update
    resp = c.post(f"/api/profile/{uid}", json={"interests": ["lora", "iot"]})
    if resp.status_code == 200 and "lora" in (resp.json().get("interests") or []):
        r.ok("POST profile interests")
    else:
        r.fail("POST profile", resp.text[:120])

    # Plan empty
    resp = c.get(f"/api/plan/{uid}")
    if resp.status_code == 200 and isinstance(resp.json(), list):
        r.ok(f"GET plan -> list (len {len(resp.json())})")
    else:
        r.fail("GET plan", resp.text[:120])

    # Annotations summary
    resp = c.get("/api/annotations/summary")
    if resp.status_code == 200 and isinstance(resp.json(), dict):
        r.ok("GET /api/annotations/summary")
    else:
        r.fail("GET annotations summary", resp.text[:120])

    # LinkedIn CSV import — small synthetic CSV
    csv = "First Name,Last Name,Company,Position\nAlex,Park,Semtech,Engineer\nKim,Lee,NVIDIA,VP\n"
    resp = c.post(f"/api/linkedin/{uid}", json={"csv": csv})
    if resp.status_code == 200 and resp.json().get("imported") == 2:
        r.ok("POST linkedin csv (2 imported)")
    else:
        r.fail("POST linkedin", resp.text[:120])

    # Tools via REST
    resp = c.post("/api/tool/search_entities", json={"user_id": uid, "query": "iot", "k": 3})
    if resp.status_code == 200 and len(resp.json().get("results", [])) > 0:
        r.ok("POST /api/tool/search_entities returned hits")
    else:
        r.fail("tool/search_entities", resp.text[:120])

    resp = c.post("/api/tool/set_user_location", json={"user_id": uid, "reference": "272"})
    if resp.status_code == 200 and resp.json().get("booth_number") == "272":
        r.ok("POST /api/tool/set_user_location 272")
    else:
        r.fail("tool/set_user_location 272", resp.text[:160])

    resp = c.post("/api/tool/query_nearby", json={"user_id": uid, "radius_meters": 60})
    if resp.status_code == 200 and isinstance(resp.json().get("results"), list):
        r.ok(f"POST /api/tool/query_nearby ({len(resp.json()['results'])} results)")
    else:
        r.fail("tool/query_nearby", resp.text[:160])

    # Unknown tool returns 404
    resp = c.post("/api/tool/nonexistent_tool", json={"user_id": uid})
    if resp.status_code == 404:
        r.ok("unknown tool -> 404")
    else:
        r.fail("unknown tool wrong status", f"status={resp.status_code}")

    c.close()
    return r


if __name__ == "__main__":
    run().print_summary()
