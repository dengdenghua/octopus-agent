"""Forbid untracked Python modules under ``runtime/`` and ``tests/``.

Why this gate exists
--------------------
A 2026-08-28 audit found 26 runtime modules that had never been ``git add``-ed,
9 of which were imported by already-tracked code. CI uses a clean checkout, so
those modules simply do not exist there — meaning **local and CI were not
running the same code**. The specific files were added, but no gate was put in
place; by 2026-09-11 the same class of bug had regrown to 37 untracked modules,
19 of them imported by tracked code.

Adding files fixes today. Only a gate fixes tomorrow. This is that gate.

Scope
-----
Everything under ``runtime/`` and ``tests/`` except ``runtime/execution/all_skills/``
— that directory is a content catalog (third-party-style skill scripts) with its
own ratchet in ``skill_cross_dir_check.py``, and it is explicitly out of scope
for code-quality gates (see ``_EXCLUDE_PARTS`` in ``god_file_check.py``).

``git ls-files --others --exclude-standard`` is used, so anything deliberately
ignored via ``.gitignore`` is not reported — this catches files that were simply
forgotten, not files that are meant to stay local.

Run::

    python tools/lint/untracked_module_check.py            # report
    python tools/lint/untracked_module_check.py --strict   # exit 1 if any found
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# Only these trees are policed. A missing ``git add`` in either one means CI is
# testing a different codebase than the developer is running.
_SCANNED_ROOTS: tuple[str, ...] = ("runtime/", "tests/")

# Content catalogs, generated trees, and caches. These are either out of scope
# for code gates or regenerated rather than committed.
_EXCLUDE_PARTS: tuple[str, ...] = (
    "runtime/execution/all_skills/",
    "__pycache__/",
)


def _untracked_python_files() -> list[str] | None:
    """Return untracked ``.py`` paths, or ``None`` if git is unavailable.

    Returning ``None`` (rather than raising) lets the caller skip gracefully:
    this check only has meaning where a git worktree exists, and the repository
    convention is that tooling which cannot run should warn and step aside
    instead of turning the pipeline red for its own reasons.
    """
    try:
        proc = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None

    hits: list[str] = []
    for raw in proc.stdout.splitlines():
        rel = raw.strip().replace("\\", "/")
        if not rel.endswith(".py"):
            continue
        if not any(rel.startswith(root) for root in _SCANNED_ROOTS):
            continue
        if any(part in rel for part in _EXCLUDE_PARTS):
            continue
        hits.append(rel)
    hits.sort()
    return hits


def _tracked_files_referencing(module_path: str) -> list[str]:
    """Best-effort: which tracked files import ``module_path``?

    Only used to report severity. A module that nothing imports is a latent
    problem; a module that tracked code imports is the bug that breaks CI.
    """
    rel = module_path[:-3] if module_path.endswith(".py") else module_path
    dotted = rel.replace("/", ".")
    if dotted.endswith(".__init__"):
        dotted = dotted[: -len(".__init__")]
    proc = subprocess.run(
        ["git", "grep", "-l", "-E", rf"^(from|import)[[:space:]]+{dotted}([[:space:]]|$|\\.)"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return []
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--strict", action="store_true", help="exit 1 when untracked modules exist")
    args = p.parse_args()

    hits = _untracked_python_files()
    if hits is None:
        print("SKIP · git unavailable — cannot determine untracked modules")
        return 0

    if not hits:
        print("OK · no untracked Python modules under " + ", ".join(_SCANNED_ROOTS))
        return 0

    imported: list[tuple[str, list[str]]] = []
    for rel in hits:
        refs = _tracked_files_referencing(rel)
        if refs:
            imported.append((rel, refs))

    print(f"{len(hits)} untracked Python module(s) under {', '.join(_SCANNED_ROOTS)}:")
    for rel in hits:
        print(f"  UNTRACKED  {rel}")

    if imported:
        print(
            f"\n{len(imported)} of them are imported by ALREADY-TRACKED code. "
            "CI checks out only tracked files, so these imports fail there —\n"
            "local and CI are not running the same code:"
        )
        for rel, refs in imported:
            print(f"  {rel}")
            for ref in refs[:3]:
                print(f"      ← {ref}")

    print(
        "\nFix:\n"
        "  1. git add the files above (review the list first — do not use"
        " 'git add -A')\n"
        "  2. If a file is meant to stay local, add it to .gitignore instead"
        " — but never for runtime/ modules.\n"
        "  3. Re-run this check; it must print OK."
    )

    return 1 if args.strict else 0


if __name__ == "__main__":
    sys.exit(main())
