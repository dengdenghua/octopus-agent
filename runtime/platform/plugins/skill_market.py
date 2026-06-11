
from __future__ import annotations

import contextlib
import json
import os
import shutil
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

try:
    import httpx

    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False
    httpx = None


class SkillMeta(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str = Field(..., min_length=1)
    version: str = "0.1.0"
    author: str = ""
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    min_octopus_version: str = ""
    requires: list[str] = Field(default_factory=list)


class SearchResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    description: str
    author: str = ""
    tags: list[str] = Field(default_factory=list)
    version: str = ""
    installed: bool = False


class InstallResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    version: str
    path: str
    status: str  # "installed" | "updated" | "already_installed" | "failed"
    message: str = ""


class SkillMarket:

    DEFAULT_REPO = "octopus-agent/skill-hub"
    DEFAULT_REGISTRY_URL = "https://raw.githubusercontent.com/octopus-agent/skill-hub/main/registry.json"

    def __init__(
        self,
        skills_dir: str | Path | None = None,
        registry_url: str | None = None,
    ) -> None:
        if skills_dir is None:
            skills_dir = Path(os.path.expanduser("~/.octopus/skills"))
        self._dir = Path(skills_dir)
        self._registry_url = registry_url or self.DEFAULT_REGISTRY_URL

    def search(self, query: str, limit: int = 20) -> list[SearchResult]:
        registry = self._fetch_registry()
        if registry is None:
            return []

        query_lower = query.lower()
        results: list[SearchResult] = []

        for entry in registry:
            name = entry.get("name", "")
            desc = entry.get("description", "")
            tags = entry.get("tags", [])
            searchable = f"{name} {desc} {' '.join(tags)}".lower()

            if query_lower in searchable:
                results.append(SearchResult(
                    name=name,
                    description=desc,
                    author=entry.get("author", ""),
                    tags=tags,
                    version=entry.get("version", "0.1.0"),
                    installed=self._is_installed(name),
                ))

            if len(results) >= limit:
                break

        return results

    def install(self, name: str, version: str | None = None) -> InstallResult:
        dest = self._dir / name
        if dest.exists():
            return InstallResult(
                name=name,
                version=version or "0.1.0",
                path=str(dest),
                status="already_installed",
                message=f"Skill '{name}' already installed at {dest}",
            )

        content = self._fetch_skill_content(name)
        if content is None:
            return InstallResult(
                name=name,
                version=version or "0.1.0",
                path="",
                status="failed",
                message=f"Skill '{name}' not found in registry",
            )

        dest.mkdir(parents=True, exist_ok=True)

        skill_md = content.get("SKILL.md", "")
        meta = content.get("meta.json", {})

        (dest / "SKILL.md").write_text(skill_md, encoding="utf-8")
        (dest / "meta.json").write_text(
            json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8",
        )

        return InstallResult(
            name=name,
            version=meta.get("version", "0.1.0"),
            path=str(dest),
            status="installed",
            message=f"Skill '{name}' installed to {dest}",
        )

    def uninstall(self, name: str) -> bool:
        dest = self._dir / name
        if not dest.exists():
            return False
        shutil.rmtree(dest, ignore_errors=True)
        return True

    def publish(self, skill_path: str | Path) -> dict[str, Any]:
        skill_path = Path(skill_path)
        if not skill_path.exists():
            return {"status": "error", "message": f"Path not found: {skill_path}"}

        skill_md = skill_path / "SKILL.md"
        meta_file = skill_path / "meta.json"

        if not skill_md.exists():
            return {"status": "error", "message": "SKILL.md not found"}

        meta: dict[str, Any] = {}
        if meta_file.exists():
            try:
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                return {"status": "error", "message": "meta.json is invalid JSON"}

        name = meta.get("name", skill_path.name)
        meta.setdefault("name", name)

        return {
            "status": "ready",
            "message": (
                f"Skill '{name}' is ready to publish.\n"
                f"To publish, create a PR to {self.DEFAULT_REPO}:\n"
                f"  1. Fork {self.DEFAULT_REPO}\n"
                f"  2. Copy your skill to skills/{name}/\n"
                f"  3. Add entry to registry.json\n"
                f"  4. Submit PR"
            ),
            "skill_name": name,
            "meta": meta,
        }

    def list_installed(self) -> list[SkillMeta]:
        if not self._dir.exists():
            return []

        results: list[SkillMeta] = []
        for item in sorted(self._dir.iterdir()):
            if not item.is_dir():
                continue
            meta_file = item / "meta.json"
            if meta_file.exists():
                try:
                    data = json.loads(meta_file.read_text(encoding="utf-8"))
                    results.append(SkillMeta(**data))
                except (OSError, json.JSONDecodeError, TypeError, ValueError):
                    results.append(SkillMeta(name=item.name))
            else:
                results.append(SkillMeta(name=item.name))

        return results

    def info(self, name: str) -> dict[str, Any] | None:
        local = self._dir / name
        if local.exists():
            meta_file = local / "meta.json"
            skill_md = local / "SKILL.md"
            result: dict[str, Any] = {"name": name, "installed": True}

            if meta_file.exists():
                with contextlib.suppress(json.JSONDecodeError, OSError, ValueError, TypeError):
                    result["meta"] = json.loads(meta_file.read_text(encoding="utf-8"))
            if skill_md.exists():
                result["skill_md"] = skill_md.read_text(encoding="utf-8")[:2000]

            return result

        registry = self._fetch_registry()
        if registry is None:
            return None

        for entry in registry:
            if entry.get("name") == name:
                return {**entry, "installed": False}

        return None

    def _is_installed(self, name: str) -> bool:
        return (self._dir / name).exists()

    def _fetch_registry(self) -> list[dict[str, Any]] | None:
        if not HTTPX_AVAILABLE:
            return self._local_registry()
        try:
            resp = httpx.get(self._registry_url, timeout=10.0, follow_redirects=True)
            if resp.status_code == 200:
                return resp.json()
        except (ConnectionError, TimeoutError, OSError, TypeError, ValueError):  # noqa: BLE001 — network probe; fall back to local registry
            pass
        return self._local_registry()

    def _local_registry(self) -> list[dict[str, Any]] | None:
        local_reg = self._dir / "registry.json"
        if local_reg.exists():
            try:
                return json.loads(local_reg.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError, TypeError, ValueError):  # noqa: BLE001 — local registry corrupt; return None for upstream fallback
                pass
        return None

    def _fetch_skill_content(self, name: str) -> dict[str, Any] | None:
        if not HTTPX_AVAILABLE:
            return None

        base = (
            f"https://raw.githubusercontent.com/"
            f"{self.DEFAULT_REPO}/main/skills/{name}"
        )

        content: dict[str, Any] = {}
        try:
            resp = httpx.get(f"{base}/SKILL.md", timeout=10.0, follow_redirects=True)
            if resp.status_code == 200:
                content["SKILL.md"] = resp.text
        except (ConnectionError, TimeoutError, OSError, ValueError, TypeError):
            return None

        try:
            resp = httpx.get(f"{base}/meta.json", timeout=10.0, follow_redirects=True)
            if resp.status_code == 200:
                content["meta.json"] = resp.json()
            else:
                content["meta.json"] = {"name": name, "version": "0.1.0"}
        except (ConnectionError, TimeoutError, OSError, ValueError, TypeError):
            content["meta.json"] = {"name": name, "version": "0.1.0"}

        return content
