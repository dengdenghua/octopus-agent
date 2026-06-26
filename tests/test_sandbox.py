"""Tests for the cross-platform :class:`SandboxRunner`.

The runner has to behave the same on Windows and POSIX, so each test
uses ``sys.executable`` (always available) and feeds Python a one-liner
via ``-c``. That dodges shell-builtin differences (``echo``, ``ls``,
``true``) without losing test coverage.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from runtime.safety.sandboxing.sandbox import (
    BubblewrapBackend,
    DirectBackend,
    SandboxPolicy,
    SandboxRunner,
    SandboxViolation,
    SeatbeltBackend,
    select_process_backend,
)


def _python(*code_chunks: str) -> list[str]:
    """Run a tiny Python program via the test interpreter."""
    return [sys.executable, "-c", "; ".join(code_chunks)]


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    return tmp_path


class TestRun:
    def test_basic_stdout(self, workspace: Path) -> None:
        runner = SandboxRunner(SandboxPolicy(workspace=workspace, timeout_s=10.0))
        result = runner.run(_python("print('hi')"))
        assert result.exit_code == 0
        assert "hi" in result.stdout
        assert result.timed_out is False

    def test_non_zero_exit(self, workspace: Path) -> None:
        runner = SandboxRunner(SandboxPolicy(workspace=workspace, timeout_s=10.0))
        result = runner.run(_python("import sys; sys.exit(2)"))
        assert result.exit_code == 2

    def test_stderr_captured(self, workspace: Path) -> None:
        runner = SandboxRunner(SandboxPolicy(workspace=workspace, timeout_s=10.0))
        result = runner.run(_python("import sys; sys.stderr.write('boom'); sys.stderr.flush()"))
        assert "boom" in result.stderr

    def test_stdin_text(self, workspace: Path) -> None:
        runner = SandboxRunner(SandboxPolicy(workspace=workspace, timeout_s=10.0))
        result = runner.run(
            _python("import sys; print(sys.stdin.read().strip().upper())"),
            stdin_text="hello",
        )
        assert "HELLO" in result.stdout

    def test_streaming_callback_receives_chunks(self, workspace: Path) -> None:
        chunks: list[str] = []
        runner = SandboxRunner(SandboxPolicy(workspace=workspace, timeout_s=10.0))
        runner.run(
            _python("for i in range(3):\n    print('line' + str(i), flush=True)\n"),
            on_output=chunks.append,
        )
        assert any("line" in c for c in chunks)


class TestEnvironmentScrub:
    def test_secret_env_blocked_by_default(
        self, workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("FAKE_API_KEY", "TOPSECRET")
        runner = SandboxRunner(SandboxPolicy(workspace=workspace, timeout_s=10.0))
        result = runner.run(_python("import os; print(os.environ.get('FAKE_API_KEY', 'MISSING'))"))
        assert "MISSING" in result.stdout
        assert "TOPSECRET" not in result.stdout

    def test_extra_env_passed_through(self, workspace: Path) -> None:
        runner = SandboxRunner(
            SandboxPolicy(
                workspace=workspace,
                timeout_s=10.0,
                extra_env={"OCT_INJECT": "yes"},
            )
        )
        result = runner.run(_python("import os; print(os.environ.get('OCT_INJECT', 'no'))"))
        assert "yes" in result.stdout

    def test_extra_env_secret_keys_are_blocked(self, workspace: Path) -> None:
        runner = SandboxRunner(
            SandboxPolicy(
                workspace=workspace,
                timeout_s=10.0,
                extra_env={
                    "OPENAI_API_KEY": "sk-secret",
                    "CUSTOM_TOKEN": "token-secret",
                    "OCTOPUS_EXPLICIT": "kept",
                },
            )
        )
        result = runner.run(
            _python(
                "import os",
                "print(os.environ.get('OPENAI_API_KEY', 'MISSING'))",
                "print(os.environ.get('CUSTOM_TOKEN', 'MISSING'))",
                "print(os.environ.get('OCTOPUS_EXPLICIT', 'MISSING'))",
            )
        )

        assert "sk-secret" not in result.stdout
        assert "token-secret" not in result.stdout
        assert result.stdout.splitlines() == ["MISSING", "MISSING", "kept"]

    def test_no_network_sets_proxy_short_circuit(self, workspace: Path) -> None:
        runner = SandboxRunner(SandboxPolicy(workspace=workspace, timeout_s=10.0))
        result = runner.run(
            _python("import os; print(os.environ.get('no_proxy'), os.environ.get('http_proxy'))")
        )
        assert "*" in result.stdout
        assert "127.0.0.1:1" in result.stdout

    def test_home_and_temp_are_redirected_inside_workspace(self, workspace: Path) -> None:
        runner = SandboxRunner(SandboxPolicy(workspace=workspace, timeout_s=10.0))
        result = runner.run(
            _python(
                "import json, os, pathlib, tempfile",
                "home = pathlib.Path.home()",
                "tmp = pathlib.Path(tempfile.gettempdir())",
                "(home / 'home-marker.txt').write_text('home')",
                "(tmp / 'tmp-marker.txt').write_text('tmp')",
                "print(json.dumps({'HOME': os.environ.get('HOME'), 'USERPROFILE': os.environ.get('USERPROFILE'), 'TMPDIR': os.environ.get('TMPDIR'), 'TMP': os.environ.get('TMP'), 'TEMP': os.environ.get('TEMP'), 'XDG_CACHE_HOME': os.environ.get('XDG_CACHE_HOME'), 'XDG_CONFIG_HOME': os.environ.get('XDG_CONFIG_HOME'), 'XDG_DATA_HOME': os.environ.get('XDG_DATA_HOME'), 'tempfile': str(tmp)}))",
            )
        )

        assert result.exit_code == 0
        env = json.loads(result.stdout)
        expected_home = workspace / ".octopus-home"
        expected_tmp = workspace / ".octopus-tmp"
        assert Path(env["HOME"]).resolve() == expected_home.resolve()
        assert Path(env["USERPROFILE"]).resolve() == expected_home.resolve()
        assert Path(env["TMPDIR"]).resolve() == expected_tmp.resolve()
        assert Path(env["TMP"]).resolve() == expected_tmp.resolve()
        assert Path(env["TEMP"]).resolve() == expected_tmp.resolve()
        assert Path(env["tempfile"]).resolve() == expected_tmp.resolve()
        assert Path(env["XDG_CACHE_HOME"]).resolve() == (workspace / ".octopus-cache").resolve()
        assert Path(env["XDG_CONFIG_HOME"]).resolve() == (workspace / ".octopus-config").resolve()
        assert Path(env["XDG_DATA_HOME"]).resolve() == (workspace / ".octopus-data").resolve()
        assert (expected_home / "home-marker.txt").read_text(encoding="utf-8") == "home"
        assert (expected_tmp / "tmp-marker.txt").read_text(encoding="utf-8") == "tmp"


class TestCwdIsolation:
    def test_default_cwd_is_workspace(self, workspace: Path) -> None:
        runner = SandboxRunner(SandboxPolicy(workspace=workspace, timeout_s=10.0))
        result = runner.run(_python("import os; print(os.getcwd())"))
        # Comparing via Path normalises Windows drive-letter casing.
        assert Path(result.stdout.strip()).resolve() == workspace.resolve()

    def test_subdir_cwd_allowed(self, workspace: Path) -> None:
        sub = workspace / "sub"
        sub.mkdir()
        runner = SandboxRunner(SandboxPolicy(workspace=workspace, timeout_s=10.0))
        result = runner.run(
            _python("import os; print(os.getcwd())"),
            cwd=sub,
        )
        assert Path(result.stdout.strip()).resolve() == sub.resolve()

    def test_outside_cwd_rejected(self, workspace: Path, tmp_path: Path) -> None:
        outside = tmp_path.parent
        runner = SandboxRunner(SandboxPolicy(workspace=workspace, timeout_s=10.0))
        with pytest.raises(SandboxViolation):
            runner.run(_python("print('x')"), cwd=outside)

    def test_nonexistent_cwd_rejected(self, workspace: Path) -> None:
        runner = SandboxRunner(SandboxPolicy(workspace=workspace, timeout_s=10.0))
        with pytest.raises(SandboxViolation):
            runner.run(_python("print('x')"), cwd=workspace / "missing")

    def test_nonexistent_workspace_rejected(self, tmp_path: Path) -> None:
        missing = tmp_path / "missing-workspace"
        runner = SandboxRunner(SandboxPolicy(workspace=missing, timeout_s=10.0))
        with pytest.raises(SandboxViolation, match="workspace is not a directory"):
            runner.run(_python("print('x')"))
        assert not missing.exists()


class TestLimits:
    def test_timeout_kills_process(self, workspace: Path) -> None:
        runner = SandboxRunner(SandboxPolicy(workspace=workspace, timeout_s=0.5))
        result = runner.run(_python("import time; time.sleep(10)"))
        assert result.timed_out is True
        assert result.killed is True

    def test_output_cap_truncates(self, workspace: Path) -> None:
        runner = SandboxRunner(
            SandboxPolicy(workspace=workspace, timeout_s=10.0, max_output_bytes=64)
        )
        # Each line is ~10 chars; produce more than the cap.
        result = runner.run(_python("for i in range(200):\n    print('xxxxxxxx', flush=True)\n"))
        assert result.truncated is True
        assert len(result.stdout) <= 64

    def test_output_cap_is_measured_in_utf8_bytes(self, workspace: Path) -> None:
        runner = SandboxRunner(
            SandboxPolicy(workspace=workspace, timeout_s=10.0, max_output_bytes=5)
        )
        result = runner.run(_python("import sys; sys.stdout.write('界' * 10)"))

        assert result.truncated is True
        assert len(result.stdout.encode("utf-8")) <= 5
        assert result.stdout == "界"

    def test_empty_command_rejected(self, workspace: Path) -> None:
        runner = SandboxRunner(SandboxPolicy(workspace=workspace, timeout_s=10.0))
        with pytest.raises(SandboxViolation):
            runner.run([])

    def test_missing_executable_rejected(self, workspace: Path) -> None:
        runner = SandboxRunner(SandboxPolicy(workspace=workspace, timeout_s=10.0))
        with pytest.raises(SandboxViolation):
            runner.run(["this-binary-definitely-does-not-exist-xyz"])


class TestBackendSeam:
    def test_direct_backend_passes_through(self, workspace: Path) -> None:
        runner = SandboxRunner(
            SandboxPolicy(workspace=workspace, timeout_s=10.0),
            backend=DirectBackend(),
        )
        result = runner.run(_python("print('seam')"))
        assert "seam" in result.stdout

    def test_custom_backend_can_inject_args(self, workspace: Path) -> None:
        captured: dict[str, list[str]] = {}

        class TaggingBackend:
            def transform(self, argv, env, cwd, policy):  # type: ignore[no-untyped-def]
                captured["argv"] = list(argv)
                # Don't actually rewrap — we just assert the seam fires.
                return argv, env, cwd

        runner = SandboxRunner(
            SandboxPolicy(workspace=workspace, timeout_s=10.0),
            backend=TaggingBackend(),
        )
        runner.run(_python("print('via backend')"))
        assert captured["argv"][0] == sys.executable


class TestProcessBackendSelection:
    def test_soft_mode_uses_direct_backend(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OCTOPUS_PROCESS_SANDBOX", "soft")

        choice = select_process_backend()

        assert choice.name == "direct"
        assert choice.hard is False
        assert isinstance(choice.backend, DirectBackend)

    def test_auto_prefers_bwrap_on_linux(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OCTOPUS_PROCESS_SANDBOX", "auto")
        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.setattr(BubblewrapBackend, "available", staticmethod(lambda: True))
        monkeypatch.setattr(SeatbeltBackend, "available", staticmethod(lambda: True))

        choice = select_process_backend()

        assert choice.name == "bwrap"
        assert choice.hard is True

    def test_strict_rejects_when_no_hard_backend(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("OCTOPUS_PROCESS_SANDBOX", "strict")
        monkeypatch.setattr(BubblewrapBackend, "available", staticmethod(lambda: False))
        monkeypatch.setattr(SeatbeltBackend, "available", staticmethod(lambda: False))

        with pytest.raises(SandboxViolation):
            select_process_backend()

    def test_bwrap_transform_wraps_command_and_network_policy(
        self,
        workspace: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "shutil.which", lambda name: "/usr/bin/bwrap" if name == "bwrap" else None
        )
        policy = SandboxPolicy(workspace=workspace, allow_network=False)

        argv, env, cwd = BubblewrapBackend().transform(
            ["python", "-V"],
            {},
            workspace,
            policy,
        )

        assert argv[0] == "/usr/bin/bwrap"
        assert "--unshare-net" in argv
        assert "--bind" in argv
        assert str(workspace.resolve()) in argv
        assert argv[-2:] == ["python", "-V"]
        assert cwd == workspace.resolve()

    def test_seatbelt_transform_wraps_command_and_network_policy(
        self,
        workspace: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "shutil.which", lambda name: "/usr/bin/sandbox-exec" if name == "sandbox-exec" else None
        )
        policy = SandboxPolicy(workspace=workspace, allow_network=True)

        argv, env, cwd = SeatbeltBackend().transform(
            ["python", "-V"],
            {},
            workspace,
            policy,
        )

        assert argv[:2] == ["/usr/bin/sandbox-exec", "-p"]
        assert "(allow network*)" in argv[2]
        assert "/dev/null" in argv[2]
        assert str(workspace.resolve()) in argv[2]
        assert argv[-2:] == ["python", "-V"]
        assert cwd == workspace.resolve()
