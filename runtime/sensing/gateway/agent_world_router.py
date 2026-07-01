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
    from fastapi import APIRouter, Depends, HTTPException, Query, Request

    FASTAPI_AVAILABLE = True
except ImportError:  # pragma: no cover
    FASTAPI_AVAILABLE = False
    APIRouter = None  # type: ignore[assignment, misc]
    Depends = None  # type: ignore[assignment, misc]
    HTTPException = None  # type: ignore[assignment, misc]
    Query = None  # type: ignore[assignment, misc]
    Request = None  # type: ignore[assignment, misc]

from runtime.execution.agents.loader import default_agents_root
from runtime.execution.misc.agent_avatar import pixel_agent_avatar_svg
from runtime.platform.io import atomic_write_json, atomic_write_text, read_json_with_backup
from runtime.platform.process.paths import resources_root

_INSTALL_STATE = Path(os.path.expanduser("~/.octopus/agents-installed.json"))
_OCTOPUS_AUTHOR = "octopus"
_OCTOPUS_AUTHOR_ALIASES = {"preset", "system", "octopus", "Octopus"}
_SAFE_AGENT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
_SAFE_SKILL_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
_MARKET_INSTALL_SOURCE = "agent-market-template"
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
    data = read_json_with_backup(_INSTALL_STATE, default={})
    if not isinstance(data, dict):
        return set()
    raw = data.get("installed", [])
    if not isinstance(raw, list):
        return set()
    installed: set[str] = set()
    for item in raw:
        agent_id = str(item).strip()
        if _is_safe_agent_id(agent_id):
            installed.add(agent_id)
    return installed


def _write_install_state(installed: set[str]) -> None:
    safe_installed = sorted(
        agent_id for agent_id in installed if _is_safe_agent_id(agent_id)
    )
    atomic_write_json(
        _INSTALL_STATE,
        {"installed": safe_installed},
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )


def _is_safe_agent_id(agent_id: str) -> bool:
    return bool(_SAFE_AGENT_ID_RE.fullmatch(str(agent_id or "")))


def _require_safe_agent_id(agent_id: str) -> str:
    value = str(agent_id or "").strip()
    if not _is_safe_agent_id(value):
        raise ValueError(
            "invalid agent_id: only alphanumeric characters, hyphens, and underscores are allowed"
        )
    return value


def _require_safe_skill_name(skill_name: str) -> str:
    value = str(skill_name or "").strip()
    if not _SAFE_SKILL_NAME_RE.fullmatch(value):
        raise ValueError(
            "invalid skill name in market template: only alphanumeric characters, "
            "hyphens, and underscores are allowed"
        )
    return value


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
        skill_name = _require_safe_skill_name(skill_name)
        source = source_root / skill_name
        if (
            source.is_symlink()
            or not source.is_dir()
            or not (source / "SKILL.md").is_file()
            or any(child.is_symlink() for child in source.rglob("*"))
        ):
            result["missing"].append(skill_name)
            continue
        target = skills_root / skill_name
        if target.exists() or target.is_symlink():
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
    if not _is_safe_agent_id(agent_id):
        return None
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


def _read_agent_profile(agent_root: Path) -> dict[str, Any] | None:
    profile_path = agent_root / "profile.jsonc"
    if profile_path.is_symlink() or not profile_path.is_file():
        return None
    try:
        profile = _parse_jsonc(profile_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return None
    return profile if isinstance(profile, dict) else None


def _is_market_managed_agent(
    agent_root: Path,
    agent_id: str,
    *,
    template: dict[str, Any] | None = None,
    installed: set[str] | None = None,
) -> bool:
    if agent_root.is_symlink() or not agent_root.is_dir():
        return False
    profile = _read_agent_profile(agent_root)
    if not profile:
        return False
    if str(profile.get("id") or agent_root.name).strip() != agent_id:
        return False
    if profile.get("source_kind") == _MARKET_INSTALL_SOURCE:
        return True
    if profile.get("managed_by") == "agent-market":
        return True

    # Backward compatibility for agents installed before the explicit
    # source marker existed: require both persisted install state and
    # catalog-identical metadata before treating the directory as managed.
    if not template or not installed or agent_id not in installed:
        return False
    return (
        str(profile.get("templateId") or "").strip() == agent_id
        and str(profile.get("creator") or "").strip()
        == str(template.get("author") or "").strip()
    )


def _cleanup_new_agent_root(agent_root: Path, *, created_new: bool) -> None:
    if created_new and agent_root.is_dir() and not agent_root.is_symlink():
        shutil.rmtree(agent_root, ignore_errors=True)


def _install_template_agent(
    agent_id: str,
    agents_root: Path,
    *,
    skills_root: Path | None = None,
) -> Path | None:
    agent_id = _require_safe_agent_id(agent_id)
    template = _template_by_id(agent_id)
    if not template:
        return None
    skills_root = skills_root or resources_root() / "skills" / "public"
    private_skills = _template_private_skills(template)
    available_skills = _template_skill_catalog(template)
    if agents_root.exists() and (agents_root.is_symlink() or not agents_root.is_dir()):
        raise ValueError("agents root must be a real directory")
    agents_root.mkdir(parents=True, exist_ok=True)
    agent_root = agents_root / agent_id
    created_new = not agent_root.exists() and not agent_root.is_symlink()
    if agent_root.exists() or agent_root.is_symlink():
        if not _is_market_managed_agent(
            agent_root,
            agent_id,
            template=template,
            installed=_read_install_state(),
        ):
            raise FileExistsError(
                f"agent directory already exists and is not market-managed: {agent_id}"
            )
        if agent_root.is_symlink() or not agent_root.is_dir():
            raise ValueError("agent directory must be a real directory")
    core = agent_root / "agent-core"
    try:
        core.mkdir(parents=True, exist_ok=True)
        if core.is_symlink() or not core.is_dir():
            raise ValueError("agent-core must be a real directory")
    except Exception:
        _cleanup_new_agent_root(agent_root, created_new=created_new)
        raise
    try:
        skill_bundle = _copy_template_private_skills(template, skills_root)
        profile = {
            "id": template["id"],
            "templateId": template["id"],
            "templateVersion": "1.0.0",
            "source_kind": _MARKET_INSTALL_SOURCE,
            "managed_by": "agent-market",
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
        atomic_write_json(agent_root / "profile.jsonc", profile, ensure_ascii=False, indent=2)
        atomic_write_text(
            agent_root / "avatar.svg",
            pixel_agent_avatar_svg(template["display_name"]),
            newline=None,
        )
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
        atomic_write_text(core / "SOUL.md", soul, newline=None)
        atomic_write_text(
            core / "IDENTITY.md",
            f"- Name: {template['display_name']}\n- Role: {template['category']} specialist\n",
            newline=None,
        )
        atomic_write_json(
            core / "tool-registry.jsonc",
            {
                "arms": ["fs_writer", "git", "shell"],
                "extra_affinity": template["tags"],
                "private_skills": private_skills,
            },
            ensure_ascii=False,
            indent=2,
        )
    except Exception:
        _cleanup_new_agent_root(agent_root, created_new=created_new)
        raise
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

    # 本地角色库只保留物理存在于 agents/ 下的默认角色(含 echo 9 角色 + 系统内建
    # agent),不再把静态模板目录(BUILTIN_TEMPLATES/agency/financial/hardware,
    # 约 200 余条)当"可装入"项混进来 —— 这批模板已整体发布到公网 registry(见
    # registry_consumer_router 的 /api/registry/roles,role+twin-role 304 条,
    # 是模板目录的超集),改走「云端角色」浏览安装,母本本地只默认这 9(+系统)个。
    return agents


def _template_to_agent_dict(template: dict[str, Any], *, installed: set[str]) -> dict[str, Any]:
    """模板 → 与 ``_list_local_agents`` 同形状的 dict(供按 id 直查 / 安装用,
    不进入列表)。"""
    agent_id = template["id"]
    return {
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
    }


def create_agent_world_router(
    *,
    registry: Any = None,
    runtime: Any = None,
    skill_registry: Any = None,
    identity_store: Any = None,
    require_auth: bool = False,
    jwt_secret: str | None = None,
    jwt_issuer: str | None = None,
    jwt_audience: str | None = None,
) -> Any:
    if not FASTAPI_AVAILABLE:
        raise RuntimeError("fastapi not installed")

    def _auth_dep(request: Request) -> None:
        # Agent market reads templates and can also install/uninstall local
        # agents. Keep dev mode unchanged; in auth-on deployments gate the
        # whole market surface at the router level.
        from runtime.adapters.web_auth import _resolve_actor

        _resolve_actor(
            request,
            identity_store,
            require_auth,
            jwt_secret=jwt_secret,
            jwt_issuer=jwt_issuer,
            jwt_audience=jwt_audience,
        )

    router = APIRouter(tags=["agent-market"], dependencies=[Depends(_auth_dep)])

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
        try:
            agent_id = _require_safe_agent_id(agent_id)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        for agent in _list_local_agents():
            if agent["id"] == agent_id:
                return agent
        # 不在本地列表(模板目录已不再列出,见 _list_local_agents)时按 id 直查——
        # 保留旧模板 id 的可解析性(供 install 等既有调用方使用),只是不再列出。
        template = _template_by_id(agent_id)
        if template:
            return _template_to_agent_dict(template, installed=_read_install_state())
        raise HTTPException(404, f"agent not found: {agent_id}")

    @router.post("/api/agent-market/store/{agent_id}/install")
    def api_agent_market_install(agent_id: str) -> dict[str, Any]:
        try:
            agent_id = _require_safe_agent_id(agent_id)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        template = _template_by_id(agent_id)
        if not template:
            agents = _list_local_agents()
            if any(a["id"] == agent_id for a in agents):
                raise HTTPException(400, f"agent is already local: {agent_id}")
            raise HTTPException(404, f"agent not found: {agent_id}")
        agents_root = default_agents_root()
        skills_root = resources_root() / "skills" / "public"
        preexisting_agent_root = agents_root / agent_id
        had_agent_root = preexisting_agent_root.exists() or preexisting_agent_root.is_symlink()
        try:
            agent_root = _install_template_agent(agent_id, agents_root, skills_root=skills_root)
        except FileExistsError as exc:
            raise HTTPException(409, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except OSError as exc:
            raise HTTPException(
                500, f"failed to install market agent: {type(exc).__name__}: {exc}"
            ) from exc
        if agent_root is None:
            raise HTTPException(404, f"agent template not found: {agent_id}")
        registered_skills = _register_public_prompt_skills(skill_registry, skills_root)
        installed = _read_install_state()
        installed.add(agent_id)
        try:
            _write_install_state(installed)
        except OSError as exc:
            if (
                not had_agent_root
                and _is_market_managed_agent(agent_root, agent_id, template=template, installed=installed)
            ):
                shutil.rmtree(agent_root, ignore_errors=True)
            raise HTTPException(
                500, f"failed to persist market install state: {type(exc).__name__}: {exc}"
            ) from exc
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
        try:
            agent_id = _require_safe_agent_id(agent_id)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        template = _template_by_id(agent_id)
        if not template:
            raise HTTPException(400, f"agent is local and cannot be uninstalled from market: {agent_id}")
        installed = _read_install_state()
        agent_root = default_agents_root() / agent_id
        if agent_root.exists() or agent_root.is_symlink():
            if not _is_market_managed_agent(
                agent_root,
                agent_id,
                template=template,
                installed=installed,
            ):
                raise HTTPException(
                    409,
                    f"agent directory is not market-managed and will not be removed: {agent_id}",
                )
            try:
                shutil.rmtree(agent_root)
            except OSError as exc:
                raise HTTPException(
                    500, f"failed to remove market agent: {type(exc).__name__}: {exc}"
                ) from exc
        installed.discard(agent_id)
        try:
            _write_install_state(installed)
        except OSError as exc:
            raise HTTPException(
                500, f"failed to persist market install state: {type(exc).__name__}: {exc}"
            ) from exc
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
