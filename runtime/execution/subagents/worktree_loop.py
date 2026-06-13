"""Deterministic worktree-isolated loop.

Run N tasks, each in its OWN git worktree, concurrently — capture each one's
diff, then clean up. Isolated parallel file-writing: workers never collide
because each operates in a separate checkout off ``HEAD``.

This is the real mechanism behind the worktree pattern the
``vibecoding-general-swarm`` SKILL only described in prose (telling sub-agents
to manually shell ``git worktree add``). Here the lifecycle is code:
deterministic, cleaned up in a ``finally``, and unit-tested against a real git
repo.

Diffs are RETURNED for the caller to review/apply — this never auto-merges,
because reconciling parallel edits to the same file is a human/lead decision,
not something to do blindly.

The ``worker`` is an injected callable ``worker(worktree_path, task) -> None``
that writes files inside the worktree. Wiring a sub-agent as the worker (so it
runs with ``cwd`` = the worktree) needs per-worker ``workspace_path`` support
in ``call_subagent`` and is a separate integration step; the loop machinery
here is agnostic to what the worker is.
"""
from __future__ import annotations

import concurrent.futures as _cf
import os
import shutil
import subprocess
import tempfile
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

# ``git worktree add/remove`` mutate the main repo's worktree registry, so
# those are serialized. The worker and the per-worktree diff capture touch only
# the worktree's OWN index/checkout, so they run concurrently without a lock.
_WORKTREE_LOCK = threading.Lock()
_MAX_WORKTREE_TASKS = 16


def _git(cwd: str, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", cwd, *args],
        capture_output=True,
        text=True,
        check=check,
    )


def is_git_repo(path: str) -> bool:
    try:
        result = _git(path, "rev-parse", "--is-inside-work-tree", check=False)
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0 and result.stdout.strip() == "true"


def _slug(text: str, fallback: str) -> str:
    cleaned = "".join(
        ch if (ch.isalnum() or ch in "-_") else "-" for ch in str(text)
    )[:32].strip("-")
    return cleaned or fallback


@contextmanager
def worktree_scope(repo_root: str, name: str) -> Iterator[tuple[str, str]]:
    """Create an isolated git worktree off HEAD, yield ``(path, branch)``, and
    remove the worktree + branch on exit (always, even on error)."""
    base = tempfile.mkdtemp(prefix="octo-wt-")
    path = os.path.join(base, "wt")
    branch = f"octo/wt-{name}"
    with _WORKTREE_LOCK:
        _git(repo_root, "worktree", "add", "-b", branch, path, "HEAD")
    try:
        yield path, branch
    finally:
        with _WORKTREE_LOCK:
            _git(repo_root, "worktree", "remove", "--force", path, check=False)
            _git(repo_root, "branch", "-D", branch, check=False)
        shutil.rmtree(base, ignore_errors=True)


def _capture_diff(worktree: str) -> tuple[str, list[str]]:
    _git(worktree, "add", "-A", check=False)
    diff = _git(worktree, "diff", "--cached", check=False).stdout
    names = _git(worktree, "diff", "--cached", "--name-only", check=False).stdout
    files = [line for line in names.split("\n") if line.strip()]
    return diff, files


def shell_worktree_worker(
    command: list[str], *, timeout_s: int = 300,
) -> Callable[[str, Any], None]:
    """A ready-made worker that runs a FIXED argv inside each worktree
    (``cwd`` = the worktree), with the task exposed as the env var
    ``$OCTOPUS_WORKTREE_TASK``. The task string is never interpolated into the
    command and no shell is spawned by us, so an untrusted task can't inject
    argv. A non-zero exit raises (the loop marks that task failed). This is the
    works-today consumer — running a sub-agent as the worker (so the agent's
    own file tools target the worktree) needs per-worker write-scope wiring in
    the executor and is deferred until it can be verified against a live run."""
    argv = [str(part) for part in command]

    def _worker(path: str, task: Any) -> None:
        env = {**os.environ, "OCTOPUS_WORKTREE_TASK": str(task)}
        subprocess.run(
            argv, cwd=path, env=env, timeout=timeout_s,
            check=True, capture_output=True, text=True,
        )

    return _worker


def run_worktree_loop(
    repo_root: str,
    tasks: list[Any],
    worker: Callable[[str, Any], None],
    *,
    max_workers: int = 4,
) -> dict[str, Any]:
    """Run each task in its own git worktree concurrently; return per-task
    ``{index, task, branch, ok, diff, files, error}``. Never auto-merges."""
    if not is_git_repo(repo_root):
        return {"ok": False, "error": f"not a git repo: {repo_root}", "results": [], "count": 0}
    clean = [t for t in (tasks or []) if t is not None][:_MAX_WORKTREE_TASKS]
    if not clean:
        return {"ok": False, "error": "no tasks", "results": [], "count": 0}

    def _run_one(index: int, task: Any) -> dict[str, Any]:
        preview = (task if isinstance(task, str) else repr(task))[:200]
        name = f"{index}-{_slug(task if isinstance(task, str) else '', f't{index}')}"
        record: dict[str, Any] = {
            "index": index, "task": preview, "branch": f"octo/wt-{name}",
            "ok": False, "diff": "", "files": [], "error": None,
        }
        try:
            with worktree_scope(repo_root, name) as (path, branch):
                record["branch"] = branch
                worker(path, task)
                record["diff"], record["files"] = _capture_diff(path)
                record["ok"] = True
        except Exception as exc:  # noqa: BLE001 — isolate one task's failure
            record["error"] = f"{type(exc).__name__}: {exc}"
        return record

    results: list[dict[str, Any]] = []
    workers = max(1, min(int(max_workers), len(clean)))
    with _cf.ThreadPoolExecutor(
        max_workers=workers, thread_name_prefix="worktree",
    ) as pool:
        futures = [pool.submit(_run_one, i, t) for i, t in enumerate(clean)]
        for future in _cf.as_completed(futures):
            results.append(future.result())
    results.sort(key=lambda r: r["index"])
    succeeded = sum(1 for r in results if r["ok"])
    return {
        "ok": succeeded > 0,
        "results": results,
        "count": len(results),
        "succeeded": succeeded,
        "failed": len(results) - succeeded,
    }
