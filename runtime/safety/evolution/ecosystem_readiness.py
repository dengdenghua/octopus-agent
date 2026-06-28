from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from runtime.platform.process.paths import project_root as default_project_root


@dataclass(frozen=True)
class ReadinessTopic:
    id: str
    title: str
    path: str
    required_terms: tuple[str, ...]


REQUIRED_TOPICS: tuple[ReadinessTopic, ...] = (
    ReadinessTopic(
        id="code_mode",
        title="Code mode",
        path="docs/guide/operator-readiness.md",
        required_terms=("code mode", "inspect", "edit", "verify"),
    ),
    ReadinessTopic(
        id="permissions",
        title="Permissions",
        path="docs/guide/operator-readiness.md",
        required_terms=("permission", "approval", "sandbox", "override"),
    ),
    ReadinessTopic(
        id="replay_gates",
        title="Replay gates",
        path="docs/guide/operator-readiness.md",
        required_terms=("replay gate", "promotion", "evidence", "audit"),
    ),
    ReadinessTopic(
        id="plugins",
        title="Plugins",
        path="docs/guide/operator-readiness.md",
        required_terms=("plugin", "smoke", "permission review", "hook"),
    ),
    ReadinessTopic(
        id="plugin_author_migration",
        title="Plugin author migration",
        path="docs/guide/plugin-author-migration.md",
        required_terms=(
            "compatibility",
            "migration",
            "permission review",
            "release checklist",
        ),
    ),
)


def compute_ecosystem_readiness(
    *,
    root: str | Path | None = None,
    include_probe: bool = True,
) -> dict[str, Any]:
    base = Path(root) if root is not None else default_project_root(Path(__file__))
    topics = [_topic_status(base, topic) for topic in REQUIRED_TOPICS]
    probe = run_ecosystem_probe() if include_probe else _skipped_probe()
    present = sum(1 for topic in topics if topic["passed"])
    total = len(topics)
    probe_weight = 2 if include_probe else 0
    passed_weight = present + (probe_weight if probe.get("ok") is True else 0)
    total_weight = total + probe_weight
    score = round(passed_weight / total_weight, 3) if total_weight else 0.0
    missing_count = (total - present) + (
        0 if not include_probe or probe.get("ok") is True else 1
    )
    return {
        "schema": "octopus.ecosystem_readiness.v1",
        "score": score,
        "passed": present,
        "total": total,
        "passed_weight": passed_weight,
        "total_weight": total_weight,
        "missing_count": missing_count,
        "topics": topics,
        "probe": probe,
        "probe_ready": probe.get("ok") is True,
        "next_actions": _next_actions(topics, probe=probe),
    }


def run_ecosystem_probe() -> dict[str, Any]:
    try:
        from runtime.platform.plugins.lifecycle_audit import audit_plugin_lifecycle
        from runtime.sensing.gateway.plugins_router import _compatibility_summary
    except Exception as exc:  # noqa: BLE001
        return {
            "schema": "octopus.ecosystem_plugin_compatibility_probe.v1",
            "ok": False,
            "error": str(exc),
        }
    plugin = {
        "id": "ecosystem-signed-toolkit",
        "name": "Ecosystem Signed Toolkit",
        "lifecycle_hooks": ["on_load", "on_execute", "on_skill_register", "on_unload"],
        "smoke": {
            "schema": "octopus.codex_plugin_smoke.v1",
            "ok": True,
            "surfaces": {
                "capabilities": True,
                "skills": True,
                "apps": False,
                "mcp": True,
                "commands": True,
            },
            "trust": {
                "level": "signed_verified",
                "signed": True,
                "provenance": {
                    "schema": "octopus.codex_plugin_provenance.v1",
                    "source": "local_manifest",
                    "source_type": "git",
                    "revision": "ecosystem-probe",
                    "signature": {
                        "present": True,
                        "kind": "sha256",
                        "value": "sha256:ecosystem-probe",
                    },
                },
            },
            "permission_resolution": {
                "schema": "octopus.codex_plugin_permission_resolution.v1",
                "status": "explicit",
                "review_required": False,
                "accepted_risk": False,
                "permissions": ["mcp:execute", "command:execute", "skill:register"],
            },
        },
    }
    audit = audit_plugin_lifecycle([plugin])
    compatibility = _compatibility_summary(
        total=1,
        failed_count=0,
        review_required_count=0,
        warning_count=0,
        surface_totals={
            "capabilities": 1,
            "skills": 1,
            "apps": 0,
            "mcp": 1,
            "commands": 1,
        },
        lifecycle_audit=audit,
    )
    requirements = {
        "signed_plugin_provenance": (
            audit.get("rows", [{}])[0].get("trust", {}).get("signed") is True
        ),
        "explicit_permission_resolution": (
            audit.get("rows", [{}])[0]
            .get("permission_resolution", {})
            .get("status")
            == "explicit"
        ),
        "lifecycle_audit_pass": (
            audit.get("schema") == "octopus.plugin_lifecycle_audit.v1"
            and audit.get("ready") is True
            and audit.get("verdict") == "pass"
        ),
        "compatibility_summary_pass": (
            compatibility.get("schema") == "octopus.codex_plugin_compatibility.v1"
            and compatibility.get("verdict") == "pass"
            and compatibility.get("passed") == compatibility.get("total")
        ),
    }
    return {
        "schema": "octopus.ecosystem_plugin_compatibility_probe.v1",
        "ok": all(requirements.values()),
        "requirements": requirements,
        "audit_score": audit.get("score"),
        "audit_verdict": audit.get("verdict"),
        "compatibility_verdict": compatibility.get("verdict"),
        "surface_totals": compatibility.get("surface_totals") or {},
    }


def _topic_status(base: Path, topic: ReadinessTopic) -> dict[str, Any]:
    path = base / topic.path
    text = path.read_text(encoding="utf-8").lower() if path.exists() else ""
    missing_terms = [
        term
        for term in topic.required_terms
        if term.lower() not in text
    ]
    return {
        "id": topic.id,
        "title": topic.title,
        "path": topic.path,
        "exists": path.exists(),
        "passed": path.exists() and not missing_terms,
        "required_terms": list(topic.required_terms),
        "missing_terms": missing_terms,
    }


def _next_actions(
    topics: list[dict[str, Any]],
    *,
    probe: dict[str, Any],
) -> list[str]:
    actions: list[str] = []
    for topic in topics:
        if topic["passed"]:
            continue
        if not topic["exists"]:
            actions.append(f"Create {topic['path']} for {topic['title']}.")
        elif topic["missing_terms"]:
            actions.append(
                f"Update {topic['path']} with {', '.join(topic['missing_terms'])}."
            )
    if not probe.get("skipped") and probe.get("ok") is not True:
        actions.append("Fix signed plugin compatibility and lifecycle probe.")
    return actions


def _skipped_probe() -> dict[str, Any]:
    return {
        "schema": "octopus.ecosystem_plugin_compatibility_probe.v1",
        "ok": False,
        "skipped": True,
    }


__all__ = [
    "REQUIRED_TOPICS",
    "ReadinessTopic",
    "compute_ecosystem_readiness",
    "run_ecosystem_probe",
]
