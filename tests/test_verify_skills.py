import sys
from pathlib import Path

from runtime.execution.suckers.verify_skills import (
    ProjectProfile,
    classify_environment_gap,
    detect_project,
    run_checks,
)


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


def test_run_checks_rejects_project_root_outside_sandbox(tmp_path: Path) -> None:
    sandbox = tmp_path / "sandbox"
    outside = tmp_path / "outside"
    sandbox.mkdir()
    outside.mkdir()
    profile = ProjectProfile(
        kind="custom",
        root=str(outside),
        checks=[
            {
                "name": "cwd",
                "argv": [sys.executable, "-c", "print('should not run')"],
                "display_cmd": "python -c cwd",
            },
        ],
    )

    [result] = run_checks(profile, sandbox_dir=str(sandbox), timeout_per_check=10)

    assert result.passed is False
    assert result.exit_code == -4
    assert "sandbox_violation" in result.stderr
    assert result.execution_policy["schema"] == "octopus.execution_policy.v1"
    assert result.execution_policy["sandbox_requested"] is True
    assert result.execution_policy["workspace"] == str(sandbox.resolve())


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


def test_python_typecheck_offered_only_when_mypy_installed(tmp_path: Path) -> None:
    # A missing checker must not become a check: "No module named mypy"
    # would be reported as a typecheck FAILURE and injected into the
    # agent's auto-diagnostics after every file write.
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'demo'\n", encoding="utf-8")

    profile = detect_project(str(tmp_path))
    names = [check["name"] for check in profile.checks]

    import importlib.util

    if importlib.util.find_spec("mypy") is None:
        assert "typecheck" not in names
    else:
        assert "typecheck" in names
    # The dependency-free syntax check is always available as the
    # fast-path candidate for auto-diagnostics.
    assert "syntax" in names


def test_python_pytest_offered_only_when_pytest_installed(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'demo'\n", encoding="utf-8")

    profile = detect_project(str(tmp_path))
    names = [check["name"] for check in profile.checks]

    import importlib.util

    if importlib.util.find_spec("pytest") is None:
        assert "test" not in names
    else:
        assert "test" in names
    assert "syntax" in names


def test_node_typecheck_offered_only_when_tsc_installed(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"name": "demo", "scripts": {}}', encoding="utf-8")
    (tmp_path / "tsconfig.json").write_text("{}", encoding="utf-8")

    # No node_modules/.bin/tsc → no typecheck entry (a bare ``npx tsc``
    # could hit the network to fetch the package).
    profile = detect_project(str(tmp_path))
    assert [check["name"] for check in profile.checks] == ["package-json"]

    bin_dir = tmp_path / "node_modules" / ".bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "tsc").write_text("#!/bin/sh\n", encoding="utf-8")

    profile = detect_project(str(tmp_path))
    typecheck = next(check for check in profile.checks if check["name"] == "typecheck")
    assert "--no-install" in typecheck["argv"]


def test_node_checks_fall_back_without_npm_or_npx(tmp_path: Path, monkeypatch) -> None:
    import runtime.execution.suckers.verify_skills as verify_skills

    (tmp_path / "package.json").write_text(
        (
            '{"name": "demo", "scripts": '
            '{"lint": "eslint .", "test": "vitest", "build": "vite build"}}'
        ),
        encoding="utf-8",
    )
    (tmp_path / "tsconfig.json").write_text("{}", encoding="utf-8")
    bin_dir = tmp_path / "node_modules" / ".bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "tsc").write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(verify_skills, "_executable_available", lambda name: False)

    profile = detect_project(str(tmp_path))

    assert profile.kind == "node-ts"
    assert [check["name"] for check in profile.checks] == ["package-json"]
    argv = profile.checks[0]["argv"]
    assert isinstance(argv, list)
    assert argv[0]
    assert "npm" not in argv
    assert "npx" not in argv


def test_node_without_scripts_uses_dependency_free_manifest_check(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"name": "demo", "scripts": {}}', encoding="utf-8")

    profile = detect_project(str(tmp_path))

    assert [check["name"] for check in profile.checks] == ["package-json"]
    [result] = run_checks(profile, timeout_per_check=10)
    assert result.passed is True
    assert result.stdout.strip() == "package=demo scripts=0"
    assert result.execution_policy["schema"] == "octopus.execution_policy.v1"
    assert result.execution_policy["sandbox_requested"] is True
    assert result.execution_policy["process_tree_kill"] is True


def test_invalid_package_json_fails_as_manifest_check(tmp_path: Path, monkeypatch) -> None:
    import runtime.execution.suckers.verify_skills as verify_skills

    (tmp_path / "package.json").write_text('{"name": "demo",', encoding="utf-8")
    monkeypatch.setattr(verify_skills, "_executable_available", lambda name: False)

    profile = detect_project(str(tmp_path))

    assert [check["name"] for check in profile.checks] == ["package-json"]
    [result] = run_checks(profile, timeout_per_check=10)
    assert result.passed is False
    assert result.exit_code == 2
    assert "invalid JSON" in result.stderr


def test_invalid_pyproject_fails_before_syntax_check(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project\nname = 'demo'\n", encoding="utf-8")
    (tmp_path / "app.py").write_text("x = 1\n", encoding="utf-8")

    profile = detect_project(str(tmp_path))
    assert profile.checks[0]["name"] == "pyproject"

    results = run_checks(profile, timeout_per_check=10)
    pyproject = results[0]
    assert pyproject.passed is False
    assert pyproject.exit_code == 2
    assert "invalid TOML" in pyproject.stderr


def test_run_checks_normalizes_cancelled_stream_result(tmp_path: Path, monkeypatch) -> None:
    import runtime.platform.process.streaming as streaming

    def fake_stream_run(*args, **kwargs):
        return {
            "stdout": "partial output",
            "stderr": "",
            "exit_code": None,
            "timed_out": False,
            "cancelled": True,
        }

    monkeypatch.setattr(streaming, "stream_run", fake_stream_run)
    profile = ProjectProfile(
        kind="unknown",
        root=str(tmp_path),
        checks=[{"name": "slow", "argv": ["tool"], "display_cmd": "tool"}],
    )

    [result] = run_checks(profile, timeout_per_check=10)

    assert result.passed is False
    assert result.exit_code == -5
    assert result.stdout == "partial output"
    assert result.stderr == "cancelled"


def test_run_checks_caps_mocked_output_by_utf8_bytes(tmp_path: Path, monkeypatch) -> None:
    import runtime.platform.process.streaming as streaming

    def fake_stream_run(*args, **kwargs):
        return {
            "stdout": "\u754c" * 10,
            "stderr": "\u9519" * 10,
            "exit_code": 1,
            "timed_out": False,
        }

    monkeypatch.setattr(streaming, "stream_run", fake_stream_run)
    profile = ProjectProfile(
        kind="unknown",
        root=str(tmp_path),
        checks=[{"name": "unicode", "argv": ["tool"], "display_cmd": "tool"}],
    )

    [result] = run_checks(profile, timeout_per_check=10, max_output=5)

    assert result.passed is False
    assert result.stdout == "\u754c"
    assert result.stderr == "\u9519"
    assert len(result.stdout.encode("utf-8")) <= 5
    assert len(result.stderr.encode("utf-8")) <= 5


def test_run_checks_legacy_cmd_uses_stream_policy(tmp_path: Path) -> None:
    profile = ProjectProfile(
        kind="legacy",
        root=str(tmp_path),
        checks=[
            {
                "name": "legacy",
                "cmd": f"{sys.executable} -c \"print('legacy-ok')\"",
            }
        ],
    )

    [result] = run_checks(profile, timeout_per_check=10)

    assert result.passed is True
    assert result.stdout.strip() == "legacy-ok"
    assert result.execution_policy["schema"] == "octopus.execution_policy.v1"
    assert result.execution_policy["sandbox_requested"] is True
    assert result.execution_policy["result"]["status"] == "completed"
    assert result.execution_policy["result"]["exit_code"] == 0


def test_run_checks_legacy_cmd_timeout_has_execution_policy(tmp_path: Path) -> None:
    profile = ProjectProfile(
        kind="legacy",
        root=str(tmp_path),
        checks=[
            {
                "name": "legacy-timeout",
                "cmd": f'{sys.executable} -c "import time; time.sleep(5)"',
            }
        ],
    )

    [result] = run_checks(profile, timeout_per_check=0.2)

    assert result.passed is False
    assert result.exit_code == -1
    assert result.stderr == "timeout"
    assert result.execution_policy["schema"] == "octopus.execution_policy.v1"
    assert result.execution_policy["result"]["status"] == "timed_out"
    assert result.execution_policy["result"]["timed_out"] is True


def test_run_checks_normalizes_malformed_stream_result(tmp_path: Path, monkeypatch) -> None:
    import runtime.platform.process.streaming as streaming

    monkeypatch.setattr(
        streaming,
        "stream_run",
        lambda *args, **kwargs: {"stdout": "", "stderr": "", "timed_out": False},
    )
    profile = ProjectProfile(
        kind="unknown",
        root=str(tmp_path),
        checks=[{"name": "odd", "argv": ["tool"], "display_cmd": "tool"}],
    )

    [result] = run_checks(profile, timeout_per_check=10)

    assert result.passed is False
    assert result.exit_code == -6
    assert "no exit_code" in result.stderr


def test_rust_checks_fall_back_without_cargo(tmp_path: Path, monkeypatch) -> None:
    import runtime.execution.suckers.verify_skills as verify_skills

    (tmp_path / "Cargo.toml").write_text("[package]\nname = 'demo'\n", encoding="utf-8")
    monkeypatch.setattr(verify_skills, "_executable_available", lambda name: False)

    profile = detect_project(str(tmp_path))

    assert profile.kind == "rust"
    assert [check["name"] for check in profile.checks] == ["cargo-manifest"]
    assert profile.checks[0]["argv"][0]


def test_rust_manifest_precheck_runs_before_cargo(tmp_path: Path, monkeypatch) -> None:
    import runtime.execution.suckers.verify_skills as verify_skills

    (tmp_path / "Cargo.toml").write_text("[package]\nname = 'demo'\n", encoding="utf-8")
    monkeypatch.setattr(verify_skills, "_executable_available", lambda name: True)

    profile = detect_project(str(tmp_path))

    assert profile.checks[0]["name"] == "cargo-manifest"
    assert "check" in [check["name"] for check in profile.checks]


def test_go_checks_fall_back_without_go_tool(tmp_path: Path, monkeypatch) -> None:
    import runtime.execution.suckers.verify_skills as verify_skills

    (tmp_path / "go.mod").write_text("module example.com/demo\n", encoding="utf-8")
    monkeypatch.setattr(verify_skills, "_executable_available", lambda name: False)

    profile = detect_project(str(tmp_path))

    assert profile.kind == "go"
    assert [check["name"] for check in profile.checks] == ["go-manifest"]
    assert profile.checks[0]["argv"][0]


def test_go_manifest_precheck_runs_before_go_commands(tmp_path: Path, monkeypatch) -> None:
    import runtime.execution.suckers.verify_skills as verify_skills

    (tmp_path / "go.mod").write_text("module example.com/demo\n", encoding="utf-8")
    monkeypatch.setattr(verify_skills, "_executable_available", lambda name: True)

    profile = detect_project(str(tmp_path))

    assert profile.checks[0]["name"] == "go-manifest"
    assert "build" in [check["name"] for check in profile.checks]


def test_auto_diagnostics_skips_missing_tool_output() -> None:
    from runtime.core.cerebrum.react_execution import _output_indicates_missing_tool

    assert _output_indicates_missing_tool("/usr/bin/python3: No module named mypy")
    assert _output_indicates_missing_tool("sh: tsc: command not found")
    assert _output_indicates_missing_tool("npm error could not determine executable to run")
    assert not _output_indicates_missing_tool(
        "error TS2345: Argument of type 'string' is not assignable"
    )
    assert not _output_indicates_missing_tool("app.py:3: SyntaxError")


def test_environment_gap_classifier_distinguishes_tool_and_dependency() -> None:
    assert classify_environment_gap("sh: tsc: command not found") == "environment_missing_tool"
    assert (
        classify_environment_gap("/usr/bin/python3: No module named pytest")
        == "environment_missing_dependency"
    )
    assert classify_environment_gap("AssertionError: expected 200 got 500") == ""
