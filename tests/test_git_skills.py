"""Implementation note."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from runtime.execution.suckers import SkillRegistry
from runtime.execution.suckers.write_skills import register_git_skills

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None,
    reason="git not on PATH",
)


# ═══════════════════════════════════════════════════════════
# Implementation note.
# ═══════════════════════════════════════════════════════════


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    r.mkdir()
    subprocess.run(
        ["git", "-C", str(r), "init", "-b", "main"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(r), "config", "user.email", "t@t.test"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(r), "config", "user.name", "Tester"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(r), "config", "commit.gpgsign", "false"],
        check=True,
        capture_output=True,
    )
    # Implementation note.
    (r / "README.md").write_text("hello\n", encoding="utf-8")
    subprocess.run(
        ["git", "-C", str(r), "add", "README.md"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(r), "commit", "-m", "initial"],
        check=True,
        capture_output=True,
    )
    return r


@pytest.fixture
def registry() -> SkillRegistry:
    reg = SkillRegistry()
    register_git_skills(reg)
    return reg


def _invoke(registry: SkillRegistry, name: str, **args):
    skill = registry.get(name)
    return skill.handler(**args)


# ═══════════════════════════════════════════════════════════
# status / diff / log
# ═══════════════════════════════════════════════════════════


class TestReadOps:
    def test_status_clean(self, registry, repo):
        out = _invoke(registry, "git_status", repo_dir=str(repo))
        assert out["clean"] is True
        assert out["branch"] == "main"
        assert out["files"] == []

    def test_status_dirty(self, registry, repo):
        (repo / "new.txt").write_text("x", encoding="utf-8")
        out = _invoke(registry, "git_status", repo_dir=str(repo))
        assert out["clean"] is False
        paths = {f["path"] for f in out["files"]}
        assert "new.txt" in paths

    def test_diff_unstaged(self, registry, repo):
        (repo / "README.md").write_text("hello v2\n", encoding="utf-8")
        out = _invoke(registry, "git_diff", repo_dir=str(repo))
        assert "hello v2" in out["diff"]
        assert out["staged"] is False

    def test_diff_staged(self, registry, repo):
        (repo / "README.md").write_text("staged\n", encoding="utf-8")
        subprocess.run(
            ["git", "-C", str(repo), "add", "README.md"],
            check=True,
            capture_output=True,
        )
        out = _invoke(registry, "git_diff", repo_dir=str(repo), staged=True)
        assert "staged" in out["diff"]
        assert out["staged"] is True

    def test_diff_flag_injection_rejected(self, registry, repo):
        out = _invoke(registry, "git_diff", repo_dir=str(repo), path="-A")
        assert "error" in out

    def test_log_returns_initial(self, registry, repo):
        out = _invoke(registry, "git_log", repo_dir=str(repo), limit=5)
        assert len(out["commits"]) == 1
        c = out["commits"][0]
        assert c["subject"] == "initial"
        assert c["author"] == "Tester"
        assert len(c["sha"]) == 40

    def test_log_limit_out_of_range(self, registry, repo):
        out = _invoke(registry, "git_log", repo_dir=str(repo), limit=0)
        assert "error" in out
        out = _invoke(registry, "git_log", repo_dir=str(repo), limit=10000)
        assert "error" in out


# ═══════════════════════════════════════════════════════════
# Implementation note.
# ═══════════════════════════════════════════════════════════


class TestWriteOps:
    def test_add_and_commit_cycle(self, registry, repo):
        (repo / "new.txt").write_text("content\n", encoding="utf-8")
        add = _invoke(
            registry,
            "git_add",
            repo_dir=str(repo),
            paths=["new.txt"],
        )
        assert add.get("exit_code") == 0
        assert add["added"] == ["new.txt"]

        cm = _invoke(
            registry,
            "git_commit",
            repo_dir=str(repo),
            message="add new.txt",
        )
        assert "error" not in cm
        assert len(cm["sha"]) == 40

        # Implementation note.
        log = _invoke(registry, "git_log", repo_dir=str(repo))
        assert len(log["commits"]) == 2
        assert log["commits"][0]["subject"] == "add new.txt"

    def test_add_rejects_flag_injection(self, registry, repo):
        out = _invoke(
            registry,
            "git_add",
            repo_dir=str(repo),
            paths=["-A"],
        )
        assert "error" in out
        assert "flag-like" in out["error"]

    def test_add_rejects_broad_paths(self, registry, repo):
        for bad in [".", "*", "../escape"]:
            out = _invoke(
                registry,
                "git_add",
                repo_dir=str(repo),
                paths=[bad],
            )
            assert "error" in out, f"should reject {bad}"

    def test_add_rejects_empty_and_non_string(self, registry, repo):
        assert "error" in _invoke(
            registry,
            "git_add",
            repo_dir=str(repo),
            paths=[],
        )
        assert "error" in _invoke(
            registry,
            "git_add",
            repo_dir=str(repo),
            paths=[""],
        )
        assert "error" in _invoke(
            registry,
            "git_add",
            repo_dir=str(repo),
            paths=None,
        )

    def test_commit_empty_message_rejected(self, registry, repo):
        out = _invoke(
            registry,
            "git_commit",
            repo_dir=str(repo),
            message="   ",
        )
        assert "error" in out

    def test_commit_bad_author_rejected(self, registry, repo):
        (repo / "x.txt").write_text("x", encoding="utf-8")
        _invoke(registry, "git_add", repo_dir=str(repo), paths=["x.txt"])
        out = _invoke(
            registry,
            "git_commit",
            repo_dir=str(repo),
            message="x",
            author="just a name",
        )
        assert "error" in out
        assert "Name <email>" in out["error"]

    def test_commit_with_author(self, registry, repo):
        (repo / "x.txt").write_text("x", encoding="utf-8")
        _invoke(registry, "git_add", repo_dir=str(repo), paths=["x.txt"])
        out = _invoke(
            registry,
            "git_commit",
            repo_dir=str(repo),
            message="x",
            author="Alice <a@b.test>",
        )
        assert "error" not in out

        log = _invoke(registry, "git_log", repo_dir=str(repo))
        assert log["commits"][0]["author"] == "Alice"

    def test_commit_fails_with_nothing_staged(self, registry, repo):
        out = _invoke(
            registry,
            "git_commit",
            repo_dir=str(repo),
            message="empty",
        )
        assert "error" in out


# ═══════════════════════════════════════════════════════════
# git_commit precheck — hook / package-manager drift
# ═══════════════════════════════════════════════════════════


class TestCommitPrecheck:
    def _hook(self, repo: Path, name: str, body: str) -> Path:
        hook = repo / ".husky" / name
        hook.parent.mkdir(parents=True, exist_ok=True)
        hook.write_text(body, encoding="utf-8")
        hook.chmod(0o755)
        return hook

    def test_pnpm_exec_in_hook_flags_blocked(self, repo: Path) -> None:
        from runtime.execution.suckers._write_skills_git import (
            _git_commit_precheck,
        )

        self._hook(
            repo,
            "commit-msg",
            "#!/bin/sh\npnpm exec commitlint --edit \"$1\"\n",
        )
        precheck = _git_commit_precheck(str(repo), None)
        assert precheck["blocked"] is True
        risks = [r for r in precheck["risks"] if r["risk"] == "pnpm_exec_in_hook"]
        assert risks and risks[0]["hook"] == "commit-msg"
        assert "pnpm" in precheck["readable"]

    def test_direct_binary_hook_not_flagged(self, repo: Path) -> None:
        from runtime.execution.suckers._write_skills_git import (
            _git_commit_precheck,
        )

        self._hook(
            repo,
            "commit-msg",
            "#!/bin/sh\n\"$PWD/node_modules/.bin/commitlint\" --edit \"$1\"\n",
        )
        precheck = _git_commit_precheck(str(repo), None)
        assert precheck["blocked"] is False

    def test_no_hooks_not_flagged(self, repo: Path) -> None:
        from runtime.execution.suckers._write_skills_git import (
            _git_commit_precheck,
        )

        precheck = _git_commit_precheck(str(repo), None)
        assert precheck["blocked"] is False

    def test_pnpm_major_drift_flagged(self, repo: Path) -> None:
        from runtime.execution.suckers._write_skills_git import (
            _package_manager_drift,
        )

        (repo / "package.json").write_text(
            '{"packageManager": "pnpm@10.26.2"}\n',
            encoding="utf-8",
        )
        modules = repo / "node_modules"
        modules.mkdir(parents=True)
        (modules / ".modules.yaml").write_text(
            "lockfileVersion: '9.0'\npackageManager: pnpm@11.20.0\n",
            encoding="utf-8",
        )
        drift = _package_manager_drift(repo)
        assert drift is not None
        assert "pnpm" in drift["detail"]
        assert drift["pinned"] == "pnpm@10.26.2"
        assert drift["installed"] == "pnpm@11.20.0"

    def test_matching_pnpm_major_not_flagged(self, repo: Path) -> None:
        from runtime.execution.suckers._write_skills_git import (
            _package_manager_drift,
        )

        (repo / "package.json").write_text(
            '{"packageManager": "pnpm@10.26.2"}\n',
            encoding="utf-8",
        )
        modules = repo / "node_modules"
        modules.mkdir(parents=True)
        (modules / ".modules.yaml").write_text(
            "lockfileVersion: '9.0'\npackageManager: pnpm@10.26.2\n",
            encoding="utf-8",
        )
        assert _package_manager_drift(repo) is None

    def test_commit_failure_enriched_with_precheck_reason(
        self,
        registry: SkillRegistry,
        repo: Path,
    ) -> None:
        """A real pnpm-style hook failure surfaces a human reason, not the
        raw stderr the user cannot decode."""
        (repo / "change.txt").write_text("change\n", encoding="utf-8")
        _invoke(registry, "git_add", repo_dir=str(repo), paths=["change.txt"])
        subprocess.run(
            ["git", "-C", str(repo), "config", "core.hooksPath", ".husky"],
            check=True,
            capture_output=True,
        )
        self._hook(
            repo,
            "commit-msg",
            (
                "#!/bin/sh\n"
                "# pnpm exec commitlint runs here\n"
                "echo \"[ERR_PNPM_ABORTED_REMOVE_MODULES_DIR_NO_TTY] "
                "Aborted removal of modules directory due to no TTY\" >&2\n"
                "exit 1\n"
            ),
        )
        out = _invoke(
            registry,
            "git_commit",
            repo_dir=str(repo),
            message="change",
        )
        assert out["error"] == "git_commit_precheck_blocked"
        assert "pnpm" in out["readable"]
        assert out["precheck"]["blocked"] is True

    def test_clean_repo_commit_has_no_precheck_block(self, registry, repo):
        (repo / "x.txt").write_text("x", encoding="utf-8")
        _invoke(registry, "git_add", repo_dir=str(repo), paths=["x.txt"])
        out = _invoke(
            registry,
            "git_commit",
            repo_dir=str(repo),
            message="x",
        )
        assert "error" not in out
        assert out.get("precheck") is None


# ═══════════════════════════════════════════════════════════
# branch
# ═══════════════════════════════════════════════════════════


class TestBranch:
    def test_branch_list(self, registry, repo):
        out = _invoke(registry, "git_branch", repo_dir=str(repo))
        names = {b["name"] for b in out["branches"]}
        assert "main" in names
        current = [b for b in out["branches"] if b["current"]]
        assert current and current[0]["name"] == "main"

    def test_branch_create(self, registry, repo):
        out = _invoke(
            registry,
            "git_branch",
            repo_dir=str(repo),
            create="feature/x",
        )
        assert out["created"] == "feature/x"

        listed = _invoke(registry, "git_branch", repo_dir=str(repo))
        names = {b["name"] for b in listed["branches"]}
        assert "feature/x" in names

    def test_branch_invalid_name(self, registry, repo):
        out = _invoke(
            registry,
            "git_branch",
            repo_dir=str(repo),
            create="-bad",
        )
        assert "error" in out
        out = _invoke(
            registry,
            "git_branch",
            repo_dir=str(repo),
            create="has space",
        )
        assert "error" in out


# ═══════════════════════════════════════════════════════════
# Implementation note.
# ═══════════════════════════════════════════════════════════


class TestSandbox:
    def test_repo_outside_sandbox_rejected(self, registry, repo, tmp_path):
        outside = tmp_path / "outside"
        outside.mkdir()
        out = _invoke(
            registry,
            "git_status",
            repo_dir=str(outside),
            sandbox_dir=str(repo),
        )
        assert "error" in out

    def test_missing_repo_dir(self, registry):
        assert "error" in _invoke(registry, "git_status", repo_dir="")
        assert "error" in _invoke(
            registry,
            "git_status",
            repo_dir="/nonexistent/xyz",
        )

    def test_git_push_allows_network_in_stream_runner(
        self,
        repo,
        monkeypatch: pytest.MonkeyPatch,
    ):
        import runtime.platform.process.streaming as streaming
        from runtime.execution.suckers.write_skills import _git_push

        captured: dict[str, object] = {}

        def fake_stream_run(argv, **kwargs):
            captured["argv"] = argv
            captured.update(kwargs)
            return {
                "stdout": "",
                "stderr": "",
                "exit_code": 0,
                "timed_out": False,
                "stdout_truncated": False,
                "stderr_truncated": False,
            }

        monkeypatch.setattr(streaming, "stream_run", fake_stream_run)

        out = _git_push(repo_dir=str(repo), sandbox_dir=str(repo))

        assert out["pushed"] is True
        assert captured["sandbox_dir"] == str(repo)
        assert captured["allow_network"] is True

    def test_git_status_keeps_network_disabled_in_stream_runner(
        self,
        repo,
        monkeypatch: pytest.MonkeyPatch,
    ):
        import runtime.platform.process.streaming as streaming
        from runtime.execution.suckers.write_skills import _git_status

        captured: dict[str, object] = {}

        def fake_stream_run(argv, **kwargs):
            captured["argv"] = argv
            captured.update(kwargs)
            return {
                "stdout": "## main\n",
                "stderr": "",
                "exit_code": 0,
                "timed_out": False,
                "stdout_truncated": False,
                "stderr_truncated": False,
            }

        monkeypatch.setattr(streaming, "stream_run", fake_stream_run)

        out = _git_status(repo_dir=str(repo), sandbox_dir=str(repo))

        assert out["branch"] == "main"
        assert captured["sandbox_dir"] == str(repo)
        assert captured["allow_network"] is False


# ═══════════════════════════════════════════════════════════
# Implementation note.
# ═══════════════════════════════════════════════════════════


class TestRegisterAllIntegration:
    def test_register_all_includes_git(self):
        from runtime.execution.suckers.builtins import register_all

        reg = SkillRegistry()
        register_all(reg)
        names = set(reg.all_names())
        for n in [
            "git_status",
            "git_diff",
            "git_log",
            "git_add",
            "git_commit",
            "git_branch",
        ]:
            assert n in names, f"missing skill: {n}"
