#!/usr/bin/env python3
"""Doc-claim drift linter: compare counts claimed in docs to filesystem reality.

Catches the common failure mode where docs say "17 个器官" but the
filesystem has 19, or "9 份契约" when there are 15.

Ground truth:
- Organs: count of subdirectories under ``docs/biomimetic/``
- Protocols: count of ``protocols/*.md`` (excluding README.md)

Run::

    python tools/lint/doc_claims_check.py           # human-readable report
    python tools/lint/doc_claims_check.py --strict  # exit 1 on drift
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# (regex pattern, label, ground-truth fn)
ROOT = Path(__file__).parent.parent.parent

PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # "19 个器官" / "20+ 个器官" / "17 器官" — bare numbers and N+ ranges
    (re.compile(r"(\d+)\+?\s*(?:个)?\s*器官"), "biomimetic"),
    (re.compile(r"(\d+)\s*份契约"), "protocols"),
    (re.compile(r"(\d+)\s*份协议"), "protocols"),
    (re.compile(r"(\d+)\s*份全齐"), "protocols"),
]


def truth_organs() -> int:
    bio = ROOT / "docs" / "biomimetic"
    if not bio.exists():
        return -1
    return sum(1 for p in bio.iterdir() if p.is_dir() and not p.name.startswith("."))


def truth_protocols() -> int:
    proto = ROOT / "protocols"
    if not proto.exists():
        return -1
    return sum(
        1
        for p in proto.glob("*.md")
        if p.name.lower() != "readme.md"
    )


TRUTH = {
    "biomimetic": truth_organs,
    "protocols": truth_protocols,
}

DOC_GLOBS = [
    "README.md",
    "docs/**/*.md",
    "protocols/README.md",
]

# Lines that name another file's count are excluded from the linter
# (cross-references should match anyway, but the noise is high). Skip
# CHANGELOG entirely — it intentionally keeps historical snapshots.
# Skip tiers.md — it describes phased scope (MVP=8, Core=13, Full=19),
# not current state drift.
SKIP_FILES = {"CHANGELOG.md", "tiers.md"}


def scan_docs() -> list[tuple[Path, int, str, int, int]]:
    """Return [(path, lineno, snippet, claimed, truth), ...] for drift."""
    drift: list[tuple[Path, int, str, int, int]] = []
    seen_files: set[Path] = set()

    for glob in DOC_GLOBS:
        for path in ROOT.glob(glob):
            if path in seen_files or path.name in SKIP_FILES:
                continue
            seen_files.add(path)
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except (OSError, UnicodeDecodeError):
                continue
            for lineno, line in enumerate(lines, 1):
                for pattern, truth_key in PATTERNS:
                    for match in pattern.finditer(line):
                        try:
                            claimed = int(match.group(1))
                        except (ValueError, IndexError):
                            continue
                        truth = TRUTH[truth_key]()
                        if truth < 0:
                            continue
                        # "20+" form: accept iff truth >= claimed AND truth < claimed+5
                        is_plus_form = "+" in match.group(0)
                        if is_plus_form:
                            if truth < claimed or truth >= claimed + 5:
                                drift.append(
                                    (path, lineno, line.strip(), claimed, truth)
                                )
                        else:
                            if claimed != truth:
                                drift.append(
                                    (path, lineno, line.strip(), claimed, truth)
                                )
    return drift


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strict", action="store_true", help="exit 1 on drift")
    args = parser.parse_args()

    drift = scan_docs()

    organs_truth = truth_organs()
    protos_truth = truth_protocols()
    print(f"Ground truth: {organs_truth} organs (docs/biomimetic/), "
          f"{protos_truth} protocols (protocols/*.md).")

    if not drift:
        print("OK · no doc-claim drift detected.")
        return 0

    print(f"\n{len(drift)} drift{'s' if len(drift) > 1 else ''} found:")
    for path, lineno, snippet, claimed, truth in drift:
        rel = path.relative_to(ROOT)
        snippet_short = snippet[:90] + "..." if len(snippet) > 90 else snippet
        print(f"  {rel}:{lineno}: claims {claimed} but truth={truth}")
        print(f"    > {snippet_short}")

    if args.strict:
        print(
            "\n::error::Doc-claim drift detected. Update docs to match "
            "filesystem ground truth, or update truth fn in this linter "
            "if the structure intentionally changed."
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
