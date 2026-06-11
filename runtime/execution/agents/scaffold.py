from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from runtime.execution.agents.loader import default_agents_root
from runtime.execution.misc.agent_avatar import pixel_agent_avatar_svg
from runtime.platform.io import atomic_write_text

_AGENT_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


@dataclass(frozen=True)
class AgentScaffoldResult:
    agent_id: str
    agent_dir: Path
    profile_path: Path
    created: bool


def validate_agent_id(agent_id: str, *, reserved: set[str] | frozenset[str] | None = None) -> str:
    normalized = agent_id.strip()
    if not normalized:
        raise ValueError("agent_id is required")
    if "/" in normalized or "\\" in normalized or normalized in {".", ".."}:
        raise ValueError("invalid agent_id: cannot contain path separators")
    if not _AGENT_ID_RE.fullmatch(normalized):
        raise ValueError("invalid agent_id: only alphanumeric, hyphens, and underscores allowed")
    if reserved and normalized in reserved:
        raise ValueError(f"agent_id '{normalized}' is reserved")
    return normalized


def scaffold_agent(
    *,
    agent_id: str,
    display_name: str | None = None,
    description: str = "",
    model: str | None = None,
    soul: str | None = None,
    tool_groups: list[str] | None = None,
    extra_affinity: list[str] | None = None,
    private_skills: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    extra_files: dict[str, str] | None = None,
    creator: str = "user",
    template_id: str | None = None,
    agents_root: Path | None = None,
    reserved_ids: set[str] | frozenset[str] | None = None,
) -> AgentScaffoldResult:
    safe_agent_id = validate_agent_id(agent_id, reserved=reserved_ids)
    root = agents_root or default_agents_root()
    agent_dir = root / safe_agent_id
    if agent_dir.exists():
        raise FileExistsError(f"agent already exists: {safe_agent_id}")

    name = (display_name or "").strip() or safe_agent_id.replace("-", " ").replace("_", " ").title()
    profile_path = agent_dir / "profile.jsonc"
    _create_agent_dirs(agent_dir)
    profile = _build_profile(
        agent_id=safe_agent_id,
        display_name=name,
        description=description,
        model=model,
        creator=creator,
        template_id=template_id,
        metadata=metadata,
    )
    atomic_write_text(
        profile_path,
        f"// Octopus Agent profile · {safe_agent_id}\n"
        f"// Created by {creator}\n\n"
        + json.dumps(profile, ensure_ascii=False, indent=2),
    )
    atomic_write_text(
        agent_dir / "agent-core" / "SOUL.md",
        soul or _default_soul(safe_agent_id, name),
        newline=None,
    )
    atomic_write_text(
        agent_dir / "agent-core" / "IDENTITY.md",
        _default_identity(safe_agent_id, name),
        newline=None,
    )
    atomic_write_text(
        agent_dir / "agent-core" / "AGENTS.md",
        _default_agents_md(),
        newline=None,
    )
    atomic_write_text(agent_dir / "avatar.svg", pixel_agent_avatar_svg(name), newline=None)

    if tool_groups or extra_affinity or private_skills:
        registry = {
            "arms": list(dict.fromkeys(tool_groups or [])),
            "extra_affinity": list(dict.fromkeys(extra_affinity or [])),
            "private_skills": list(dict.fromkeys(private_skills or [])),
        }
        atomic_write_text(
            agent_dir / "agent-core" / "tool-registry.jsonc",
            "// Tool registry for this agent\n\n"
            + json.dumps(registry, ensure_ascii=False, indent=2),
        )

    for relative_path, content in (extra_files or {}).items():
        target = _safe_agent_file(agent_dir, relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(target, content, newline=None)

    return AgentScaffoldResult(
        agent_id=safe_agent_id,
        agent_dir=agent_dir,
        profile_path=profile_path,
        created=True,
    )


def _create_agent_dirs(agent_dir: Path) -> None:
    agent_dir.mkdir(parents=True)
    for relative in (
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
        (agent_dir / relative).mkdir()


def _safe_agent_file(agent_dir: Path, relative_path: str) -> Path:
    if not relative_path or Path(relative_path).is_absolute():
        raise ValueError("extra file path must be relative")
    target = (agent_dir / relative_path).resolve()
    root = agent_dir.resolve()
    if target != root and root not in target.parents:
        raise ValueError("extra file path escapes the agent directory")
    return target


def _build_profile(
    *,
    agent_id: str,
    display_name: str,
    description: str,
    model: str | None,
    creator: str,
    template_id: str | None,
    metadata: dict[str, Any] | None,
) -> dict[str, Any]:
    profile: dict[str, Any] = {
        "id": agent_id,
        "templateId": template_id or agent_id,
        "templateVersion": "1.0.0",
        "name": display_name,
        "icon": "🤖",
        "did": f"DID-{uuid.uuid4().hex[:12].upper()}-{uuid.uuid4().hex[:6].upper()}",
        "description": description or f"A custom agent named {agent_id}.",
        "avatar": "avatar.svg",
        "model": {
            "provider": "auto",
            "name": model or "auto",
        },
        "runtime": "local",
        "creator": creator,
        "defaultProject": {
            "dir": "project",
        },
        "capabilities": {},
    }
    if metadata:
        profile["metadata"] = metadata
    return profile


def _default_soul(agent_id: str, display_name: str) -> str:
    return f"""# Soul

You are {display_name} ({agent_id}), a helpful AI collaborator.

## Personality

- Clear, steady, and practical.
- Proactive about surfacing risks and missing context.
- Adaptable to the user's project stage and constraints.

## Values

- Be useful while respecting user autonomy.
- Ground decisions in available evidence.
- Acknowledge uncertainty and propose the next smallest useful step.

---

_This file is yours to evolve. As you learn who you are, update it._
"""


def _default_identity(agent_id: str, display_name: str) -> str:
    return f"""# Identity

- **Name**: {display_name}
- **Agent ID**: {agent_id}
- **Role**: Company project collaborator

## Communication Style

- Clear and professional.
- Matches the user's language.
- Turns ambiguity into concrete options.

## Available arms

- Configurable via tool-registry.jsonc
"""


def _default_agents_md() -> str:
    return """# Working rules (shared by all Octopus agents)

## Project context discovery

Before starting any task, automatically discover the project context.

## Following conventions

When making changes, first read the surrounding code.

## Security

- Never introduce code that exposes or logs secrets.
- Never commit secrets or keys to the repository.
"""


__all__ = [
    "AgentScaffoldResult",
    "scaffold_agent",
    "validate_agent_id",
]
