#!/usr/bin/env python3
"""生成云商城的插件/连接器数据 plugin-store.json。

数据源:
  1. 我们的 Codex 格式插件: ~/.octopus/plugins/codex/*/.codex-plugin/plugin.json
     (google-drive / figma / sites / browser / ... 等 OpenAI/Codex 生态插件)
  2. WorkBuddy 连接器: extensions/workbuddy-connectors/octopus-manifest.json
     (108 个,含 cli.json / mcp.json / auth_mode)

输出: extensions/workbuddy-experts/storefront/data/plugin-store.json
"""

import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
# Codex 格式插件统一放 octopus 名下;旧 ~/.codex/plugins/cache 由同步一次性搬入。
CODEX_CACHE = Path.home() / ".octopus" / "plugins" / "codex"
WB_MANIFEST = REPO / "extensions" / "workbuddy-connectors" / "octopus-manifest.json"
# 连接器实体源目录(cli.json / mcp.json / skills / vendor)
CONNECTOR_ROOT = REPO / "extensions" / "workbuddy-connectors" / "connectors"
OUT = REPO / "extensions" / "workbuddy-experts" / "storefront" / "data" / "plugin-store.json"

# 插件/连接器内容包(发布到 GitHub Release 的单一归档,安装时按 id 解出)。
CONTENT_PLUGINS_URL = os.environ.get(
    "OCTOPUS_PLUGINS_CONTENT_URL",
    "https://github.com/dengdenghua/workbuddy-expert-market/releases/download/octopus-content/octopus-plugins.tar.gz",
)


def scan_codex_plugins() -> list[dict]:
    out = []
    # 旧 Codex 缓存(~/.codex/plugins/cache)首次同步进 octopus 目录
    if not CODEX_CACHE.is_dir():
        sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
        from runtime.platform.plugins.codex_discovery import (
            sync_codex_cache_to_octopus,
        )

        sync_codex_cache_to_octopus(dest=CODEX_CACHE)
    if not CODEX_CACHE.is_dir():
        return out
    for plugin_json in sorted(CODEX_CACHE.glob("*/.codex-plugin/plugin.json")):
        try:
            meta = json.loads(plugin_json.read_text("utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        name = str(meta.get("name") or plugin_json.parent.parent.name)
        interface = meta.get("interface") or {}
        skills = []
        skills_dir = plugin_json.parent.parent / "skills"
        if skills_dir.exists():
            skills = [p.parent.name for p in skills_dir.rglob("SKILL.md")]
        # .app.json → 需要的 connector
        app_json = plugin_json.parent.parent / ".app.json"
        connectors = []
        if app_json.exists():
            try:
                apps = json.loads(app_json.read_text("utf-8")).get("apps", {})
                for app in apps.values():
                    cid = app.get("id", "")
                    if cid:
                        connectors.append(cid)
            except (OSError, json.JSONDecodeError):
                pass
        out.append(
            {
                "id": f"codex_{name}",
                "plugin": name,
                "source": "codex",
                "kind": "plugin",
                "name": str(interface.get("displayName") or name),
                "name_zh": str(interface.get("displayName") or name),
                "description": str(
                    interface.get("longDescription")
                    or interface.get("shortDescription")
                    or meta.get("description")
                    or ""
                ),
                "category": str(interface.get("category") or ""),
                "author": (meta.get("author") or {}).get("name", "OpenAI"),
                "version": str(meta.get("version") or "0.1.0"),
                "skills": skills,
                "connectors": connectors,
                "path": str(plugin_json.parent.parent),
                "download_url": CONTENT_PLUGINS_URL,
                "install": {"kind": "codex-plugin", "path": str(plugin_json.parent.parent)},
            }
        )
    return out


def _scan_vendor_deps(connector_id: str) -> list[dict]:
    """扫描连接器目录 vendor/ 下已 vendor 的依赖,生成安装依赖元数据。

    约定:connectors/<id>/vendor/*.tgz 由 download-vendor-deps.py 预先下载。
    安装方解出内容包后,可用 npm install -g <本地 tgz> 离线安装,不依赖外网 registry。
    """
    deps: list[dict] = []
    vdir = CONNECTOR_ROOT / connector_id / "vendor"
    if not vdir.is_dir():
        return deps
    for f in sorted(vdir.iterdir()):
        if f.is_file() and f.suffix.lower() in (".tgz", ".tar.gz", ".whl"):
            dep_type = "pip" if f.suffix.lower() == ".whl" else "npm"
            install_cmd = (
                "pip install <解出的 vendor whl 本地路径>"
                if dep_type == "pip"
                else "npm install -g <解出的 vendor tgz 本地路径>"
            )
            deps.append(
                {
                    "type": dep_type,
                    "package": f.stem,
                    "vendored": f"plugins/connector/{connector_id}/vendor/{f.name}",
                    "install": install_cmd,
                }
            )
    return deps


def scan_workbuddy_connectors() -> list[dict]:
    if not WB_MANIFEST.exists():
        return []
    data = json.loads(WB_MANIFEST.read_text("utf-8"))
    out = []
    for c in data.get("connectors", []):
        install: dict = {"kind": "connector", "connector_id": c["id"]}
        deps = _scan_vendor_deps(c["id"])
        if deps:
            install["dependencies"] = deps
        out.append(
            {
                "id": f"wb_{c['id']}",
                "plugin": c["id"],
                "source": "workbuddy",
                "kind": "connector",
                "name": c.get("name") or c["id"],
                "name_zh": c.get("name_zh") or c.get("name") or c["id"],
                "description": c.get("description_zh") or c.get("description") or "",
                "category": c.get("type", "mcp"),
                "author": "WorkBuddy(腾讯)",
                "version": "1.0.0",
                "skills_count": c.get("skill_count", 0),
                "skills": [],
                "type": c.get("type"),
                "auth_mode": c.get("auth_mode"),
                "mcp_servers": c.get("mcp_servers", []),
                "examples_zh": c.get("examples_zh", [])[:3],
                "download_url": CONTENT_PLUGINS_URL,
                "install": install,
            }
        )
    return out


def main():
    codex = scan_codex_plugins()
    wb = scan_workbuddy_connectors()
    items = codex + wb
    data = {
        "meta": {
            "title": "Octopus 插件/连接器商城",
            "count": len(items),
            "codex_plugins": len(codex),
            "workbuddy_connectors": len(wb),
            "sources": ["codex(OpenAI/Codex 生态)", "workbuddy(腾讯连接器)"],
            "generated_at": __import__("datetime").datetime.now().isoformat(),
        },
        "items": items,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1), "utf-8")
    # 发布流程每次重建 store,这里必须同步挂图标(否则图标字段被覆盖丢失)
    # 文件名带连字符无法 import,用 subprocess 调图标脚本
    import subprocess

    subprocess.run(
        [sys.executable, str(Path(__file__).resolve().parent / "build-plugin-icons.py")],
        check=False,
    )
    print(f"✔ {OUT} — 插件 {len(codex)} + 连接器 {len(wb)} = {len(items)}")
    for it in items[:5]:
        print("  ", it["id"], "|", it["name_zh"][:30], "|", it["kind"])


if __name__ == "__main__":
    main()
