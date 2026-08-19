"""统一「能力包(Capability)」注册表 —— 连接器与插件归一。

连接器(WorkBuddy 108)与 Codex 插件(我们正在运行的 ~/.codex/plugins/cache)
本质都是「能力包」:元数据 + skills + 工具(MCP/CLI) + 认证编排。
本模块把两者归一成同一个 schema、同一套生命周期,让前端一个市场统一管理。

统一模型(CapabilityItem):
  source: "connector" | "codex_plugin"
  auth_mode: token | oauth | server-side | oneid-token | none
  lifecycle: installed / enabled / connected
  install → 复制 skills 到 ~/.octopus/skills + 登记 MCP
  connect → 认证编排(连接器 token/oauth;插件默认无需认证)
"""
from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path
from typing import Any

# ── 默认路径 ────────────────────────────────────────────────
CODEX_PLUGIN_CACHE = Path(os.path.expanduser("~/.codex/plugins/cache"))
CONNECTOR_ROOT = Path(os.path.expanduser("~/.octopus/connectors"))
CONNECTOR_STATE_FILE = CONNECTOR_ROOT / "state.json"
CAPABILITY_STATE_FILE = Path(os.path.expanduser("~/.octopus/capabilities/state.json"))
SKILLS_ROOT = Path(os.path.expanduser("~/.octopus/skills"))

_SLUG_RE = re.compile(r"[^a-z0-9_-]+", re.I)


def _slug(value: str) -> str:
    return _SLUG_RE.sub("-", value.strip()).strip("-").lower()


class CapabilityRegistry:
    """连接器 + Codex 插件的统一注册表(只读市场 + 统一生命周期)。"""

    def __init__(
        self,
        *,
        connector_registry: Any = None,
        auth_orchestrator: Any = None,
        codex_cache: str | Path | None = None,
        capability_state_file: str | Path | None = None,
        skills_root: str | Path | None = None,
    ) -> None:
        if connector_registry is None:
            from runtime.platform.connectors.connector_registry import ConnectorRegistry

            connector_registry = ConnectorRegistry()
        if auth_orchestrator is None:
            from runtime.platform.connectors.auth_orchestrator import AuthOrchestrator

            auth_orchestrator = AuthOrchestrator()
        self._connectors = connector_registry
        self._auth = auth_orchestrator
        self._codex_cache = Path(codex_cache or CODEX_PLUGIN_CACHE)
        self._state_file = Path(capability_state_file or CAPABILITY_STATE_FILE)
        self._skills_root = Path(skills_root or SKILLS_ROOT)

    # ── 统一列表 ────────────────────────────────────────────
    def list(self) -> list[dict[str, Any]]:
        return [*self._list_connectors(), *self._list_codex_plugins()]

    def get(self, cid: str) -> dict[str, Any] | None:
        for item in self.list():
            if item["id"] == cid:
                return item
        return None

    def _list_connectors(self) -> list[dict[str, Any]]:
        out = []
        for c in self._connectors.list():
            item = dict(c)  # ConnectorRegistry.to_dict() 已含 installed/enabled
            item["source"] = "connector"
            item["author"] = "WorkBuddy"
            item["category"] = c.get("type", "mcp")
            out.append(item)
        return out

    def _list_codex_plugins(self) -> list[dict[str, Any]]:
        state = self._state()
        out = []
        scanned = self._scan_codex_plugins()
        # 同 id 多版本缓存:保留版本号最大的(避免 chrome 等重复)
        scanned.sort(key=lambda mr: self._version_key(mr[0].get("version", "")), reverse=True)
        seen: set[str] = set()
        for manifest, root in scanned:
            pid = str(manifest.get("name") or root.name)
            if pid in seen:
                continue
            seen.add(pid)
            pid = str(manifest.get("name") or root.name)
            skills_dir = self._plugin_skills_dir(root, manifest)
            st = state.get(pid) or {}
            author = (
                (manifest.get("author") or {}).get("name", "")
                if isinstance(manifest.get("author"), dict)
                else str(manifest.get("author") or "")
            )
            iface = manifest.get("interface") or {}
            out.append(
                {
                    "id": pid,
                    "name": str(iface.get("displayName") or pid),
                    "name_zh": str(iface.get("displayName") or pid),
                    "description": str(
                        iface.get("shortDescription") or manifest.get("description") or ""
                    ),
                    "description_zh": str(
                        iface.get("shortDescription") or manifest.get("description") or ""
                    ),
                    "type": "plugin",
                    "auth_mode": "none",
                    "source": "codex_plugin",
                    "provider_id": pid,
                    "author": author,
                    "category": str(iface.get("category") or "plugin"),
                    "icon": str(iface.get("logo") or iface.get("composerIcon") or ""),
                    "mcp_servers": [],
                    "skill_count": self._skill_count(skills_dir),
                    "examples_zh": [str(p) for p in (manifest.get("keywords") or [])[:3]],
                    "installed": bool(st.get("installed")),
                    "enabled": bool(st.get("enabled")),
                    "connected": False,
                    "version": str(manifest.get("version") or "1.0.0"),
                    "_skills_dir": str(skills_dir) if skills_dir else None,
                }
            )
        return out

    @staticmethod
    def _version_key(version: str) -> tuple[int, ...]:
        parts = []
        for seg in version.replace("-", ".").split("."):
            if seg.isdigit():
                parts.append(int(seg))
            else:
                parts.append(0)
        return tuple(parts)

    # ── Codex 插件扫描 ──────────────────────────────────────
    def _scan_codex_plugins(self) -> list[tuple[dict[str, Any], Path]]:
        """遍历 ~/.codex/plugins/cache/<family>/<plugin>/<version>/.codex-plugin/plugin.json"""
        if not self._codex_cache.is_dir():
            return []
        out = []
        for manifest_path in sorted(
            self._codex_cache.glob("*/*/*/.codex-plugin/plugin.json")
        ):
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):  # noqa: BLE001
                continue
            if not isinstance(manifest, dict) or not manifest.get("name"):
                continue
            out.append((manifest, manifest_path.parent.parent))  # 插件根目录
        return out

    def _plugin_skills_dir(self, root: Path, manifest: dict[str, Any]) -> Path | None:
        rel = str(manifest.get("skills") or "").strip()
        if not rel:
            return None
        d = (root / rel).resolve()
        return d if d.exists() else None

    def _skill_count(self, skills_dir: Path | None) -> int:
        if not skills_dir or not skills_dir.exists():
            return 0
        return sum(1 for p in skills_dir.rglob("SKILL.md"))

    # ── 统一状态(仅 codex_plugin 用;连接器状态以 ConnectorRegistry 为准)────
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

    def _set_state(self, cid: str, **fields: Any) -> None:
        state = self._state()
        state.setdefault(cid, {})["id"] = cid
        state[cid].update(fields)
        self._write_state(state)

    @staticmethod
    def _public(item: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in item.items() if not k.startswith("_")}

    # ── 统一生命周期:安装/卸载/启停 ─────────────────────────
    def install(self, cid: str) -> dict[str, Any]:
        item = self.get(cid)
        if item is None:
            raise KeyError(f"capability not found: {cid}")
        if item["source"] == "connector":
            return self._connectors.install(cid)
        return self._install_plugin(item)

    def uninstall(self, cid: str) -> bool:
        item = self.get(cid)
        if item is None:
            return False
        if item["source"] == "connector":
            return self._connectors.uninstall(cid)
        return self._uninstall_plugin(cid)

    def set_enabled(self, cid: str, enabled: bool) -> bool:
        item = self.get(cid)
        if item is None:
            return False
        if item["source"] == "connector":
            return self._connectors.set_enabled(cid, enabled)
        if not item["installed"] and enabled:
            return False
        self._set_state(cid, installed=True, enabled=enabled)
        return True

    def _install_plugin(self, item: dict[str, Any]) -> dict[str, Any]:
        cid = item["id"]
        skills_dir = Path(item["_skills_dir"]) if item.get("_skills_dir") else None
        copied = self._install_skills(cid, skills_dir)
        self._set_state(cid, installed=True, enabled=False)
        return {
            "installed": True,
            "capability_id": cid,
            "source": "codex_plugin",
            "type": "plugin",
            "auth_mode": "none",
            "copied_skills": copied,
            "mcp_servers": [],
            "enabled": False,
            "message": f"已安装插件技能({len(copied)} 个)到 ~/.octopus/skills。",
        }

    def _uninstall_plugin(self, cid: str) -> bool:
        state = self._state()
        if cid not in state:
            return False
        del state[cid]
        self._write_state(state)
        # 清理已复制的 skills
        for dest in self._skills_root.glob(f"{_slug(cid)}__*"):
            shutil.rmtree(dest, ignore_errors=True)
        return True

    def _install_skills(self, cid: str, skills_dir: Path | None) -> list[str]:
        if not skills_dir or not skills_dir.exists():
            return []
        self._skills_root.mkdir(parents=True, exist_ok=True)
        copied: list[str] = []
        for skill_md in sorted(skills_dir.rglob("SKILL.md")):
            slug = _slug(f"{cid}__{skill_md.parent.name}")
            dest = self._skills_root / slug
            if dest.exists():
                copied.append(slug)
                continue
            shutil.copytree(skill_md.parent, dest)
            copied.append(slug)
        return copied

    # ── 认证编排(统一入口,连接器走 AuthOrchestrator)────────
    def status(self, cid: str) -> dict[str, Any]:
        item = self.get(cid)
        if item is None:
            raise KeyError(f"capability not found: {cid}")
        if item["source"] == "connector":
            conn = self._connectors.get(cid)
            if conn is None:
                raise KeyError(f"connector not found: {cid}")
            return self._auth.status(conn)
        return {
            "capability_id": cid,
            "auth_mode": "none",
            "connected": False,
            "has_token": False,
            "stored_keys": [],
        }

    def connect(self, cid: str, *, tokens: dict[str, str] | None = None, run_cli: bool = False) -> dict[str, Any]:
        item = self.get(cid)
        if item is None:
            raise KeyError(f"capability not found: {cid}")
        if item["source"] == "connector":
            conn = self._connectors.get(cid)
            if conn is None:
                raise KeyError(f"connector not found: {cid}")
            return self._auth.connect(conn, tokens=tokens, run_cli=run_cli)
        # 插件无需认证,视为已连接
        return {
            "capability_id": cid,
            "connected": True,
            "message": "插件无需认证,已就绪。",
        }

    def disconnect(self, cid: str) -> dict[str, Any]:
        item = self.get(cid)
        if item is None:
            raise KeyError(f"capability not found: {cid}")
        if item["source"] == "connector":
            conn = self._connectors.get(cid)
            if conn is None:
                raise KeyError(f"connector not found: {cid}")
            return self._auth.disconnect(conn)
        return {"capability_id": cid, "connected": False}

    def resolve_headers(self, cid: str) -> dict[str, Any]:
        item = self.get(cid)
        if item is None:
            raise KeyError(f"capability not found: {cid}")
        if item["source"] == "connector":
            conn = self._connectors.get(cid)
            if conn is None:
                raise KeyError(f"connector not found: {cid}")
            return {"headers": self._auth.resolve_headers(conn)}
        return {"headers": {}}


def default_capability_registry() -> CapabilityRegistry:
    return CapabilityRegistry()
