"""Git core skills for write_skills · extracted from write_skills.py.

Contains the shared ``_run_git`` runner plus the read-only / local write git
skills (status / diff / log / add / commit / branch).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ._write_skills_common import (
    _ensure_sandbox,
    _error_with_execution_policy,
    _execution_policy_from_result,
)

_GIT_READ_TIMEOUT_S = 15.0
_GIT_WRITE_TIMEOUT_S = 30.0
_GIT_OUTPUT_CAP = 200_000


def _run_git(
    repo_dir: str | Path,
    argv: list[str],
    *,
    timeout_s: float,
    sandbox_dir: str | None = None,
    allow_network: bool = False,
) -> dict[str, Any]:
    if not repo_dir:
        return {"error": "missing repo_dir"}
    resolved, err = _ensure_sandbox(repo_dir, sandbox_dir)
    if err:
        return {"error": err}
    if not resolved.is_dir():
        return {"error": f"repo_dir not a directory: {resolved}"}

    from runtime.platform.process.streaming import stream_run

    full_argv = ["git", "-C", str(resolved), *argv]
    r = stream_run(
        full_argv,
        timeout=timeout_s,
        output_cap_bytes=_GIT_OUTPUT_CAP,
        sandbox_dir=sandbox_dir,
        allow_network=allow_network,
    )
    if "error" in r and "exit_code" not in r:
        msg = r["error"]
        if "FileNotFoundError" in msg or "No such file" in msg or "not found" in msg.lower():
            return _error_with_execution_policy("git_not_found_on_path", r)
        return _error_with_execution_policy(f"git_exec_failed: {msg}", r)
    if r.get("timed_out"):
        return {
            "error": f"git timeout after {timeout_s}s",
            "timed_out": True,
            "execution_policy": _execution_policy_from_result(r),
        }
    return {
        "exit_code": r["exit_code"],
        "stdout": r["stdout"],
        "stderr": r["stderr"],
        "stdout_truncated": r["stdout_truncated"],
        "resolved_repo": str(resolved),
        "sandbox_backend": r.get("sandbox_backend", "direct"),
        "sandbox_hard": bool(r.get("sandbox_hard")),
        "execution_policy": _execution_policy_from_result(r),
    }


def _git_status(
    repo_dir: str = "",
    *,
    sandbox_dir: str | None = None,
    **_kw: Any,
) -> dict[str, Any]:
    r = _run_git(
        repo_dir,
        ["status", "--porcelain=v1", "--branch"],
        timeout_s=_GIT_READ_TIMEOUT_S,
        sandbox_dir=sandbox_dir,
    )
    if "error" in r:
        return r
    if r["exit_code"] != 0:
        return {"error": "git_status_failed", **r}

    branch = ""
    files: list[dict[str, str]] = []
    for line in r["stdout"].splitlines():
        if line.startswith("## "):
            branch = line[3:].split("...")[0]
            continue
        if len(line) < 3:
            continue
        code = line[:2]
        path = line[3:]
        files.append({"status": code.strip() or code, "path": path})
    return {
        "branch": branch,
        "files": files,
        "clean": not files,
    }


def _git_diff(
    repo_dir: str = "",
    *,
    path: str | None = None,
    staged: bool = False,
    sandbox_dir: str | None = None,
    **_kw: Any,
) -> dict[str, Any]:
    argv = ["diff"]
    if staged:
        argv.append("--staged")
    if path:
        if path.startswith("-"):
            return {"error": "invalid path (leading '-')"}
        argv.extend(["--", path])
    r = _run_git(
        repo_dir,
        argv,
        timeout_s=_GIT_READ_TIMEOUT_S,
        sandbox_dir=sandbox_dir,
    )
    if "error" in r:
        return r
    if r["exit_code"] != 0:
        return {"error": "git_diff_failed", **r}
    return {
        "diff": r["stdout"],
        "truncated": r["stdout_truncated"],
        "staged": staged,
    }


def _git_log(
    repo_dir: str = "",
    *,
    limit: int = 10,
    path: str | None = None,
    sandbox_dir: str | None = None,
    **_kw: Any,
) -> dict[str, Any]:
    if limit <= 0 or limit > 500:
        return {"error": f"limit out of range: {limit}"}
    fmt = "%H%x1f%an%x1f%aI%x1f%s"
    argv = ["log", f"-n{limit}", f"--pretty=format:{fmt}"]
    if path:
        if path.startswith("-"):
            return {"error": "invalid path (leading '-')"}
        argv.extend(["--", path])
    r = _run_git(
        repo_dir,
        argv,
        timeout_s=_GIT_READ_TIMEOUT_S,
        sandbox_dir=sandbox_dir,
    )
    if "error" in r:
        return r
    if r["exit_code"] != 0:
        return {"error": "git_log_failed", **r}

    commits: list[dict[str, str]] = []
    for line in r["stdout"].splitlines():
        parts = line.split("\x1f")
        if len(parts) != 4:
            continue
        sha, author, date, subject = parts
        commits.append(
            {
                "sha": sha,
                "author": author,
                "date": date,
                "subject": subject,
            }
        )
    return {"commits": commits}


def _git_add(
    repo_dir: str = "",
    paths: list[str] | None = None,
    *,
    sandbox_dir: str | None = None,
    **_kw: Any,
) -> dict[str, Any]:
    if not paths:
        return {"error": "paths must be a non-empty list"}
    if not isinstance(paths, list):
        return {"error": f"paths must be list (got {type(paths).__name__})"}
    safe_paths: list[str] = []
    for p in paths:
        if not isinstance(p, str) or not p:
            return {"error": "each path must be a non-empty string"}
        if p.startswith("-"):
            return {"error": f"flag-like path rejected: {p}"}
        if p in (".", "*") or ".." in Path(p).parts:
            return {"error": f"overly broad or traversal path: {p}"}
        safe_paths.append(p)

    r = _run_git(
        repo_dir,
        ["add", "--", *safe_paths],
        timeout_s=_GIT_WRITE_TIMEOUT_S,
        sandbox_dir=sandbox_dir,
    )
    if "error" in r:
        return r
    if r["exit_code"] != 0:
        return {"error": "git_add_failed", **r}
    return {"added": safe_paths, "exit_code": 0}


def _git_commit(
    repo_dir: str = "",
    message: str = "",
    *,
    author: str | None = None,
    sandbox_dir: str | None = None,
    **_kw: Any,
) -> dict[str, Any]:
    if not message.strip():
        return {"error": "commit message must be non-empty"}
    if len(message.encode("utf-8")) > 10_000:
        return {"error": "commit message too large"}

    argv = ["commit", "-m", message]
    if author:
        if "<" not in author or ">" not in author:
            return {"error": "author must be 'Name <email>' format"}
        argv.extend(["--author", author])

    r = _run_git(
        repo_dir,
        argv,
        timeout_s=_GIT_WRITE_TIMEOUT_S,
        sandbox_dir=sandbox_dir,
    )
    if "error" in r:
        return r
    if r["exit_code"] != 0:
        return {"error": "git_commit_failed", **r}

    head = _run_git(
        repo_dir,
        ["rev-parse", "HEAD"],
        timeout_s=_GIT_READ_TIMEOUT_S,
        sandbox_dir=sandbox_dir,
    )
    sha = head.get("stdout", "").strip() if "error" not in head else ""
    return {"sha": sha, "stdout": r["stdout"], "stderr": r["stderr"]}


def _git_branch(
    repo_dir: str = "",
    *,
    create: str | None = None,
    from_ref: str | None = None,
    sandbox_dir: str | None = None,
    **_kw: Any,
) -> dict[str, Any]:
    if create:
        if create.startswith("-") or " " in create:
            return {"error": f"invalid branch name: {create!r}"}
        argv = ["branch", create]
        if from_ref:
            if from_ref.startswith("-"):
                return {"error": f"invalid ref: {from_ref!r}"}
            argv.append(from_ref)
        r = _run_git(
            repo_dir,
            argv,
            timeout_s=_GIT_WRITE_TIMEOUT_S,
            sandbox_dir=sandbox_dir,
        )
        if "error" in r:
            return r
        if r["exit_code"] != 0:
            return {"error": "git_branch_create_failed", **r}
        return {"created": create, "from_ref": from_ref}

    r = _run_git(
        repo_dir,
        ["branch", "--list"],
        timeout_s=_GIT_READ_TIMEOUT_S,
        sandbox_dir=sandbox_dir,
    )
    if "error" in r:
        return r
    if r["exit_code"] != 0:
        return {"error": "git_branch_list_failed", **r}
    branches: list[dict[str, Any]] = []
    for line in r["stdout"].splitlines():
        line = line.rstrip()
        if not line:
            continue
        current = line.startswith("*")
        name = line[2:] if len(line) > 2 else line
        branches.append({"name": name.strip(), "current": current})
    return {"branches": branches}
