"""Implementation note."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from runtime.execution.suckers import SkillRegistry
from runtime.execution.suckers.write_skills import (
    _BACKGROUND_PROCESSES,
    EXEC_SKILL_NAME,
    WRITE_SKILL_NAMES,
    _append_text_file,
    _background_exec,
    _edit_file,
    _edit_text_file,
    _exec_shell,
    _format_code,
    _ipython,
    _kill_background_exec,
    _kill_shell,
    _lint_check,
    _multi_edit_file,
    _read_background_output,
    _read_shell_output,
    _run_git,
    _run_quality_cmd,
    _run_tests,
    _snapshot_background_metadata,
    _write_text_file,
    register_exec_skill,
    register_write_skills,
)


def _stream_error_result(status: str = "sandbox_violation") -> dict[str, object]:
    return {
        "error": f"{status}: denied by policy",
        "execution_policy": {
            "schema": "octopus.execution_policy.v1",
            "sandbox_requested": True,
            "backend": "direct",
            "hard": False,
            "result": {
                "status": status,
                "exit_code": None,
                "timed_out": False,
                "cancelled": False,
                "killed": False,
                "stdout_truncated": False,
                "stderr_truncated": False,
                "output_truncated": False,
                "error_type": status,
            },
        },
    }


# ═══════════════════════════════════════════════════════════
# write_text_file
# ═══════════════════════════════════════════════════════════


class TestWriteTextFile:
    def test_create_new_file(self, tmp_path: Path):
        p = tmp_path / "out.txt"
        r = _write_text_file(path=str(p), content="hello")
        assert "error" not in r
        assert p.read_text(encoding="utf-8") == "hello"
        assert r["bytes_written"] == 5

    def test_write_marks_verified_on_disk(self, tmp_path: Path):
        """Write-after verification (Hermes parity): success returns verified=True."""
        p = tmp_path / "verify.txt"
        r = _write_text_file(path=str(p), content="hello")
        assert "error" not in r
        assert r["verified"] is True
        assert "verify_error" not in r

    def test_write_reports_read_back_failure(self, tmp_path: Path, monkeypatch):
        """A read-back failure surfaces as verify_error, not silent success."""
        from pathlib import Path as PathCls

        p = tmp_path / "verify-fail.txt"

        def broken_read_bytes(self, *args, **kwargs):
            raise OSError("simulated read-back failure")

        monkeypatch.setattr(PathCls, "read_bytes", broken_read_bytes)
        r = _write_text_file(path=str(p), content="hello")
        assert "error" not in r  # write itself succeeded
        assert "verify_error" in r
        assert "read_back_failed" in r["verify_error"]

    def test_write_reports_content_mismatch(self, tmp_path: Path, monkeypatch):
        """Disk content differing from what we wrote is not silently accepted."""
        from pathlib import Path as PathCls

        p = tmp_path / "verify-mismatch.txt"

        real_write_bytes = PathCls.write_bytes

        def corrupt_write_bytes(self, data, *args, **kwargs):
            # Simulate a partial write: only half the bytes land.
            real_write_bytes(self, data[: len(data) // 2])

        monkeypatch.setattr(PathCls, "write_bytes", corrupt_write_bytes)
        r = _write_text_file(path=str(p), content="hello world")
        assert "verify_error" in r
        assert "read_back_mismatch" in r["verify_error"]

    def test_refuse_overwrite_by_default(self, tmp_path: Path):
        p = tmp_path / "exists.txt"
        p.write_text("old", encoding="utf-8")
        r = _write_text_file(path=str(p), content="new")
        assert "error" in r
        assert "exists" in r["error"]
        assert p.read_text(encoding="utf-8") == "old"  # Implementation note.

    def test_overwrite_true_replaces(self, tmp_path: Path):
        p = tmp_path / "exists.txt"
        p.write_text("old", encoding="utf-8")
        r = _write_text_file(path=str(p), content="new", overwrite=True)
        assert "error" not in r
        assert p.read_text(encoding="utf-8") == "new"

    def test_size_cap_rejects_big_content(self, tmp_path: Path):
        p = tmp_path / "big.txt"
        r = _write_text_file(
            path=str(p),
            content="x" * 1000,
            max_bytes=100,
        )
        assert "error" in r
        assert not p.exists()

    def test_creates_parent_directories(self, tmp_path: Path):
        p = tmp_path / "deep" / "nested" / "out.txt"
        r = _write_text_file(path=str(p), content="x")
        assert "error" not in r
        assert p.exists()

    def test_sandbox_dir_allows_inner(self, tmp_path: Path):
        r = _write_text_file(
            path="inner.txt",
            content="x",
            sandbox_dir=str(tmp_path),
        )
        assert "error" not in r
        assert (tmp_path / "inner.txt").exists()

    def test_sandbox_dir_blocks_escape(self, tmp_path: Path):
        outside = tmp_path.parent / f"escape_{tmp_path.name}.txt"
        r = _write_text_file(
            path=str(outside),
            content="pwned",
            sandbox_dir=str(tmp_path),
        )
        assert "error" in r
        assert "escapes_sandbox" in r["error"]
        assert not outside.exists()

    def test_missing_path_error(self):
        r = _write_text_file(path="", content="x")
        assert "error" in r


# ═══════════════════════════════════════════════════════════
# append_text_file
# ═══════════════════════════════════════════════════════════


class TestAppendTextFile:
    def test_create_new(self, tmp_path: Path):
        p = tmp_path / "a.log"
        r = _append_text_file(path=str(p), content="line1\n")
        assert "error" not in r
        assert p.read_text(encoding="utf-8") == "line1\n"

    def test_append_preserves_existing(self, tmp_path: Path):
        p = tmp_path / "a.log"
        p.write_text("line1\n", encoding="utf-8")
        _append_text_file(path=str(p), content="line2\n")
        assert p.read_text(encoding="utf-8") == "line1\nline2\n"

    def test_size_cap(self, tmp_path: Path):
        p = tmp_path / "a.log"
        r = _append_text_file(
            path=str(p),
            content="x" * 1000,
            max_bytes=100,
        )
        assert "error" in r
        assert not p.exists()


# ═══════════════════════════════════════════════════════════
# edit_text_file
# ═══════════════════════════════════════════════════════════


class TestEditTextFile:
    def test_simple_replace(self, tmp_path: Path):
        p = tmp_path / "e.txt"
        p.write_text("hello world · hello again", encoding="utf-8")
        r = _edit_text_file(path=str(p), find="hello", replace="hi")
        assert r["replaced"] == 2
        assert p.read_text(encoding="utf-8") == "hi world · hi again"

    def test_count_limits_replacements(self, tmp_path: Path):
        p = tmp_path / "e.txt"
        p.write_text("a a a a", encoding="utf-8")
        r = _edit_text_file(path=str(p), find="a", replace="b", count=2)
        assert r["replaced"] == 2
        assert p.read_text(encoding="utf-8") == "b b a a"

    def test_find_not_present_error(self, tmp_path: Path):
        p = tmp_path / "e.txt"
        p.write_text("hello", encoding="utf-8")
        r = _edit_text_file(path=str(p), find="nope", replace="x")
        assert "error" in r
        assert r["occurrences"] == 0
        assert p.read_text(encoding="utf-8") == "hello"  # Implementation note.

    def test_missing_find_error(self):
        r = _edit_text_file(path="/tmp/x", find="", replace="y")
        assert "error" in r

    def test_missing_file_error(self, tmp_path: Path):
        r = _edit_text_file(
            path=str(tmp_path / "nope"),
            find="a",
            replace="b",
        )
        assert "error" in r
        assert "not found" in r["error"]


# ─────────────────────────────────────────────────────────────
# edit_file / multi_edit_file
# ─────────────────────────────────────────────────────────────


class TestEditFile:
    def test_unique_replacement(self, tmp_path: Path):
        p = tmp_path / "edit.txt"
        p.write_text("alpha beta gamma", encoding="utf-8")
        r = _edit_file(
            path=str(p),
            old_string="beta",
            new_string="delta",
        )
        assert "error" not in r
        assert p.read_text(encoding="utf-8") == "alpha delta gamma"

    def test_rejects_non_unique_old_string(self, tmp_path: Path):
        p = tmp_path / "edit.txt"
        p.write_text("alpha beta alpha", encoding="utf-8")
        r = _edit_file(
            path=str(p),
            old_string="alpha",
            new_string="omega",
        )
        assert "error" in r
        assert "unique" in r["error"]
        assert p.read_text(encoding="utf-8") == "alpha beta alpha"

    def test_rejects_noop(self, tmp_path: Path):
        p = tmp_path / "edit.txt"
        p.write_text("alpha beta", encoding="utf-8")
        r = _edit_file(
            path=str(p),
            old_string="beta",
            new_string="beta",
        )
        assert "error" in r
        assert "no-op" in r["error"]


class TestMultiEditFile:
    def test_applies_multiple_edits_atomically(self, tmp_path: Path):
        p = tmp_path / "multi.txt"
        p.write_text("one two three", encoding="utf-8")
        r = _multi_edit_file(
            path=str(p),
            edits=[
                {"old_string": "one", "new_string": "1"},
                {"old_string": "three", "new_string": "3"},
            ],
        )
        assert "error" not in r
        assert p.read_text(encoding="utf-8") == "1 two 3"

    def test_rejects_duplicate_old_string(self, tmp_path: Path):
        p = tmp_path / "multi.txt"
        p.write_text("repeat repeat", encoding="utf-8")
        r = _multi_edit_file(
            path=str(p),
            edits=[{"old_string": "repeat", "new_string": "done"}],
        )
        assert "error" in r
        assert "unique" in r["error"]


# ═══════════════════════════════════════════════════════════
# exec_shell
# ═══════════════════════════════════════════════════════════


class TestExecShell:
    def test_simple_str_command_platform_neutral(self):
        """Implementation note."""
        import sys

        # Implementation note.
        r = _exec_shell(command=f"{sys.executable} --version")
        if "error" in r:
            pytest.skip(f"python not runnable: {r}")
        assert r["exit_code"] == 0
        # Implementation note.
        combined = (r["stdout"] or "") + (r["stderr"] or "")
        assert "Python" in combined

    def test_argv_list(self):
        import sys

        r = _exec_shell(command=[sys.executable, "-c", "print(2+2)"])
        assert "error" not in r
        assert "4" in r["stdout"]
        assert r["exit_code"] == 0

    def test_nonzero_exit_returned(self):
        import sys

        r = _exec_shell(command=[sys.executable, "-c", "import sys; sys.exit(3)"])
        assert "error" not in r
        assert r["exit_code"] == 3

    def test_timeout(self):
        import sys

        r = _exec_shell(
            command=[sys.executable, "-c", "import time; time.sleep(5)"],
            timeout_s=0.3,
        )
        assert r.get("timed_out") is True
        assert "timeout" in r["error"]

    def test_command_not_found(self):
        r = _exec_shell(command=["no_such_binary_xyz_1234"])
        assert "error" in r

    def test_stream_error_preserves_execution_policy(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(
            "runtime.platform.process.streaming.stream_run",
            lambda *args, **kwargs: _stream_error_result("sandbox_violation"),
        )

        r = _exec_shell(command=["blocked-tool"], sandbox_dir="/tmp")

        assert "error" in r
        assert r["execution_policy"]["schema"] == "octopus.execution_policy.v1"
        assert r["execution_policy"]["result"]["status"] == "sandbox_violation"
        assert r["execution_policy"]["result"]["error_type"] == "sandbox_violation"

    def test_missing_command_error(self):
        assert "error" in _exec_shell(command="")

    @pytest.mark.parametrize(
        "command",
        (
            "cd tests && python -m pytest",
            "python -m pytest 2>&1",
            ["python", "-m", "pytest", "|", "tee", "result.txt"],
        ),
    )
    def test_shell_operators_fail_loudly_instead_of_false_success(self, command):
        result = _exec_shell(command=command)

        assert "error" in result
        assert "shell operators are not supported" in result["error"]
        assert "cwd" in result["error"]

    def test_cwd_sandbox_blocks_escape(self, tmp_path: Path):
        outside = tmp_path.parent
        r = _exec_shell(
            command=["echo", "x"],
            cwd=str(outside),
            sandbox_dir=str(tmp_path),
        )
        assert "error" in r
        assert "escapes_sandbox" in r["error"]

    def test_sandbox_dir_defaults_cwd_to_workspace(self, tmp_path: Path):
        import sys

        r = _exec_shell(
            command=[
                sys.executable,
                "-c",
                "from pathlib import Path; print(Path.cwd())",
            ],
            sandbox_dir=str(tmp_path),
        )

        assert "error" not in r
        assert Path(r["stdout"].strip()).resolve() == tmp_path.resolve()
        policy = r["execution_policy"]
        assert policy["schema"] == "octopus.execution_policy.v1"
        assert policy["sandbox_requested"] is True
        assert policy["workspace"] == str(tmp_path.resolve())
        assert policy["cwd"] == str(tmp_path.resolve())
        assert policy["env_mode"] == "allowlist"
        assert policy["process_tree_kill"] is True

    def test_sandbox_dir_scrubs_inherited_env(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        import sys

        monkeypatch.setenv("OCTOPUS_TEST_SECRET", "do-not-inherit")

        r = _exec_shell(
            command=[
                sys.executable,
                "-c",
                (
                    "import os\n"
                    "print('secret=' + str('OCTOPUS_TEST_SECRET' in os.environ))\n"
                    "print('explicit=' + os.environ.get('OCTOPUS_EXPLICIT', ''))\n"
                ),
            ],
            env={"OCTOPUS_EXPLICIT": "kept"},
            sandbox_dir=str(tmp_path),
        )

        assert "error" not in r
        assert "secret=False" in r["stdout"]
        assert "explicit=kept" in r["stdout"]

    def test_no_shell_injection(self, tmp_path: Path):
        """Implementation note."""
        import sys

        # Implementation note.
        r = _exec_shell(
            command=[sys.executable, "-c", "print('safe')"],
        )
        assert "error" not in r
        assert r["exit_code"] == 0

    def test_run_in_background_returns_task_id(self):
        import sys

        r = _exec_shell(
            command=[sys.executable, "-u", "-c", "print('ready')"],
            run_in_background=True,
        )
        assert "error" not in r
        assert r["task_id"].startswith("bg_")
        assert "read_shell_output" in r["message"] or "read_background_output" in r["message"]


def test_ipython_stream_error_preserves_execution_policy(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "runtime.platform.process.streaming.stream_run",
        lambda *args, **kwargs: _stream_error_result("sandbox_violation"),
    )

    r = _ipython(code="print('blocked')")

    assert "error" in r
    assert r["execution_policy"]["result"]["status"] == "sandbox_violation"


def test_git_stream_error_preserves_execution_policy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        "runtime.platform.process.streaming.stream_run",
        lambda *args, **kwargs: _stream_error_result("sandbox_violation"),
    )

    r = _run_git(tmp_path, ["status"], timeout_s=1)

    assert "error" in r
    assert r["execution_policy"]["result"]["status"] == "sandbox_violation"


def test_quality_stream_error_preserves_execution_policy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        "runtime.platform.process.streaming.stream_run",
        lambda *args, **kwargs: _stream_error_result("sandbox_violation"),
    )

    r = _run_quality_cmd(["tool"], tmp_path, timeout_s=1)

    assert "error" in r
    assert r["execution_policy"]["result"]["status"] == "sandbox_violation"


def test_python_quality_defaults_disable_tool_caches(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    (tmp_path / "pyproject.toml").write_text("[tool.pytest.ini_options]\n", encoding="utf-8")
    commands: list[list[str]] = []
    timeouts: list[float | None] = []

    def fake_stream_run(command, **kwargs):
        commands.append(command)
        timeouts.append(kwargs.get("timeout"))
        return {
            "exit_code": 0,
            "stdout": "",
            "stderr": "",
            "timed_out": False,
            "sandbox_backend": "direct",
            "sandbox_hard": False,
        }

    monkeypatch.setattr("runtime.platform.process.streaming.stream_run", fake_stream_run)

    assert _run_tests(cwd=str(tmp_path))["success"] is True
    assert _lint_check(cwd=str(tmp_path))["success"] is True
    assert _format_code(cwd=str(tmp_path))["success"] is True

    assert commands[0][3:5] == ["-p", "no:cacheprovider"]
    assert "--no-cache" in commands[1]
    assert "--diff" in commands[1]
    assert "--no-cache" in commands[2]
    assert timeouts == [None, 60.0, 60.0]

    assert _lint_check(cwd=str(tmp_path), fix=True)["success"] is True
    assert "--fix" in commands[3]
    assert "--diff" not in commands[3]


def test_run_tests_forwards_explicit_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    (tmp_path / "pyproject.toml").write_text("[tool.pytest.ini_options]\n", encoding="utf-8")
    observed: dict[str, float | None] = {}

    def fake_stream_run(_command, **kwargs):
        observed["timeout"] = kwargs.get("timeout")
        return {
            "exit_code": 0,
            "stdout": "",
            "stderr": "",
            "timed_out": False,
            "sandbox_backend": "direct",
            "sandbox_hard": False,
        }

    monkeypatch.setattr("runtime.platform.process.streaming.stream_run", fake_stream_run)

    assert _run_tests(cwd=str(tmp_path), timeout_s=12.5)["success"] is True
    assert observed["timeout"] == 12.5


def test_quality_paths_accept_one_string_without_splitting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    (tmp_path / "pyproject.toml").write_text("[tool.pytest.ini_options]\n", encoding="utf-8")
    (tmp_path / "sample.py").write_text("value = 1\n", encoding="utf-8")
    commands: list[list[str]] = []

    def fake_stream_run(command, **_kwargs):
        commands.append(command)
        return {
            "exit_code": 0,
            "stdout": "",
            "stderr": "",
            "timed_out": False,
            "sandbox_backend": "direct",
            "sandbox_hard": False,
        }

    monkeypatch.setattr("runtime.platform.process.streaming.stream_run", fake_stream_run)

    assert _run_tests(cwd=str(tmp_path), paths="sample.py")["success"] is True
    assert _lint_check(cwd=str(tmp_path), paths="sample.py")["success"] is True
    assert _format_code(cwd=str(tmp_path), paths="sample.py")["success"] is True

    assert all(command[-1:] == ["sample.py"] for command in commands)
    assert all("/" not in command for command in commands)


def test_quality_paths_accept_space_separated_string(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    (tmp_path / "pyproject.toml").write_text("[tool.pytest.ini_options]\n", encoding="utf-8")
    (tmp_path / "one.py").write_text("one = 1\n", encoding="utf-8")
    (tmp_path / "two.py").write_text("two = 2\n", encoding="utf-8")
    commands: list[list[str]] = []

    def fake_stream_run(command, **_kwargs):
        commands.append(command)
        return {
            "exit_code": 0,
            "stdout": "",
            "stderr": "",
            "timed_out": False,
            "sandbox_backend": "direct",
            "sandbox_hard": False,
        }

    monkeypatch.setattr("runtime.platform.process.streaming.stream_run", fake_stream_run)

    assert _lint_check(cwd=str(tmp_path), paths="one.py two.py")["success"] is True
    assert commands[0][-2:] == ["one.py", "two.py"]


@pytest.mark.parametrize("bad_path", ["../outside.py", "/tmp/outside.py", "--config"])
def test_quality_paths_reject_scope_escape(tmp_path: Path, bad_path: str):
    (tmp_path / "pyproject.toml").write_text("[tool.pytest.ini_options]\n", encoding="utf-8")

    for quality_tool in (_run_tests, _lint_check, _format_code):
        result = quality_tool(cwd=str(tmp_path), paths=bad_path)
        assert result["error"] == f"invalid path: {bad_path}"


# ═══════════════════════════════════════════════════════════
# Implementation note.
# ═══════════════════════════════════════════════════════════


class TestBackgroundExec:
    def test_background_command_returns_task_id_and_output_can_be_polled(self):
        import sys
        import time

        started = _background_exec(
            command=[
                sys.executable,
                "-u",
                "-c",
                "import time; print('ready'); time.sleep(0.2); print('done')",
            ],
        )
        assert "error" not in started
        assert started["status"] == "running"
        assert started["execution_policy"]["result"]["status"] == "running"
        assert started["execution_policy"]["result"]["exit_code"] is None
        task_id = started["task_id"]

        deadline = time.monotonic() + 3
        polled = {}
        while time.monotonic() < deadline:
            polled = _read_background_output(task_id=task_id)
            if polled.get("status") == "completed":
                break
            time.sleep(0.05)

        assert polled["status"] == "completed"
        assert polled["exit_code"] == 0
        assert "ready" in polled["stdout"]
        assert "done" in polled["stdout"]
        assert polled["execution_policy"]["result"]["status"] == "completed"
        assert polled["execution_policy"]["result"]["exit_code"] == 0
        assert polled["execution_policy"]["result"]["output_truncated"] is False

    def test_background_sandbox_defaults_cwd_and_scrubs_env(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        import sys
        import time

        monkeypatch.setenv("OCTOPUS_TEST_SECRET", "do-not-inherit")
        started = _background_exec(
            command=[
                sys.executable,
                "-u",
                "-c",
                (
                    "import os\n"
                    "from pathlib import Path\n"
                    "print('cwd=' + str(Path.cwd()))\n"
                    "print('secret=' + str('OCTOPUS_TEST_SECRET' in os.environ))\n"
                    "print('explicit=' + os.environ.get('OCTOPUS_EXPLICIT', ''))\n"
                ),
            ],
            env={"OCTOPUS_EXPLICIT": "kept"},
            sandbox_dir=str(tmp_path),
        )
        assert "error" not in started
        task_id = started["task_id"]

        deadline = time.monotonic() + 3
        polled = {}
        while time.monotonic() < deadline:
            polled = _read_background_output(task_id=task_id)
            if polled.get("status") == "completed":
                break
            time.sleep(0.05)

        assert polled["status"] == "completed"
        assert f"cwd={tmp_path.resolve()}" in polled["stdout"]
        assert "secret=False" in polled["stdout"]
        assert "explicit=kept" in polled["stdout"]

    def test_background_sandbox_uses_selected_backend(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        import sys
        import time

        import runtime.safety.sandboxing.sandbox as sandbox_mod
        from runtime.safety.sandboxing.sandbox import DirectBackend

        class TaggingBackend(DirectBackend):
            def transform(self, argv, env, cwd, policy):  # type: ignore[no-untyped-def]
                return (
                    [
                        sys.executable,
                        "-u",
                        "-c",
                        "print('wrapped-bg')",
                    ],
                    env,
                    cwd,
                )

        monkeypatch.setattr(
            sandbox_mod,
            "resolved_process_backend",
            lambda: sandbox_mod.BackendChoice(TaggingBackend(), "tagged", hard=True),
        )

        started = _background_exec(
            command=[sys.executable, "-u", "-c", "print('original-bg')"],
            sandbox_dir=str(tmp_path),
        )
        assert "error" not in started
        assert started["sandbox_backend"] == "tagged"
        assert started["sandbox_hard"] is True

        deadline = time.monotonic() + 3
        polled = {}
        while time.monotonic() < deadline:
            polled = _read_background_output(task_id=started["task_id"])
            if polled.get("status") == "completed":
                break
            time.sleep(0.05)

        assert polled["status"] == "completed"
        assert polled["stdout"].strip() == "wrapped-bg"
        assert polled["sandbox_backend"] == "tagged"
        assert polled["sandbox_hard"] is True
        policy = polled["execution_policy"]
        assert policy["schema"] == "octopus.execution_policy.v1"
        assert policy["sandbox_requested"] is True
        assert policy["backend"] == "tagged"
        assert policy["hard"] is True
        assert policy["env_mode"] == "allowlist"
        assert policy["process_tree_kill"] is True
        assert policy["result"]["status"] == "completed"
        assert policy["result"]["exit_code"] == 0

    def test_background_output_survives_registry_loss(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        import sys
        import time

        monkeypatch.setenv("OCTOPUS_DATA_DIR", str(tmp_path / "data"))
        started = _background_exec(
            command=[
                sys.executable,
                "-u",
                "-c",
                "import time; print('ready'); time.sleep(0.2); print('done')",
            ],
        )
        task_id = started["task_id"]
        _BACKGROUND_PROCESSES.clear()

        deadline = time.monotonic() + 3
        polled = {}
        while time.monotonic() < deadline:
            polled = _read_background_output(task_id=task_id)
            if polled.get("status") == "completed":
                break
            time.sleep(0.05)

        assert polled["status"] == "completed"
        assert polled["exit_code"] == 0
        assert "ready" in polled["stdout"]
        assert "done" in polled["stdout"]
        assert polled["execution_policy"]["result"]["status"] == "completed"
        assert polled["execution_policy"]["result"]["exit_code"] == 0

    def test_lost_background_without_exit_code_is_not_marked_completed(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        monkeypatch.setenv("OCTOPUS_DATA_DIR", str(tmp_path / "data"))
        stdout_path = tmp_path / "stdout.txt"
        stderr_path = tmp_path / "stderr.txt"
        stdout_path.write_text("partial\n", encoding="utf-8")
        stderr_path.write_text("", encoding="utf-8")
        monkeypatch.setattr(
            "runtime.execution.suckers.write_skills._probe_process",
            lambda _pid: (False, None),
        )

        polled = _snapshot_background_metadata(
            {
                "task_id": "bg_lost",
                "argv": ["python", "-c", "print('partial')"],
                "cwd": str(tmp_path),
                "pid": 999999,
                "exit_code": None,
                "stdout_path": str(stdout_path),
                "stderr_path": str(stderr_path),
            }
        )

        assert polled["status"] == "unknown"
        assert polled["exit_code"] is None
        assert polled["running"] is False
        assert polled["stdout"] == "partial\n"

    def test_probe_process_treats_unwaitable_live_pid_as_running(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ):
        from runtime.execution.suckers.write_skills import _probe_process

        monkeypatch.setattr(
            "os.waitpid", lambda _pid, _flags: (_ for _ in ()).throw(ChildProcessError())
        )
        monkeypatch.setattr("os.kill", lambda _pid, _signal: None)

        assert _probe_process(os.getpid()) == (True, None)

    def test_kill_background_command_marks_cancelled(self):
        import sys

        started = _background_exec(
            command=[sys.executable, "-u", "-c", "import time; time.sleep(10)"],
        )
        task_id = started["task_id"]

        killed = _kill_background_exec(task_id=task_id)
        assert killed["status"] in {"cancelled", "completed"}
        assert killed["execution_policy"]["result"]["status"] in {"cancelled", "completed"}

        polled = _read_background_output(task_id=task_id)
        assert polled["status"] in {"cancelled", "completed"}
        assert polled["execution_policy"]["result"]["status"] in {"cancelled", "completed"}

    def test_kill_background_command_kills_child_process_tree(self, tmp_path: Path):
        import sys
        import time

        marker = tmp_path / "child-survived.txt"
        code = (
            "import subprocess, sys, time\n"
            "subprocess.Popen([\n"
            "    sys.executable,\n"
            "    '-c',\n"
            f"    \"import pathlib, time; time.sleep(1.0); pathlib.Path({str(marker)!r}).write_text('alive')\",\n"
            "])\n"
            "time.sleep(10)\n"
        )
        started = _background_exec(
            command=[sys.executable, "-u", "-c", code],
            cwd=str(tmp_path),
        )
        assert "error" not in started

        killed = _kill_background_exec(task_id=started["task_id"])

        assert killed["status"] in {"cancelled", "completed"}
        time.sleep(1.2)
        assert not marker.exists()

    def test_shell_aliases_poll_and_kill_background_command(self):
        import sys

        started = _exec_shell(
            command=[sys.executable, "-u", "-c", "import time; time.sleep(10)"],
            run_in_background=True,
        )
        task_id = started["task_id"]

        polled = _read_shell_output(task_id=task_id)
        assert polled["task_id"] == task_id
        assert polled["status"] == "running"

        killed = _kill_shell(task_id=task_id)
        assert killed["status"] in {"cancelled", "completed"}


class TestRegistration:
    def test_register_write_skills_count(self):
        reg = SkillRegistry()
        n = register_write_skills(reg)
        assert n == 5
        for name in WRITE_SKILL_NAMES:
            assert reg.has(name)

    def test_exec_not_in_write_skills(self):
        reg = SkillRegistry()
        register_write_skills(reg)
        assert not reg.has(EXEC_SKILL_NAME)

    def test_register_exec_skill_separate(self):
        reg = SkillRegistry()
        n = register_exec_skill(reg)
        # register_exec_skill registers shell-execution-class skills.
        assert n == 7
        assert reg.has(EXEC_SKILL_NAME)
        assert reg.has("background_exec")
        assert reg.has("read_background_output")
        assert reg.has("kill_background_exec")
        assert reg.has("read_shell_output")
        assert reg.has("kill_shell")
        s = reg.get(EXEC_SKILL_NAME)
        assert "dangerous" in s.affinity

    def test_register_all_includes_write_but_not_exec(self):
        from runtime.execution.suckers.builtins import register_all

        reg = SkillRegistry()
        register_all(reg)
        for name in WRITE_SKILL_NAMES:
            assert reg.has(name), f"{name} should be in register_all"
        assert not reg.has(EXEC_SKILL_NAME), "exec_shell must NOT be auto-registered · opt-in only"


# ═══════════════════════════════════════════════════════════
# Implementation note.
# ═══════════════════════════════════════════════════════════


class TestEndToEnd:
    def test_write_skill_via_executor(self, tmp_path: Path):
        from uuid import uuid4

        from runtime.execution.tool_engine import ToolExecutor
        from runtime.memory.journal import InMemoryJournal
        from runtime.platform.models import (
            ArmId,
            Budget,
            BudgetLimits,
            SkillId,
            TaskId,
        )
        from runtime.safety.auth import TrustEngine

        reg = SkillRegistry()
        register_write_skills(reg)
        executor = ToolExecutor(
            registry=reg,
            immunity=TrustEngine(trusted_sources=["skill://public/*"]),
            journal=InMemoryJournal(),
        )
        tid = TaskId(uuid4())
        step = executor.execute_step(
            step_id=0,
            node_id="n0",
            sucker_id=SkillId("write_text_file"),
            args={
                "path": "out.txt",
                "content": "via-agent",
                "sandbox_dir": str(tmp_path),
            },
            caller="arms/x",
            task_id=tid,
            arm_id=ArmId("x"),
            budget=Budget(task_id=tid, limits=BudgetLimits(tokens=1000, usd=0.01)),
        )
        assert step.success
        assert (tmp_path / "out.txt").read_text(encoding="utf-8") == "via-agent"
