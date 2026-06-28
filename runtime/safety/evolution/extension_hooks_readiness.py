from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from runtime.platform.process.paths import project_root as default_project_root

_SCHEMA = "octopus.extension_hooks_readiness.v1"
_PROBE_SCHEMA = "octopus.extension_hooks_probe.v1"


@dataclass(frozen=True)
class ExtensionHookCapability:
    id: str
    title: str
    path: str
    required_terms: tuple[str, ...]
    weight: int = 1


CAPABILITIES: tuple[ExtensionHookCapability, ...] = (
    ExtensionHookCapability(
        id="signed_provenance_manifest",
        title="Signed plugin provenance manifest",
        path="runtime/platform/plugins/codex_discovery.py",
        required_terms=(
            "signature",
            "provenance",
            "trust",
            "signed",
        ),
        weight=3,
    ),
    ExtensionHookCapability(
        id="permission_lifecycle_audit",
        title="Permission-aware lifecycle audit",
        path="runtime/platform/plugins/lifecycle_audit.py",
        required_terms=(
            "octopus.plugin_lifecycle_audit.v1",
            "permission_review",
            "lifecycle_audit",
            "provenance",
        ),
        weight=3,
    ),
    ExtensionHookCapability(
        id="operator_compatibility_summary",
        title="Operator-visible compatibility summary",
        path="runtime/sensing/gateway/plugins_router.py",
        required_terms=(
            "octopus.codex_plugin_compatibility.v1",
            "lifecycle_audit",
            "provenance",
            "permission_resolutions",
        ),
        weight=2,
    ),
    ExtensionHookCapability(
        id="threat_model_coverage",
        title="Threat-model coverage for plugin lifecycle hooks",
        path="runtime/safety/evolution/tool_threat_model.py",
        required_terms=(
            "plugin_lifecycle",
            "supply_chain_drift",
            "provenance",
        ),
        weight=2,
    ),
    ExtensionHookCapability(
        id="plugin_regression_tests",
        title="Plugin provenance regression tests",
        path="tests/test_codex_plugin_smoke.py",
        required_terms=(
            "provenance",
            "signed",
            "lifecycle_audit",
        ),
        weight=2,
    ),
)


def compute_extension_hooks_readiness(
    *,
    root: str | Path | None = None,
    include_probe: bool = True,
) -> dict[str, Any]:
    base = Path(root) if root is not None else default_project_root(Path(__file__))
    capabilities = [_capability_status(base, capability) for capability in CAPABILITIES]
    probe = run_extension_hooks_probe() if include_probe else _skipped_probe()
    capabilities.extend(_probe_capabilities(probe))
    total_weight = sum(int(item["weight"]) for item in capabilities)
    passed_weight = sum(int(item["weight"]) for item in capabilities if item["passed"])
    score = round(passed_weight / total_weight, 3) if total_weight else 0.0
    missing = [item for item in capabilities if not item["passed"]]
    return {
        "schema": _SCHEMA,
        "score": score,
        "ready": score >= 1.0 and not missing,
        "verdict": "pass" if score >= 1.0 and not missing else "review",
        "passed": len(capabilities) - len(missing),
        "total": len(capabilities),
        "passed_weight": passed_weight,
        "total_weight": total_weight,
        "missing_count": len(missing),
        "capabilities": capabilities,
        "probe": probe,
        "next_actions": _next_actions(missing),
        "calibration": {
            "schema": "octopus.extension_hooks_calibration.v1",
            "compares_to": {
                "claude_code": (
                    "mature slash-command, MCP, and hook ecosystem with broad "
                    "operator familiarity"
                ),
            },
            "octopus_edge": (
                "local plugin surfaces are normalized into signed provenance, "
                "explicit permission resolution, lifecycle audit rows, threat-model "
                "coverage, and operator-visible compatibility summaries"
            ),
        },
    }


def run_extension_hooks_probe() -> dict[str, Any]:
    try:
        from runtime.platform.plugins.lifecycle_audit import audit_plugin_lifecycle
        from runtime.sensing.gateway.plugins_router import _compatibility_summary
    except Exception as exc:  # noqa: BLE001
        return {
            "schema": _PROBE_SCHEMA,
            "ok": False,
            "error": str(exc),
            "signed_provenance": False,
            "permission_review": False,
            "lifecycle_audit": False,
            "compatibility_summary": False,
        }

    plugin = {
        "id": "signed-research",
        "name": "Signed Research",
        "lifecycle_hooks": ["on_load", "on_execute", "on_unload"],
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
                    "signature": "sha256:test",
                },
            },
            "permission_resolution": {
                "schema": "octopus.codex_plugin_permission_resolution.v1",
                "status": "explicit",
                "review_required": False,
                "accepted_risk": False,
                "permissions": ["mcp:execute", "command:execute"],
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
    lifecycle_audit_ready = (
        audit.get("schema") == "octopus.plugin_lifecycle_audit.v1"
        and audit.get("verdict") == "pass"
        and audit.get("ready") is True
    )
    signed_provenance = (
        audit.get("rows", [{}])[0]
        .get("trust", {})
        .get("signed")
        is True
        and bool(
            audit.get("rows", [{}])[0]
            .get("trust", {})
            .get("provenance"),
        )
    )
    compatibility_ready = (
        compatibility.get("schema") == "octopus.codex_plugin_compatibility.v1"
        and compatibility.get("verdict") == "pass"
        and compatibility.get("passed") == compatibility.get("total")
    )
    permission_review = all(
        item.get("passed") is True
        for item in audit.get("requirements", [])
        if item.get("id") in {"permission_review_visible", "provenance_visible"}
    )
    return {
        "schema": _PROBE_SCHEMA,
        "ok": (
            signed_provenance
            and permission_review
            and lifecycle_audit_ready
            and compatibility_ready
        ),
        "signed_provenance": signed_provenance,
        "permission_review": permission_review,
        "lifecycle_audit": lifecycle_audit_ready,
        "compatibility_summary": compatibility_ready,
        "audit_score": audit.get("score"),
        "compatibility_verdict": compatibility.get("verdict"),
    }


def _probe_capabilities(probe: dict[str, Any]) -> list[dict[str, Any]]:
    if probe.get("skipped"):
        return [
            _dynamic_capability(
                "extension_hooks_probe",
                "Offline extension-hooks probe",
                False,
                "probe skipped",
                weight=3,
            ),
        ]
    return [
        _dynamic_capability(
            "signed_provenance_probe",
            "Signed provenance probe",
            bool(probe.get("signed_provenance")),
            "Synthetic signed plugin provenance is accepted by lifecycle audit",
            weight=2,
        ),
        _dynamic_capability(
            "permission_lifecycle_probe",
            "Permission lifecycle probe",
            bool(probe.get("permission_review") and probe.get("lifecycle_audit")),
            "Lifecycle audit materializes permission and hook state",
            weight=2,
        ),
        _dynamic_capability(
            "compatibility_summary_probe",
            "Compatibility summary probe",
            bool(probe.get("compatibility_summary")),
            "Plugin compatibility summary accepts clean signed extension set",
            weight=1,
        ),
    ]


def _capability_status(
    base: Path,
    capability: ExtensionHookCapability,
) -> dict[str, Any]:
    path = base / capability.path
    text = _read_text(path) if path.exists() else ""
    missing_terms = [
        term for term in capability.required_terms
        if term not in text
    ]
    return {
        "id": capability.id,
        "title": capability.title,
        "path": capability.path,
        "weight": capability.weight,
        "exists": path.exists(),
        "passed": path.exists() and not missing_terms,
        "required_terms": list(capability.required_terms),
        "missing_terms": missing_terms,
    }


def _dynamic_capability(
    capability_id: str,
    title: str,
    passed: bool,
    detail: str,
    *,
    weight: int,
) -> dict[str, Any]:
    return {
        "id": capability_id,
        "title": title,
        "path": "",
        "weight": weight,
        "exists": True,
        "passed": passed,
        "required_terms": [],
        "missing_terms": [] if passed else [detail],
    }


def _skipped_probe() -> dict[str, Any]:
    return {
        "schema": _PROBE_SCHEMA,
        "ok": False,
        "skipped": True,
        "signed_provenance": False,
        "permission_review": False,
        "lifecycle_audit": False,
        "compatibility_summary": False,
    }


def _next_actions(missing: list[dict[str, Any]]) -> list[str]:
    actions: list[str] = []
    for item in missing:
        if not item["exists"]:
            actions.append(f"Add {item['path']} for {item['title']}.")
        elif item["missing_terms"]:
            actions.append(
                f"Update {item['path']} with {', '.join(item['missing_terms'])}."
            )
    return actions


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


__all__ = [
    "CAPABILITIES",
    "ExtensionHookCapability",
    "compute_extension_hooks_readiness",
    "run_extension_hooks_probe",
]
