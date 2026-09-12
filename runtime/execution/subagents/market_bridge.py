"""子 agent 与角色市场（agent world）的身份桥。

设计原则：**已安装角色是子 agent 职位与头像的唯一来源**——
- 正向：``agents/<id>/profile.jsonc`` 里的角色自动注册为可派发的
  子 agent（scope="market"，优先级最低），职位（display_name）与
  头像（avatar.svg → /api/agents/<id>/avatar）直接复用，不用另造；
- 反查：任何子 agent 名字都能反查市场身份（``resolve_market_identity``），
  列表与生命周期事件借此带上职位和头像；
- 晋升：使用过程中没有合适岗位时，把子 agent 定义晋升为市场角色
  （``promote_definition_to_market``）——写 profile.jsonc + 生成头像 +
  SOUL.md，立刻出现在"我的安装"里。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from runtime.execution.subagents.registry import SubagentDefinition

_SAFE_AGENT_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")
_AVATAR_EXTS = ("png", "webp", "jpg", "jpeg", "svg")


def _normalize_name(value: str) -> str:
    return re.sub(r"[\s_]+", "-", str(value or "").strip().lower())


def _avatar_url_for(agent_id: str, agent_dir: Path) -> str:
    for ext in _AVATAR_EXTS:
        path = agent_dir / f"avatar.{ext}"
        if path.is_file():
            return f"/api/agents/{agent_id}/avatar?v={int(path.stat().st_mtime)}"
    return ""


@dataclass(frozen=True)
class MarketIdentity:
    """一个已安装角色的展示身份（职位 + 头像）。"""

    agent_id: str
    display_name: str
    avatar_url: str
    description: str
    soul_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "display_name": self.display_name,
            "avatar_url": self.avatar_url,
            "description": self.description,
            "identity_source": "agent-market",
        }


def _read_profile(agent_dir: Path) -> dict[str, Any] | None:
    profile_path = agent_dir / "profile.jsonc"
    if not profile_path.is_file():
        return None
    text = profile_path.read_text(encoding="utf-8")
    # profile.jsonc 允许 // 注释：解析前剥掉行注释（与 gateway 的 jsonc 读取一致）。
    stripped = "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("//")
    )
    try:
        data = json.loads(stripped)
    except (json.JSONDecodeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def iter_market_agents(agents_root: Path | None = None):
    """遍历已安装角色目录，产出 (agent_id, agent_dir, profile)。"""

    if agents_root is None:
        from runtime.execution.agents.loader import default_agents_root

        agents_root = default_agents_root()
    if not agents_root.is_dir():
        return
    for agent_dir in sorted(agents_root.iterdir()):
        if not agent_dir.is_dir() or agent_dir.name.startswith("_"):
            continue
        profile = _read_profile(agent_dir)
        if profile is None:
            continue
        agent_id = str(profile.get("id") or agent_dir.name).strip()
        if not _SAFE_AGENT_ID_RE.fullmatch(agent_id):
            continue
        yield agent_id, agent_dir, profile


def market_identity_index(
    agents_root: Path | None = None,
) -> dict[str, MarketIdentity]:
    """按 id / name / display_name 的归一化名字建身份索引。"""

    index: dict[str, MarketIdentity] = {}
    for agent_id, agent_dir, profile in iter_market_agents(agents_root):
        soul_path = agent_dir / "agent-core" / "SOUL.md"
        identity = MarketIdentity(
            agent_id=agent_id,
            display_name=str(profile.get("name") or agent_id),
            avatar_url=_avatar_url_for(agent_id, agent_dir),
            description=str(profile.get("description") or ""),
            soul_path=str(soul_path) if soul_path.is_file() else "",
        )
        for key in {
            _normalize_name(agent_id),
            _normalize_name(identity.display_name),
        }:
            if key:
                index.setdefault(key, identity)
    return index


def resolve_market_identity(
    name: str, agents_root: Path | None = None
) -> MarketIdentity | None:
    """子 agent 名字 → 市场角色身份（职位+头像）。未命中返回 None。"""

    key = _normalize_name(name)
    if not key:
        return None
    return market_identity_index(agents_root).get(key)


def market_definitions(
    agents_root: Path | None = None,
) -> list[SubagentDefinition]:
    """已安装角色 → 可派发的子 agent 定义（scope="market"）。

    系统提示词取角色的 SOUL.md（安装时已生成）；没有 SOUL.md 的角色
    用 profile 描述合成最小提示词，保证每个已装角色都能被派发。
    """

    out: list[SubagentDefinition] = []
    for agent_id, agent_dir, profile in iter_market_agents(agents_root):
        soul_path = agent_dir / "agent-core" / "SOUL.md"
        if soul_path.is_file():
            try:
                system_prompt = soul_path.read_text(encoding="utf-8").strip()
            except OSError:
                system_prompt = ""
        else:
            system_prompt = ""
        description = str(profile.get("description") or "").strip()
        if not system_prompt:
            display_name = str(profile.get("name") or agent_id)
            system_prompt = (
                f"You are {display_name}.\n\n"
                f"Primary mission: {description or display_name}.\n"
                "Be concise, action-oriented, and precise."
            )
        out.append(
            SubagentDefinition(
                name=agent_id,
                description=description or agent_id,
                system_prompt=system_prompt,
                source_path=str(agent_dir / "profile.jsonc"),
                scope="market",
                display_name=str(profile.get("name") or agent_id),
                avatar_url=_avatar_url_for(agent_id, agent_dir),
            )
        )
    return out


def promote_definition_to_market(
    definition: SubagentDefinition,
    agents_root: Path,
) -> dict[str, Any]:
    """把一个子 agent 定义晋升为市场角色（进"我的安装"）。

    幂等：同名角色已存在时直接返回现状，不覆盖用户改过的文件。
    """

    agent_id = definition.name.strip()
    if not _SAFE_AGENT_ID_RE.fullmatch(agent_id):
        raise ValueError(
            "invalid subagent name for promotion: only alphanumeric characters, "
            "hyphens, and underscores are allowed"
        )
    agent_dir = agents_root / agent_id
    profile_path = agent_dir / "profile.jsonc"
    if profile_path.is_file():
        profile = _read_profile(agent_dir) or {}
        return {
            "agent_id": agent_id,
            "created": False,
            "display_name": str(profile.get("name") or agent_id),
            "avatar_url": _avatar_url_for(agent_id, agent_dir),
        }

    from runtime.execution.misc.agent_avatar import pixel_agent_avatar_svg
    from runtime.platform.io import atomic_write_json, atomic_write_text

    display_name = definition.display_name or definition.name
    core = agent_dir / "agent-core"
    core.mkdir(parents=True, exist_ok=True)
    atomic_write_json(
        profile_path,
        {
            "id": agent_id,
            "templateId": agent_id,
            "source_kind": "subagent-promoted",
            "managed_by": "agent-market",
            "name": display_name,
            "icon": "🤖",
            "description": definition.description or agent_id,
            "avatar": "avatar.svg",
            "category": "promoted-subagent",
            "tags": list(definition.capabilities),
            "model": {"provider": "auto", "name": definition.model or "auto"},
            "runtime": "local",
            "available_skills": [],
            "key_skills": [],
        },
        ensure_ascii=False,
        indent=2,
    )
    atomic_write_text(
        agent_dir / "avatar.svg",
        pixel_agent_avatar_svg(display_name),
        newline=None,
    )
    atomic_write_text(
        core / "SOUL.md",
        definition.system_prompt or f"You are {display_name}.",
        newline=None,
    )
    atomic_write_text(
        core / "IDENTITY.md",
        f"- Name: {display_name}\n- Role: promoted subagent ({definition.name})\n",
        newline=None,
    )
    return {
        "agent_id": agent_id,
        "created": True,
        "display_name": display_name,
        "avatar_url": _avatar_url_for(agent_id, agent_dir),
    }


def auto_promote_if_unpositioned(
    *,
    name: str,
    has_registry_definition: bool,
    has_builtin_display: bool,
    mission_preview: str = "",
    agents_root: Path | None = None,
) -> dict[str, Any] | None:
    """使用过程中没有合适岗位 → 现造一个并进"我的安装"。

    只在名字匹配不到任何既有身份（registry 定义、内置角色、已装市场角色）
    时触发；幂等——同名的晋升过的角色不会被重建或覆盖。可用环境变量
    ``OCTOPUS_SUBAGENT_AUTOPROMOTE=0`` 关闭。返回晋升结果（含 display_name
    与 avatar_url），未触发返回 None。
    """

    import os

    if str(os.environ.get("OCTOPUS_SUBAGENT_AUTOPROMOTE", "")).strip().lower() in (
        "0",
        "false",
        "off",
    ):
        return None
    candidate = str(name or "").strip()
    # 至少 3 个字符、含字母——派发器偶发的纯数字/单字符 lane id 不配占岗。
    if len(candidate) < 3 or not re.search(r"[A-Za-z]", candidate):
        return None
    if not _SAFE_AGENT_ID_RE.fullmatch(candidate):
        return None
    if has_registry_definition or has_builtin_display:
        return None

    if agents_root is None:
        from runtime.execution.agents.loader import default_agents_root

        agents_root = default_agents_root()
    display_name = " ".join(
        part.capitalize() for part in re.split(r"[-_]+", candidate) if part
    )
    preview = mission_preview.strip()
    charter = (
        f"You are {display_name} ({candidate}).\n\n"
        "This position was auto-created from its first delegation. "
        "Provisional charter (refine as the role's responsibilities "
        "become clearer):\n\n"
        f"{preview or '(no mission preview recorded)'}\n"
    )
    definition = SubagentDefinition(
        name=candidate,
        description=f"Auto-created from delegation ({display_name})",
        system_prompt=charter,
        source_path="",
        scope="auto",
        display_name=display_name,
    )
    result = promote_definition_to_market(definition, agents_root)
    if result.get("created"):
        result["identity_source"] = "agent-market-auto"
    return result


__all__ = [
    "MarketIdentity",
    "auto_promote_if_unpositioned",
    "iter_market_agents",
    "market_definitions",
    "market_identity_index",
    "promote_definition_to_market",
    "resolve_market_identity",
]
