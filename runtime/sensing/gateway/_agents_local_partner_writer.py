"""SOUL.md template + agent writer for LocalPartner registration.

Extracted from ``agents_local_partner.py`` (god-file reduction). Writes a
LocalPartner agent's profile + SOUL/IDENTITY/AGENTS docs to disk and registers
it in the agent registry.
"""

from __future__ import annotations

import json
from typing import Any

from runtime.execution.misc.agent_avatar import pixel_agent_avatar_svg

from ._agents_local_partner_security import _cleanup_created_agent_dir, _require_safe_agent_id


def soul_template(*, alias: str, partner_name: str, command: str) -> str:
    """Render the SOUL.md persona block for a registered partner."""
    return f"""# Soul

## Persona

你是 {alias}，一个接入到 Octopus 人力池的本地伙伴。你的背后对应本机已经安装的 {partner_name} 工作流。

## Working Style

- 优先用中文和用户协作，保持简洁、可执行。
- 当任务明确需要调用本地伙伴能力时，通过 shell 运行 `{command}`，并把关键结果整理回对话。
- 调用外部命令前先判断是否必要；涉及文件写入、网络、账号态或长任务时说明将要做什么。
- 如果本地工具返回错误,先给出降级方案,而不是把用户卡在工具细节里。
"""


def write_partner_agent(
    *,
    spec: dict[str, Any],
    alias: str,
    command: str,
    executable: str,
    runtime: Any,
    registry: Any,
) -> Any:
    """Write a LocalPartner agent's profile + SOUL/IDENTITY/AGENTS docs
    to disk and register it in the agent registry. Returns the loaded
    Agent instance.

    Idempotent: if the agent dir already exists with a profile.jsonc,
    we just reload + re-register without overwriting any existing
    customizations the user made.
    """
    import uuid

    from runtime.execution.agents.loader import default_agents_root, load_agent
    from runtime.platform.io import atomic_write_text

    agent_id = _require_safe_agent_id(str(spec["agent_id"]))
    root = default_agents_root().resolve()
    agent_dir = root / agent_id
    if agent_dir.is_symlink():
        raise ValueError(f"agent folder is not a real directory: {agent_id}")
    if agent_dir.exists() and not agent_dir.is_dir():
        raise ValueError(f"agent path is not a directory: {agent_id}")
    if agent_dir.exists():
        profile_path = agent_dir / "profile.jsonc"
        if profile_path.is_symlink() or not profile_path.is_file():
            raise ValueError(f"agent folder exists without profile: {agent_id}")
        agent = load_agent(agent_dir, runtime, root / "_shared")
        if hasattr(registry, "replace"):
            registry.replace(agent)
        elif not registry.has(agent_id):
            registry.register(agent)
        return agent

    created_agent_dir = False
    try:
        agent_dir.mkdir(parents=True)
        created_agent_dir = True
        for rel in (
            "agent-core",
            "agent-core/.soul_history",
            "agent-core/diary",
            "agent-core/skills",
            "memory",
            "permissions",
            "project",
            "runtime",
            "sessions",
            "skills",
        ):
            (agent_dir / rel).mkdir(parents=True, exist_ok=True)
    except OSError:
        _cleanup_created_agent_dir(agent_dir, created=created_agent_dir)
        raise

    did = f"DID-{uuid.uuid4().hex[:12].upper()}-{uuid.uuid4().hex[:6].upper()}"
    profile = {
        "id": agent_id,
        "templateId": str(spec["id"]),
        "templateVersion": "1.0.0",
        "name": alias,
        "icon": str(spec.get("icon") or "L"),
        "did": did,
        "description": str(spec["description"]),
        "avatar": "avatar.svg",
        "model": {"provider": "auto", "name": "auto"},
        "runtime": "local_partner",
        "creator": "user",
        "category": "automation",
        "tags": list(spec.get("tags") or []),
        "defaultProject": {"dir": "project"},
        "capabilities": {
            "local_partner": True,
            "local_partner_id": str(spec["id"]),
            "local_partner_command": command,
            "local_partner_executable": executable,
        },
    }
    try:
        atomic_write_text(
            agent_dir / "profile.jsonc",
            (
                f"// Octopus local partner profile · {agent_id}\n"
                "// Created by local partner registration\n\n"
                + json.dumps(profile, ensure_ascii=False, indent=2)
            ),
        )
        soul = soul_template(
            alias=alias,
            partner_name=str(spec["name"]),
            command=command,
        )
        atomic_write_text(agent_dir / "agent-core" / "SOUL.md", soul, newline=None)
        atomic_write_text(
            agent_dir / "agent-core" / "IDENTITY.md",
            f"""# Identity

- **Name**: {alias}
- **Role**: Local partner bridge for {spec["name"]}

## Boundary

- You are registered from a local executable detected on this machine.
- Respect the current workspace and the user's requested task.
""",
            newline=None,
        )
        atomic_write_text(
            agent_dir / "agent-core" / "AGENTS.md",
            """# Working rules

Before using the local partner command, understand the user's task and current workspace. Keep outputs concise and user-facing.
""",
            newline=None,
        )
        atomic_write_text(
            agent_dir / "agent-core" / "tool-registry.jsonc",
            (
                "// Tool registry for this local partner\n\n"
                + json.dumps(
                    {
                        "arms": list(spec.get("tool_groups") or []),
                        "extra_affinity": ["local_partner", str(spec["id"])],
                        "private_skills": [],
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            ),
        )
        atomic_write_text(agent_dir / "avatar.svg", pixel_agent_avatar_svg(alias), newline=None)
    except OSError:
        _cleanup_created_agent_dir(agent_dir, created=created_agent_dir)
        raise

    try:
        agent = load_agent(agent_dir, runtime, root / "_shared")
    except (OSError, ValueError, TypeError):
        _cleanup_created_agent_dir(agent_dir, created=created_agent_dir)
        raise
    try:
        registry.register(agent)
    except (ValueError, TypeError):
        _cleanup_created_agent_dir(agent_dir, created=created_agent_dir)
        raise
    return agent


__all__ = ["soul_template", "write_partner_agent"]
