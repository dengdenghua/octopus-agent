"""云商城插件/技能目录源 —— 读发布到 GitHub Pages 的 plugin-store.json / skill-registry.json。

与 CloudExpertStore(专家)同构:远程 GitHub Pages 数据 + 本地镜像回退 + 磁盘缓存。
发布链路(把我们本地插件/技能带上云):
  extensions/workbuddy-experts/scripts/build-plugin-store.py   → plugin-store.json
  extensions/workbuddy-experts/scripts/build-skill-registry.py → skill-registry.json
  extensions/workbuddy-experts/scripts/publish-cloud.py        → 推到 gh-pages
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import tarfile
import tempfile
from pathlib import Path
from typing import Any

from runtime.platform.plugins._secure_fetch import fetch_public_https_bytes
from runtime.platform.process.paths import app_paths

REPO = Path(__file__).resolve().parents[3]
LOCAL_MIRROR_DIR = REPO / "extensions" / "workbuddy-experts" / "storefront" / "data"
CACHE_DIR = app_paths().data_dir / "cache"

_REMOTE_BASE = os.environ.get(
    "OCTOPUS_CLOUD_STORE_URL",
    "https://raw.githubusercontent.com/dengdenghua/workbuddy-expert-market/gh-pages/data",
)

_MAX_CATALOG_BYTES = 8 * 1024 * 1024
_MAX_ARCHIVE_BYTES = 128 * 1024 * 1024
_MAX_ARCHIVE_MEMBERS = 10_000
_MAX_EXTRACTED_BYTES = 256 * 1024 * 1024
_MAX_MEMBER_BYTES = 64 * 1024 * 1024


def _load_remote(name: str) -> dict[str, Any] | None:
    try:
        body = fetch_public_https_bytes(
            f"{_REMOTE_BASE.rstrip('/')}/{name}",
            timeout=15,
            max_bytes=_MAX_CATALOG_BYTES,
        )
        return json.loads(body.decode("utf-8"))
    except Exception:  # noqa: BLE001
        return None


class CloudCatalog:
    """读取云商城插件/技能目录(远程 + 本地镜像回退 + 磁盘缓存)。"""

    KIND_KEYS = {"plugins": "items", "skills": "skills"}

    def __init__(self, kind: str, *, use_cache: bool = True, use_remote: bool = True) -> None:
        if kind not in self.KIND_KEYS:
            raise ValueError(f"unknown cloud catalog kind: {kind}")
        self._kind = kind
        self._list_key = self.KIND_KEYS[kind]
        self._file = "plugin-store.json" if kind == "plugins" else "skill-registry.json"
        self._cache_file = CACHE_DIR / f"cloud-{self._file}"
        self._mirror = LOCAL_MIRROR_DIR / self._file
        self._use_cache = use_cache
        self._use_remote = use_remote
        self._store: dict[str, Any] | None = None

    def _load(self) -> dict[str, Any]:
        if self._store is not None:
            return self._store
        store = None
        # 本地镜像优先:这是我们发布到 Pages 的数据源(仓库内 checked-in),
        # 保证本地看到的就是我们刚生成的插件/技能目录。
        if store is None and self._mirror.exists():
            try:
                store = json.loads(self._mirror.read_text("utf-8"))
            except (OSError, json.JSONDecodeError):
                store = None
        if store is None and self._use_cache and self._cache_file.exists():
            try:
                store = json.loads(self._cache_file.read_text("utf-8"))
            except (OSError, json.JSONDecodeError):
                store = None
        if store is None and self._use_remote:
            remote = _load_remote(self._file)
            if remote and remote.get(self._list_key):
                store = remote
                if self._use_cache:
                    CACHE_DIR.mkdir(parents=True, exist_ok=True)
                    with contextlib.suppress(OSError):
                        self._cache_file.write_text(
                            json.dumps(store, ensure_ascii=False), encoding="utf-8"
                        )
        if store is None:
            raise RuntimeError(
                f"cloud {self._kind} catalog unavailable (remote + local mirror both failed)"
            )
        self._store = store
        return store

    def refresh(self) -> None:
        self._store = None
        if self._use_cache and self._cache_file.exists():
            with contextlib.suppress(OSError):
                self._cache_file.unlink()
        return self._load()

    def meta(self) -> dict[str, Any]:
        return dict(self._load().get("meta") or {})

    def items(self) -> list[dict[str, Any]]:
        return list(self._load().get(self._list_key) or [])

    def list(
        self,
        *,
        search: str | None = None,
        kind: str | None = None,
        offset: int = 0,
        limit: int = 200,
    ) -> dict[str, Any]:
        items = self.items()
        if kind:
            items = [i for i in items if i.get("kind") == kind]
        if search:
            q = search.lower()
            items = [
                i
                for i in items
                if q in str(i.get("name", "")).lower()
                or q in str(i.get("name_zh", "")).lower()
                or q in str(i.get("description", "")).lower()
                or q in str(i.get("id", "")).lower()
            ]
        total = len(items)
        return {"items": items[offset : offset + limit], "total": total}

    # ── 内容包下载 + 安装(从云端下载内容,解包落地) ──────────
    CONTENT_URLS = {
        "plugins": (
            "https://github.com/dengdenghua/workbuddy-expert-market/releases/download/"
            "octopus-content/octopus-plugins.tar.gz"
        ),
        "skills": (
            "https://github.com/dengdenghua/workbuddy-expert-market/releases/download/"
            "octopus-content/octopus-skills.tar.gz"
        ),
    }

    def _archive_path(self) -> Path:
        """下载并缓存内容包 tar.gz,返回本地路径。"""
        url = os.environ.get(
            "OCTOPUS_PLUGINS_CONTENT_URL"
            if self._kind == "plugins"
            else "OCTOPUS_SKILLS_CONTENT_URL",
            self.CONTENT_URLS[self._kind],
        )
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        dest = CACHE_DIR / f"octopus-{self._kind}.tar.gz"
        # 已缓存且非空 → 直接用
        if dest.exists() and dest.stat().st_size > 0:
            if dest.stat().st_size > _MAX_ARCHIVE_BYTES:
                raise ValueError("cached marketplace archive is too large")
            return dest
        tmp = dest.with_suffix(".part")
        try:
            body = fetch_public_https_bytes(
                url,
                timeout=180,
                max_bytes=_MAX_ARCHIVE_BYTES,
            )
            tmp.write_bytes(body)
            tmp.replace(dest)
        finally:
            with contextlib.suppress(OSError):
                tmp.unlink()
        return dest

    @staticmethod
    def _extract_member(
        archive: Path, member_prefix: str, dest_dir: Path, member_name: str
    ) -> Path | None:
        """从 tar.gz 解出 prefix 下的单个目录到 dest_dir,路径穿越安全。返回解出目录或 None。"""
        with tarfile.open(archive, "r:gz") as tf:
            prefix = f"{member_prefix.rstrip('/')}/{member_name}"
            members = [
                m for m in tf.getmembers() if m.name == prefix or m.name.startswith(prefix + "/")
            ]
            if not members:
                return None
            if len(members) > _MAX_ARCHIVE_MEMBERS:
                raise ValueError("marketplace archive contains too many members")
            out = dest_dir / member_name
            out.mkdir(parents=True, exist_ok=True)
            out_res = out.resolve()
            extracted_bytes = 0
            validated: list[tuple[tarfile.TarInfo, Path]] = []
            # 安全校验:每个成员相对 prefix 的路径必须落在 out 内。
            # Links/devices/FIFOs are not needed by skills or plugins and are
            # rejected so a later member cannot write through them.
            for m in members:
                if "\\" in m.name or "\x00" in m.name:
                    raise ValueError(f"unsafe tar path: {m.name}")
                if not (m.isdir() or m.isreg()):
                    raise ValueError(f"unsupported tar member: {m.name}")
                rel = os.path.relpath(m.name, prefix)
                target = (out / rel).resolve()
                if out_res not in target.parents and target != out_res:
                    raise ValueError(f"unsafe tar path: {m.name}")
                if m.isreg():
                    if m.size < 0 or m.size > _MAX_MEMBER_BYTES:
                        raise ValueError(f"tar member is too large: {m.name}")
                    extracted_bytes += m.size
                    if extracted_bytes > _MAX_EXTRACTED_BYTES:
                        raise ValueError("marketplace archive expands beyond the size limit")
                validated.append((m, target))
            for m, target in validated:
                if m.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    source = tf.extractfile(m)
                    if source is None:
                        raise ValueError(f"tar member has no file content: {m.name}")
                    with source, target.open("wb") as output:
                        shutil.copyfileobj(source, output, length=1024 * 1024)
        return out

    def install_skill(self, name: str, *, skills_dir: str | Path | None = None) -> dict[str, Any]:
        """下载技能内容包,把 skills/<name> 落地到技能目录。"""
        safe = re.sub(r"[^A-Za-z0-9_-]", "_", name).strip("_") or "skill"
        dest_root = Path(skills_dir or self.SKILLS_ROOT)
        dest_root.mkdir(parents=True, exist_ok=True)
        target = dest_root / safe
        if (target / "SKILL.md").exists():
            return {"installed": True, "already_exists": True, "name": safe, "path": str(target)}
        with tempfile.TemporaryDirectory(prefix="octopus-skill-") as tmp:
            extracted = self._extract_member(self._archive_path(), "skills", Path(tmp), safe)
            if extracted is None or not (extracted / "SKILL.md").exists():
                raise KeyError(f"skill not found in content pack: {name}")
            if any(child.is_symlink() for child in extracted.rglob("*")):
                raise ValueError(f"skill contains symlinks: {name}")
            shutil.copytree(extracted, target)
        return {"installed": True, "name": safe, "path": str(target), "source": "cloud"}

    # All mutable deployment state follows OCTOPUS_DATA_DIR. In the container
    # that is the /data PVC/bind mount, never the read-only image layer.
    PLUGIN_INSTALL_ROOT = app_paths().data_dir / "plugins"
    # Cloud-catalog skills are mutable runtime state under the data volume.
    SKILLS_ROOT = app_paths().data_dir / "skills"
    # Codex-format plugins use the same writable path as registry consumers.
    CODEX_CACHE_ROOT = app_paths().codex_plugins_path
    # 连接器安装状态(与 connector_registry 的 state.json 同文件,标记已安装)
    CONNECTOR_STATE_FILE = app_paths().data_dir / "connectors" / "state.json"

    @staticmethod
    def _slug(value: str) -> str:
        return re.sub(r"[^a-z0-9_-]+", "-", value.strip()).strip("-").lower()

    def installed_skills(self, skills_dir: str | Path | None = None) -> list[str]:
        """本地已安装技能名(目录含 SKILL.md)。"""
        root = Path(skills_dir or self.SKILLS_ROOT)
        if not root.exists():
            return []
        return sorted(
            d.name
            for d in root.iterdir()
            if d.is_dir() and (d / "SKILL.md").exists() and not d.name.startswith((".", "_"))
        )

    def installed_plugins(self) -> list[str]:
        """本地已安装插件/连接器(按存档成员名)。

        来源合并三处,保证线上商城对「本地已有」的项直接标已安装:
          1. 云安装落点 ~/.octopus/plugins/<kind>/<id>(本功能装的)
          2. Codex 格式插件 ~/.octopus/plugins/codex/<plugin>/.codex-plugin/plugin.json
             (首次自动从旧 ~/.codex/plugins/cache 同步)
          3. 连接器安装状态 ~/.octopus/connectors/state.json(installed=true)
        """
        names: set[str] = set()
        root = self.PLUGIN_INSTALL_ROOT
        if root.exists():
            for kind_dir in root.iterdir():
                if kind_dir.is_dir():
                    for d in kind_dir.iterdir():
                        if d.is_dir():
                            names.add(d.name)
        codex_cache = self.CODEX_CACHE_ROOT
        if not codex_cache.is_dir():
            from runtime.platform.plugins.codex_discovery import (
                sync_codex_cache_to_octopus,
            )

            sync_codex_cache_to_octopus(dest=codex_cache)
        if codex_cache.is_dir():
            for manifest in codex_cache.glob("*/.codex-plugin/plugin.json"):
                try:
                    meta = json.loads(manifest.read_text("utf-8"))
                    pid = str(meta.get("name") or "")
                except (OSError, json.JSONDecodeError):  # noqa: BLE001
                    continue
                if pid:
                    names.add(pid)
        if self.CONNECTOR_STATE_FILE.exists():
            try:
                state = json.loads(self.CONNECTOR_STATE_FILE.read_text("utf-8"))
            except (OSError, json.JSONDecodeError):  # noqa: BLE001
                state = {}
            for cid, v in state.items():
                if isinstance(v, dict) and v.get("installed"):
                    names.add(cid)
        return sorted(names)

    def _copy_bundled_skills(self, plugin_dir: Path, plugin_id: str) -> list[str]:
        """把插件捆绑的 skills/ 复制到 ~/.octopus/skills/<id>__<skill> 并登记。"""
        skills_dir = plugin_dir / "skills"
        if not skills_dir.exists():
            return []
        skills_root = self.SKILLS_ROOT
        skills_root.mkdir(parents=True, exist_ok=True)
        registry_path = skills_root / "registry.json"
        registry: list[dict[str, Any]] = []
        if registry_path.exists():
            try:
                registry = json.loads(registry_path.read_text("utf-8"))
            except (OSError, json.JSONDecodeError):  # noqa: BLE001
                registry = []
        by_name = {e.get("name"): e for e in registry}
        copied: list[str] = []
        for skill_md in sorted(skills_dir.rglob("SKILL.md")):
            slug = self._slug(f"{plugin_id}__{skill_md.parent.name}")
            dest = skills_root / slug
            if dest.exists():
                copied.append(slug)
                continue
            shutil.copytree(skill_md.parent, dest)
            meta = {"name": slug, "author": f"cloud-plugin:{plugin_id}", "source": "cloud"}
            (dest / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), "utf-8")
            by_name[slug] = {
                "name": slug,
                "version": "0.1.0",
                "author": meta["author"],
                "description": f"云插件 {plugin_id} 捆绑技能",
                "tags": [plugin_id, "cloud"],
                "source": "cloud",
            }
            copied.append(slug)
        registry_path.write_text(
            json.dumps(list(by_name.values()), ensure_ascii=False, indent=1), "utf-8"
        )
        return copied

    def install_plugin(
        self, plugin_id: str, *, plugin_kind: str = "connector", dest_root: str | Path | None = None
    ) -> dict[str, Any]:
        """下载插件内容包,把 plugins/<kind>/<id> 落地 + 复制捆绑技能到本地技能库。"""
        safe = re.sub(r"[^A-Za-z0-9_-]", "_", plugin_id).strip("_") or "plugin"
        member_prefix = f"plugins/{plugin_kind}"
        dest = Path(dest_root or (self.PLUGIN_INSTALL_ROOT / plugin_kind))
        dest.mkdir(parents=True, exist_ok=True)
        target = dest / safe
        with tempfile.TemporaryDirectory(prefix="octopus-plugin-") as tmp:
            extracted = self._extract_member(self._archive_path(), member_prefix, Path(tmp), safe)
            if extracted is None:
                raise KeyError(f"plugin not found in content pack: {plugin_id}")
            if any(child.is_symlink() for child in extracted.rglob("*")):
                raise ValueError(f"plugin contains symlinks: {plugin_id}")
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(extracted, target)
        copied = self._copy_bundled_skills(target, safe)
        # 连接器 → 标记安装状态(与 connector_registry 共用 state.json)
        if plugin_kind == "connector":
            self.CONNECTOR_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            state: dict[str, Any] = {}
            if self.CONNECTOR_STATE_FILE.exists():
                try:
                    state = json.loads(self.CONNECTOR_STATE_FILE.read_text("utf-8"))
                except (OSError, json.JSONDecodeError):  # noqa: BLE001
                    state = {}
            state.setdefault(safe, {})["id"] = safe
            state[safe].update(installed=True, enabled=False, source="cloud")
            self.CONNECTOR_STATE_FILE.write_text(
                json.dumps(state, ensure_ascii=False, indent=1), "utf-8"
            )
        return {
            "installed": True,
            "plugin_id": plugin_id,
            "kind": plugin_kind,
            "path": str(target),
            "copied_skills": copied,
            "source": "cloud",
        }
