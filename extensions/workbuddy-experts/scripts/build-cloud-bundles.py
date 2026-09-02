#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把本地技能/插件打包成云端内容包(从云端安装下载用)。

产出(remote/bundles/):
  octopus-skills.tar.gz  内含 skills/<name>/SKILL.md + scripts/references/meta.json
  octopus-plugins.tar.gz 内含 plugins/<id>/(codex 插件 plugin.json+skills / 连接器 cli.json+mcp.json+skills)

用法:
  python3 extensions/workbuddy-experts/scripts/build-cloud-bundles.py
  python3 extensions/workbuddy-experts/scripts/build-cloud-bundles.py --out remote/bundles
"""
import argparse
import json
import os
import shutil
import sys
import tarfile
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
STORE_DATA = REPO / "extensions" / "workbuddy-experts" / "storefront" / "data"
BUILTIN_SKILLS = REPO / "runtime" / "execution" / "all_skills"
USER_SKILLS = Path.home() / ".octopus" / "skills"
# Codex 格式插件统一放 octopus 名下;旧 ~/.codex/plugins/cache 由同步一次性搬入。
CODEX_CACHE = Path.home() / ".octopus" / "plugins" / "codex"
CONNECTOR_ROOT = REPO / "extensions" / "workbuddy-connectors" / "connectors"

# codex 插件根目录里跳过的大文件目录(运行时/构建产物,本地安装本就不需要)
_CODEX_SKIP_DIRS = {"node_modules", "dist", "build", ".git", "__pycache__"}


def _tar_add(tf: tarfile.TarFile, src: Path, arc_prefix: str) -> int:
    """把 src 目录递归加进 tar,返回文件数;跳过 _CODEX_SKIP_DIRS。"""
    n = 0
    if not src.exists():
        return n
    for p in sorted(src.rglob("*")):
        if any(part in _CODEX_SKIP_DIRS for part in p.relative_to(src).parts):
            continue
        if p.is_file():
            tf.add(p, arcname=f"{arc_prefix}/{p.relative_to(src)}", recursive=False)
            n += 1
    return n


def build_skills(out: Path) -> int:
    """打包所有技能(内置 + 用户)到 octopus-skills.tar.gz。"""
    count = 0
    with tarfile.open(out / "octopus-skills.tar.gz", "w:gz") as tf:
        for name, root in [
            *[(d.name, d) for d in sorted(BUILTIN_SKILLS.iterdir()) if d.is_dir() and not d.name.startswith("__")],
            *[(d.name, d) for d in sorted(USER_SKILLS.iterdir()) if d.is_dir() and not d.name.startswith((".", "__"))],
        ]:
            count += _tar_add(tf, root, f"skills/{name}")
    return count


def build_plugins(out: Path) -> int:
    """打包 codex 插件 + 连接器到 octopus-plugins.tar.gz。"""
    count = 0
    with tarfile.open(out / "octopus-plugins.tar.gz", "w:gz") as tf:
        # codex 格式插件:~/.octopus/plugins/codex/<plugin>(旧缓存首次自动同步)
        if not CODEX_CACHE.is_dir():
            from runtime.platform.plugins.codex_discovery import (
                sync_codex_cache_to_octopus,
            )

            sync_codex_cache_to_octopus(dest=CODEX_CACHE)
        if CODEX_CACHE.is_dir():
            for manifest_path in sorted(CODEX_CACHE.glob("*/.codex-plugin/plugin.json")):
                try:
                    meta = json.loads(manifest_path.read_text("utf-8"))
                    pid = str(meta.get("name") or "")
                except (OSError, json.JSONDecodeError):
                    continue
                if not pid:
                    continue
                root = manifest_path.parent.parent
                count += _tar_add(tf, root, f"plugins/codex/{pid}")
        # 连接器:extensions/workbuddy-connectors/connectors/<id>
        if CONNECTOR_ROOT.exists():
            for d in sorted(CONNECTOR_ROOT.iterdir()):
                if d.is_dir() and not d.name.startswith((".", "__")):
                    count += _tar_add(tf, d, f"plugins/connector/{d.name}")
    return count


def main() -> None:
    ap = argparse.ArgumentParser(description="打包本地技能/插件为云端内容包")
    ap.add_argument("--out", type=Path, default=None,
                    help="输出目录(默认 extensions/workbuddy-experts/remote/bundles)")
    args = ap.parse_args()
    out = (args.out or REPO / "extensions" / "workbuddy-experts" / "remote" / "bundles")
    out.mkdir(parents=True, exist_ok=True)

    n_skills = build_skills(out)
    n_plugins = build_plugins(out)
    for f in ("octopus-skills.tar.gz", "octopus-plugins.tar.gz"):
        p = out / f
        print(f"✔ {p} — {p.stat().st_size / 1024:.1f} KB")
    print(f"  技能文件数: {n_skills} | 插件/连接器文件数: {n_plugins}")


if __name__ == "__main__":
    main()
