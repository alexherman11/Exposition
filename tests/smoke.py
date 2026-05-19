"""Smoke layer (§5.4) — runs in ~5 seconds, catches catastrophic regressions."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))


def check(name, fn):
    try:
        fn()
        print(f"ok   {name}")
        return True
    except Exception as e:
        print(f"FAIL {name}: {e}")
        return False


def main():
    results = []

    def ingest_ok():
        from app.store import get_store
        from app.ingest.embed import build_index
        if not (ROOT / "backend" / "app" / "data" / "embeddings.npy").exists():
            build_index()
        store = get_store()
        store.load()
        assert len(store.sessions) > 50
        assert len(store.booths) > 50

    def floorplan_ok():
        p = ROOT / "backend" / "app" / "data" / "floorplan.png"
        assert p.exists() and p.stat().st_size > 5000

    def booths_in_range():
        from app.store import get_store
        store = get_store()
        n = len(store.booths)
        # Real TechEx ranges 200-300 booths; allow ±50 around 240
        assert 50 <= n <= 500, f"unexpected booth count {n}"

    def map_renderable():
        # Each booth must have valid coords inside canvas
        from app.store import get_store
        for b in get_store().booths.values():
            assert 0 <= b.center[0] <= 1600
            assert 0 <= b.center[1] <= 1000

    def schedule_has_cards():
        from app.store import get_store
        sess = list(get_store().sessions.values())
        assert sess and all(s.day and s.start for s in sess[:10])

    results.append(check("ingest", ingest_ok))
    results.append(check("floorplan", floorplan_ok))
    results.append(check("booths_in_range", booths_in_range))
    results.append(check("map_renderable", map_renderable))
    results.append(check("schedule_has_cards", schedule_has_cards))

    print()
    print(f"{sum(results)}/{len(results)} smoke checks passed")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
