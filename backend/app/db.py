"""Postgres / SQLite persistence for per-user state.

The static expo corpus (sessions, speakers, exhibitors, booths, embeddings)
stays in memory — it's read-only data refreshed via ingest scripts. Only the
mutable per-user surface (accounts, profiles, plans, annotations, uploaded
LinkedIn connections) lives in the database.

Connection model:
  - If DATABASE_URL is set (Railway / production), connect to that Postgres.
    Railway hands us postgres://... — SQLAlchemy 2.x wants postgresql+psycopg2://...
    so we rewrite the scheme.
  - Otherwise fall back to a local SQLite file. This keeps `pytest` and
    `uvicorn` working out-of-the-box on a laptop with no Postgres installed.
"""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator, Optional

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Session, relationship, sessionmaker


def _resolve_db_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if url:
        # Railway / Heroku ship "postgres://" which SQLAlchemy 2 doesn't accept.
        if url.startswith("postgres://"):
            url = "postgresql+psycopg2://" + url[len("postgres://"):]
        elif url.startswith("postgresql://"):
            url = "postgresql+psycopg2://" + url[len("postgresql://"):]
        return url
    sqlite_path = Path(__file__).resolve().parent.parent / "local.db"
    return f"sqlite:///{sqlite_path}"


DB_URL = _resolve_db_url()
IS_SQLITE = DB_URL.startswith("sqlite")

engine = create_engine(
    DB_URL,
    pool_pre_ping=True,
    connect_args={"check_same_thread": False} if IS_SQLITE else {},
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


class Base(DeclarativeBase):
    pass


# ─── tables ─────────────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    id = Column(String(64), primary_key=True)  # "linkedin:<sub>" or "guest:<uuid>"
    email = Column(String(320), nullable=True, index=True)
    name = Column(String(200), nullable=False, default="Attendee")
    picture_url = Column(Text, nullable=True)
    linkedin_sub = Column(String(120), nullable=True, unique=True, index=True)
    is_guest = Column(Integer, nullable=False, default=0)  # bool as int for sqlite compat
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    last_login_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    # mutable profile fields the agent reads/writes
    role = Column(String(200), nullable=False, default="")
    company = Column(String(200), nullable=False, default="")
    interests = Column(JSON, nullable=False, default=list)
    session_intent = Column(JSON, nullable=False, default=list)
    career_history = Column(JSON, nullable=False, default=list)
    behavioral_log = Column(JSON, nullable=False, default=list)
    connections = Column(JSON, nullable=False, default=list)  # LinkedIn CSV import
    location_reference = Column(String(40), nullable=True)


class PlanItem(Base):
    __tablename__ = "plan_items"
    __table_args__ = (UniqueConstraint("user_id", "entity_id", "layer", name="uq_plan_user_entity_layer"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    entity_id = Column(String(64), nullable=False)
    entity_type = Column(String(32), nullable=False, default="session")
    layer = Column(String(16), nullable=False)  # saved | planned | attended
    note = Column(Text, nullable=True)
    added_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class Annotation(Base):
    __tablename__ = "annotations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    entity_id = Column(String(64), nullable=False, index=True)
    type = Column(String(32), nullable=False)
    payload = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


# ─── lifecycle ──────────────────────────────────────────────────────────

def init_db() -> None:
    """Create tables idempotently on startup."""
    Base.metadata.create_all(bind=engine)


@contextmanager
def db_session() -> Iterator[Session]:
    s = SessionLocal()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()
