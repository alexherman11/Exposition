"""Stage C — embed every entity with Gemini text-embedding-004.

Format: `[entity_type] | [name] | [tags] | [description/abstract] | [related]`
Batched, written to a single `embeddings.npy` (N x 768) plus an `ids.json`
that maps row index → entity id.

If GEMINI_API_KEY is unset we fall back to a deterministic hash-based
pseudo-embedding so the rest of the system still works for local dev /
tests. Real Gemini embeddings are used in production and during the demo.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

import numpy as np

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DIM = 768


def _format_session(s, speakers_by_id):
    spk_names = ", ".join(speakers_by_id[sid].get("name", "") for sid in s.get("speaker_ids", []) if sid in speakers_by_id)
    return f"[session] | {s['title']} | {', '.join(s.get('tags', []))} | {s.get('abstract','')} | {spk_names}"


def _format_speaker(sp):
    return f"[speaker] | {sp['name']} | {sp.get('title','')}, {sp.get('company','')} | {sp.get('bio','')}"


def _format_exhibitor(e):
    return f"[exhibitor] | {e['company']} | {', '.join(e.get('tags', []))} | {e.get('description','')} | booth {e.get('booth_number','')} {e.get('hall_zone','')}"


def _pseudo_embed(text: str) -> np.ndarray:
    """Deterministic fallback. Hash text → seed → np.random.normal."""
    seed = int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:16], 16) & 0xFFFFFFFF
    rng = np.random.default_rng(seed)
    v = rng.normal(0, 1, DIM).astype(np.float32)
    return v / (np.linalg.norm(v) + 1e-9)


def _gemini_embed_batch(texts: list[str], client) -> list[np.ndarray]:
    from google.genai import types
    out = []
    # 100/req upper bound; we go in chunks of 50
    for i in range(0, len(texts), 50):
        chunk = texts[i : i + 50]
        resp = client.models.embed_content(
            model="gemini-embedding-001",
            contents=chunk,
            config=types.EmbedContentConfig(output_dimensionality=DIM),
        )
        for e in resp.embeddings:
            v = np.array(e.values, dtype=np.float32)
            out.append(v / (np.linalg.norm(v) + 1e-9))
        time.sleep(0.2)
    return out


def build_index(use_gemini: bool | None = None) -> None:
    use_gemini = bool(os.getenv("GEMINI_API_KEY")) if use_gemini is None else use_gemini
    with open(DATA_DIR / "sessions.json") as f:
        sessions = json.load(f)
    with open(DATA_DIR / "speakers.json") as f:
        speakers = json.load(f)
    with open(DATA_DIR / "exhibitors.json") as f:
        exhibitors = json.load(f)
    speakers_by_id = {s["id"]: s for s in speakers}

    texts = []
    ids = []
    types = []
    for s in sessions:
        texts.append(_format_session(s, speakers_by_id))
        ids.append(s["id"])
        types.append("session")
    for sp in speakers:
        texts.append(_format_speaker(sp))
        ids.append(sp["id"])
        types.append("speaker")
    for e in exhibitors:
        texts.append(_format_exhibitor(e))
        ids.append(e["id"])
        types.append("exhibitor")

    if use_gemini:
        from google import genai
        client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        vecs = _gemini_embed_batch(texts, client)
    else:
        vecs = [_pseudo_embed(t) for t in texts]

    matrix = np.vstack(vecs).astype(np.float32)
    np.save(DATA_DIR / "embeddings.npy", matrix)
    with open(DATA_DIR / "embedding_ids.json", "w") as f:
        json.dump({"ids": ids, "types": types}, f)
    print(f"Wrote {matrix.shape} -> {DATA_DIR/'embeddings.npy'} (gemini={use_gemini})")


def embed_query(text: str, use_gemini: bool | None = None) -> np.ndarray:
    use_gemini = bool(os.getenv("GEMINI_API_KEY")) if use_gemini is None else use_gemini
    if not use_gemini:
        return _pseudo_embed(text)
    from google import genai
    from google.genai import types
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    resp = client.models.embed_content(
        model="gemini-embedding-001",
        contents=[text],
        config=types.EmbedContentConfig(output_dimensionality=DIM),
    )
    v = np.array(resp.embeddings[0].values, dtype=np.float32)
    return v / (np.linalg.norm(v) + 1e-9)


if __name__ == "__main__":
    build_index()
