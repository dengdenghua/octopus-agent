#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 WorkBuddy 108 个连接器转成 octopus 插件格式。

输出(每个连接器一个自包含插件):
  extensions/workbuddy-connectors/packs/<id>/
    ├── plugin.json        # 规范化插件清单(connector 型: auth/mcp/cli/skills)
    ├── mcp.json           # MCP server 定义(如适用)
    ├── cli.json           # CLI 认证流程(如适用)
    ├── connector.json     # 认证编排元数据(auth_mode / 注入规则)
    └── skills/            # 捆绑技能(SKILL.md)

以及汇总:
  extensions/workbuddy-connectors/octopus-manifest.json   # 全量规范化索引
  extensions/workbuddy-connectors/INDEX.md                # 可读索引

用法:
  python3 extensions/workbuddy-connectors/scripts/port-connectors-to-octopus.py [--packs]
    --packs  同时生成 packs/<id>/ 插件目录(默认只生成 manifest + INDEX)
"""
import argparse
import json
import shutil
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # extensions/workbuddy-connectors
MANIFEST = ROOT / ".codebuddy-connector" / "connectors.json"
OUT_MANIFEST = ROOT / "octopus-manifest.json"
OUT_INDEX = ROOT / "INDEX.md"
PACKS = ROOT / "packs"


def normalize(meta: dict) -> dict:
    cid = str(meta.get("id") or "")
    cdir = ROOT / "connectors" / cid
    mcp = {}
    cli = {}
    if (cdir / "mcp.json").exists():
        mcp = json.loads((cdir / "mcp.json").read_text("utf-8")).get("mcpServers", {})
    if (cdir / "cli.json").exists():
        cli = json.loads((cdir / "cli.json").read_text("utf-8"))
    ctype = str(meta.get("type") or "")
    if not ctype:
        ctype = "cli" if cli else ("mcp" if mcp else "skill-only")
    skill_count = len(list((cdir / "skills").rglob("SKILL.md"))) if (cdir / "skills").exists() else 0
    return {
        "id": cid,
        "name": str(meta.get("name") or cid),
        "name_zh": str(meta.get("name_zh") or meta.get("name") or cid),
        "description": str(meta.get("description") or ""),
        "description_zh": str(meta.get("description_zh") or ""),
        "type": ctype,
        "auth_mode": str(meta.get("auth_mode") or ("none" if ctype == "skill-only" else "token")),
        "source": str(meta.get("source") or "workbuddy"),
        "provider_id": str(meta.get("provider_id") or ""),
        "mcp_servers": list(mcp.keys()),
        "mcp": mcp,
        "cli": cli,
        "skill_count": skill_count,
        "examples_zh": meta.get("examples_zh") or [],
        "visible_in": meta.get("visible_in") or [],
        "min_version": str(meta.get("minWorkbuddyVersion") or ""),
    }


def write_pack(entry: dict) -> None:
    pack_dir = PACKS / entry["id"]
    src = ROOT / "connectors" / entry["id"]
    if pack_dir.exists():
        shutil.rmtree(pack_dir, ignore_errors=True)
    pack_dir.mkdir(parents=True)
    plugin_json = {
        "name": entry["id"],
        "version": "1.0.0",
        "description": entry["description_zh"] or entry["description"],
        "author": {"name": "WorkBuddy(Tencent)", "email": "codebuddy@tencent.com"},
        "type": "connector",
        "connector": {
            "id": entry["id"],
            "display_name": entry["name_zh"] or entry["name"],
            "auth_mode": entry["auth_mode"],
            "source": entry["source"],
            "mcp_servers": entry["mcp"],
            "cli": entry["cli"],
        },
        "skills": "./skills/",
    }
    (pack_dir / "plugin.json").write_text(json.dumps(plugin_json, ensure_ascii=False, indent=1), "utf-8")
    (pack_dir / "connector.json").write_text(json.dumps(entry, ensure_ascii=False, indent=1), "utf-8")
    if entry["mcp"]:
        (pack_dir / "mcp.json").write_text(json.dumps({"mcpServers": entry["mcp"]}, ensure_ascii=False, indent=1), "utf-8")
    if entry["cli"]:
        (pack_dir / "cli.json").write_text(json.dumps(entry["cli"], ensure_ascii=False, indent=1), "utf-8")
    if (src / "skills").exists():
        shutil.copytree(src / "skills", pack_dir / "skills")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--packs", action="store_true", help="同时生成 packs/<id>/ 插件目录")
    args = ap.parse_args()

    data = json.loads(MANIFEST.read_text("utf-8"))
    rules = data.get("auth_injection_rules") or []
    entries = [normalize(m) for m in data.get("connectors", [])]
    entries.sort(key=lambda e: e["id"])

    manifest_out = {
        "schema": "octopus.connectors.v1",
        "source": "WorkBuddy(腾讯) 连接器市场 fork",
        "total": len(entries),
        "auth_injection_rules": rules,
        "connectors": entries,
    }
    OUT_MANIFEST.write_text(json.dumps(manifest_out, ensure_ascii=False, indent=1), "utf-8")

    if args.packs:
        for e in entries:
            write_pack(e)
        print(f"✔ 生成 {len(entries)} 个插件包 → {PACKS}/")

    lines = ["# WorkBuddy 连接器 → octopus 插件索引", ""]
    tc = Counter(e["type"] for e in entries)
    lines.append(f"共 **{len(entries)}** 个连接器: mcp {tc.get('mcp',0)} / cli {tc.get('cli',0)} / skill-only {tc.get('skill-only',0)}。")
    lines.append("")
    for e in entries:
        badge = {"mcp": "🔌MCP", "cli": "⌨️CLI", "skill-only": "🧩SKILL"}.get(e["type"], "❓")
        lines.append(f"- `{e['id']}` **{e['name_zh']}** · {badge} · auth={e['auth_mode']} · skills={e['skill_count']}")
    OUT_INDEX.write_text("\n".join(lines), "utf-8")
    print(f"✔ {OUT_MANIFEST.name} + {OUT_INDEX.name} 已生成({len(entries)} 个)")


if __name__ == "__main__":
    main()
