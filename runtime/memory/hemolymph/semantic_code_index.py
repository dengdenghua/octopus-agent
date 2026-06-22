"""Read-only semantic search over the work-mode KB's persisted code index.

octopus already has a local knowledge base: ``code_intelligence_skills`` + the
``/api/index/*`` panel build a SQLite index of ``(path, chunk, embedding)`` at
``data/code_index.db`` using a local SentenceTransformer. The react-chat
grounding (``code_index.retrieve_code_context``) was BM25-only and ignored it.

This module *reuses that exact artifact* — same DB file, same model — read-only,
**never building** (safe on the hot grounding path), so the grounding retriever
can fuse dense semantic recall on top of BM25. No new index, no new model.

Self-gating + best-effort: no DB (the user hasn't indexed), no
``sentence-transformers``/``numpy``, or ``OCTOPUS_CODEBASE_SEMANTIC=0`` →
returns ``None`` and the caller stays pure BM25 (zero-dependency behaviour
unchanged).
"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any

# The same artifact the work-mode KB agent writes (code_intelligence_skills /
# index_router). Reusing this path IS the reuse — index once via the panel, the
# chat grounding picks it up automatically.
_DEFAULT_DB = Path("data/code_index.db")
# Must match the indexer's model so query/corpus vectors share a space.
_EMBED_MODEL = "all-MiniLM-L6-v2"

_EMBEDDER: Any = None
_EMBEDDER_LOCK = threading.Lock()


def _disabled() -> bool:
    return os.environ.get("OCTOPUS_CODEBASE_SEMANTIC", "auto").strip().lower() in (
        "0",
        "false",
        "no",
        "off",
    )


def _get_embedder() -> Any:
    """Load + cache the SentenceTransformer once; ``None`` if unavailable."""
    global _EMBEDDER
    if _EMBEDDER is not None:
        return _EMBEDDER
    with _EMBEDDER_LOCK:
        if _EMBEDDER is not None:
            return _EMBEDDER
        try:
            from sentence_transformers import SentenceTransformer

            _EMBEDDER = SentenceTransformer(_EMBED_MODEL)
        except Exception:  # noqa: BLE001 — lib/model absent → no semantic layer
            _EMBEDDER = None
        return _EMBEDDER


def _load_rows(db_path: Path) -> list[tuple[str, str, Any]]:
    """Read ``(path, chunk, vector)`` rows from the persisted index, or ``[]``."""
    if not db_path.exists():
        return []
    try:
        import sqlite3

        import numpy as np

        conn = sqlite3.connect(str(db_path))
        try:
            rows = conn.execute("SELECT path, chunk, embedding FROM code_chunks").fetchall()
        finally:
            conn.close()
        return [(str(r[0]), str(r[1]), np.frombuffer(r[2], dtype=np.float32)) for r in rows]
    except Exception:  # noqa: BLE001 — missing table / numpy / corrupt → no semantic
        return []


def search_persisted(
    query: str,
    *,
    top_k: int = 5,
    db_path: str | Path | None = None,
) -> list[dict[str, Any]] | None:
    """Top-k semantically-nearest chunks from the persisted KB index, or
    ``None`` when the semantic layer isn't available (no DB / no model /
    disabled). Read-only: never (re)builds the index, so it's safe on a hot
    path — it only consults what the user already indexed."""
    query = (query or "").strip()
    if not query or _disabled():
        return None
    path = Path(db_path) if db_path is not None else _DEFAULT_DB
    rows = _load_rows(path)
    if not rows:
        return None
    embedder = _get_embedder()
    if embedder is None:
        return None
    try:
        import numpy as np

        q = embedder.encode([query])[0]
        q_norm = float(np.linalg.norm(q)) + 1e-9
        scored: list[tuple[float, str, str]] = []
        for p, chunk, emb in rows:
            denom = q_norm * (float(np.linalg.norm(emb)) + 1e-9)
            sim = float(np.dot(q, emb) / denom)
            scored.append((sim, p, chunk))
        scored.sort(key=lambda t: -t[0])
        return [
            {"path": p, "snippet": c, "score": round(s, 4)}
            for s, p, c in scored[: max(1, int(top_k))]
        ]
    except Exception:  # noqa: BLE001 — any embed/maths failure → no semantic
        return None
