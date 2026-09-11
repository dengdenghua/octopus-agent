"""Forbid new god files (≥ a configured line count) in the watched trees.

The repository still has legacy files ≥1000 lines. Splitting all of them in one
release is risky, so the ratchet records the current debt while preventing new
god files or any growth in an existing one. For each watched tree this linter:

  * Captures the existing list in its baseline file.
  * On each run, reports any file ≥ threshold that's not on the baseline
    (= a new god file → fails).
  * Reports baseline entries that have shrunk below the threshold or been
    removed (= contributors actually split a file → must be removed from the
    baseline to lock in the win).
  * Reports baseline entries at or above the escrow threshold that GREW
    (= regression → fails).

Watched trees
-------------
``runtime/``
    Python. Threshold 1000.
``frontend/src/``
    TypeScript/TSX. Threshold 1000. Added 2026-09-11 — the frontend had no size
    gate at all while reaching 467k lines, and ``workspace/design/page.tsx`` sat
    at 8114 lines and climbing. Generated and data files are excluded.

Run::

    python tools/lint/god_file_check.py            # report
    python tools/lint/god_file_check.py --strict   # exit 1 on new gods or stale baseline
    python tools/lint/god_file_check.py --target runtime --strict
    python tools/lint/god_file_check.py --write-baseline
                                                   # snapshot current state
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


@dataclass(frozen=True)
class Target:
    """One watched tree and the debt ledger that freezes its current state."""

    name: str
    root: str
    patterns: tuple[str, ...]
    threshold: int
    baseline: str
    # Substrings matched against the repo-relative path. Generated code,
    # vendored content catalogs, and translation/data files are out of scope:
    # they are large by nature and cannot be split into modules.
    exclude_parts: tuple[str, ...]


TARGETS: tuple[Target, ...] = (
    Target(
        name="runtime",
        root="runtime",
        patterns=("*.py",),
        threshold=1000,
        baseline="tools/lint/god_files_baseline.txt",
        exclude_parts=(
            "all_skills",  # third-party-style scripts; out of CI scope
            "__pycache__",
            "tools/lint/fixtures",
        ),
    ),
    Target(
        name="frontend",
        root="frontend/src",
        patterns=("*.ts", "*.tsx"),
        threshold=1000,
        baseline="tools/lint/god_files_baseline_frontend.txt",
        exclude_parts=(
            "core/api/openapi-types.ts",  # generated from the OpenAPI contract
            "core/i18n/locales/",  # translation data, not hand-written logic
            "node_modules",
        ),
    ),
)

# Every baseline god file is in escrow: any line increase is a regression.
# Files must shrink, split into focused modules, or stay flat until they fall
# below the ordinary threshold. Keeping this equal to the target's threshold
# makes accepting legacy debt a one-time act instead of permission for more
# growth.
ESCROW_FRACTION_OF_THRESHOLD = 1.0


def _escrow_threshold(target: Target) -> int:
    return int(target.threshold * ESCROW_FRACTION_OF_THRESHOLD)


def _baseline_path(target: Target) -> Path:
    return REPO_ROOT / target.baseline


def _scan(target: Target) -> list[tuple[Path, int]]:
    hits: list[tuple[Path, int]] = []
    root = REPO_ROOT / target.root
    seen: set[Path] = set()
    for pattern in target.patterns:
        for p in root.rglob(pattern):
            if p in seen or not p.is_file():
                continue
            seen.add(p)
            rel_str = str(p).replace("\\", "/")
            if any(part in rel_str for part in target.exclude_parts):
                continue
            try:
                count = sum(1 for _ in p.read_text(encoding="utf-8").splitlines())
            except (OSError, UnicodeDecodeError):
                continue
            if count >= target.threshold:
                hits.append((p, count))
    hits.sort(key=lambda h: -h[1])
    return hits


def _load_baseline(target: Target) -> dict[str, int]:
    """Return baseline as {path: line_count}. Backward-compat: older
    baseline lines without a count are read as 0 (escrow check
    skipped for them)."""
    path = _baseline_path(target)
    if not path.is_file():
        return {}
    out: dict[str, int] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        # Each line is "<path>\t<lines>"
        parts = line.split("\t", 1)
        rel = parts[0]
        count = 0
        if len(parts) == 2:
            try:
                count = int(parts[1])
            except ValueError:
                count = 0
        out[rel] = count
    return out


def _write_baseline(target: Target, hits: list[tuple[Path, int]]) -> None:
    lines = [
        f"# God files ≥{target.threshold} lines in {target.root}/, "
        f"captured by tools/lint/god_file_check.py",
        "# Splitting one of these? Remove its line from this file so the",
        "# audit can lock in your win.",
        "",
    ]
    for p, n in sorted(hits, key=lambda h: str(h[0])):
        rel = p.relative_to(REPO_ROOT).as_posix()
        lines.append(f"{rel}\t{n}")
    _baseline_path(target).write_text("\n".join(lines) + "\n", encoding="utf-8")


def _audit_target(target: Target, strict: bool) -> int:
    hits = _scan(target)
    baseline = _load_baseline(target)
    seen_paths = {p.relative_to(REPO_ROOT).as_posix() for p, _ in hits}
    baseline_paths = set(baseline.keys())
    escrow_threshold = _escrow_threshold(target)

    new_gods = [
        (p, n) for p, n in hits if p.relative_to(REPO_ROOT).as_posix() not in baseline_paths
    ]
    shrunk = baseline_paths - seen_paths

    # Escrow check: files at or above ESCROW_THRESHOLD MUST NOT grow.
    escrow_breaches: list[tuple[str, int, int]] = []
    for p, current in hits:
        rel = p.relative_to(REPO_ROOT).as_posix()
        if rel not in baseline:
            continue  # new gods are caught by the new_gods branch
        baseline_count = baseline[rel]
        if baseline_count >= escrow_threshold and current > baseline_count:
            escrow_breaches.append((rel, baseline_count, current))

    prefix = f"[{target.name}]"
    if not new_gods and not shrunk and not escrow_breaches:
        print(
            f"OK · {prefix} {len(baseline)} baseline god files unchanged "
            f"(threshold {target.threshold} lines in {target.root}/, escrow {escrow_threshold})"
        )
        return 0

    if shrunk:
        print(f"{prefix} {len(shrunk)} baseline file(s) shrunk below threshold:")
        for entry in sorted(shrunk):
            print(f"  SHRUNK  {entry}")
        print(
            "\nRemove them from "
            f"{target.baseline} so the split-up gain is locked in."
        )

    if escrow_breaches:
        print(
            f"\n{prefix} {len(escrow_breaches)} ESCROW BREACH "
            f"(file ≥{escrow_threshold} lines must not grow):"
        )
        for rel, baseline_count, current in escrow_breaches:
            delta = current - baseline_count
            print(f"  GREW  +{delta:5d}  {rel} ({baseline_count} → {current})")
        print(
            "\nFiles in escrow are too large to allow further growth. "
            "Either:\n"
            "  1. Refactor to bring the line count DOWN, or\n"
            "  2. Split the file into modules so it falls below the\n"
            f"     {escrow_threshold}-line escrow threshold."
        )

    if new_gods:
        print(f"\n{prefix} {len(new_gods)} NEW god file(s) ≥{target.threshold} lines:")
        for p, n in new_gods:
            rel = p.relative_to(REPO_ROOT).as_posix()
            print(f"  NEW    {n:5d}  {rel}")
        print(
            "\nFix one of:\n"
            "  1. Split the file (preferred — see runtime/core/cerebrum/ "
            "for an example of breaking one big module into 7 focused subs)\n"
            "  2. If genuinely irreducible, raise the threshold for this "
            f"target in {Path(__file__).name}\n"
            "     and document the reason."
        )

    if strict and (new_gods or shrunk or escrow_breaches):
        return 1
    return 0


def _select_targets(name: str | None) -> tuple[Target, ...]:
    if not name:
        return TARGETS
    chosen = tuple(t for t in TARGETS if t.name == name)
    if not chosen:
        known = ", ".join(t.name for t in TARGETS)
        raise SystemExit(f"unknown target {name!r}; known targets: {known}")
    return chosen


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--strict", action="store_true", help="exit 1 on new god files or stale baseline entries"
    )
    p.add_argument(
        "--write-baseline", action="store_true", help="snapshot current state to baseline files"
    )
    p.add_argument("--target", default=None, help="limit to one target (default: all)")
    args = p.parse_args()

    targets = _select_targets(args.target)

    if args.write_baseline:
        for target in targets:
            hits = _scan(target)
            _write_baseline(target, hits)
            print(f"wrote {len(hits)} entries to {target.baseline}")
        return 0

    exit_code = 0
    for target in targets:
        exit_code |= _audit_target(target, strict=args.strict)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
