"""Tests for post-write diagnostics hook.

Covers the auto-triggered lint/typecheck path that fires after every
successful code-write tool. The hook is best-effort — every failure
mode (timeout, missing tool, no project, non-write skill) returns
``None`` rather than raising.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from runtime.safety.hooks.tool_edge_hooks import (
    post_write_diagnostic_record,
    post_write_diagnostics,
    post_write_regression_matrix,
    regression_matrix_for_path,
)


def _make_python_project(tmp_path: Path) -> Path:
    """Create a minimal python project marker so detect_project() returns 'python'."""
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname = 'fixture'\nversion = '0.0.0'\n",
        encoding="utf-8",
    )
    return tmp_path


def test_successful_write_clean_python_returns_none(tmp_path: Path) -> None:
    """Clean python file → ruff passes → hook returns None."""
    proj = _make_python_project(tmp_path)
    target = proj / "ok.py"
    target.write_text(
        "def add(a: int, b: int) -> int:\n    return a + b\n",
        encoding="utf-8",
    )
    out = post_write_diagnostics(
        "write_text_file",
        {"path": str(target)},
        {"path": str(target), "bytes_written": target.stat().st_size},
        workspace_path=str(proj),
    )
    assert out is None


def test_python_syntax_error_returns_string(tmp_path: Path) -> None:
    """Bad python file → ruff fails → hook returns string mentioning ruff."""
    proj = _make_python_project(tmp_path)
    target = proj / "bad.py"
    # syntax error: unmatched paren / missing body
    target.write_text("def foo( \n", encoding="utf-8")
    out = post_write_diagnostics(
        "write_text_file",
        {"path": str(target)},
        {"path": str(target)},
        workspace_path=str(proj),
    )
    assert out is not None
    lower = out.lower()
    # ruff prefix in the formatted output OR a syntax-error mention from ruff
    assert "ruff" in lower or "syntax" in lower


def test_post_write_diagnostic_record_covers_write_file_alias(tmp_path: Path) -> None:
    """write_file aliases must produce an auditable post-write record."""
    proj = _make_python_project(tmp_path)
    target = proj / "ok.py"
    target.write_text("x = 1\n", encoding="utf-8")

    out = post_write_diagnostic_record(
        "write_file",
        {"path": str(target)},
        {"path": str(target)},
        workspace_path=str(proj),
    )

    assert out["schema"] == "octopus.post_write_diagnostic_record.v1"
    assert out["tool_name"] == "write_file"
    assert out["target"] == str(target)
    assert out["status"] in {"passed", "failed"}
    assert out["required"] is True


def test_non_write_tool_returns_none(tmp_path: Path) -> None:
    """read_file → hook short-circuits, no subprocess invoked."""
    proj = _make_python_project(tmp_path)
    target = proj / "any.py"
    target.write_text("def foo( \n", encoding="utf-8")
    # If the hook fired ruff on this bad file, we'd get a string back.
    # Asserting None proves the early-return for non-write tools fires
    # before any subprocess spawn.
    with patch(
        "runtime.execution.suckers.verify_skills.detect_project"
    ) as mock_detect:
        out = post_write_diagnostics(
            "read_file",
            {"path": str(target)},
            {"path": str(target), "content": "def foo( "},
            workspace_path=str(proj),
        )
    assert out is None
    # detect_project must not even be called for non-write tools
    mock_detect.assert_not_called()


def test_workspace_not_a_project_returns_none(tmp_path: Path) -> None:
    """Workspace with no project markers → 'unknown' kind → returns None."""
    # tmp_path has no pyproject.toml / package.json / Cargo.toml / go.mod
    target = tmp_path / "loose.py"
    target.write_text("def foo( \n", encoding="utf-8")
    out = post_write_diagnostics(
        "edit_text_file",
        {"path": str(target)},
        {"path": str(target)},
        workspace_path=str(tmp_path),
    )
    assert out is None


def test_result_with_error_key_no_path_returns_none(tmp_path: Path) -> None:
    """Failed write (error key, no path) → diagnostics skipped."""
    proj = _make_python_project(tmp_path)
    target = proj / "wont-exist.py"
    out = post_write_diagnostics(
        "write_text_file",
        {"path": str(target)},
        {"error": "permission denied"},
        workspace_path=str(proj),
    )
    assert out is None


def test_unsupported_language_returns_none(tmp_path: Path) -> None:
    """Markdown file → no language-specific check → returns None."""
    proj = _make_python_project(tmp_path)
    target = proj / "README.md"
    target.write_text("# hello\n", encoding="utf-8")
    out = post_write_diagnostics(
        "write_text_file",
        {"path": str(target)},
        {"path": str(target)},
        workspace_path=str(proj),
    )
    assert out is None


def test_detect_project_failure_returns_none(tmp_path: Path) -> None:
    """detect_project blowing up → swallowed silently."""
    proj = _make_python_project(tmp_path)
    target = proj / "x.py"
    target.write_text("def foo( \n", encoding="utf-8")
    with patch(
        "runtime.execution.suckers.verify_skills.detect_project",
        side_effect=RuntimeError("boom"),
    ):
        out = post_write_diagnostics(
            "write_text_file",
            {"path": str(target)},
            {"path": str(target)},
            workspace_path=str(proj),
        )
    assert out is None


def test_regression_matrix_recommends_python_hook_tests(tmp_path: Path) -> None:
    proj = _make_python_project(tmp_path)
    target = proj / "runtime" / "safety" / "hooks" / "tool_edge_hooks.py"
    target.parent.mkdir(parents=True)
    target.write_text("VALUE = 1\n", encoding="utf-8")
    tests_dir = proj / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_tool_edge_hooks.py").write_text("def test_ok(): pass\n", encoding="utf-8")
    (tests_dir / "test_post_write_diagnostics.py").write_text(
        "def test_ok(): pass\n",
        encoding="utf-8",
    )

    out = post_write_regression_matrix(
        "write_text_file",
        {"path": str(target)},
        {"path": str(target)},
        workspace_path=str(proj),
    )

    assert out is not None
    assert "python -m ruff check runtime/safety/hooks/tool_edge_hooks.py" in out
    assert "python -m pytest tests/test_tool_edge_hooks.py -q" in out
    assert "python -m pytest tests/test_post_write_diagnostics.py -q" in out


def test_regression_matrix_recommends_frontend_colocated_test(tmp_path: Path) -> None:
    proj = tmp_path
    frontend = proj / "frontend"
    source = frontend / "src" / "components" / "widget.tsx"
    source.parent.mkdir(parents=True)
    source.write_text("export function Widget() { return null }\n", encoding="utf-8")
    (source.parent / "widget.test.tsx").write_text("test('ok', () => {})\n", encoding="utf-8")
    (frontend / "package.json").write_text('{"scripts":{"check":"tsc --noEmit"}}\n', encoding="utf-8")

    matrix = regression_matrix_for_path(source, workspace_path=proj)
    rendered = matrix.render()

    assert rendered is not None
    assert "cd frontend && pnpm vitest run src/components/widget.test.tsx" in rendered
    assert "cd frontend && pnpm check" in rendered


def test_regression_matrix_skips_non_write_tool(tmp_path: Path) -> None:
    proj = _make_python_project(tmp_path)
    target = proj / "x.py"
    target.write_text("VALUE = 1\n", encoding="utf-8")

    out = post_write_regression_matrix(
        "read_file",
        {"path": str(target)},
        {"path": str(target)},
        workspace_path=str(proj),
    )

    assert out is None
