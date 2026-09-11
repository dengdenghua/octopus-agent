"""Local file inventory; presence does not imply runtime execution permission."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

import yaml

from runtime.platform.process.paths import app_paths, resources_root

SKIP_DIRS = {".git", "node_modules", ".venv", "__pycache__", "dist", "build", "release"}


def skill_roots() -> list[tuple[Path, str]]:
    repo = resources_root()
    return [
        (app_paths().data_dir / "skills", "local"),
        (repo / "runtime", "builtin"),
        (repo / "skills", "local"),
        (repo / "extensions", "builtin"),
        (repo / "agents", "local"),
        (repo / ".octopus", "imported"),
        (Path.home() / ".octopus" / "skills", "local"),
        (Path.home() / ".octopus" / "imported", "imported"),
        (Path.home() / ".octopus" / "plugins", "imported"),
    ]


def scan_local_skills(roots: list[tuple[Path, str]] | None = None) -> list[dict[str, Any]]:
    by_name: dict[str, dict[str, Any]] = {}
    visited: set[Path] = set()
    for root, source in roots if roots is not None else skill_roots():
        if not root.is_dir():
            continue
        for directory, dirs, files in os.walk(root, followlinks=False):
            dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not (Path(directory) / d).is_symlink())
            if "SKILL.md" not in files:
                continue
            md = Path(directory) / "SKILL.md"
            if md.is_symlink() or md.resolve() in visited:
                continue
            visited.add(md.resolve())
            try:
                content = md.read_bytes()
                try:
                    text = content.decode("utf-8-sig")
                except UnicodeDecodeError:
                    text = content.decode("gb18030", errors="replace")
                fm: dict[str, Any] = {}
                if text.startswith("---\n") or text.startswith("---\r\n"):
                    try:
                        parsed = yaml.safe_load(text.split("---", 2)[1])
                        if isinstance(parsed, dict):
                            fm = parsed
                    except yaml.YAMLError:
                        pass
            except OSError:
                continue
            name = str(fm.get("name") or md.parent.name).strip()
            metadata = fm.get("metadata") if isinstance(fm.get("metadata"), dict) else {}
            author = fm.get("author") or metadata.get("author")
            if isinstance(author, dict):
                author = author.get("name")
            author = author.strip() if isinstance(author, str) else ""
            key = name.casefold()
            variant = {"path": str(md.parent.resolve()), "sha256": hashlib.sha256(content).hexdigest()}
            if key in by_name:
                by_name[key]["variants"].append(variant)
                continue
            by_name[key] = {
                "id": name, "name": name, "kind": "skill", "source": source,
                "description": str(fm.get("description") or ""),
                "author": author,
                "version": str(fm.get("version") or "0.1.0"),
                "variants": [variant],
            }
    return [by_name[key] for key in sorted(by_name)]


def public_skill_inventory() -> list[dict[str, Any]]:
    return [{key: value for key, value in item.items() if key != "variants"}
            for item in scan_local_skills()
            if not item["name"].startswith(("android.", "ios."))]
