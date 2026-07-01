"""octopus-runtime · 启动同步 / lockfile(capability-plane.md §B「拉取 pin 好的 lockfile」)。

**「停止打包」的消费机制**:产品不再把成百个 SKILL.md 提交进 git,改为提交**一个 lockfile**
(列出要的技能 slug,可选 pin 版本);启动时 `bootstrap_skills` 从 registry 同步**缺失**的到本地现有布局,
再由产品自有 loader 加载。git 里只剩一个 lockfile,资产成为版本化、可共享的单一事实源。

迁移辅助:`write_lockfile` 把现有已打包技能列成 lockfile,便于日后逐步停止打包。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .client import DEFAULT_BASE, safe_registry_skill_slug
from .materialize import sync_skills


def read_lockfile(path: Path | str) -> dict:
    p = Path(path)
    if not p.is_file():
        return {"skills": []}
    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"lockfile must contain a JSON object: {p}")
    skills = data.get("skills", [])
    if skills is None:
        data["skills"] = []
    elif not isinstance(skills, list):
        raise ValueError(f"lockfile skills must be a list: {p}")
    return data


def _lock_slug(entry: Any) -> str | None:
    slug = entry if isinstance(entry, str) else (entry or {}).get("slug")
    if not slug:
        return None
    text = str(slug)
    return text if "/" in text else safe_registry_skill_slug(text)


def _lock_slugs(lock: dict) -> list[str]:
    out: list[str] = []
    for entry in lock.get("skills", []) or []:
        slug = _lock_slug(entry)
        if slug:
            out.append(slug)
    return out


def bootstrap_skills(
    lockfile: Path | str,
    skills_dir: Path | str,
    *,
    base_url: str = DEFAULT_BASE,
    force: bool = False,
) -> tuple[list[str], list[str], list[tuple[str, str]]]:
    """按 lockfile 同步**缺失**的技能到 skills_dir(已存在且非 force 则跳过)。
    返回 (synced, present, errors)。启动时调一发即可。"""
    slugs = _lock_slugs(read_lockfile(lockfile))
    skills_dir = Path(skills_dir)
    todo: list[str] = []
    present: list[str] = []
    for slug in slugs:
        bare = safe_registry_skill_slug(slug)
        if not force and (skills_dir / bare / "SKILL.md").is_file():
            present.append(bare)
        else:
            todo.append(slug)
    if not todo:
        return [], present, []
    ok, _skipped, errors = sync_skills(todo, skills_dir, base_url=base_url)
    return [s for s, _ in ok], present, errors


def write_lockfile(skills_dir: Path | str, out_path: Path | str) -> list[str]:
    """从现有 skills_dir 生成 lockfile(迁移辅助:把已打包技能列成 lockfile,以便停止打包)。"""
    skills_dir = Path(skills_dir)
    slugs = sorted(d.name for d in skills_dir.iterdir() if (d / "SKILL.md").is_file())
    Path(out_path).write_text(
        json.dumps({"skills": slugs}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return slugs
