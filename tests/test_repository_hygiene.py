"""Repository-level guardrails for source/runtime boundaries."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _ignored_tracked_files(paths: list[str]) -> list[str]:
    """Return the tracked paths that ``.gitignore`` would exclude.

    Deriving the verdict from ``.gitignore`` instead of a second hand-kept
    suffix list keeps the two from drifting. A blanket rule like ``*.jsonl``
    plus a deliberate ``!**/__fixtures__/*.jsonl`` negation is one decision
    expressed in one place; a parallel list in this test only ever learns
    about the blanket half, so it flagged committed fixtures as runtime
    garbage. Anything still reported here was force-added past a rule that
    the repository does mean to enforce.
    """
    if not paths:
        return []
    try:
        proc = subprocess.run(
            ["git", "check-ignore", "--stdin", "--no-index"],
            cwd=ROOT,
            input="\n".join(paths),
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    except FileNotFoundError as exc:  # pragma: no cover - git absent
        pytest.skip(f"git check-ignore unavailable ({exc})")
    # Exit 0 = at least one match, 1 = no matches; anything else is a real
    # failure and must not be read as a clean bill of health.
    if proc.returncode not in (0, 1):
        pytest.fail(f"git check-ignore failed ({proc.returncode}): {proc.stderr.strip()}")
    return [line.strip().replace("\\", "/") for line in proc.stdout.splitlines() if line.strip()]


def _tracked_files() -> list[str]:
    try:
        probe = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        if probe.returncode != 0 or probe.stdout.strip() != "true":
            pytest.skip("not a git worktree — hygiene check requires git ls-files")
        output = subprocess.check_output(
            ["git", "ls-files"],
            cwd=ROOT,
            text=True,
            encoding="utf-8",
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        pytest.skip(f"git ls-files unavailable ({exc})")
    tracked: list[str] = []
    for line in output.splitlines():
        path = line.strip().replace("\\", "/")
        if path and (ROOT / path).exists():
            tracked.append(path)
    return tracked


def test_runtime_artifacts_are_not_tracked() -> None:
    tracked = _tracked_files()
    violations = _ignored_tracked_files(tracked)
    # Session transcripts are per-run state that no ``.gitignore`` rule covers,
    # because the directories themselves are committed via ``.gitkeep``.
    violations += [
        path
        for path in tracked
        if "/sessions/" in path and not path.endswith("/.gitkeep") and path not in violations
    ]
    assert sorted(violations) == []


def test_gitignore_keeps_runtime_artifacts_local() -> None:
    text = (ROOT / ".gitignore").read_text(encoding="utf-8")
    required_patterns = (
        "data/",
        "logs/",
        ".runtime-logs/",
        "test-results/",
        "*.jsonl",
        "*.sqlite",
        "*.sqlite3",
        "*.db",
        "*.log",
        ".octopus/*.bak",
        ".octopus/*.lock",
        ".octopus/archive/",
        "agents/*/workspace/",
        "benchmarks/results/",
        "frontend/release/",
        "frontend/coverage/",
        "frontend/playwright-report/",
        "frontend/dist-regression/",
    )
    missing = [pattern for pattern in required_patterns if pattern not in text]
    assert missing == []
