"""Auto-retrieve relevant *source* chunks for planner grounding.

The wiki retriever (``repo_context``) grounds the planner in code *summaries*;
this grounds it in the actual *source*, the way Qoder pulls real code into
context. It builds a bounded BM25 index over the project's source files
(line-window chunks, no AST parse so it's fast and language-agnostic) and
returns the top chunks for a goal as ``path:line`` excerpts — no LLM, no new
dependency. Ranking reuses ``repo_context``'s BM25 + identifier-aware
tokenization, so a word goal matches camelCase / snake_case identifiers.

Cost is bounded (file / chunk caps, noise dirs pruned, large files skipped)
and the index is cached per root with a short TTL, so a hot planning loop pays
the walk once. Self-gating: no source under the root → ``None``.
"""
from __future__ import annotations

import os
import threading
import time
from collections import Counter
from pathlib import Path
from typing import Any

from runtime.memory.hemolymph.repo_context import _bm25, _tokenize

# v1 indexes Python source; the chunker is language-agnostic, so extending the
# extension set later needs no other change.
_CODE_EXTS = frozenset({".py"})
_SKIP_DIRS = frozenset({
    ".git", ".venv", "venv", "env", "node_modules", "__pycache__",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", "dist", "build", ".next",
    "site-packages", "docs", "tests", "test", "migrations", ".tox", "vendor",
    ".idea", ".vscode", "coverage", "htmlcov",
})

_MAX_FILES = 1200
_MAX_CHUNKS = 2500
_MAX_FILE_BYTES = 200_000
_CHUNK_LINES = 50
_INDEX_TTL_S = 120.0

_CACHE_LOCK = threading.Lock()
# root -> (built_monotonic, index)
_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


def _iter_source_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS and not d.startswith(".")]
        for name in filenames:
            if Path(name).suffix in _CODE_EXTS:
                files.append(Path(dirpath) / name)
                if len(files) >= _MAX_FILES:
                    return files
    return files


def _chunk_file(path: Path, rel: str) -> list[tuple[str, int, str]]:
    try:
        if path.stat().st_size > _MAX_FILE_BYTES:
            return []
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    chunks: list[tuple[str, int, str]] = []
    for start in range(0, len(lines), _CHUNK_LINES):
        body = "\n".join(lines[start:start + _CHUNK_LINES]).strip()
        if body:
            chunks.append((rel, start + 1, body))
    return chunks


def _build_index(root: Path) -> dict[str, Any]:
    pages: list[dict[str, Any]] = []
    df: Counter[str] = Counter()
    total_len = 0
    for path in _iter_source_files(root):
        try:
            rel = str(path.relative_to(root))
        except ValueError:
            rel = str(path)
        for rel_path, line, body in _chunk_file(path, rel):
            # The path joins the tokens so a filename hit counts toward the chunk.
            tf = Counter(_tokenize(f"{rel_path} {body}"))
            if not tf:
                continue
            length = sum(tf.values())
            total_len += length
            for term in tf:
                df[term] += 1
            pages.append({
                "path": rel_path, "line": line, "body": body,
                "tf": tf, "length": length,
            })
            if len(pages) >= _MAX_CHUNKS:
                break
        if len(pages) >= _MAX_CHUNKS:
            break
    n = len(pages)
    return {
        "pages": pages,
        "df": df,
        "n": n,
        "avgdl": (total_len / n) if n else 0.0,
    }


def _default_root() -> Path:
    return Path.cwd()


def _get_index(root: Path, *, ttl: float = _INDEX_TTL_S) -> dict[str, Any]:
    key = str(root)
    now = time.monotonic()
    with _CACHE_LOCK:
        cached = _CACHE.get(key)
        if cached is not None and (now - cached[0]) < ttl:
            return cached[1]
    built = _build_index(root)
    with _CACHE_LOCK:
        _CACHE[key] = (now, built)
    return built


def retrieve_code_context(
    query: str,
    *,
    root: str | Path | None = None,
    budget_tokens: int = 1500,
    max_chunks: int = 3,
    ttl: float = _INDEX_TTL_S,
) -> str | None:
    """Return the source chunks most relevant to ``query`` as a prompt section,
    or ``None`` when there is no source or no chunk overlaps the query."""
    query = (query or "").strip()
    if not query:
        return None
    q_terms = list(dict.fromkeys(_tokenize(query)))
    if not q_terms:
        return None

    base = Path(root) if root is not None else _default_root()
    idx = _get_index(base, ttl=ttl)
    if not idx["pages"]:
        return None

    scored = [(_bm25(q_terms, p, idx), p) for p in idx["pages"]]
    scored = [(s, p) for s, p in scored if s > 0]
    if not scored:
        return None
    scored.sort(key=lambda sp: (-sp[0], sp[1]["path"], sp[1]["line"]))

    per_chunk_chars = max(300, (budget_tokens * 4) // max(1, max_chunks))
    parts: list[str] = [
        "RELEVANT SOURCE (auto-retrieved by relevance to the goal — read the "
        "files for full context before editing):",
    ]
    for _score, chunk in scored[:max_chunks]:
        body = chunk["body"]
        if len(body) > per_chunk_chars:
            body = body[:per_chunk_chars].rstrip() + "\n…(truncated)"
        parts.append(f"\n### {chunk['path']}:{chunk['line']}\n{body}")
    return "\n".join(parts)
