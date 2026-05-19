"""In-memory store for the demo snapshot + per-user runtime state.

Loads JSON files from `data/` once at startup. Embeddings live as a single
NxD numpy array next to an `embedding_ids.json` index. Annotations and
plan items live in tiny SQLite-shaped lists.

This is intentionally simple — for a 750-entity corpus, pgvector is overkill
and an in-memory cosine similarity is fast enough.
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np

from .models import Annotation, Booth, Exhibitor, PlanItem, Session, Speaker, UserProfile

DATA_DIR = Path(__file__).resolve().parent / "data"


class Store:
    def __init__(self):
        self._lock = threading.RLock()
        self.sessions: dict[str, Session] = {}
        self.speakers: dict[str, Speaker] = {}
        self.exhibitors: dict[str, Exhibitor] = {}
        self.booths: dict[str, Booth] = {}
        self.exhibitor_by_booth: dict[str, str] = {}

        self._emb_matrix: Optional[np.ndarray] = None
        self._emb_ids: list[str] = []
        self._emb_types: list[str] = []

        # runtime
        self.profiles: dict[str, UserProfile] = {}
        self.plans: list[PlanItem] = []
        self.annotations: list[Annotation] = []

    # ---------- loaders ----------
    def load(self) -> None:
        with self._lock:
            with open(DATA_DIR / "sessions.json") as f:
                self.sessions = {r["id"]: Session(**r) for r in json.load(f)}
            with open(DATA_DIR / "speakers.json") as f:
                self.speakers = {r["id"]: Speaker(**r) for r in json.load(f)}
            with open(DATA_DIR / "exhibitors.json") as f:
                self.exhibitors = {r["id"]: Exhibitor(**r) for r in json.load(f)}
            with open(DATA_DIR / "booths.json") as f:
                self.booths = {r["booth_number"]: Booth(**r) for r in json.load(f)}
            self.exhibitor_by_booth = {b.booth_number: b.exhibitor_id for b in self.booths.values() if b.exhibitor_id}

            emb_path = DATA_DIR / "embeddings.npy"
            idx_path = DATA_DIR / "embedding_ids.json"
            if emb_path.exists() and idx_path.exists():
                self._emb_matrix = np.load(emb_path)
                idx = json.loads(idx_path.read_text())
                self._emb_ids = idx["ids"]
                self._emb_types = idx["types"]

    # ---------- vector search ----------
    def search(self, query_vec: np.ndarray, type_filter: Optional[str] = None, k: int = 8) -> list[tuple[str, str, float]]:
        if self._emb_matrix is None or len(self._emb_ids) == 0:
            return []
        sims = self._emb_matrix @ query_vec
        order = np.argsort(-sims)
        out = []
        for i in order:
            t = self._emb_types[i]
            if type_filter and t != type_filter:
                continue
            out.append((self._emb_ids[i], t, float(sims[i])))
            if len(out) >= k:
                break
        return out

    def get(self, entity_id: str) -> Optional[dict]:
        if entity_id in self.sessions:
            return {"type": "session", **self.sessions[entity_id].model_dump(mode="json")}
        if entity_id in self.speakers:
            return {"type": "speaker", **self.speakers[entity_id].model_dump(mode="json")}
        if entity_id in self.exhibitors:
            return {"type": "exhibitor", **self.exhibitors[entity_id].model_dump(mode="json")}
        if entity_id in self.booths:
            return {"type": "booth", **self.booths[entity_id].model_dump(mode="json")}
        return None

    # ---------- spatial ----------
    def find_booth_for_reference(self, reference: str) -> Optional[Booth]:
        ref = (reference or "").strip()
        if not ref:
            return None
        # booth number direct
        for key, b in self.booths.items():
            if key.lower() == ref.lower():
                return b
        # exhibitor name fuzzy
        ref_lc = ref.lower()
        for ex in self.exhibitors.values():
            if ex.company.lower() == ref_lc:
                return self.booths.get(ex.booth_number)
        for ex in self.exhibitors.values():
            if ref_lc in ex.company.lower():
                return self.booths.get(ex.booth_number)
        return None

    def query_nearby(self, ref_point: tuple[float, float], radius: float, filter_tags: Optional[list[str]] = None) -> list[dict]:
        rx, ry = ref_point
        out = []
        for b in self.booths.values():
            cx, cy = b.center
            d = ((cx - rx) ** 2 + (cy - ry) ** 2) ** 0.5
            if d > radius:
                continue
            ex = self.exhibitors.get(b.exhibitor_id) if b.exhibitor_id else None
            if filter_tags and ex:
                ex_tags = {t.lower() for t in ex.tags}
                if not any(t.lower() in ex_tags for t in filter_tags):
                    continue
            out.append({
                "booth_number": b.booth_number,
                "distance_px": d,
                "approx_minutes": round(d / 240, 1),  # 1600px≈100m / ~1.2m/s
                "hall_zone": b.hall_zone,
                "exhibitor": ex.model_dump(mode="json") if ex else None,
            })
        out.sort(key=lambda r: r["distance_px"])
        return out

    # ---------- profile ----------
    def get_profile(self, user_id: str) -> UserProfile:
        with self._lock:
            if user_id not in self.profiles:
                self.profiles[user_id] = UserProfile(user_id=user_id)
            return self.profiles[user_id]

    def update_profile(self, user_id: str, **fields) -> UserProfile:
        with self._lock:
            p = self.get_profile(user_id)
            for k, v in fields.items():
                if hasattr(p, k):
                    setattr(p, k, v)
            return p

    def log_behavior(self, user_id: str, action: str, entity_id: str, note: str = "") -> None:
        with self._lock:
            p = self.get_profile(user_id)
            p.behavioral_log.append({
                "ts": datetime.utcnow().isoformat(),
                "action": action,
                "entity_id": entity_id,
                "note": note,
            })

    # ---------- plan ----------
    def add_to_plan(self, user_id: str, entity_id: str, layer: str, entity_type: str = "session") -> PlanItem:
        with self._lock:
            # idempotent: replace existing same-id+layer
            self.plans = [p for p in self.plans if not (p.user_id == user_id and p.entity_id == entity_id and p.layer == layer)]
            item = PlanItem(user_id=user_id, entity_id=entity_id, entity_type=entity_type, layer=layer)
            self.plans.append(item)
            return item

    def remove_from_plan(self, user_id: str, entity_id: str, layer: Optional[str] = None) -> int:
        with self._lock:
            before = len(self.plans)
            self.plans = [
                p for p in self.plans
                if not (p.user_id == user_id and p.entity_id == entity_id and (layer is None or p.layer == layer))
            ]
            return before - len(self.plans)

    def get_plan(self, user_id: str) -> list[dict]:
        return [
            {**p.model_dump(mode="json"), "entity": self.get(p.entity_id)}
            for p in self.plans
            if p.user_id == user_id
        ]

    # ---------- annotations ----------
    def add_annotation(self, user_id: str, entity_id: str, ann_type: str, payload: dict) -> Annotation:
        with self._lock:
            a = Annotation(user_id=user_id, entity_id=entity_id, type=ann_type, payload=payload)
            self.annotations.append(a)
            return a

    def annotations_for(self, entity_id: str) -> list[dict]:
        return [a.model_dump(mode="json") for a in self.annotations if a.entity_id == entity_id]

    def annotations_summary(self) -> dict[str, dict]:
        """Aggregate per-entity: flags, rating mean, comments count."""
        out: dict[str, dict] = {}
        for a in self.annotations:
            agg = out.setdefault(a.entity_id, {"flags": [], "ratings": [], "comments": 0})
            if a.type in ("free_drinks", "good_swag"):
                if a.type not in agg["flags"]:
                    agg["flags"].append(a.type)
            elif a.type == "rating":
                agg["ratings"].append(a.payload.get("value", 0))
            elif a.type == "comment":
                agg["comments"] += 1
        for eid, agg in out.items():
            if agg["ratings"]:
                agg["rating_mean"] = round(sum(agg["ratings"]) / len(agg["ratings"]), 1)
                agg["rating_count"] = len(agg["ratings"])
            del agg["ratings"]
        return out


STORE = Store()


def get_store() -> Store:
    return STORE
