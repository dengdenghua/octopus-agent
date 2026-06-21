"""Auto-retrieve relevant codebase context from the project wiki.

The context composer feeds the planner system / skills / memory, but nothing
about the *codebase* — so the agent re-greps the repo every task. octopus
already generates a structured project wiki under ``docs/auto`` (titled topic
pages + ``index.json``); this module retrieves the pages most relevant to a
task and renders them into a compact prompt section, so the planner gets
codebase grounding the way Qoder's repo wiki does — without an LLM call.

Self-gating: if no wiki is present (no ``docs/auto/index.json``), retrieval
returns ``None`` and the planner simply omits the section.
"""
from __future__ import annotations

import contextlib
import json
import re
import threading
from pathlib import Path
from typing import Any

# Short / structural tokens carry no retrieval signal — drop them so scoring
# keys on meaningful identifiers (module names, domain nouns).
_STOPWORDS = frozenset({
    "the", "and", "for", "with", "this", "that", "from", "into", "your", "you",
    "are", "use", "add", "fix", "run", "get", "set", "how", "why", "what",
    "where", "when", "make", "new", "all", "any", "can", "should", "would",
    "的", "了", "在", "和", "是", "把", "给", "做", "加", "改",
})

_TOKEN_RE = re.compile(r"[A-Za-z0-9_一-鿿]+")

# Cache the parsed wiki keyed by (dir, index.json mtime) so a hot planning
# loop doesn't re-read ~30 files every turn, but a regenerated wiki is picked
# up automatically.
_CACHE_LOCK = threading.Lock()
_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}


def _tokens(text: str) -> set[str]:
    out: set[str] = set()
    for raw in _TOKEN_RE.findall(text.lower()):
        if len(raw) < 3 or raw in _STOPWORDS:
            continue
        out.add(raw)
    return out


def _flatten(tree: Any) -> list[tuple[str, str]]:
    """Walk the index.json ``tree`` into a flat ``[(title, path)]`` list."""
    pages: list[tuple[str, str]] = []
    if not isinstance(tree, list):
        return pages
    for node in tree:
        if not isinstance(node, dict):
            continue
        if node.get("type") == "doc" and node.get("path"):
            pages.append((str(node.get("title") or ""), str(node["path"])))
        children = node.get("children")
        if children:
            pages.extend(_flatten(children))
    return pages


def _load_wiki(wiki_dir: Path) -> list[dict[str, Any]]:
    """Return ``[{title, path, tokens}]`` for every wiki page, cached by mtime."""
    index_path = wiki_dir / "index.json"
    try:
        mtime = index_path.stat().st_mtime
    except OSError:
        return []

    key = str(wiki_dir)
    with _CACHE_LOCK:
        cached = _CACHE.get(key)
        if cached is not None and cached[0] == mtime:
            return cached[1]

    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []

    pages: list[dict[str, Any]] = []
    for title, rel in _flatten(index.get("tree")):
        body = ""
        with contextlib.suppress(OSError):
            body = (wiki_dir / rel).read_text(encoding="utf-8")
        # Title + path weigh into matching even when the body is unreadable.
        pages.append({
            "title": title,
            "path": rel,
            "body": body,
            "tokens": _tokens(f"{title} {rel} {body}"),
        })

    with _CACHE_LOCK:
        _CACHE[key] = (mtime, pages)
    return pages


def _default_wiki_dir() -> Path:
    return Path.cwd() / "docs" / "auto"


def retrieve_repo_context(
    query: str,
    *,
    wiki_dir: str | Path | None = None,
    budget_tokens: int = 1400,
    max_pages: int = 2,
) -> str | None:
    """Retrieve the wiki pages most relevant to ``query`` as a prompt section.

    Returns ``None`` when there is no wiki or no page overlaps the query, so
    the caller can omit the section entirely.
    """
    query = (query or "").strip()
    if not query:
        return None
    q_tokens = _tokens(query)
    if not q_tokens:
        return None

    base = Path(wiki_dir) if wiki_dir is not None else _default_wiki_dir()
    pages = _load_wiki(base)
    if not pages:
        return None

    scored = [
        (len(q_tokens & p["tokens"]), p)
        for p in pages
    ]
    scored = [(s, p) for s, p in scored if s > 0]
    if not scored:
        return None
    scored.sort(key=lambda sp: (-sp[0], sp[1]["path"]))

    # ~4 chars/token; split the body budget across the chosen pages.
    per_page_chars = max(400, (budget_tokens * 4) // max(1, max_pages))
    parts: list[str] = [
        "RELEVANT CODEBASE DOCS (auto-retrieved from the project wiki — use to "
        "orient before grepping; verify against source before relying on it):",
    ]
    for _score, page in scored[:max_pages]:
        body = (page["body"] or "").strip()
        if len(body) > per_page_chars:
            body = body[:per_page_chars].rstrip() + "\n…(truncated)"
        header = page["title"] or page["path"]
        parts.append(f"\n## {header}  ({page['path']})\n{body}")
    return "\n".join(parts)
