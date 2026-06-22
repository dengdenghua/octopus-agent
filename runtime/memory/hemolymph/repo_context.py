"""Auto-retrieve relevant codebase context from the project wiki.

The context composer feeds the planner system / skills / memory, but nothing
about the *codebase* — so the agent re-greps the repo every task. octopus
already generates a structured project wiki under ``docs/auto`` (titled topic
pages + ``index.json``); this module retrieves the pages most relevant to a
task and renders them into a compact prompt section, so the planner gets
codebase grounding the way Qoder's repo wiki does — without an LLM call.

Ranking is **BM25** over **identifier-aware** tokens: ``ToolEngine`` and
``tool_engine`` both tokenize to {tool, engine}, so a natural-language goal
matches code identifiers; BM25's length normalization stops a long index page
from out-ranking a short on-topic one just by having more words (the failure
plain keyword-overlap had). Bilingual wiki titles (e.g. "Cerebrum · 规划")
mean an EN or 中 goal hits the same page for free. True synonym bridging with
no shared token (planner→cerebrum) still needs embeddings — out of scope here.

Self-gating: no wiki (no ``docs/auto/index.json``) → returns ``None`` and the
planner omits the section.
"""
from __future__ import annotations

import contextlib
import json
import math
import re
import threading
from collections import Counter
from pathlib import Path
from typing import Any

# Short / structural tokens carry no retrieval signal — drop them so scoring
# keys on meaningful identifiers (module names, domain nouns).
_STOPWORDS = frozenset({
    "the", "and", "for", "with", "this", "that", "from", "into", "your", "you",
    "are", "use", "add", "fix", "run", "get", "set", "how", "why", "what",
    "where", "when", "make", "new", "all", "any", "can", "should", "would",
    "does", "did", "its", "our", "out", "via",
    "的", "了", "在", "和", "是", "把", "给", "做", "加", "改", "怎么", "如何",
})

# Runs of alnum or CJK, separators (incl. ``_``) drop out — so snake_case is
# already split. Camel/acronym/number boundaries are split by _SUBWORD_RE.
_WORD_RE = re.compile(r"[A-Za-z0-9]+|[一-鿿]+")
_SUBWORD_RE = re.compile(
    r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|[0-9]+|[一-鿿]+"
)

# BM25 params (standard defaults).
_BM25_K1 = 1.5
_BM25_B = 0.75

# Cache the parsed + indexed wiki keyed by (dir, index.json mtime) so a hot
# planning loop doesn't re-read/re-index ~30 files every turn, but a
# regenerated wiki is picked up automatically.
_CACHE_LOCK = threading.Lock()
_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


def _tokenize(text: str) -> list[str]:
    """Identifier-aware tokens: split camelCase / snake_case / acronyms into
    sub-words so ``ToolEngine`` and ``tool_engine`` both yield {tool, engine};
    CJK runs are kept whole."""
    out: list[str] = []
    for word in _WORD_RE.findall(text):
        if "一" <= word[0] <= "鿿":
            if word not in _STOPWORDS:
                out.append(word)
            continue
        for part in _SUBWORD_RE.findall(word):
            p = part.lower()
            if len(p) >= 2 and p not in _STOPWORDS:
                out.append(p)
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


def _build_index(wiki_dir: Path) -> dict[str, Any]:
    """Read every wiki page and build a small BM25 index over it."""
    index_path = wiki_dir / "index.json"
    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"pages": [], "df": {}, "n": 0, "avgdl": 0.0}

    pages: list[dict[str, Any]] = []
    df: Counter[str] = Counter()
    total_len = 0
    for title, rel in _flatten(index.get("tree")):
        body = ""
        with contextlib.suppress(OSError):
            body = (wiki_dir / rel).read_text(encoding="utf-8")
        # Title + path weigh into matching even when the body is unreadable;
        # repeat the title so a title hit counts for more than a body mention.
        tf = Counter(_tokenize(f"{title} {title} {rel} {body}"))
        if not tf:
            continue
        length = sum(tf.values())
        total_len += length
        for term in tf:
            df[term] += 1
        pages.append({"title": title, "path": rel, "body": body, "tf": tf, "length": length})

    n = len(pages)
    avgdl = (total_len / n) if n else 0.0
    return {"pages": pages, "df": df, "n": n, "avgdl": avgdl}


def _load_index(wiki_dir: Path) -> dict[str, Any]:
    """Return the BM25 index for ``wiki_dir``, cached by index.json mtime."""
    index_path = wiki_dir / "index.json"
    try:
        mtime = index_path.stat().st_mtime
    except OSError:
        return {"pages": [], "df": {}, "n": 0, "avgdl": 0.0}

    key = str(wiki_dir)
    with _CACHE_LOCK:
        cached = _CACHE.get(key)
        if cached is not None and cached[0] == mtime:
            return cached[1]

    built = _build_index(wiki_dir)

    with _CACHE_LOCK:
        _CACHE[key] = (mtime, built)
    return built


def _bm25(q_terms: list[str], page: dict[str, Any], idx: dict[str, Any]) -> float:
    tf: Counter[str] = page["tf"]
    df: dict[str, int] = idx["df"]
    n: int = idx["n"]
    avgdl: float = idx["avgdl"] or 1.0
    length = page["length"]
    score = 0.0
    for term in q_terms:
        f = tf.get(term, 0)
        if not f:
            continue
        # idf with the +1 inside log keeps it non-negative even for common terms.
        idf = math.log(1 + (n - df.get(term, 0) + 0.5) / (df.get(term, 0) + 0.5))
        denom = f + _BM25_K1 * (1 - _BM25_B + _BM25_B * length / avgdl)
        score += idf * (f * (_BM25_K1 + 1)) / denom
    return score


def _default_wiki_dir() -> Path:
    return Path.cwd() / "docs" / "auto"


def retrieve_repo_context(
    query: str,
    *,
    wiki_dir: str | Path | None = None,
    budget_tokens: int = 1400,
    max_pages: int = 2,
) -> str | None:
    """Retrieve the wiki pages most relevant to ``query`` (BM25) as a prompt
    section. Returns ``None`` when there is no wiki or no page overlaps."""
    query = (query or "").strip()
    if not query:
        return None
    q_terms = list(dict.fromkeys(_tokenize(query)))  # unique, order kept
    if not q_terms:
        return None

    base = Path(wiki_dir) if wiki_dir is not None else _default_wiki_dir()
    idx = _load_index(base)
    if not idx["pages"]:
        return None

    scored = [(_bm25(q_terms, p, idx), p) for p in idx["pages"]]
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


def render_codebase_context(goal: str) -> str:
    """Combined codebase grounding for a goal: relevant wiki pages (summaries)
    + the actual source chunks. Shared by the planner AND the react chat loop
    so interactive chat gets the same grounding as planned turns — not just the
    graph paths. Self-gating + best-effort; disabled by OCTOPUS_CODEBASE_CONTEXT=0.
    """
    import os

    if os.environ.get("OCTOPUS_CODEBASE_CONTEXT", "1").strip().lower() in (
        "0", "false", "no", "off",
    ):
        return ""
    goal = (goal or "").strip()
    if not goal:
        return ""
    parts: list[str] = []
    with contextlib.suppress(Exception):
        wiki = retrieve_repo_context(goal)
        if wiki:
            parts.append(wiki)
    with contextlib.suppress(Exception):
        from runtime.memory.hemolymph.code_index import retrieve_code_context

        code = retrieve_code_context(goal)
        if code:
            parts.append(code)
    return "\n\n".join(parts)
