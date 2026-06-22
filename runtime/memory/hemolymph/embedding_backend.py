"""Unified, configurable text embedder for octopus's code index.

By default the code semantic index embeds in-process with a SentenceTransformer
(``all-MiniLM-L6-v2``). To let the WHOLE local stack share ONE embedding model —
the same local Ollama / OpenAI-compatible endpoint octopus-storage uses (bge-m3)
— this backend makes the embedder configurable from three env vars:

  ``OCTOPUS_EMBED_URL``    OpenAI-compatible base, e.g. ``http://127.0.0.1:11434/v1``
                          (Ollama). Set → embeddings come from there over HTTP.
  ``OCTOPUS_EMBED_MODEL``  model name (default ``all-MiniLM-L6-v2`` in-process;
                          for a remote endpoint use e.g. ``bge-m3`` / ``nomic-embed-text``).
  ``OCTOPUS_EMBED_API_KEY`` optional bearer for the endpoint (Ollama needs none).

Resolution: URL set → remote (``urllib``, zero new dependency); else in-process
SentenceTransformer; else ``None``.

CRITICAL invariant: the corpus index and the query MUST embed with the SAME
model, or cosine is meaningless. Both the index BUILD (``code_intelligence_skills``)
and the QUERY (``semantic_code_index``) go through this one backend, so switching
the model is a single config change — followed by a re-index.
"""

from __future__ import annotations

import json
import os
import threading
import urllib.error
import urllib.request
from typing import Any

_DEFAULT_MODEL = "all-MiniLM-L6-v2"
_TIMEOUT_S = 30.0

_ST_MODEL: Any = None
_ST_LOCK = threading.Lock()


def embed_model() -> str:
    return (os.environ.get("OCTOPUS_EMBED_MODEL") or "").strip() or _DEFAULT_MODEL


def embed_endpoint() -> str:
    return (os.environ.get("OCTOPUS_EMBED_URL") or "").strip().rstrip("/")


def backend_info() -> dict[str, Any]:
    """Describe the active embedding backend — for the setup UI / CLI to show
    the user, in plain terms, what their stack is wired to."""
    url = embed_endpoint()
    if url:
        return {"kind": "remote", "endpoint": url, "model": embed_model(), "local_only": True}
    return {"kind": "in_process", "endpoint": None, "model": embed_model(), "local_only": True}


def _embed_remote(texts: list[str]) -> list[list[float]] | None:
    url = embed_endpoint()
    if not url:
        return None
    headers = {"Content-Type": "application/json"}
    key = (os.environ.get("OCTOPUS_EMBED_API_KEY") or "").strip()
    if key:
        headers["Authorization"] = f"Bearer {key}"
    req = urllib.request.Request(
        url + "/embeddings",
        data=json.dumps({"model": embed_model(), "input": texts}).encode("utf-8"),
        method="POST",
        headers=headers,
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:  # noqa: S310 — local/configured endpoint
            body = json.loads(resp.read().decode("utf-8", "replace"))
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return None
    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, list) or not data:
        return None
    out: list[list[float]] = []
    for d in data:
        vec = d.get("embedding") if isinstance(d, dict) else None
        if not isinstance(vec, list):
            return None
        out.append([float(x) for x in vec])
    return out


def _st_model() -> Any:
    global _ST_MODEL
    if _ST_MODEL is not None:
        return _ST_MODEL
    with _ST_LOCK:
        if _ST_MODEL is not None:
            return _ST_MODEL
        try:
            from sentence_transformers import SentenceTransformer

            _ST_MODEL = SentenceTransformer(embed_model())
        except Exception:  # noqa: BLE001 — lib/model absent
            _ST_MODEL = None
        return _ST_MODEL


def _embed_local(texts: list[str]) -> list[list[float]] | None:
    model = _st_model()
    if model is None:
        return None
    try:
        return [[float(x) for x in vec] for vec in model.encode(texts)]
    except Exception:  # noqa: BLE001
        return None


def available() -> bool:
    """True when SOME embedding backend is reachable (remote endpoint set, or
    sentence-transformers importable) — cheap, doesn't embed."""
    if embed_endpoint():
        return True
    try:
        import sentence_transformers  # noqa: F401

        return True
    except Exception:  # noqa: BLE001
        return False


def embed_texts(texts: list[str]) -> list[list[float]] | None:
    """Embed ``texts`` via the configured backend (remote endpoint preferred,
    else in-process). ``None`` when no backend is available; ``[]`` for no input.
    Never raises."""
    if not texts:
        return []
    if embed_endpoint():
        return _embed_remote(texts)
    return _embed_local(texts)


class _EncoderAdapter:
    """A ``.encode(texts)``-shaped object so legacy callers
    (``code_intelligence_skills``) route through the configurable backend
    unchanged. Returns float32 ndarrays (those callers need numpy for storage)."""

    def encode(self, texts: Any, **_kw: Any) -> Any:
        import numpy as np

        vecs = embed_texts(list(texts))
        if vecs is None:
            raise RuntimeError("embedding backend unavailable")
        return np.asarray(vecs, dtype=np.float32)


def get_encoder() -> Any:
    """Return an ``.encode``-compatible encoder for the configured backend, or
    ``None`` when nothing is available."""
    return _EncoderAdapter() if available() else None
