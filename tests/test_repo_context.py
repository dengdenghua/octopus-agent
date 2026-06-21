"""Auto-retrieval of project-wiki context for planner grounding."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from runtime.memory.hemolymph.repo_context import (
    _flatten,
    _tokenize,
    retrieve_repo_context,
)


def _make_wiki(root: Path, pages: list[tuple[str, str, str]]) -> Path:
    auto = root / "docs" / "auto"
    auto.mkdir(parents=True, exist_ok=True)
    tree: list[dict[str, Any]] = []
    for title, rel, body in pages:
        (auto / rel).parent.mkdir(parents=True, exist_ok=True)
        (auto / rel).write_text(body, encoding="utf-8")
        tree.append({"type": "doc", "title": title, "path": rel})
    (auto / "index.json").write_text(
        json.dumps({"version": 2, "tree": tree}), encoding="utf-8",
    )
    return auto


def test_retrieves_most_relevant_page(tmp_path: Path) -> None:
    auto = _make_wiki(tmp_path, [
        ("Cerebrum planning", "cerebrum.md", "The planner builds a ReAct loop with tool calls."),
        ("Browser automation", "browser.md", "Playwright drives chromium via skills."),
    ])
    out = retrieve_repo_context("how does the planner cerebrum work", wiki_dir=auto)
    assert out is not None
    assert "Cerebrum planning" in out and "ReAct loop" in out
    assert "Browser automation" not in out  # no overlap → not selected


def test_nested_tree_is_flattened() -> None:
    tree = [
        {"type": "doc", "title": "A", "path": "a.md"},
        {"type": "dir", "title": "D", "children": [
            {"type": "doc", "title": "B", "path": "d/b.md"},
        ]},
    ]
    assert _flatten(tree) == [("A", "a.md"), ("B", "d/b.md")]


def test_no_wiki_returns_none(tmp_path: Path) -> None:
    assert retrieve_repo_context("anything", wiki_dir=tmp_path / "nope") is None


def test_no_overlap_returns_none(tmp_path: Path) -> None:
    auto = _make_wiki(tmp_path, [("Browser", "b.md", "playwright chromium")])
    assert retrieve_repo_context("quantum entanglement theory", wiki_dir=auto) is None


def test_empty_or_stopword_query_returns_none(tmp_path: Path) -> None:
    auto = _make_wiki(tmp_path, [("Topic", "x.md", "content")])
    assert retrieve_repo_context("", wiki_dir=auto) is None
    assert retrieve_repo_context("the and for you", wiki_dir=auto) is None


def test_budget_truncates_long_pages(tmp_path: Path) -> None:
    big = "alpha\n" + ("word " * 5000)
    auto = _make_wiki(tmp_path, [("Alpha topic", "a.md", big)])
    out = retrieve_repo_context("alpha", wiki_dir=auto, budget_tokens=100, max_pages=1)
    assert out is not None
    assert "(truncated)" in out
    assert len(out) < 1200


def test_cache_refreshes_on_mtime(tmp_path: Path) -> None:
    auto = _make_wiki(tmp_path, [("Alpha topic", "a.md", "alpha content one")])
    assert "content one" in (retrieve_repo_context("alpha", wiki_dir=auto) or "")
    # rewrite the page and bump index.json mtime → cache must invalidate
    (auto / "a.md").write_text("alpha content two", encoding="utf-8")
    idx = auto / "index.json"
    idx.write_text(idx.read_text())
    future = time.time() + 10
    os.utime(idx, (future, future))
    assert "content two" in (retrieve_repo_context("alpha", wiki_dir=auto) or "")


def test_identifier_tokenization_splits_camel_and_snake() -> None:
    assert set(_tokenize("ToolEngine")) >= {"tool", "engine"}
    assert set(_tokenize("tool_engine executor")) >= {"tool", "engine", "executor"}
    assert set(_tokenize("HTTPServer")) >= {"http", "server"}
    assert "规划" in _tokenize("cerebrum 规划")


def test_word_goal_matches_camelcase_identifier(tmp_path: Path) -> None:
    auto = _make_wiki(tmp_path, [
        ("Engine", "e.md", "The ToolEngine executes skills via execute_token."),
        ("Other", "o.md", "unrelated browser playwright content"),
    ])
    out = retrieve_repo_context("how does the tool engine execute", wiki_dir=auto)
    assert out is not None and "ToolEngine" in out


def test_bm25_length_normalization_beats_long_page(tmp_path: Path) -> None:
    # Both pages contain the query terms, but the catalog page buries them in
    # 1800 unrelated tokens. Plain overlap would tie (or favour the long page);
    # BM25 length-normalizes so the short on-topic page wins.
    short = "Cerebrum planner: plans tool calls."
    longp = "cerebrum planner " + ("catalog skill registry module export summary " * 300)
    auto = _make_wiki(tmp_path, [
        ("Cerebrum planning", "cere.md", short),
        ("Skills catalog", "cat.md", longp),
    ])
    out = retrieve_repo_context("cerebrum planner", wiki_dir=auto, max_pages=1)
    assert out is not None
    assert "Cerebrum planning" in out
    assert "Skills catalog" not in out


def test_real_wiki_smoke() -> None:
    # the repo ships a generated wiki under docs/auto
    out = retrieve_repo_context("cerebrum planner tool engine skills", wiki_dir="docs/auto")
    assert out is None or "CODEBASE DOCS" in out
