"""Pydantic schemas for the four top-level tables (§1.3) plus runtime tables.

Relationships are by ID (string) — no FK constraints. Each entity carries an
embedding vector, freshness timestamp, and a flat metadata blob.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


EntityType = Literal["session", "speaker", "exhibitor", "booth"]


class Session(BaseModel):
    id: str
    title: str
    abstract: str
    track: str
    day: str  # "2026-05-18" or "2026-05-19"
    start: str  # "HH:MM"
    end: str
    room: str
    speaker_ids: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    microsite: str = ""
    freshness: datetime = Field(default_factory=datetime.utcnow)


class Speaker(BaseModel):
    id: str
    name: str
    title: str
    company: str
    bio: str
    session_ids: list[str] = Field(default_factory=list)
    headshot_url: Optional[str] = None
    freshness: datetime = Field(default_factory=datetime.utcnow)


class Exhibitor(BaseModel):
    id: str
    company: str
    booth_number: str
    description: str
    tags: list[str] = Field(default_factory=list)
    hall_zone: str = ""
    website: Optional[str] = None
    freshness: datetime = Field(default_factory=datetime.utcnow)


class Booth(BaseModel):
    booth_number: str
    bbox: list[float]  # [x1, y1, x2, y2] in image pixel coords
    center: list[float]  # [x, y]
    hall_zone: str
    exhibitor_id: Optional[str] = None


# Runtime / per-user state -----------------------------------------------------

class Annotation(BaseModel):
    entity_id: str
    type: Literal["free_drinks", "good_swag", "rating", "comment", "presenter_contact"]
    payload: dict
    user_id: str
    created_at: datetime = Field(default_factory=datetime.utcnow)


PlanLayer = Literal["saved", "planned", "attended"]


class PlanItem(BaseModel):
    user_id: str
    entity_id: str
    entity_type: EntityType
    layer: PlanLayer
    note: Optional[str] = None
    added_at: datetime = Field(default_factory=datetime.utcnow)


class UserProfile(BaseModel):
    user_id: str
    name: str = "Demo Attendee"
    role: str = ""
    company: str = ""
    career_history: list[str] = Field(default_factory=list)
    interests: list[str] = Field(default_factory=list)  # stable
    session_intent: list[str] = Field(default_factory=list)  # per-session
    behavioral_log: list[dict] = Field(default_factory=list)
    connections: list[dict] = Field(default_factory=list)  # imported from LinkedIn CSV
    location_reference: Optional[str] = None  # e.g. "B14"
