"""In-memory store for the static expo corpus + DB-backed per-user state.

Two-tier storage:
  - Static corpus (sessions/speakers/exhibitors/booths/embeddings): loaded
    once from JSON at startup, lives in RAM. Read-only at runtime.
  - Per-user state (profiles, plans, annotations, behavioral logs, uploaded
    LinkedIn connections): persisted in Postgres via `db.py`. Reads pull
    a fresh row each call; writes commit immediately. No caching here —
    SQLAlchemy session-per-call keeps things simple.

The expo corpus methods stay sync; the per-user methods open a short-lived
DB session each time. This means tools can call `store.add_to_plan(...)`
without knowing or caring that it crossed a network boundary.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np

from . import db as db_module
from .db import Annotation as DBAnnotation
from .db import PlanItem as DBPlanItem
from .db import User as DBUser
from .db import db_session
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

    # ---------- static corpus loaders ----------
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
        for key, b in self.booths.items():
            if key.lower() == ref.lower():
                return b
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
                "approx_minutes": round(d / 240, 1),
                "hall_zone": b.hall_zone,
                "exhibitor": ex.model_dump(mode="json") if ex else None,
            })
        out.sort(key=lambda r: r["distance_px"])
        return out

    # ---------- user / profile (DB-backed) ----------
    def _row_to_profile(self, u: DBUser) -> UserProfile:
        return UserProfile(
            user_id=u.id,
            name=u.name or "Attendee",
            role=u.role or "",
            company=u.company or "",
            career_history=list(u.career_history or []),
            interests=list(u.interests or []),
            session_intent=list(u.session_intent or []),
            behavioral_log=list(u.behavioral_log or []),
            connections=list(u.connections or []),
            location_reference=u.location_reference,
        )

    def _ensure_user_row(self, s, user_id: str) -> DBUser:
        u = s.get(DBUser, user_id)
        if u is None:
            is_guest = 1 if user_id.startswith("guest:") or user_id == "demo" else 0
            u = DBUser(
                id=user_id,
                name="Guest Attendee" if is_guest else "Attendee",
                is_guest=is_guest,
                interests=[],
                session_intent=[],
                career_history=[],
                behavioral_log=[],
                connections=[],
            )
            s.add(u)
            s.flush()
        return u

    def get_profile(self, user_id: str) -> UserProfile:
        with db_session() as s:
            u = self._ensure_user_row(s, user_id)
            return self._row_to_profile(u)

    def update_profile(self, user_id: str, **fields) -> UserProfile:
        # Whitelist — only fields the agent / API may write.
        allowed = {
            "name", "role", "company",
            "career_history", "interests", "session_intent",
            "connections", "location_reference",
        }
        with db_session() as s:
            u = self._ensure_user_row(s, user_id)
            for k, v in fields.items():
                if k in allowed:
                    setattr(u, k, v)
            s.flush()
            return self._row_to_profile(u)

    def upsert_linkedin_user(
        self,
        sub: str,
        email: Optional[str],
        name: Optional[str],
        picture_url: Optional[str],
    ) -> str:
        """Create or refresh a user row from a LinkedIn OIDC userinfo payload.
        Returns the canonical user_id ('linkedin:<sub>')."""
        user_id = f"linkedin:{sub}"
        with db_session() as s:
            u = s.get(DBUser, user_id)
            now = datetime.utcnow()
            if u is None:
                u = DBUser(
                    id=user_id,
                    linkedin_sub=sub,
                    email=email,
                    name=name or "LinkedIn User",
                    picture_url=picture_url,
                    is_guest=0,
                    created_at=now,
                    last_login_at=now,
                    interests=[],
                    session_intent=[],
                    career_history=[],
                    behavioral_log=[],
                    connections=[],
                )
                s.add(u)
            else:
                u.last_login_at = now
                if email and not u.email:
                    u.email = email
                if name:
                    u.name = name
                if picture_url:
                    u.picture_url = picture_url
            s.flush()
        return user_id

    def get_user_card(self, user_id: str) -> dict:
        """Return the small payload the frontend renders in the user pill."""
        with db_session() as s:
            u = self._ensure_user_row(s, user_id)
            return {
                "user_id": u.id,
                "name": u.name,
                "email": u.email,
                "picture_url": u.picture_url,
                "is_guest": bool(u.is_guest),
                "interests": list(u.interests or []),
                "role": u.role or "",
                "company": u.company or "",
                "linkedin_connections_imported": len(u.connections or []),
            }

    def log_behavior(self, user_id: str, action: str, entity_id: str, note: str = "") -> None:
        with db_session() as s:
            u = self._ensure_user_row(s, user_id)
            log = list(u.behavioral_log or [])
            log.append({
                "ts": datetime.utcnow().isoformat(),
                "action": action,
                "entity_id": entity_id,
                "note": note,
            })
            # cap log length so the JSON column doesn't grow unbounded
            u.behavioral_log = log[-500:]

    # ---------- plan (DB-backed) ----------
    def add_to_plan(self, user_id: str, entity_id: str, layer: str, entity_type: str = "session") -> PlanItem:
        with db_session() as s:
            self._ensure_user_row(s, user_id)
            existing = (
                s.query(DBPlanItem)
                .filter_by(user_id=user_id, entity_id=entity_id, layer=layer)
                .one_or_none()
            )
            if existing:
                return PlanItem(
                    user_id=existing.user_id,
                    entity_id=existing.entity_id,
                    entity_type=existing.entity_type,
                    layer=existing.layer,
                    note=existing.note,
                    added_at=existing.added_at,
                )
            row = DBPlanItem(
                user_id=user_id,
                entity_id=entity_id,
                entity_type=entity_type,
                layer=layer,
            )
            s.add(row)
            s.flush()
            return PlanItem(
                user_id=row.user_id,
                entity_id=row.entity_id,
                entity_type=row.entity_type,
                layer=row.layer,
                note=row.note,
                added_at=row.added_at,
            )

    def remove_from_plan(self, user_id: str, entity_id: str, layer: Optional[str] = None) -> int:
        with db_session() as s:
            q = s.query(DBPlanItem).filter_by(user_id=user_id, entity_id=entity_id)
            if layer is not None:
                q = q.filter_by(layer=layer)
            rows = q.all()
            for r in rows:
                s.delete(r)
            return len(rows)

    def get_plan(self, user_id: str) -> list[dict]:
        with db_session() as s:
            rows = s.query(DBPlanItem).filter_by(user_id=user_id).order_by(DBPlanItem.added_at).all()
            out = []
            for r in rows:
                out.append({
                    "user_id": r.user_id,
                    "entity_id": r.entity_id,
                    "entity_type": r.entity_type,
                    "layer": r.layer,
                    "note": r.note,
                    "added_at": r.added_at.isoformat() if r.added_at else None,
                    "entity": self.get(r.entity_id),
                })
            return out

    # ---------- annotations (DB-backed, global / cross-user reads) ----------
    def add_annotation(self, user_id: str, entity_id: str, ann_type: str, payload: dict) -> Annotation:
        with db_session() as s:
            self._ensure_user_row(s, user_id)
            row = DBAnnotation(
                user_id=user_id,
                entity_id=entity_id,
                type=ann_type,
                payload=payload or {},
            )
            s.add(row)
            s.flush()
            return Annotation(
                entity_id=row.entity_id,
                type=row.type,  # type: ignore[arg-type]
                payload=row.payload,
                user_id=row.user_id,
                created_at=row.created_at,
            )

    def annotations_for(self, entity_id: str) -> list[dict]:
        with db_session() as s:
            rows = s.query(DBAnnotation).filter_by(entity_id=entity_id).all()
            return [
                {
                    "entity_id": r.entity_id,
                    "type": r.type,
                    "payload": r.payload,
                    "user_id": r.user_id,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in rows
            ]

    def annotations_summary(self) -> dict[str, dict]:
        with db_session() as s:
            rows = s.query(DBAnnotation).all()
        out: dict[str, dict] = {}
        for a in rows:
            agg = out.setdefault(a.entity_id, {"flags": [], "ratings": [], "comments": 0})
            if a.type in ("free_drinks", "good_swag"):
                if a.type not in agg["flags"]:
                    agg["flags"].append(a.type)
            elif a.type == "rating":
                agg["ratings"].append((a.payload or {}).get("value", 0))
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
