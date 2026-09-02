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
    LandlockBackend,
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

    def test_no_network_keeps_inference_domains_reachable(self, workspace: Path) -> None:
        """Claude Desktop parity: a network-denied sandbox still lets the
        agent reach the LLM inference endpoint(s). ``no_proxy`` enumerates
        them (direct connect) while the HTTP(S) proxy stays short-circuited,
        so every other host is blocked."""
        runner = SandboxRunner(
            SandboxPolicy(
                workspace=workspace,
                timeout_s=10.0,
                inference_domains=("octopus.aurest.ai", "ark.cn-beijing.volces.com"),
            )
        )
        result = runner.run(
            _python(
                "import os",
                "print(os.environ.get('no_proxy', 'MISSING'))",
                "print(os.environ.get('http_proxy', 'MISSING'))",
                "print(os.environ.get('https_proxy', 'MISSING'))",
            )
        )
        lines = result.stdout.splitlines()
        # Inference domains are in no_proxy → direct connect, not blocked.
        assert "octopus.aurest.ai" in lines[0]
        assert "ark.cn-beijing.volces.com" in lines[0]
        # Other hosts still go through the dead proxy → blocked.
        assert "127.0.0.1:1" in lines[1]
        assert "127.0.0.1:1" in lines[2]

    def test_no_network_without_inference_domains_denies_everything(self, workspace: Path) -> None:
        runner = SandboxRunner(SandboxPolicy(workspace=workspace, timeout_s=10.0))
        result = runner.run(_python("import os; print(os.environ.get('no_proxy', 'MISSING'))"))
        assert result.stdout.strip() == "*"

    def test_common_domains_tier_pre_allows_dev_tool_hosts(self, workspace: Path) -> None:
        """The "common domains" tier (egress_allow_common) additionally puts
        the bundled dev-tool registries/mirrors into ``no_proxy`` while the
        dead proxy still blocks everything else. Users never maintain this
        list by hand."""
        from runtime.safety.sandboxing.sandbox import default_egress_domains

        preset = default_egress_domains()
        assert "registry.npmjs.org" in preset
        assert "pypi.org" in preset
        assert "github.com" in preset

        runner = SandboxRunner(
            SandboxPolicy(
                workspace=workspace,
                timeout_s=10.0,
                inference_domains=("octopus.aurest.ai",),
                egress_allow_common=True,
            )
        )
        result = runner.run(
            _python(
                "import os",
                "print(os.environ.get('no_proxy', 'MISSING'))",
                "print(os.environ.get('https_proxy', 'MISSING'))",
            )
        )
        lines = result.stdout.splitlines()
        no_proxy = set(lines[0].split(","))
        # Inference + pre-bundled dev-tool hosts are reachable.
        assert "octopus.aurest.ai" in no_proxy
        assert "registry.npmjs.org" in no_proxy
        assert "pypi.org" in no_proxy
        assert "github.com" in no_proxy
        assert "archive.ubuntu.com" in no_proxy
        # Everything else still goes through the dead proxy.
        assert "127.0.0.1:1" in lines[1]

    def test_common_domains_tier_off_keeps_deny_scope(self, workspace: Path) -> None:
        runner = SandboxRunner(
            SandboxPolicy(
                workspace=workspace,
                timeout_s=10.0,
                inference_domains=("octopus.aurest.ai",),
                egress_allow_common=False,
            )
        )
        result = runner.run(
            _python(
                "import os",
                "print(os.environ.get('no_proxy', 'MISSING'))",
            )
        )
        # Only inference is pre-allowed; npm etc. must NOT appear.
        assert result.stdout.strip() == "octopus.aurest.ai"

    def test_allow_network_keeps_real_proxy(
        self, workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("https_proxy", "http://proxy.internal:3128")
        monkeypatch.setenv("no_proxy", "localhost")
        runner = SandboxRunner(
            SandboxPolicy(workspace=workspace, timeout_s=10.0, allow_network=True)
        )
        result = runner.run(
            _python(
                "import os",
                "print(os.environ.get('no_proxy', 'MISSING'))",
                "print(os.environ.get('http_proxy', 'MISSING'))",
                "print(os.environ.get('https_proxy', 'MISSING'))",
            )
        )
        lines = result.stdout.splitlines()
        # allow_network=True must NOT inject the proxy short-circuit —
        # the child keeps its own network configuration (direct by default).
        assert "*" not in lines[0]
        assert "127.0.0.1:1" not in lines[0]
        assert "127.0.0.1:1" not in lines[1]
        assert "127.0.0.1:1" not in lines[2]

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


# ═══════════════════════════════════════════════════════════
# dsh-ported sandbox vocabulary: mode tiers + enforcement report
# ═══════════════════════════════════════════════════════════


class TestEnforcementReport:
    def test_direct_backend_reports_none(self, workspace: Path) -> None:
        backend = DirectBackend()
        policy = SandboxPolicy(workspace=workspace)
        assert backend.enforcement(policy) == "none"

    def test_bwrap_reports_full(self, workspace: Path) -> None:
        policy = SandboxPolicy(workspace=workspace)
        assert BubblewrapBackend().enforcement(policy) == "full"

    def test_seatbelt_reports_partial(self, workspace: Path) -> None:
        policy = SandboxPolicy(workspace=workspace)
        # macOS Seatbelt scopes reads loosely, so the write/network guard
        # is only partial enforcement of the tier.
        assert SeatbeltBackend().enforcement(policy) == "partial"

    def test_landlock_reports_partial(self, workspace: Path, monkeypatch) -> None:
        monkeypatch.setattr(
            "runtime.safety.sandboxing.sandbox._landlock_kernel_available",
            lambda: True,
        )
        policy = SandboxPolicy(workspace=workspace)
        # Reads are unconfined and network is outside Landlock's vocabulary,
        # so like Seatbelt this is only partial enforcement of the tier.
        assert LandlockBackend().enforcement(policy) == "partial"


class TestReadOnlyMode:
    def test_bwrap_read_only_mounts_workspace_ro(self, workspace: Path, monkeypatch) -> None:
        monkeypatch.setattr(
            "shutil.which", lambda name: "/usr/bin/bwrap" if name == "bwrap" else None
        )
        argv, _env, _cwd = BubblewrapBackend().transform(
            ["python", "-V"],
            {},
            workspace,
            SandboxPolicy(workspace=workspace, mode="read-only"),
        )
        workspace_index = argv.index(str(workspace))
        assert argv[workspace_index - 1] == "--ro-bind"

    def test_bwrap_workspace_write_uses_rw_bind(self, workspace: Path, monkeypatch) -> None:
        monkeypatch.setattr(
            "shutil.which", lambda name: "/usr/bin/bwrap" if name == "bwrap" else None
        )
        argv, _env, _cwd = BubblewrapBackend().transform(
            ["python", "-V"],
            {},
            workspace,
            SandboxPolicy(workspace=workspace, mode="workspace-write"),
        )
        workspace_index = argv.index(str(workspace))
        assert argv[workspace_index - 1] == "--bind"

    def test_seatbelt_read_only_keeps_only_null_sink(self, workspace: Path, monkeypatch) -> None:
        monkeypatch.setattr(
            "shutil.which", lambda name: "/usr/bin/sandbox-exec" if name == "sandbox-exec" else None
        )
        argv, _env, _cwd = SeatbeltBackend().transform(
            ["python", "-V"],
            {},
            workspace,
            SandboxPolicy(workspace=workspace, mode="read-only"),
        )
        profile = argv[2]
        assert str(workspace) not in profile
        assert "/dev/null" in profile

    def test_seatbelt_workspace_write_allows_workspace(self, workspace: Path, monkeypatch) -> None:
        monkeypatch.setattr(
            "shutil.which", lambda name: "/usr/bin/sandbox-exec" if name == "sandbox-exec" else None
        )
        argv, _env, _cwd = SeatbeltBackend().transform(
            ["python", "-V"],
            {},
            workspace,
            SandboxPolicy(workspace=workspace, mode="workspace-write"),
        )
        profile = argv[2]
        assert str(workspace) in profile


class TestAdditionalWriteRoots:
    @staticmethod
    def _roots(tmp_path: Path) -> tuple[Path, Path, Path]:
        outer_root = tmp_path.parent / f"outer-sidecar-{tmp_path.name}"
        thread_root = outer_root / "sidecar-state" / "thread"
        codex_home = thread_root / "codex-home"
        task_root = thread_root / "tasks" / "turn"
        scratch_root = outer_root / "sidecar-scratch" / "turn"
        for root in (codex_home, task_root, scratch_root):
            root.mkdir(parents=True, exist_ok=True)
        return codex_home, task_root, scratch_root

    def test_policy_requires_exact_existing_non_symlink_directories(
        self,
        workspace: Path,
        tmp_path: Path,
    ) -> None:
        missing = tmp_path / "missing"
        with pytest.raises(SandboxViolation, match="does not exist"):
            SandboxPolicy(workspace=workspace, additional_write_roots=(missing,))

        regular = tmp_path / "regular-file"
        regular.write_text("x", encoding="utf-8")
        with pytest.raises(SandboxViolation, match="not a directory"):
            SandboxPolicy(workspace=workspace, additional_write_roots=(regular,))

        target = tmp_path / "target"
        target.mkdir()
        link = tmp_path / "link"
        link.symlink_to(target, target_is_directory=True)
        with pytest.raises(SandboxViolation, match="cannot be a symlink"):
            SandboxPolicy(workspace=workspace, additional_write_roots=(link,))

        with pytest.raises(SandboxViolation, match="must not overlap a system directory"):
            SandboxPolicy(
                workspace=workspace,
                additional_write_roots=(Path("/usr/bin"),),
            )

        exact_roots = self._roots(tmp_path)
        with pytest.raises(SandboxViolation, match="exact non-overlapping"):
            SandboxPolicy(
                workspace=workspace,
                additional_write_roots=(exact_roots[0].parent, exact_roots[0]),
            )

    def test_bwrap_binds_each_exact_root_in_safe_parent_first_order(
        self,
        workspace: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "shutil.which", lambda name: "/usr/bin/bwrap" if name == "bwrap" else None
        )
        roots = self._roots(tmp_path)
        policy = SandboxPolicy(
            workspace=workspace,
            allow_network=True,
            additional_write_roots=roots,
        )

        argv, _env, _cwd = BubblewrapBackend().transform(
            ["codex", "app-server"],
            {},
            workspace,
            policy,
        )

        assert "--unshare-net" not in argv
        bind_indexes: list[int] = []
        for root in roots:
            rendered = str(root.resolve())
            index = next(
                index
                for index in range(len(argv) - 2)
                if argv[index : index + 3] == ["--bind", rendered, rendered]
            )
            bind_indexes.append(index)
        mounted_depths = [
            len(root.parts) for _index, root in sorted(zip(bind_indexes, roots, strict=True))
        ]
        assert mounted_depths == sorted(mounted_depths)
        adjacent = roots[0].parent / "adjacent-untrusted"
        adjacent.mkdir()
        assert str(adjacent.resolve()) not in argv

    def test_seatbelt_read_only_allows_only_private_roots_not_workspace(
        self,
        workspace: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "shutil.which", lambda name: "/usr/bin/sandbox-exec" if name == "sandbox-exec" else None
        )
        roots = self._roots(tmp_path)
        argv, _env, _cwd = SeatbeltBackend().transform(
            ["codex", "app-server"],
            {},
            workspace,
            SandboxPolicy(
                workspace=workspace,
                mode="read-only",
                allow_network=True,
                additional_write_roots=roots,
            ),
        )
        profile = argv[2]
        assert str(workspace.resolve()) not in profile
        for root in roots:
            assert str(root.resolve()) in profile
        adjacent = roots[0].parent / "adjacent-untrusted"
        adjacent.mkdir()
        assert str(adjacent.resolve()) not in profile

    def test_landlock_read_only_keeps_only_private_roots(
        self,
        workspace: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "runtime.safety.sandboxing.sandbox._landlock_kernel_available",
            lambda: True,
        )
        roots = self._roots(tmp_path)
        _argv, env, _cwd = LandlockBackend().transform(
            ["codex", "app-server"],
            {},
            workspace,
            SandboxPolicy(
                workspace=workspace,
                mode="read-only",
                allow_network=True,
                additional_write_roots=roots,
            ),
        )
        spec = json.loads(env["OCTOPUS_LANDLOCK_SPEC"])
        assert spec["write_paths"] == [str(root.resolve()) for root in roots]
        adjacent = roots[0].parent / "adjacent-untrusted"
        adjacent.mkdir()
        assert str(adjacent.resolve()) not in spec["write_paths"]


class TestLandlockBackend:
    def test_available_false_off_linux(self, monkeypatch) -> None:
        monkeypatch.setattr(sys, "platform", "darwin")
        assert LandlockBackend.available() is False

    def test_transform_wraps_with_wrapper_and_write_paths(
        self, workspace: Path, monkeypatch
    ) -> None:
        monkeypatch.setattr(
            "runtime.safety.sandboxing.sandbox._landlock_kernel_available",
            lambda: True,
        )
        policy = SandboxPolicy(workspace=workspace, mode="workspace-write")
        argv, env, cwd = LandlockBackend().transform(
            ["python", "-V"],
            {"HOME": str(workspace / ".octopus-home"), "TMPDIR": str(workspace / ".octopus-tmp")},
            workspace,
            policy,
        )
        assert argv[0] == sys.executable
        assert argv[1] == "-c"
        assert "--" in argv
        assert argv[argv.index("--") + 1 :] == ["python", "-V"]
        spec = json.loads(env["OCTOPUS_LANDLOCK_SPEC"])
        assert str(workspace) in spec["write_paths"]
        assert spec["write_paths"][0] == str(workspace)

    def test_transform_read_only_has_no_write_paths(self, workspace: Path, monkeypatch) -> None:
        monkeypatch.setattr(
            "runtime.safety.sandboxing.sandbox._landlock_kernel_available",
            lambda: True,
        )
        argv, env, _cwd = LandlockBackend().transform(
            ["python", "-V"],
            {},
            workspace,
            SandboxPolicy(workspace=workspace, mode="read-only"),
        )
        spec = json.loads(env["OCTOPUS_LANDLOCK_SPEC"])
        assert spec["write_paths"] == []

    def test_transform_rejects_cwd_escape(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setattr(
            "runtime.safety.sandboxing.sandbox._landlock_kernel_available",
            lambda: True,
        )
        workspace = tmp_path / "ws"
        workspace.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        with pytest.raises(SandboxViolation):
            LandlockBackend().transform(
                ["python", "-V"],
                {},
                outside,
                SandboxPolicy(workspace=workspace),
            )

    def test_transform_fails_closed_without_kernel(self, workspace: Path, monkeypatch) -> None:
        monkeypatch.setattr(
            "runtime.safety.sandboxing.sandbox._landlock_kernel_available",
            lambda: False,
        )
        with pytest.raises(SandboxViolation):
            LandlockBackend().transform(
                ["python", "-V"], {}, workspace, SandboxPolicy(workspace=workspace)
            )


class TestLandlockSelection:
    def test_landlock_mode_selects_backend(self, monkeypatch) -> None:
        monkeypatch.setenv("OCTOPUS_PROCESS_SANDBOX", "landlock")
        monkeypatch.setattr(
            "runtime.safety.sandboxing.sandbox._landlock_kernel_available",
            lambda: True,
        )
        choice = select_process_backend()
        assert choice.name == "landlock"
        assert choice.hard is True

    def test_landlock_mode_rejects_when_unavailable(self, monkeypatch) -> None:
        monkeypatch.setenv("OCTOPUS_PROCESS_SANDBOX", "landlock")
        monkeypatch.setattr(
            "runtime.safety.sandboxing.sandbox._landlock_kernel_available",
            lambda: False,
        )
        with pytest.raises(SandboxViolation):
            select_process_backend()

    def test_auto_falls_back_to_landlock_on_linux(
        self,
        monkeypatch,
    ) -> None:
        monkeypatch.setenv("OCTOPUS_PROCESS_SANDBOX", "auto")
        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.setattr(BubblewrapBackend, "available", staticmethod(lambda: False))
        monkeypatch.setattr(
            "runtime.safety.sandboxing.sandbox._landlock_kernel_available",
            lambda: True,
        )
        monkeypatch.setattr(SeatbeltBackend, "available", staticmethod(lambda: False))
        choice = select_process_backend()
        assert choice.name == "landlock"


# ═══════════════════════════════════════════════════════════
# Resolved posture: real probe + single source of truth
# ═══════════════════════════════════════════════════════════


@pytest.fixture
def fresh_backend_cache():
    from runtime.safety.sandboxing import sandbox as sandbox_mod

    sandbox_mod._reset_process_backend_cache()
    yield
    sandbox_mod._reset_process_backend_cache()


class TestResolvedPosture:
    def test_probe_direct_backend_runs(self, workspace: Path) -> None:
        from runtime.safety.sandboxing.sandbox import DirectBackend, probe_backend_runs

        assert probe_backend_runs(DirectBackend()) is True

    def test_resolve_soft_uses_direct(
        self, monkeypatch: pytest.MonkeyPatch, fresh_backend_cache
    ) -> None:
        monkeypatch.setenv("OCTOPUS_PROCESS_SANDBOX", "soft")
        from runtime.safety.sandboxing.sandbox import DirectBackend, resolve_process_backend

        choice = resolve_process_backend()
        assert choice.name == "direct"
        assert choice.hard is False
        assert isinstance(choice.backend, DirectBackend)

    def test_resolve_strict_fails_closed_without_verified_backend(
        self, monkeypatch: pytest.MonkeyPatch, fresh_backend_cache
    ) -> None:
        monkeypatch.setenv("OCTOPUS_PROCESS_SANDBOX", "strict")
        from runtime.safety.sandboxing import sandbox as sandbox_mod
        from runtime.safety.sandboxing.sandbox import (
            BubblewrapBackend,
            SandboxViolation,
            SeatbeltBackend,
            resolve_process_backend,
        )

        monkeypatch.setattr(BubblewrapBackend, "available", staticmethod(lambda: False))
        monkeypatch.setattr(SeatbeltBackend, "available", staticmethod(lambda: False))
        monkeypatch.setattr(sandbox_mod, "probe_backend_runs", lambda _b: True)

        with pytest.raises(SandboxViolation, match="has no usable hard backend"):
            resolve_process_backend()

    def test_resolve_auto_falls_back_to_soft_loudly(
        self, monkeypatch: pytest.MonkeyPatch, fresh_backend_cache
    ) -> None:
        monkeypatch.setenv("OCTOPUS_PROCESS_SANDBOX", "auto")
        from runtime.safety.sandboxing import sandbox as sandbox_mod
        from runtime.safety.sandboxing.sandbox import (
            BubblewrapBackend,
            DirectBackend,
            SeatbeltBackend,
            resolve_process_backend,
        )

        monkeypatch.setattr(BubblewrapBackend, "available", staticmethod(lambda: False))
        monkeypatch.setattr(SeatbeltBackend, "available", staticmethod(lambda: False))
        monkeypatch.setattr(sandbox_mod, "probe_backend_runs", lambda _b: True)

        choice = resolve_process_backend()
        assert choice.name == "direct"
        assert choice.hard is False
        assert isinstance(choice.backend, DirectBackend)

    def test_resolve_requires_real_probe_for_present_backend(
        self, monkeypatch: pytest.MonkeyPatch, fresh_backend_cache
    ) -> None:
        """A backend that is 'available' (binary present) but fails to run is
        treated as unavailable — this is the present-but-broken seatbelt case."""
        monkeypatch.setenv("OCTOPUS_PROCESS_SANDBOX", "seatbelt")
        from runtime.safety.sandboxing.sandbox import (
            SandboxViolation,
            SeatbeltBackend,
            resolve_process_backend,
        )

        monkeypatch.setattr(SeatbeltBackend, "available", staticmethod(lambda: True))
        # Probe fails even though the binary is present.
        from runtime.safety.sandboxing import sandbox as sandbox_mod

        monkeypatch.setattr(sandbox_mod, "probe_backend_runs", lambda _b: False)

        with pytest.raises(SandboxViolation, match="has no usable hard backend"):
            resolve_process_backend()

    def test_resolve_picks_verified_backend(
        self, monkeypatch: pytest.MonkeyPatch, fresh_backend_cache
    ) -> None:
        monkeypatch.setenv("OCTOPUS_PROCESS_SANDBOX", "auto")
        monkeypatch.setattr(sys, "platform", "linux")
        from runtime.safety.sandboxing import sandbox as sandbox_mod
        from runtime.safety.sandboxing.sandbox import (
            BubblewrapBackend,
            SeatbeltBackend,
            resolve_process_backend,
        )

        monkeypatch.setattr(BubblewrapBackend, "available", staticmethod(lambda: True))
        monkeypatch.setattr(SeatbeltBackend, "available", staticmethod(lambda: True))
        # Only bwrap verifies; seatbelt is present but does not verify.
        monkeypatch.setattr(
            sandbox_mod,
            "probe_backend_runs",
            lambda b: isinstance(b, BubblewrapBackend),
        )

        choice = resolve_process_backend()
        assert choice.name == "bwrap"
        assert choice.hard is True

    def test_resolved_process_backend_is_cached_single_source(
        self, monkeypatch: pytest.MonkeyPatch, fresh_backend_cache
    ) -> None:
        monkeypatch.setenv("OCTOPUS_PROCESS_SANDBOX", "auto")
        monkeypatch.setattr(sys, "platform", "linux")
        from runtime.safety.sandboxing import sandbox as sandbox_mod
        from runtime.safety.sandboxing.sandbox import (
            BubblewrapBackend,
            SeatbeltBackend,
            resolve_process_backend,
        )

        monkeypatch.setattr(BubblewrapBackend, "available", staticmethod(lambda: True))
        monkeypatch.setattr(SeatbeltBackend, "available", staticmethod(lambda: True))
        monkeypatch.setattr(sandbox_mod, "probe_backend_runs", lambda _b: True)

        first = resolve_process_backend()
        # Second resolution must return the identical cached instance and must
        # not re-run the (now-failing) resolution path.
        monkeypatch.setattr(
            sandbox_mod,
            "resolve_process_backend",
            lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not re-resolve")),
        )
        second = sandbox_mod.resolved_process_backend()
        assert second is first

    def test_posture_reports_backend_and_strength(
        self, monkeypatch: pytest.MonkeyPatch, fresh_backend_cache, tmp_path
    ) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("OCTOPUS_PROCESS_SANDBOX", "soft")
        from runtime.safety.sandboxing.sandbox import (
            DirectBackend,
            resolved_process_sandbox_posture,
        )

        posture = resolved_process_sandbox_posture()
        assert posture.backend == "direct"
        assert posture.hard is False
        assert posture.enforcement == DirectBackend().enforcement(
            __import__(
                "runtime.safety.sandboxing.sandbox", fromlist=["SandboxPolicy"]
            ).SandboxPolicy(workspace=tmp_path)
        )
