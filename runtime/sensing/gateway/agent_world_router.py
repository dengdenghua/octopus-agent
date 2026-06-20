# ruff: noqa: E402 — module-level imports below are intentionally late
"""Agent Market router · local agent marketplace.

Exposes the built-in agents under `agents/` as a browsable store and
persists install/uninstall state to a lightweight JSON file under the
user's home directory. This makes the frontend Agent Market usable even
before a remote marketplace exists.
"""
from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path
from typing import Any

try:
    from fastapi import APIRouter, HTTPException, Query

    FASTAPI_AVAILABLE = True
except ImportError:  # pragma: no cover
    FASTAPI_AVAILABLE = False
    APIRouter = None  # type: ignore[assignment, misc]
    HTTPException = None  # type: ignore[assignment, misc]
    Query = None  # type: ignore[assignment, misc]

from runtime.execution.agents.loader import default_agents_root
from runtime.execution.misc.agent_avatar import write_pixel_agent_avatar
from runtime.platform.process.paths import resources_root

_INSTALL_STATE = Path(os.path.expanduser("~/.octopus/agents-installed.json"))
_OCTOPUS_AUTHOR = "octopus"
_OCTOPUS_AUTHOR_ALIASES = {"preset", "system", "octopus", "Octopus"}
_AGENCY_AGENTS_ROOT = Path(__file__).with_name("agent_market_sources") / "agency-agents"
_FINANCIAL_SERVICES_ROOT = Path(__file__).with_name("agent_market_sources") / "financial-services"
_HARDWARE_STARTUP_ROOT = Path(__file__).with_name("agent_market_sources") / "hardware-startup"
_AGENCY_AGENT_DIRS = {
    "academic": "researcher",
    "design": "creative",
    "engineering": "coder",
    "finance": "specialist",
    "game-development": "creative",
    "marketing": "creative",
    "paid-media": "creative",
    "product": "researcher",
    "project-management": "automation",
    "sales": "assistant",
    "spatial-computing": "specialist",
    "specialized": "specialist",
    "strategy": "researcher",
    "support": "assistant",
    "testing": "coder",
}
BUILTIN_TEMPLATES: list[dict[str, Any]] = [
    {"id": "test_writer", "display_name": "Test Writer", "description": "Writes focused unit, integration, and regression tests from changed code.", "author": "octopus", "category": "coder", "tags": ["test", "coverage", "pytest"], "icon": "🧪", "featured": True},
    {"id": "code_reviewer", "display_name": "Code Reviewer", "description": "Finds logic gaps, unsafe changes, and maintainability issues before merge.", "author": "octopus", "category": "coder", "tags": ["review", "quality", "diff"], "icon": "🧐", "featured": True},
    {"id": "security_auditor", "display_name": "Security Auditor", "description": "Audits code for auth flaws, injection risks, secrets, and unsafe file operations.", "author": "octopus", "category": "specialist", "tags": ["security", "audit", "owasp"], "icon": "🔐", "featured": True},
    {"id": "api_architect", "display_name": "API Architect", "description": "Designs service boundaries, request contracts, and migration-friendly API changes.", "author": "octopus", "category": "specialist", "tags": ["api", "architecture", "backend"], "icon": "🧭", "featured": True},
    {"id": "frontend_copilot", "display_name": "Frontend Copilot", "description": "Builds polished UI flows, empty states, loading states, and responsive layouts.", "author": "octopus", "category": "creative", "tags": ["ui", "react", "tailwind"], "icon": "🎨", "featured": True},
    {"id": "docs_writer", "display_name": "Docs Writer", "description": "Turns implementation details into README, migration notes, and user-facing docs.", "author": "octopus", "category": "assistant", "tags": ["docs", "readme", "guide"], "icon": "📝", "featured": False},
    {"id": "bug_hunter", "display_name": "Bug Hunter", "description": "Reproduces bugs, narrows root causes, and proposes the smallest safe fix.", "author": "octopus", "category": "coder", "tags": ["bug", "debug", "triage"], "icon": "🐛", "featured": True},
    {"id": "refactor_surgeon", "display_name": "Refactor Surgeon", "description": "Performs targeted refactors while preserving behavior and minimizing blast radius.", "author": "octopus", "category": "coder", "tags": ["refactor", "cleanup", "maintainability"], "icon": "✂️", "featured": False},
    {"id": "release_manager", "display_name": "Release Manager", "description": "Prepares changelogs, verifies ship readiness, and checks release blocking issues.", "author": "octopus", "category": "automation", "tags": ["release", "changelog", "ship"], "icon": "🚀", "featured": False},
    {"id": "data_analyst", "display_name": "Data Analyst", "description": "Reads datasets, summarizes metrics, and produces analysis notebooks or reports.", "author": "octopus", "category": "researcher", "tags": ["data", "analysis", "notebook"], "icon": "📊", "featured": False},
    {"id": "deep_researcher", "display_name": "Deep Researcher", "description": "Performs broad multi-file and multi-source investigations before implementation.", "author": "octopus", "category": "researcher", "tags": ["research", "investigation", "planning"], "icon": "🔬", "featured": True},
    {"id": "performance_engineer", "display_name": "Performance Engineer", "description": "Finds bottlenecks, reduces bundle size, and improves runtime performance.", "author": "octopus", "category": "specialist", "tags": ["performance", "profiling", "optimization"], "icon": "⚙️", "featured": False},
    {"id": "cli_builder", "display_name": "CLI Builder", "description": "Designs commands, flags, help text, and ergonomic terminal-first workflows.", "author": "octopus", "category": "coder", "tags": ["cli", "terminal", "argparse"], "icon": "⌨️", "featured": False},
    {"id": "database_migrator", "display_name": "Database Migrator", "description": "Plans safe schema changes, backfills, and rollback-aware migrations.", "author": "octopus", "category": "specialist", "tags": ["database", "migration", "sql"], "icon": "🗃️", "featured": False},
    {"id": "observability_ops", "display_name": "Observability Ops", "description": "Improves logs, metrics, tracing, and alertability for production services.", "author": "octopus", "category": "automation", "tags": ["logs", "metrics", "tracing"], "icon": "📡", "featured": False},
    {"id": "prompt_designer", "display_name": "Prompt Designer", "description": "Tunes prompts, structured outputs, and tool-use contracts for AI products.", "author": "octopus", "category": "creative", "tags": ["prompt", "llm", "ai"], "icon": "✨", "featured": False},
    {"id": "workflow_automator", "display_name": "Workflow Automator", "description": "Builds repeatable workflow, task, and ops automations across tools.", "author": "octopus", "category": "automation", "tags": ["workflow", "ops", "automation"], "icon": "🔁", "featured": False},
    {"id": "knowledge_curator", "display_name": "Knowledge Curator", "description": "Collects scattered project knowledge into reusable reference pages and guides.", "author": "octopus", "category": "assistant", "tags": ["knowledge", "wiki", "curation"], "icon": "📚", "featured": False},
    {"id": "content_strategist", "display_name": "Content Strategist", "description": "Creates landing copy, positioning, and campaign messaging for product launches.", "author": "octopus", "category": "creative", "tags": ["marketing", "copywriting", "content"], "icon": "📣", "featured": False},
    {"id": "support_triager", "display_name": "Support Triager", "description": "Turns user reports into repro steps, suspected root causes, and fix tickets.", "author": "octopus", "category": "assistant", "tags": ["support", "triage", "issues"], "icon": "🧰", "featured": False},
    {"id": "browser_operator", "display_name": "Browser Operator", "description": "Handles browser-based workflows, form filling, and visual verification steps.", "author": "octopus", "category": "automation", "tags": ["browser", "web", "operator"], "icon": "🌐", "featured": False},
    {"id": "product_analyst", "display_name": "Product Analyst", "description": "Converts qualitative requests into specs, risks, tradeoffs, and delivery slices.", "author": "octopus", "category": "researcher", "tags": ["product", "spec", "analysis"], "icon": "🧠", "featured": False},
]


def _read_install_state() -> set[str]:
    try:
        if _INSTALL_STATE.is_file():
            data = json.loads(_INSTALL_STATE.read_text(encoding="utf-8"))
            return set(data.get("installed", []))
    except (OSError, json.JSONDecodeError, ValueError):  # noqa: BLE001 — installed list missing/corrupt; treat as empty set
        pass
    return set()


def _write_install_state(installed: set[str]) -> None:
    _INSTALL_STATE.parent.mkdir(parents=True, exist_ok=True)
    _INSTALL_STATE.write_text(
        json.dumps({"installed": sorted(installed)}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


from runtime.platform.process.utils import parse_jsonc as _parse_jsonc


def _slug_to_title(slug: str) -> str:
    return " ".join(part.capitalize() for part in re.split(r"[-_]+", slug) if part)


def _normalize_local_author(value: Any) -> str:
    author = str(value or "").strip()
    if author in _OCTOPUS_AUTHOR_ALIASES:
        return _OCTOPUS_AUTHOR
    return author or "local"


def _parse_agent_markdown(path: Path) -> tuple[dict[str, str], str]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}, text
    lines = text.splitlines()
    end = next((i for i, line in enumerate(lines[1:], start=1) if line.strip() == "---"), None)
    if end is None:
        return {}, text
    meta: dict[str, str] = {}
    for line in lines[1:end]:
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        meta[key.strip()] = value.strip().strip("\"'")
    return meta, "\n".join(lines[end + 1 :]).strip()


def _parse_agent_key_skills(body: str) -> list[str]:
    section = re.search(
        r"^##+\s+Skills\s+this\s+agent\s+uses\s*$([\s\S]*?)(?=^##+\s+|\Z)",
        body,
        flags=re.IGNORECASE | re.MULTILINE,
    )
    if not section:
        return []
    skills = re.findall(r"`([^`]+)`", section.group(1))
    return list(dict.fromkeys(skill.strip() for skill in skills if skill.strip()))


def _template_private_skills(template: dict[str, Any]) -> list[str]:
    raw = template.get("private_skills") or []
    if not isinstance(raw, list):
        return []
    return list(dict.fromkeys(str(skill).strip() for skill in raw if str(skill).strip()))


def _template_skill_catalog(template: dict[str, Any]) -> list[str]:
    raw = template.get("available_skills") or []
    if isinstance(raw, list) and raw:
        return list(dict.fromkeys(str(skill).strip() for skill in raw if str(skill).strip()))
    source_rel = template.get("skill_source_root")
    if not source_rel:
        return _template_private_skills(template)
    source_root = _template_source_root(template) / str(source_rel)
    if not source_root.is_dir():
        return _template_private_skills(template)
    names = [
        path.parent.name
        for path in sorted(source_root.rglob("SKILL.md"))
        if path.parent.is_dir()
    ]
    return list(dict.fromkeys(name for name in names if name))


def _load_agency_templates() -> list[dict[str, Any]]:
    if not _AGENCY_AGENTS_ROOT.is_dir():
        return []
    templates: list[dict[str, Any]] = []
    for division, category in _AGENCY_AGENT_DIRS.items():
        division_root = _AGENCY_AGENTS_ROOT / division
        if not division_root.is_dir():
            continue
        for path in sorted(division_root.rglob("*.md")):
            if path.name.upper() in {"README.MD", "EXECUTIVE-BRIEF.MD", "QUICKSTART.MD"}:
                continue
            meta, body = _parse_agent_markdown(path)
            if not body or not meta.get("name") or not meta.get("description"):
                continue
            slug = path.stem.lower().replace("_", "-")
            agent_id = f"agency_{slug.replace('-', '_')}"
            tags = ["agency-agents", division, *[p for p in slug.split("-")[:4] if p != division]]
            templates.append({
                "id": agent_id,
                "display_name": meta.get("name") or _slug_to_title(path.stem),
                "description": meta.get("description") or meta.get("vibe") or f"{_slug_to_title(path.stem)} from The Agency.",
                "author": "msitarzewski/agency-agents",
                "category": category,
                "tags": list(dict.fromkeys(tags)),
                "icon": meta.get("emoji") or "🤖",
                "featured": False,
                "source_repo": "agency-agents",
                "source_path": str(path.relative_to(_AGENCY_AGENTS_ROOT)),
                "source_url": f"https://github.com/msitarzewski/agency-agents/blob/main/{path.relative_to(_AGENCY_AGENTS_ROOT).as_posix()}",
            })
    return templates


def _load_financial_services_templates() -> list[dict[str, Any]]:
    agent_root = _FINANCIAL_SERVICES_ROOT / "agent-plugins"
    if not agent_root.is_dir():
        return []
    icons = {
        "earnings-reviewer": "📈",
        "gl-reconciler": "🧾",
        "kyc-screener": "🛡️",
        "market-researcher": "🔎",
        "meeting-prep-agent": "📋",
        "model-builder": "📊",
        "month-end-closer": "🗓️",
        "pitch-agent": "💼",
        "statement-auditor": "✅",
        "valuation-reviewer": "💵",
    }
    display_names = {
        "gl-reconciler": "GL Reconciler",
        "kyc-screener": "KYC Screener",
    }
    templates: list[dict[str, Any]] = []
    for path in sorted(agent_root.glob("*/agents/*.md")):
        meta, body = _parse_agent_markdown(path)
        if not body or not meta.get("name") or not meta.get("description"):
            continue
        slug = str(meta["name"]).strip().lower().replace("_", "-")
        agent_id = f"financial_{slug.replace('-', '_')}"
        repo_path = Path("plugins") / path.relative_to(_FINANCIAL_SERVICES_ROOT)
        key_skills = _parse_agent_key_skills(body)
        skill_source_root = str((path.parent.parent / "skills").relative_to(_FINANCIAL_SERVICES_ROOT))
        tags = ["financial-services", "finance", *[p for p in slug.split("-") if p not in {"agent"}]]
        templates.append({
            "id": agent_id,
            "display_name": display_names.get(slug, _slug_to_title(slug)),
            "description": meta["description"],
            "author": "anthropics/financial-services",
            "category": "financial",
            "tags": list(dict.fromkeys(tags)),
            "icon": icons.get(slug, "💼"),
            "featured": False,
            "source_repo": "financial-services",
            "source_path": str(path.relative_to(_FINANCIAL_SERVICES_ROOT)),
            "source_url": f"https://github.com/anthropics/financial-services/blob/main/{repo_path.as_posix()}",
            "private_skills": key_skills,
            "skill_source_root": skill_source_root,
        })
    return templates


def _load_hardware_startup_templates() -> list[dict[str, Any]]:
    """Load templates from the hardware-startup bundle.

    Mirrors _load_financial_services_templates: walks
    ``agent_market_sources/hardware-startup/agent-plugins/*/agents/*.md``
    and turns each agent markdown into a market template entry.

    Hardware-startup agents (patent/FTO, certification, crowdfunding,
    supply-chain) target the early-stage hardware product lifecycle.
    """
    agent_root = _HARDWARE_STARTUP_ROOT / "agent-plugins"
    if not agent_root.is_dir():
        return []
    icons = {
        "patent-fto-screener": "🔬",
        "certification-readiness": "📜",
        "crowdfunding-launch-manager": "🚀",
        "supply-chain-monitor": "🏭",
    }
    display_names = {
        "patent-fto-screener": "Patent / FTO Screener",
    }
    templates: list[dict[str, Any]] = []
    for path in sorted(agent_root.glob("*/agents/*.md")):
        meta, body = _parse_agent_markdown(path)
        if not body or not meta.get("name") or not meta.get("description"):
            continue
        slug = str(meta["name"]).strip().lower().replace("_", "-")
        agent_id = f"hardware_{slug.replace('-', '_')}"
        key_skills = _parse_agent_key_skills(body)
        skill_source_root = str(
            (path.parent.parent / "skills").relative_to(_HARDWARE_STARTUP_ROOT)
        )
        tags = ["hardware-startup", *[p for p in slug.split("-") if p not in {"agent"}]]
        templates.append({
            "id": agent_id,
            "display_name": display_names.get(slug, _slug_to_title(slug)),
            "description": meta["description"],
            "author": "octopus/hardware-startup",
            "category": "specialist",
            "tags": list(dict.fromkeys(tags)),
            "icon": icons.get(slug, "🛠️"),
            "featured": False,
            "source_repo": "hardware-startup",
            "source_path": str(path.relative_to(_HARDWARE_STARTUP_ROOT)),
            "private_skills": key_skills,
            "skill_source_root": skill_source_root,
        })
    return templates


def _template_source_root(template: dict[str, Any]) -> Path:
    if template.get("source_repo") == "financial-services":
        return _FINANCIAL_SERVICES_ROOT
    if template.get("source_repo") == "hardware-startup":
        return _HARDWARE_STARTUP_ROOT
    return _AGENCY_AGENTS_ROOT


def _copy_template_private_skills(
    template: dict[str, Any],
    skills_root: Path,
) -> dict[str, list[str]]:
    _template_private_skills(template)
    available_skills = _template_skill_catalog(template)
    source_rel = template.get("skill_source_root")
    result: dict[str, list[str]] = {"copied": [], "skipped": [], "missing": []}
    if not available_skills or not source_rel:
        return result
    source_root = _template_source_root(template) / str(source_rel)
    skills_root.mkdir(parents=True, exist_ok=True)
    for skill_name in available_skills:
        source = source_root / skill_name
        if not (source / "SKILL.md").is_file():
            result["missing"].append(skill_name)
            continue
        target = skills_root / skill_name
        if target.exists():
            result["skipped"].append(skill_name)
            continue
        shutil.copytree(source, target)
        result["copied"].append(skill_name)
    return result


def _register_public_prompt_skills(skill_registry: Any, skills_root: Path) -> int:
    if skill_registry is None or not skills_root.is_dir():
        return 0
    try:
        from runtime.execution.suckers.market_skills import register_market_skills

        return int(register_market_skills(
            skill_registry,
            all_skills_dir=skills_root,
            respect_enabled_flag=False,
            verify_tests=False,
        ))
    except Exception:  # noqa: BLE001 - copied skills are optional; agent still installs
        return 0


def _category_for(agent_id: str) -> str:
    if agent_id == "coder":
        return "coder"
    if agent_id in {"general", "octopus"}:
        return "assistant"
    if agent_id in {"ecommerce_mind"}:
        return "specialist"
    if agent_id in {"vibe_selling"}:
        return "creative"
    if agent_id in {"desktop_operator", "admin"}:
        return "automation"
    return "assistant"


def _tags_for(agent_id: str, profile: dict[str, Any] | None = None) -> list[str]:
    if profile:
        raw_tags = profile.get("tags")
        if isinstance(raw_tags, list):
            tags = [str(item) for item in raw_tags if str(item).strip()]
            if tags:
                return tags
    mapping = {
        "coder": ["code", "debug", "refactor", "test"],
        "general": ["general", "writing", "research"],
        "ecommerce_mind": ["ecommerce", "growth", "sourcing"],
        "vibe_selling": ["sales", "copywriting", "creative"],
        "desktop_operator": ["desktop", "browser", "automation"],
        "admin": ["system", "admin"],
    }
    return mapping.get(agent_id, [agent_id])


def _model_name_for_wire(value: Any) -> str | None:
    if isinstance(value, str):
        return value or None
    if isinstance(value, dict):
        name = str(value.get("name") or "").strip()
        provider = str(value.get("provider") or "").strip()
        if name and name != "auto":
            return name
        if provider and provider != "auto":
            return provider
    return None


def _template_by_id(agent_id: str) -> dict[str, Any] | None:
    template = next((t for t in BUILTIN_TEMPLATES if t["id"] == agent_id), None)
    if template:
        return template
    return next(
        (
            t
            for t in [
                *_load_agency_templates(),
                *_load_financial_services_templates(),
                *_load_hardware_startup_templates(),
            ]
            if t["id"] == agent_id
        ),
        None,
    )


def _install_template_agent(
    agent_id: str,
    agents_root: Path,
    *,
    skills_root: Path | None = None,
) -> Path | None:
    template = _template_by_id(agent_id)
    if not template:
        return None
    skills_root = skills_root or resources_root() / "skills" / "public"
    private_skills = _template_private_skills(template)
    available_skills = _template_skill_catalog(template)
    skill_bundle = _copy_template_private_skills(template, skills_root)
    agent_root = agents_root / agent_id
    core = agent_root / "agent-core"
    core.mkdir(parents=True, exist_ok=True)
    profile = {
        "id": template["id"],
        "templateId": template["id"],
        "templateVersion": "1.0.0",
        "name": template["display_name"],
        "icon": template["icon"],
        "did": f"DID-{template['id'].upper()}-LOCAL",
        "description": template["description"],
        "avatar": "avatar.svg",
        "category": template["category"],
        "tags": template["tags"],
        "model": {"provider": "auto", "name": "auto"},
        "runtime": "local",
        "creator": template["author"],
        "source": template.get("source_url"),
        "key_skills": private_skills,
        "available_skills": available_skills,
        "skill_bundle": skill_bundle,
    }
    (agent_root / "profile.jsonc").write_text(
        json.dumps(profile, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    write_pixel_agent_avatar(agent_root / "avatar.svg", template["display_name"])
    source_path = template.get("source_path")
    source_body = ""
    if source_path:
        try:
            _meta, source_body = _parse_agent_markdown(
                _template_source_root(template) / str(source_path),
            )
        except OSError:
            source_body = ""
    soul = source_body or (
        f"You are {template['display_name']}.\n\n"
        f"Primary mission: {template['description']}\n\n"
        f"Specialties: {', '.join(template['tags'])}.\n"
        "Be concise, action-oriented, and precise."
    )
    if template.get("source_url"):
        soul = f"{soul}\n\n---\nSource: {template['source_url']}\n"
    (core / "SOUL.md").write_text(soul, encoding="utf-8")
    (core / "IDENTITY.md").write_text(
        f"- Name: {template['display_name']}\n- Role: {template['category']} specialist\n",
        encoding="utf-8",
    )
    (core / "tool-registry.jsonc").write_text(
        json.dumps(
            {
                "arms": ["fs_writer", "git", "shell"],
                "extra_affinity": template["tags"],
                "private_skills": private_skills,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return agent_root


def _read_agent_tool_registry(agent_dir: Path) -> dict[str, list[str]]:
    path = agent_dir / "agent-core" / "tool-registry.jsonc"
    if not path.is_file():
        return {"arms": [], "extra_affinity": [], "private_skills": []}
    try:
        data = _parse_jsonc(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return {"arms": [], "extra_affinity": [], "private_skills": []}

    def _string_list(key: str) -> list[str]:
        raw = data.get(key) or []
        if not isinstance(raw, list):
            return []
        return list(dict.fromkeys(str(item).strip() for item in raw if str(item).strip()))

    return {
        "arms": _string_list("arms"),
        "extra_affinity": _string_list("extra_affinity"),
        "private_skills": _string_list("private_skills"),
    }


def _read_agent_private_skills(agent_dir: Path) -> list[str]:
    raw = _read_agent_tool_registry(agent_dir).get("private_skills") or []
    if not isinstance(raw, list):
        return []
    return list(dict.fromkeys(str(skill).strip() for skill in raw if str(skill).strip()))


def _avatar_url_for(
    agent_id: str,
    agent_dir: Path,
    profile: dict[str, Any] | None = None,
) -> str | None:
    if profile is not None and "avatar" in profile and (
        profile.get("avatar") is None or profile.get("avatar") is False
    ):
        return None
    for ext in ("png", "webp", "jpg", "jpeg", "svg"):
        path = agent_dir / f"avatar.{ext}"
        if path.is_file():
            return f"/api/agents/{agent_id}/avatar?v={int(path.stat().st_mtime)}"
    return None


def _agent_visual_urls_for(agent_id: str, agent_dir: Path) -> dict[str, str]:
    visuals_dir = agent_dir / "visuals"
    urls: dict[str, str] = {}
    for view in ("front", "side", "back"):
        for ext in ("png", "jpg", "jpeg", "webp", "svg"):
            path = visuals_dir / f"{view}.{ext}"
            if path.is_file():
                urls[view] = (
                    f"/api/agents/{agent_id}/visuals/{view}"
                    f"?v={int(path.stat().st_mtime)}"
                )
                break

    reference = visuals_dir / "reference.png"
    if reference.is_file():
        version = int(reference.stat().st_mtime)
        for view in ("front", "side", "back"):
            urls.setdefault(view, f"/api/agents/{agent_id}/visuals/{view}?v={version}")
    return urls


def _list_local_agents() -> list[dict[str, Any]]:
    root = default_agents_root()
    installed = _read_install_state()
    agents: list[dict[str, Any]] = []
    seen: set[str] = set()
    if root.is_dir():
        for agent_dir in root.iterdir():
            if not agent_dir.is_dir() or agent_dir.name.startswith("_"):
                continue
            profile_path = agent_dir / "profile.jsonc"
            if not profile_path.is_file():
                continue
            try:
                profile = _parse_jsonc(profile_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError, ValueError):
                continue
            agent_id = str(profile.get("id") or agent_dir.name)
            display_name = str(profile.get("name") or agent_id)
            description = str(profile.get("description") or "")
            icon = (
                str(profile.get("icon") or "")
                if "icon" in profile
                else "🤖"
            )
            author = _normalize_local_author(profile.get("creator"))
            category = str(profile.get("category") or _category_for(agent_id))
            tags = _tags_for(agent_id, profile)
            tool_registry = _read_agent_tool_registry(agent_dir)
            private_skills = tool_registry["private_skills"]
            avatar_url = _avatar_url_for(agent_id, agent_dir, profile)
            is_official = author == _OCTOPUS_AUTHOR
            # Agents discovered from ``agents/`` are already present on disk,
            # regardless of whether they came from official presets, packs, or
            # user-created folders.
            is_installed = True
            mtime = profile_path.stat().st_mtime
            agents.append({
                "id": agent_id,
                "name": agent_id,
                "display_name": display_name,
                "description": description,
                "author": author,
                "category": category,
                "tags": tags,
                "icon": icon,
                "avatar_url": avatar_url,
                "visual_urls": _agent_visual_urls_for(agent_id, agent_dir),
                "character_profile": profile.get("character_profile") or None,
                "model": _model_name_for_wire(profile.get("model")),
                "tool_groups": tool_registry["arms"],
                "extra_affinity": tool_registry["extra_affinity"],
                "private_skills": private_skills,
                "capabilities": profile.get("capabilities") or {},
                "version": str(profile.get("templateVersion") or "1.0.0"),
                "downloads": 0,
                "rating": 4.6 if is_official else 4.2,
                "rating_count": 0,
                "is_featured": agent_id in {"general", "coder", "ecommerce_mind", "vibe_selling"},
                "is_official": is_official,
                "is_installed": is_installed,
                "created_at": str(mtime),
                "key_skills": private_skills or profile.get("key_skills") or [],
                "available_skills": profile.get("available_skills")
                or private_skills
                or profile.get("key_skills")
                or [],
            })
            seen.add(agent_id)

    for template in [
        *BUILTIN_TEMPLATES,
        *_load_agency_templates(),
        *_load_financial_services_templates(),
        *_load_hardware_startup_templates(),
    ]:
        if template["id"] in seen:
            continue
        agent_id = template["id"]
        agents.append({
            "id": agent_id,
            "name": agent_id,
            "display_name": template["display_name"],
            "description": template["description"],
            "author": template["author"],
            "category": template["category"],
            "tags": template["tags"],
            "icon": template["icon"],
            "avatar_url": None,
            "model": None,
            "tool_groups": ["fs_writer", "git", "shell"],
            "extra_affinity": list(template["tags"]),
            "private_skills": _template_private_skills(template),
            "capabilities": {},
            "version": "1.0.0",
            "downloads": 0,
            "rating": 4.5,
            "rating_count": 0,
            "is_featured": bool(template.get("featured")),
            "is_official": template["author"] == "octopus",
            "is_installed": agent_id in installed,
            "created_at": "0",
            "source_url": template.get("source_url"),
            "key_skills": _template_private_skills(template),
            "available_skills": _template_skill_catalog(template),
        })
    return agents


def create_agent_world_router(
    *,
    registry: Any = None,
    runtime: Any = None,
    skill_registry: Any = None,
) -> Any:
    if not FASTAPI_AVAILABLE:
        raise RuntimeError("fastapi not installed")

    router = APIRouter(tags=["agent-market"])

    @router.get("/api/agent-market/store")
    def api_agent_market_store(
        category: str | None = None,
        search: str | None = None,
        sort: str = "downloads",
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=20, ge=1, le=500),
    ) -> dict[str, Any]:
        agents = _list_local_agents()
        if category:
            agents = [a for a in agents if a["category"] == category]
        if search:
            q = search.lower()
            agents = [a for a in agents if q in a["display_name"].lower() or q in a["description"].lower() or any(q in t for t in a["tags"])]
        if sort == "rating":
            agents.sort(key=lambda a: a["rating"], reverse=True)
        elif sort == "created_at":
            agents.sort(key=lambda a: a["created_at"], reverse=True)
        elif sort == "name":
            agents.sort(key=lambda a: a["display_name"].lower())
        else:
            agents.sort(key=lambda a: (a["downloads"], a["is_featured"], a["is_official"]), reverse=True)
        total = len(agents)
        paged = agents[offset:offset + limit]
        page = offset // limit + 1
        return {"agents": paged, "total": total, "page": page, "page_size": limit}

    @router.get("/api/agent-market/store/featured")
    def api_agent_market_featured(limit: int = Query(default=20, ge=1, le=500)) -> dict[str, Any]:
        agents = [a for a in _list_local_agents() if a["is_featured"]]
        agents.sort(key=lambda a: (a["is_official"], a["display_name"].lower()), reverse=True)
        return {"agents": agents[:limit], "total": len(agents), "page": 1, "page_size": limit}

    @router.get("/api/agent-market/store/{agent_id}")
    def api_agent_market_detail(agent_id: str) -> dict[str, Any]:
        for agent in _list_local_agents():
            if agent["id"] == agent_id:
                return agent
        raise HTTPException(404, f"agent not found: {agent_id}")

    @router.post("/api/agent-market/store/{agent_id}/install")
    def api_agent_market_install(agent_id: str) -> dict[str, Any]:
        agents = _list_local_agents()
        if not any(a["id"] == agent_id for a in agents):
            raise HTTPException(404, f"agent not found: {agent_id}")
        template = _template_by_id(agent_id)
        if not template:
            raise HTTPException(400, f"agent is already local: {agent_id}")
        agents_root = default_agents_root()
        skills_root = resources_root() / "skills" / "public"
        agent_root = _install_template_agent(agent_id, agents_root, skills_root=skills_root)
        if agent_root is None:
            raise HTTPException(404, f"agent template not found: {agent_id}")
        registered_skills = _register_public_prompt_skills(skill_registry, skills_root)
        installed = _read_install_state()
        installed.add(agent_id)
        _write_install_state(installed)
        if registry is not None and runtime is not None:
            from runtime.execution.agents.loader import load_agent

            loaded = load_agent(agent_root, runtime, agents_root / "_shared")
            if hasattr(registry, "replace") and registry.has(agent_id):
                registry.replace(loaded)
            elif not registry.has(agent_id):
                registry.register(loaded)
        tool_registry_path = agent_root / "agent-core" / "tool-registry.jsonc"
        return {
            "installed": True,
            "agent_id": agent_id,
            "key_skills": _read_agent_private_skills(agent_root),
            "available_skills": _template_skill_catalog(template),
            "registered_skills": registered_skills,
            "tool_registry": str(tool_registry_path),
        }

    @router.delete("/api/agent-market/store/{agent_id}/install")
    def api_agent_market_uninstall(agent_id: str) -> dict[str, Any]:
        if not _template_by_id(agent_id):
            raise HTTPException(400, f"agent is local and cannot be uninstalled from market: {agent_id}")
        installed = _read_install_state()
        installed.discard(agent_id)
        _write_install_state(installed)
        agent_root = default_agents_root() / agent_id
        if agent_root.is_dir():
            import shutil
            shutil.rmtree(agent_root, ignore_errors=True)
        if registry is not None and hasattr(registry, "remove"):
            registry.remove(agent_id)
        return {"installed": False, "agent_id": agent_id}

    @router.get("/api/agent-market/profile/{agent_name}")
    def api_agent_market_profile(agent_name: str) -> dict[str, Any]:
        for agent in _list_local_agents():
            if agent["name"] == agent_name or agent["id"] == agent_name:
                return {
                    "agent_name": agent["name"],
                    "display_name": agent["display_name"],
                    "avatar_url": agent["avatar_url"],
                    "bio": agent["description"],
                    "category": agent["category"],
                    "tags": agent["tags"],
                    "stats": {
                        "total_conversations": 0,
                        "total_messages": 0,
                        "satisfaction_rate": agent["rating"] / 5 if agent["rating"] else 0,
                        "avg_response_time_ms": 0,
                        "tasks_completed": 0,
                    },
                    "capabilities": agent["tags"],
                    "last_active": None,
                }
        raise HTTPException(404, f"agent not found: {agent_name}")

    @router.get("/api/agent-market/memory/{agent_name}")
    def api_agent_market_memory(agent_name: str) -> dict[str, Any]:
        return {"memories": []}

    @router.get("/api/agent-market/store/{agent_id}/ratings")
    def api_agent_market_ratings(agent_id: str) -> dict[str, Any]:
        return {"ratings": []}

    @router.get("/api/agent-market/packs/preview")
    def api_agent_pack_preview(path: str) -> dict[str, Any]:
        from runtime.execution.misc.agent_packs import scan_agent_pack

        try:
            return scan_agent_pack(path).to_dict()
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        except NotADirectoryError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.post("/api/agent-market/packs/import-agent")
    def api_agent_pack_import_agent(body: dict[str, Any]) -> dict[str, Any]:
        from runtime.execution.misc.agent_packs import import_agent_from_pack

        path = str(body.get("path") or "").strip()
        agent_name = str(body.get("agent_name") or body.get("agentId") or body.get("agent_id") or "").strip()
        if not path:
            raise HTTPException(400, "path is required")
        if not agent_name:
            raise HTTPException(400, "agent_name is required")
        try:
            result = import_agent_from_pack(
                path,
                agent_name,
                agents_root=default_agents_root(),
                skills_root=resources_root() / "skills" / "public",
            )
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        except NotADirectoryError as exc:
            raise HTTPException(400, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc
        return result.to_dict()

    @router.get("/api/agent-market/social/{agent_name}/relationships")
    def api_agent_market_social(agent_name: str) -> dict[str, Any]:
        return {"relationships": []}

    return router


__all__ = ["create_agent_world_router"]
