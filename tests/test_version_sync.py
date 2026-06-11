from __future__ import annotations

import tomllib
from pathlib import Path

import runtime


def test_runtime_version_matches_project_metadata():
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    metadata = tomllib.loads(pyproject.read_text(encoding="utf-8"))

    assert runtime.__version__ == metadata["project"]["version"]
