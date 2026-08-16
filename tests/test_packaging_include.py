"""Packaging regression (audit A-10): every shippable top-level package must
be matched by [tool.setuptools.packages.find] include patterns, or `pip
install` produces a wheel that silently drops runtime-imported packages."""

from __future__ import annotations

import fnmatch
import re
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent


def _find_include_patterns() -> list[str]:
    text = (_REPO / "pyproject.toml").read_text(encoding="utf-8")
    m = re.search(
        r"\[tool\.setuptools\.packages\.find\](.*?)(?:\n\[|\Z)",
        text,
        re.DOTALL,
    )
    assert m, "packages.find section not found"
    section = m.group(1)
    include_m = re.search(r"include\s*=\s*\[(.*?)\]", section, re.DOTALL)
    assert include_m, "include patterns not found"
    return [s.strip().strip('"') for s in include_m.group(1).split(",") if s.strip()]


def _top_level_packages() -> list[str]:
    out = []
    for child in _REPO.iterdir():
        if child.is_dir() and (child / "__init__.py").is_file():
            out.append(child.name)
    return sorted(out)


def test_all_shippable_top_level_packages_are_included() -> None:
    """runtime, tools, octopus_runtime and demos are imported from shipped
    code; none of them may silently drop out of the wheel."""
    include = _find_include_patterns()
    for pkg in _top_level_packages():
        if pkg == "tests":  # excluded by design
            continue
        assert any(
            fnmatch.fnmatch(pkg, pattern) for pattern in include
        ), f"top-level package {pkg!r} is not matched by packages.find include={include}"
