#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成云商城技能数据 skill-registry.json(本地技能 → 云端技能市场)。

数据源:
  1. Octopus 内置技能: runtime/execution/all_skills/<name>/SKILL.md(101 个)
  2. 用户已安装技能:  ~/.octopus/skills/<name>/SKILL.md
  3. 云端已有条目(expert-store 镜像里 workbuddy 技能) → 保留不覆盖

输出: extensions/workbuddy-experts/storefront/data/skill-registry.json
每次运行会合并本地与云端:云端已有的 workbuddy 技能原样保留,新增本地
Octopus 技能(内置 + 用户),同名优先保留云端条目(不覆盖),按名字排序。

用法:
  python3 extensions/workbuddy-experts/scripts/build-skill-registry.py [--out PATH]
"""
import argparse
import datetime
import json
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
BUILTIN_SKILLS = REPO / "runtime" / "execution" / "all_skills"
USER_SKILLS = Path.home() / ".octopus" / "skills"
OUT = REPO / "extensions" / "workbuddy-experts" / "storefront" / "data" / "skill-registry.json"

# Octopus 技能内容包(发布到 GitHub Release 的单一归档,安装时按 name 解出)。
CONTENT_SKILLS_URL = os.environ.get(
    "OCTOPUS_SKILLS_CONTENT_URL",
    "https://github.com/dengdenghua/workbuddy-expert-market/releases/download/octopus-content/octopus-skills.tar.gz",
)


def frontmatter(text: str) -> dict:
    """解析 SKILL.md 顶部 frontmatter(name/description/version/author/tags)。"""
    m = re.match(r"^---\s*\n(.*?)\n---", text, re.S)
    if not m:
        return {}
    out: dict = {}
    for line in m.group(1).splitlines():
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        key = k.strip().lower()
        val = v.strip().strip('"\'')
        if key in ("name", "description", "version", "author", "license", "category"):
            out[key] = val
    return out


def scan_dir(skills_dir: Path, source: str) -> list[dict]:
    out: list[dict] = []
    if not skills_dir.exists():
        return out
    for d in sorted(skills_dir.iterdir()):
        if not d.is_dir() or d.name.startswith(("__", ".")):
            continue
        sm = d / "SKILL.md"
        if not sm.exists():
            continue
        fm = frontmatter(sm.read_text(encoding="utf-8", errors="replace"))
        name = (fm.get("name") or d.name).strip()
        desc = (fm.get("description") or "").strip()
        if not name or not desc:
            # 没 frontmatter 的技能不入册
            continue
        tags = ["octopus"]
        if fm.get("category"):
            tags.append(fm["category"].lower().replace(" ", "-"))
        out.append(
            {
                "name": name,
                "version": fm.get("version") or "0.1.0",
                "author": fm.get("author") or "octopus-agent",
                "description": desc,
                "tags": tags,
                "source": source,
                "download_url": CONTENT_SKILLS_URL,
            }
        )
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="生成云商城技能注册表 skill-registry.json")
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--builtin-dir", type=Path, default=BUILTIN_SKILLS)
    ap.add_argument("--user-dir", type=Path, default=USER_SKILLS)
    args = ap.parse_args()

    # 云端已有条目(保留)
    existing: dict[str, dict] = {}
    if args.out.exists():
        try:
            for s in json.loads(args.out.read_text("utf-8")).get("skills", []):
                existing[s["name"]] = s
        except (OSError, json.JSONDecodeError):
            existing = {}

    builtin = scan_dir(args.builtin_dir, "octopus")
    user = scan_dir(args.user_dir, "octopus-local")
    local = {s["name"]: s for s in builtin + user}

    merged: dict[str, dict] = {}
    for name, entry in existing.items():
        merged[name] = entry
    for name, entry in local.items():
        if name not in merged:
            merged[name] = entry
        elif entry.get("source", "").startswith("octopus"):
            # Octopus 本地技能:刷新内容包 download_url + 描述,保留云端版本号
            merged[name].setdefault("source", entry["source"])
            if entry.get("download_url"):
                merged[name]["download_url"] = entry["download_url"]
            if entry.get("description") and not merged[name].get("description"):
                merged[name]["description"] = entry["description"]

    skills = [merged[k] for k in sorted(merged)]
    data = {
        "meta": {
            "title": "Octopus Skill Hub — 云商城技能",
            "count": len(skills),
            "workbuddy_skills": sum(1 for s in skills if s.get("source", "").startswith("workbuddy")),
            "octopus_skills": sum(1 for s in skills if s.get("source", "").startswith("octopus")),
            "source": (
                "https://raw.githubusercontent.com/dengdenghua/workbuddy-expert-market/gh-pages/data/skill-registry.json"
            ),
            "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        },
        "skills": skills,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(data, ensure_ascii=False, indent=1), "utf-8")
    print(
        f"✔ {args.out} — 共 {len(skills)} 个技能"
        f"(云端保留 {data['meta']['workbuddy_skills']} / 新增 Octopus {data['meta']['octopus_skills']})"
    )
    added = [n for n in local if n not in existing]
    if added:
        print("  新增本地技能:", ", ".join(sorted(added)[:40]))
    else:
        print("  无新增(本地技能已全部在册)")


if __name__ == "__main__":
    main()
