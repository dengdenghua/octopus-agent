from pathlib import Path

from runtime.execution.suckers.verify_skills import detect_project, run_checks


def test_unknown_project_file_count_is_cross_platform(tmp_path: Path) -> None:
    (tmp_path / "website").mkdir()
    (tmp_path / "website" / "index.html").write_text("<!doctype html>", encoding="utf-8")

    profile = detect_project(str(tmp_path))

    assert profile.kind == "unknown"
    assert profile.checks[0]["name"] == "file-count"
    # No Unix-only shell pipes in the argv — runs on Windows too.
    argv = profile.checks[0]["argv"]
    assert isinstance(argv, list) and argv
    joined = " ".join(argv)
    assert "find . -maxdepth" not in joined
    assert "wc -l" not in joined

    [result] = run_checks(profile, timeout_per_check=10)
    assert result.passed is True
    assert result.stdout.strip() == "1"
    assert result.command == 'python -c "count files up to depth 3"'


def test_python_syntax_check_avoids_unix_pipes(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'demo'\n", encoding="utf-8")
    (tmp_path / "app.py").write_text("x = 1\n", encoding="utf-8")

    profile = detect_project(str(tmp_path))
    syntax = next(check for check in profile.checks if check["name"] == "syntax")

    argv = syntax["argv"]
    assert isinstance(argv, list) and argv
    joined = " ".join(argv)
    assert "find ." not in joined
    assert "head -" not in joined
    # Inline code still uses py_compile — no shell piping required.
    assert "py_compile" in joined
