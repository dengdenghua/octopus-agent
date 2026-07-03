"""Deterministic worktree-isolated loop, exercised against a real git repo.

Each task runs in its own ``git worktree`` off HEAD, so parallel file writes
never collide; every worktree + branch is removed afterwards and the main
checkout is left untouched.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from runtime.execution.subagents.worktree_loop import (
    is_git_repo,
    run_worktree_loop,
    shell_worktree_worker,
    subagent_worktree_worker,
    worktree_scope,
)

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None,
    reason="git not available",
)


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()

    def g(*args: str) -> None:
        subprocess.run(
            ["git", "-C", str(repo), *args],
            check=True,
            capture_output=True,
            text=True,
        )

    g("init", "-q")
    g("config", "user.email", "t@example.com")
    g("config", "user.name", "Test")
    (repo / "README.md").write_text("base\n")
    g("add", "-A")
    g("commit", "-q", "-m", "init")
    return repo


def _worktree_count(repo: Path) -> int:
    out = subprocess.run(
        ["git", "-C", str(repo), "worktree", "list"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return len([line for line in out.splitlines() if line.strip()])


def test_not_a_git_repo(tmp_path: Path):
    r = run_worktree_loop(str(tmp_path), ["t"], lambda p, t: None)
    assert r["ok"] is False
    assert "not a git repo" in r["error"]


def test_no_tasks(tmp_path: Path):
    repo = _init_repo(tmp_path)
    r = run_worktree_loop(str(repo), [], lambda p, t: None)
    assert r["ok"] is False
    assert r["error"] == "no tasks"


def test_isolated_parallel_writes(tmp_path: Path):
    repo = _init_repo(tmp_path)

    def worker(path: str, task: str) -> None:
        (Path(path) / f"{task}.txt").write_text(f"content {task}\n")

    r = run_worktree_loop(str(repo), ["alpha", "beta", "gamma"], worker)

    assert r["ok"] is True
    assert r["succeeded"] == 3
    by_index = {res["index"]: res for res in r["results"]}
    # each task's diff contains ONLY its own new file — proves isolation
    assert by_index[0]["files"] == ["alpha.txt"]
    assert by_index[1]["files"] == ["beta.txt"]
    assert "content alpha" in by_index[0]["diff"]
    assert "beta.txt" not in by_index[0]["diff"]
    # main checkout untouched + every worktree cleaned up
    assert not (repo / "alpha.txt").exists()
    assert _worktree_count(repo) == 1


def test_worker_failure_is_isolated_and_cleaned_up(tmp_path: Path):
    repo = _init_repo(tmp_path)

    def worker(path: str, task: str) -> None:
        if task == "bad":
            raise RuntimeError("boom")
        (Path(path) / f"{task}.txt").write_text("ok\n")

    r = run_worktree_loop(str(repo), ["good", "bad"], worker)

    assert r["succeeded"] == 1
    assert r["failed"] == 1
    by_index = {res["index"]: res for res in r["results"]}
    assert by_index[0]["ok"] is True
    assert by_index[1]["ok"] is False
    assert "boom" in by_index[1]["error"]
    # the failed task's worktree was still removed
    assert _worktree_count(repo) == 1


def test_shell_worktree_worker_writes_in_isolation(tmp_path: Path):
    repo = _init_repo(tmp_path)
    worker = shell_worktree_worker(
        ["sh", "-c", 'printf "%s" "$OCTOPUS_WORKTREE_TASK" > note.txt'],
    )
    r = run_worktree_loop(str(repo), ["one", "two"], worker)

    assert r["succeeded"] == 2
    by_index = {res["index"]: res for res in r["results"]}
    # each worktree got note.txt with ITS OWN task content
    assert by_index[0]["files"] == ["note.txt"]
    assert "one" in by_index[0]["diff"]
    assert "two" in by_index[1]["diff"]
    assert "two" not in by_index[0]["diff"]
    assert _worktree_count(repo) == 1


def test_shell_worktree_worker_nonzero_exit_marks_failure(tmp_path: Path):
    repo = _init_repo(tmp_path)
    worker = shell_worktree_worker(["sh", "-c", "exit 3"])
    r = run_worktree_loop(str(repo), ["x"], worker)
    assert r["succeeded"] == 0
    assert r["results"][0]["ok"] is False
    assert _worktree_count(repo) == 1


def test_subagent_worktree_worker_passes_workspace_path(monkeypatch):
    captured: dict[str, object] = {}

    def fake(agent_id: str = "", prompt: str = "", workspace_path: str = "", **_kw):
        captured.update(
            agent_id=agent_id,
            prompt=prompt,
            workspace_path=workspace_path,
        )
        return {"success": True, "output": "ok"}

    monkeypatch.setattr("runtime.execution.subagents.call_subagent", fake)
    worker = subagent_worktree_worker(agent_id="worktree_writer")
    worker("/some/worktree", "do the thing")
    assert captured == {
        "agent_id": "worktree_writer",
        "prompt": "do the thing",
        "workspace_path": "/some/worktree",
    }


def test_subagent_worktree_worker_raises_on_failure(monkeypatch):
    def fake(**_kw):
        return {"success": False, "error": "boom"}

    monkeypatch.setattr("runtime.execution.subagents.call_subagent", fake)
    worker = subagent_worktree_worker()
    with pytest.raises(RuntimeError, match="boom"):
        worker("/wt", "task")


def test_worktree_scope_cleans_up_on_error(tmp_path: Path):
    repo = _init_repo(tmp_path)
    assert is_git_repo(str(repo)) is True
    with pytest.raises(RuntimeError), worktree_scope(str(repo), "boom") as (path, _branch):
        assert Path(path).is_dir()
        raise RuntimeError("x")
    assert _worktree_count(repo) == 1
