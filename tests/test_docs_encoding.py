"""Guard core onboarding docs against UTF-8 and mojibake regressions."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

CORE_DOCS = (
    "README.md",
    "README.en.md",
    "QUICKSTART.md",
    "ROOT_LAYOUT.md",
    "mkdocs.yml",
    "docs/index.md",
    "docs/GOLDEN_PATH.md",
    "docs/CONCEPTS.md",
    "docs/architecture.md",
    "docs/architecture/core-path.md",
    "docs/main-path-audit.md",
    "docs/self-evolution-min-loop.md",
    "docs/engineering-hygiene-plan.md",
)

MOJIBAKE_MARKERS = (
    "\ufffd",  # replacement character
    "\u00c3",  # common UTF-8-as-Latin-1 marker
    "\u00c2",  # common UTF-8-as-Latin-1 marker
    "\u00e2\u20ac",  # smart punctuation decoded as Latin-1/CP1252
    "\u00e4\u00b8",  # common Chinese UTF-8 bytes decoded as Latin-1
    "\u00e7\u0161",  # common Chinese UTF-8 bytes decoded as CP1252
)


def test_core_docs_decode_as_utf8() -> None:
    for rel in CORE_DOCS:
        path = ROOT / rel
        assert path.is_file(), f"core doc missing: {rel}"
        path.read_bytes().decode("utf-8")


def test_core_docs_do_not_contain_common_mojibake_markers() -> None:
    failures: list[str] = []
    for rel in CORE_DOCS:
        text = (ROOT / rel).read_text(encoding="utf-8")
        hits = [
            marker.encode("unicode_escape").decode("ascii")
            for marker in MOJIBAKE_MARKERS
            if marker in text
        ]
        if hits:
            failures.append(f"{rel}: {', '.join(hits)}")
    assert failures == []
