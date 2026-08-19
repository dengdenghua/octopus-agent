"""连接器注册表 — 加载连接器定义 + 安装/启用状态。

数据源(合并):
  1. WorkBuddy 连接器 fork: extensions/workbuddy-connectors/
     - .codebuddy-connector/connectors.json(108 个索引)
     - connectors/<id>/cli.json + mcp.json + skills/**/SKILL.md
  2. 内置本地连接器: octopus/connectors/ 下的 connector.json(可选)

安装到:
  - skills   → ~/.octopus/skills/<connector>__<skill>/  并登记 registry.json
  - MCP      → 合并进 octopus MCP 配置(默认禁用,需显式启用)
  - state    → ~/.octopus/connectors/state.json
"""
from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path
from typing import Any

CONNECTOR_ROOT = Path(os.path.expanduser("~/.octopus/connectors"))
STATE_FILE = CONNECTOR_ROOT / "state.json"
_SLUG_RE = re.compile(r"[^a-z0-9_-]+", re.I)


def _slug(value: str) -> str:
    return _SLUG_RE.sub("-", value.strip()).strip("-").lower()


class ConnectorDefinition:
    """规范化后的连接器定义(兼收 WorkBuddy / 我们的格式)。"""

    def __init__(
        self,
        *,
        id: str,
        name: str = "",
        name_zh: str = "",
        description: str = "",
        description_zh: str = "",
        type: str = "mcp",  # mcp | cli | skill-only | other
        auth_mode: str = "token",  # token | oauth | server-side | oneid-token | none
        source: str = "workbuddy",
        provider_id: str = "",
        mcp_servers: dict[str, Any] | None = None,
        cli: dict[str, Any] | None = None,
        skills_dir: Path | None = None,
        examples_zh: list[str] | None = None,
        examples_en: list[str] | None = None,
        visible_in: list[str] | None = None,
        min_version: str = "",
        version: str = "1.0.0",
    ) -> None:
        self.id = id
        self.name = name or id
        self.name_zh = name_zh or name or id
        self.description = description
        self.description_zh = description_zh or description
        self.type = type
        self.auth_mode = auth_mode
        self.source = source
        self.provider_id = provider_id
        self.mcp_servers = mcp_servers or {}
        self.cli = cli or {}
        self.skills_dir = skills_dir
        self.examples_zh = examples_zh or []
        self.examples_en = examples_en or []
        self.visible_in = visible_in or []
        self.min_version = min_version
        self.version = version

    def to_dict(self, *, installed: bool = False, enabled: bool = False) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "name_zh": self.name_zh,
            "description": self.description,
            "description_zh": self.description_zh,
            "type": self.type,
            "auth_mode": self.auth_mode,
            "source": self.source,
            "provider_id": self.provider_id,
            "mcp_servers": list(self.mcp_servers.keys()),
            "skill_count": self.skill_count(),
            "examples_zh": self.examples_zh[:3],
            "installed": installed,
            "enabled": enabled,
            "version": self.version,
        }

    def skill_count(self) -> int:
        if not self.skills_dir or not self.skills_dir.exists():
            return 0
        return sum(1 for p in self.skills_dir.rglob("SKILL.md"))


class ConnectorRegistry:
    """从 WorkBuddy fork + 内置目录加载连接器,并维护安装状态。"""

    def __init__(
        self,
        *,
        marketplace_root: str | Path | None = None,
        skills_root: str | Path | None = None,
        state_file: str | Path | None = None,
    ) -> None:
        # 默认指向仓库内 fork: extensions/workbuddy-connectors/
        if marketplace_root is None:
            repo = Path(__file__).resolve().parents[3]  # octopus-agent/
            marketplace_root = repo / "extensions" / "workbuddy-connectors"
        self._root = Path(marketplace_root)
        self._skills_root = Path(skills_root or Path(os.path.expanduser("~/.octopus/skills")))
        self._state_file = Path(state_file or STATE_FILE)

    # ── 定义加载 ──────────────────────────────────────────────
    def _manifest(self) -> dict[str, Any]:
        manifest_path = self._root / ".codebuddy-connector" / "connectors.json"
        if not manifest_path.exists():
            return {"connectors": []}
        try:
            return json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):  # noqa: BLE001
            return {"connectors": []}

    def _connector_dir(self, connector_id: str) -> Path:
        return self._root / "connectors" / connector_id

    def _load_one(self, meta: dict[str, Any]) -> ConnectorDefinition | None:
        cid = str(meta.get("id") or "")
        if not cid:
            return None
        cdir = self._connector_dir(cid)
        mcp: dict[str, Any] = {}
        cli: dict[str, Any] = {}
        if (cdir / "mcp.json").exists():
            try:
                mcp = json.loads((cdir / "mcp.json").read_text(encoding="utf-8")).get(
                    "mcpServers", {}
                )
            except (OSError, json.JSONDecodeError):  # noqa: BLE001
                mcp = {}
        if (cdir / "cli.json").exists():
            try:
                cli = json.loads((cdir / "cli.json").read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):  # noqa: BLE001
                cli = {}
        ctype = str(meta.get("type") or "")
        if not ctype:
            if cli:
                ctype = "cli"
            elif mcp:
                ctype = "mcp"
            else:
                ctype = "skill-only"
        return ConnectorDefinition(
            id=cid,
            name=str(meta.get("name") or cid),
            name_zh=str(meta.get("name_zh") or meta.get("name") or cid),
            description=str(meta.get("description") or ""),
            description_zh=str(meta.get("description_zh") or ""),
            type=ctype,
            auth_mode=str(meta.get("auth_mode") or ("none" if ctype == "skill-only" else "token")),
            source=str(meta.get("source") or "workbuddy"),
            provider_id=str(meta.get("provider_id") or ""),
            mcp_servers=mcp,
            cli=cli,
            skills_dir=cdir / "skills" if (cdir / "skills").exists() else None,
            examples_zh=meta.get("examples_zh") or [],
            examples_en=meta.get("examples_en") or [],
            visible_in=meta.get("visible_in") or [],
            min_version=str(meta.get("minWorkbuddyVersion") or ""),
            version="1.0.0",
        )

    def list(self) -> list[dict[str, Any]]:
        state = self._state()
        out = []
        for meta in self._manifest().get("connectors", []):
            conn = self._load_one(meta)
            if conn is None:
                continue
            st = state.get(conn.id) or {}
            out.append(
                conn.to_dict(
                    installed=bool(st.get("installed")),
                    enabled=bool(st.get("enabled")),
                )
            )
        return out

    def get(self, connector_id: str) -> ConnectorDefinition | None:
        for meta in self._manifest().get("connectors", []):
            if str(meta.get("id")) == connector_id:
                return self._load_one(meta)
        return None

    # ── 状态 ──────────────────────────────────────────────────
    def _state(self) -> dict[str, Any]:
        if not self._state_file.exists():
            return {}
        try:
            return json.loads(self._state_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):  # noqa: BLE001
            return {}

    def _write_state(self, state: dict[str, Any]) -> None:
        self._state_file.parent.mkdir(parents=True, exist_ok=True)
        self._state_file.write_text(json.dumps(state, ensure_ascii=False, indent=1), "utf-8")

    def _set_state(self, connector_id: str, **fields: Any) -> None:
        state = self._state()
        state.setdefault(connector_id, {})["id"] = connector_id
        state[connector_id].update(fields)
        self._write_state(state)

    # ── 安装 / 卸载 / 启停 ────────────────────────────────────
    def install(self, connector_id: str) -> dict[str, Any]:
        conn = self.get(connector_id)
        if conn is None:
            raise KeyError(f"connector not found: {connector_id}")
        copied = self._install_skills(conn)
        self._set_state(connector_id, installed=True, enabled=False, installed_at=None)
        return {
            "installed": True,
            "connector_id": connector_id,
            "type": conn.type,
            "auth_mode": conn.auth_mode,
            "copied_skills": copied,
            "mcp_servers": list(conn.mcp_servers.keys()),
            "enabled": False,
            "message": (
                "已安装技能与 MCP 定义。MCP 默认禁用,连接后(connect)按需启用。"
                if conn.mcp_servers
                else "已安装技能(纯技能连接器无需 MCP)。"
            ),
        }

    def _install_skills(self, conn: ConnectorDefinition) -> list[str]:
        if not conn.skills_dir or not conn.skills_dir.exists():
            return []
        self._skills_root.mkdir(parents=True, exist_ok=True)
        copied: list[str] = []
        registry_path = self._skills_root / "registry.json"
        registry = []
        if registry_path.exists():
            try:
                registry = json.loads(registry_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):  # noqa: BLE001
                registry = []
        by_name = {e.get("name"): e for e in registry}

        for skill_md in sorted(conn.skills_dir.rglob("SKILL.md")):
            slug = _slug(f"{conn.id}__{skill_md.parent.name}")
            dest = self._skills_root / slug
            if dest.exists():
                copied.append(slug)
                continue
            shutil.copytree(skill_md.parent, dest)
            # 补 meta.json
            meta = {"name": slug, "author": f"workbuddy-connector:{conn.id}", "source": "connector"}
            (dest / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), "utf-8")
            by_name[slug] = {
                "name": slug,
                "version": "0.1.0",
                "author": meta["author"],
                "description": f"WorkBuddy 连接器 {conn.id} 捆绑技能",
                "tags": [conn.id, "connector", "workbuddy"],
                "source": "connector",
            }
            copied.append(slug)

        registry_path.write_text(
            json.dumps(list(by_name.values()), ensure_ascii=False, indent=1), "utf-8"
        )
        return copied

    def uninstall(self, connector_id: str) -> bool:
        conn = self.get(connector_id)
        state = self._state()
        if connector_id not in state:
            return False
        if conn is not None and conn.skills_dir:
            for skill_md in conn.skills_dir.rglob("SKILL.md"):
                slug = _slug(f"{conn.id}__{skill_md.parent.name}")
                dest = self._skills_root / slug
                if dest.exists():
                    shutil.rmtree(dest, ignore_errors=True)
            self._rebuild_registry(conn.id)
        del state[connector_id]
        self._write_state(state)
        return True

    def _rebuild_registry(self, removed_connector: str) -> None:
        registry_path = self._skills_root / "registry.json"
        if not registry_path.exists():
            return
        try:
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):  # noqa: BLE001
            return
        registry = [
            e for e in registry if e.get("author") != f"workbuddy-connector:{removed_connector}"
        ]
        registry_path.write_text(json.dumps(registry, ensure_ascii=False, indent=1), "utf-8")

    def set_enabled(self, connector_id: str, enabled: bool) -> bool:
        state = self._state()
        if connector_id not in state:
            return False
        state[connector_id]["enabled"] = bool(enabled)
        self._write_state(state)
        return True

    def installed_ids(self) -> set[str]:
        return {cid for cid, st in self._state().items() if st.get("installed")}


__all__ = ["ConnectorRegistry", "ConnectorDefinition", "CONNECTOR_ROOT"]
