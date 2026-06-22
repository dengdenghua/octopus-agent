"""Auto-retrieval of relevant source chunks for planner grounding."""
from __future__ import annotations

from pathlib import Path

from runtime.memory.hemolymph.code_index import retrieve_code_context


def _make_src(root: Path, files: dict[str, str]) -> None:
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")


def test_retrieves_relevant_source_chunk(tmp_path: Path) -> None:
    _make_src(tmp_path, {
        "runtime/planner.py": "def plan_tool_calls():\n    # planner builds react steps\n    return step()\n",
        "runtime/browser.py": "def open_browser():\n    return playwright_launch()\n",
    })
    out = retrieve_code_context("how does plan_tool_calls work", root=tmp_path)
    assert out is not None
    assert "runtime/planner.py:1" in out
    assert "plan_tool_calls" in out
    assert "browser" not in out  # no overlap → not selected


def test_skips_noise_dirs(tmp_path: Path) -> None:
    _make_src(tmp_path, {
        "node_modules/pkg/index.py": "def widget_factory(): return alpha()\n",
        "tests/test_x.py": "def widget_factory(): pass\n",
        "src/real.py": "def widget_factory():\n    return real_impl()\n",
    })
    out = retrieve_code_context("widget factory", root=tmp_path)
    assert out is not None
    assert "src/real.py" in out
    assert "node_modules" not in out
    assert "tests/" not in out


def test_no_source_returns_none(tmp_path: Path) -> None:
    (tmp_path / "readme.md").write_text("not code", encoding="utf-8")
    assert retrieve_code_context("anything", root=tmp_path) is None


def test_no_overlap_returns_none(tmp_path: Path) -> None:
    _make_src(tmp_path, {"a.py": "def alpha(): return beta()\n"})
    assert retrieve_code_context("quantum chromodynamics lattice", root=tmp_path) is None


def test_word_query_matches_camelcase_symbol(tmp_path: Path) -> None:
    _make_src(tmp_path, {"a.py": "class ToolEngine:\n    def execute(self):\n        return run()\n"})
    out = retrieve_code_context("tool engine execute", root=tmp_path)
    assert out is not None and "ToolEngine" in out


def test_empty_or_stopword_query_returns_none(tmp_path: Path) -> None:
    _make_src(tmp_path, {"a.py": "def x(): pass\n"})
    assert retrieve_code_context("", root=tmp_path) is None
    assert retrieve_code_context("the and for", root=tmp_path) is None


def test_cache_respects_ttl(tmp_path: Path) -> None:
    _make_src(tmp_path, {"a.py": "def alpha_one(): pass\n"})
    assert "alpha_one" in (retrieve_code_context("alpha one", root=tmp_path) or "")
    (tmp_path / "a.py").write_text("def alpha_two(): pass\n", encoding="utf-8")
    # ttl=0 forces a rebuild → the new symbol is seen
    assert "alpha_two" in (retrieve_code_context("alpha two", root=tmp_path, ttl=0) or "")


def test_real_repo_smoke() -> None:
    out = retrieve_code_context(
        "compose context segments token budget", root="runtime", max_chunks=2,
    )
    assert out is None or "RELEVANT SOURCE" in out


def test_sink_captures_chosen_chunks_faithfully(tmp_path: Path) -> None:
    _make_src(tmp_path, {
        "runtime/planner.py": "def plan_tool_calls():\n    # planner builds react steps\n    return step()\n",
        "runtime/browser.py": "def open_browser():\n    return playwright_launch()\n",
    })
    sink: list[dict[str, str]] = []
    out = retrieve_code_context("how does plan_tool_calls work", root=tmp_path, _sink=sink)
    assert out is not None
    # the sink lists EXACTLY the chunk(s) folded into the prompt — same scoring,
    # so a UI chip can't drift from what was actually injected.
    assert sink == [
        {"kind": "source", "title": "planner.py", "path": "runtime/planner.py:1"},
    ]
    assert sink[0]["path"] in out  # faithful: the cited path is in the prompt
