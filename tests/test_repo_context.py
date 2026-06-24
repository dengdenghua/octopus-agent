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
    build_codebase_context,
    collect_codebase_sources,
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
        json.dumps({"version": 2, "tree": tree}),
        encoding="utf-8",
    )
    return auto


def test_retrieves_most_relevant_page(tmp_path: Path) -> None:
    auto = _make_wiki(
        tmp_path,
        [
            (
                "Cerebrum planning",
                "cerebrum.md",
                "The planner builds a ReAct loop with tool calls.",
            ),
            ("Browser automation", "browser.md", "Playwright drives chromium via skills."),
        ],
    )
    out = retrieve_repo_context("how does the planner cerebrum work", wiki_dir=auto)
    assert out is not None
    assert "Cerebrum planning" in out and "ReAct loop" in out
    assert "Browser automation" not in out  # no overlap → not selected


def test_nested_tree_is_flattened() -> None:
    tree = [
        {"type": "doc", "title": "A", "path": "a.md"},
        {
            "type": "dir",
            "title": "D",
            "children": [
                {"type": "doc", "title": "B", "path": "d/b.md"},
            ],
        },
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


def test_cjk_run_emits_bigrams_and_whole_run() -> None:
    # A CJK run yields its adjacent bigrams (partial-overlap signal) AND the
    # whole run (exact-match signal). ADR-009 Phase 0: whole-run-only made BM25
    # weak on Chinese — a CN goal shares bigrams, not whole runs, with a CN doc.
    toks = set(_tokenize("简历优化"))
    assert {"简历", "历优", "优化"} <= toks  # bigrams
    assert "简历优化" in toks  # whole run still present
    # 2-char run: its only bigram is itself, so single domain words still surface
    assert "规划" in _tokenize("规划")


def test_retrieves_chinese_page_by_bigram_overlap(tmp_path: Path) -> None:
    # No shared *whole* CJK run and no shared English token between goal and the
    # target page — only shared bigrams (简历 / 关键 / 键词). Whole-run-only
    # tokenization missed this; bigrams retrieve it.
    auto = _make_wiki(
        tmp_path,
        [
            ("简历助手", "resume.md", "简历优化与关键词匹配分析"),
            ("浏览器", "b.md", "playwright chromium 自动化测试"),
        ],
    )
    out = retrieve_repo_context("帮我改简历做关键词", wiki_dir=auto)
    assert out is not None
    assert "简历助手" in out
    assert "浏览器" not in out


def test_word_goal_matches_camelcase_identifier(tmp_path: Path) -> None:
    auto = _make_wiki(
        tmp_path,
        [
            ("Engine", "e.md", "The ToolEngine executes skills via execute_token."),
            ("Other", "o.md", "unrelated browser playwright content"),
        ],
    )
    out = retrieve_repo_context("how does the tool engine execute", wiki_dir=auto)
    assert out is not None and "ToolEngine" in out


def test_bm25_length_normalization_beats_long_page(tmp_path: Path) -> None:
    # Both pages contain the query terms, but the catalog page buries them in
    # 1800 unrelated tokens. Plain overlap would tie (or favour the long page);
    # BM25 length-normalizes so the short on-topic page wins.
    short = "Cerebrum planner: plans tool calls."
    longp = "cerebrum planner " + ("catalog skill registry module export summary " * 300)
    auto = _make_wiki(
        tmp_path,
        [
            ("Cerebrum planning", "cere.md", short),
            ("Skills catalog", "cat.md", longp),
        ],
    )
    out = retrieve_repo_context("cerebrum planner", wiki_dir=auto, max_pages=1)
    assert out is not None
    assert "Cerebrum planning" in out
    assert "Skills catalog" not in out


def test_real_wiki_smoke() -> None:
    # the repo ships a generated wiki under docs/auto
    out = retrieve_repo_context("cerebrum planner tool engine skills", wiki_dir="docs/auto")
    assert out is None or "CODEBASE DOCS" in out


# ── render_codebase_context: shared wiki+code grounding (planner + chat) ──


def test_render_codebase_context_combines_wiki_and_code(monkeypatch) -> None:
    import runtime.memory.hemolymph.code_index as ci
    import runtime.memory.hemolymph.repo_context as rc

    monkeypatch.delenv("OCTOPUS_CODEBASE_CONTEXT", raising=False)
    monkeypatch.setattr(rc, "retrieve_repo_context", lambda goal, **k: "WIKI-PART")
    monkeypatch.setattr(ci, "retrieve_code_context", lambda goal, **k: "CODE-PART")
    out = rc.render_codebase_context("fix the planner")
    assert "WIKI-PART" in out and "CODE-PART" in out


def test_render_codebase_context_empty_goal_and_env_off(monkeypatch) -> None:
    import runtime.memory.hemolymph.repo_context as rc

    monkeypatch.delenv("OCTOPUS_CODEBASE_CONTEXT", raising=False)
    assert rc.render_codebase_context("") == ""
    assert rc.render_codebase_context("   ") == ""
    monkeypatch.setenv("OCTOPUS_CODEBASE_CONTEXT", "0")
    assert rc.render_codebase_context("anything") == ""


# ── grounding sources: faithful to what render_codebase_context injects ──


def test_sink_captures_chosen_doc_faithfully(tmp_path: Path) -> None:
    auto = _make_wiki(
        tmp_path,
        [
            ("Cerebrum planning", "cerebrum.md", "The planner builds a ReAct loop."),
            ("Browser automation", "browser.md", "Playwright drives chromium."),
        ],
    )
    sink: list[dict[str, str]] = []
    out = retrieve_repo_context("how does the planner cerebrum work", wiki_dir=auto, _sink=sink)
    assert out is not None
    assert sink == [{"kind": "doc", "title": "Cerebrum planning", "path": "cerebrum.md"}]
    assert all(s["path"] in out for s in sink)  # every cited path is in the prompt


def test_build_codebase_context_returns_text_and_sources(monkeypatch) -> None:
    import runtime.memory.hemolymph.code_index as ci
    import runtime.memory.hemolymph.repo_context as rc

    monkeypatch.delenv("OCTOPUS_CODEBASE_CONTEXT", raising=False)

    def _fake_wiki(goal: str, **k: Any) -> str:
        sink = k.get("_sink")
        if sink is not None:
            sink.append({"kind": "doc", "title": "Cerebrum", "path": "cerebrum.md"})
        return "WIKI-PART"

    def _fake_code(goal: str, **k: Any) -> str:
        sink = k.get("_sink")
        if sink is not None:
            sink.append({"kind": "source", "title": "planner.py", "path": "p.py:1"})
        return "CODE-PART"

    monkeypatch.setattr(rc, "retrieve_repo_context", _fake_wiki)
    monkeypatch.setattr(ci, "retrieve_code_context", _fake_code)

    text, sources = build_codebase_context("fix the planner")
    assert "WIKI-PART" in text and "CODE-PART" in text
    assert sources == [
        {"kind": "doc", "title": "Cerebrum", "path": "cerebrum.md"},
        {"kind": "source", "title": "planner.py", "path": "p.py:1"},
    ]
    # collect_codebase_sources is just the sources half
    assert collect_codebase_sources("fix the planner") == sources


def test_collect_codebase_sources_empty_when_off(monkeypatch) -> None:
    monkeypatch.setenv("OCTOPUS_CODEBASE_CONTEXT", "0")
    assert collect_codebase_sources("anything") == []
    monkeypatch.delenv("OCTOPUS_CODEBASE_CONTEXT", raising=False)
    assert collect_codebase_sources("") == []
