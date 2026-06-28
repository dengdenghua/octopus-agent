from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from runtime.platform.process.paths import project_root as default_project_root

SCHEMA = "octopus.browser_desktop_runtime_contract.v1"


@dataclass(frozen=True)
class BrowserDesktopRuntimeContractCheck:
    id: str
    title: str
    path: str
    required_terms: tuple[str, ...]
    weight: int = 1


CHECKS: tuple[BrowserDesktopRuntimeContractCheck, ...] = (
    BrowserDesktopRuntimeContractCheck(
        id="browser_session_control_plane",
        title="Browser session control plane",
        path="runtime/platform/ui/browser_router.py",
        required_terms=(
            "/api/browser/session/ensure",
            "/api/browser/session/health",
            "/api/browser/session/reset",
            "/api/browser/session/replay-case/queue",
            "ReviewQueue",
        ),
        weight=3,
    ),
    BrowserDesktopRuntimeContractCheck(
        id="desktop_preview_execute_contract",
        title="Desktop preview, lease, execute contract",
        path="runtime/sensing/gateway/computer_router.py",
        required_terms=(
            "/actions/preview",
            "/actions/execute",
            "lease_owner_id",
            "preview_queued",
            "/activity/replay-case",
            "/activity/replay-case/queue",
        ),
        weight=3,
    ),
    BrowserDesktopRuntimeContractCheck(
        id="runtime_probe_contract",
        title="Live runtime probe contract",
        path="runtime/safety/evolution/browser_desktop_runtime_probe.py",
        required_terms=(
            "run_browser_desktop_runtime_probe",
            "/api/browser/session/ensure",
            "/api/browser/session/reset",
            "/api/computer/actions/preview",
            "/api/computer/actions/execute",
            "/api/computer/activity/replay-case",
            "/api/computer/lease/release",
            "auto_local_auth",
            "write_browser_desktop_runtime_evidence",
        ),
        weight=3,
    ),
    BrowserDesktopRuntimeContractCheck(
        id="runtime_evidence_cache_contract",
        title="Fresh runtime evidence cache contract",
        path="runtime/safety/evolution/browser_desktop_runtime_evidence.py",
        required_terms=(
            "browser_desktop_runtime_evidence_path",
            "load_browser_desktop_runtime_evidence",
            "write_browser_desktop_runtime_evidence",
            "DEFAULT_MAX_AGE_S",
            "secrets_redacted",
        ),
        weight=2,
    ),
    BrowserDesktopRuntimeContractCheck(
        id="runtime_readiness_gate",
        title="Runtime readiness gate",
        path="runtime/safety/evolution/browser_desktop_runtime_readiness.py",
        required_terms=(
            "compute_browser_desktop_runtime_readiness",
            "runtime_probe_operations",
            "computer_preview_observed",
            "computer_execute_observed",
            "computer_replay_case_observed",
            "replay_queue_clean",
            "repair_recipe_gate_ready",
        ),
        weight=3,
    ),
    BrowserDesktopRuntimeContractCheck(
        id="repair_recipe_gate_contract",
        title="Deterministic repair recipe gate",
        path="runtime/safety/evolution/browser_desktop_repair_recipes.py",
        required_terms=(
            "compute_browser_desktop_repair_recipe_quality_gate",
            "requires_replay_rerun",
            "rerun_browser_desktop_repair_recipe_batch",
            "reject_stale_browser_desktop_replay_artifacts",
        ),
        weight=2,
    ),
    BrowserDesktopRuntimeContractCheck(
        id="runtime_probe_cli",
        title="Operator runtime probe CLI",
        path="scripts/browser_desktop_runtime_probe.py",
        required_terms=(
            "--auto-local-auth",
            "--cleanup-session",
            "run_browser_desktop_runtime_probe",
            "runtime_readiness",
        ),
        weight=1,
    ),
    BrowserDesktopRuntimeContractCheck(
        id="browser_desktop_runtime_tests",
        title="Browser/desktop runtime regression tests",
        path="tests/test_browser_desktop_runtime_probe.py",
        required_terms=(
            "test_scorecard_can_use_runtime_probe_to_close_browser_desktop_gap",
            "test_scorecard_uses_fresh_runtime_evidence_snapshot_by_default",
            "computer_execute",
            "computer_replay_case",
            "load_browser_desktop_runtime_evidence",
        ),
        weight=2,
    ),
    BrowserDesktopRuntimeContractCheck(
        id="desktop_router_tests",
        title="Desktop router preview and replay tests",
        path="tests/test_computer_router.py",
        required_terms=(
            "/api/computer/actions/preview",
            "/api/computer/actions/execute",
            "/api/computer/activity/replay-case/queue",
            "lease_owner_id",
        ),
        weight=2,
    ),
)


def compute_browser_desktop_runtime_contract(
    *,
    root: str | Path | None = None,
) -> dict[str, Any]:
    base = Path(root) if root is not None else default_project_root(Path(__file__))
    checks = [_check_status(base, check) for check in CHECKS]
    total_weight = sum(int(item["weight"]) for item in checks)
    passed_weight = sum(int(item["weight"]) for item in checks if item["passed"])
    score = round(passed_weight / total_weight, 3) if total_weight else 0.0
    missing = [item for item in checks if not item["passed"]]
    return {
        "schema": SCHEMA,
        "score": score,
        "ready": score >= 1.0 and not missing,
        "verdict": "pass" if score >= 1.0 and not missing else "review",
        "passed": len(checks) - len(missing),
        "total": len(checks),
        "passed_weight": passed_weight,
        "total_weight": total_weight,
        "checks": checks,
        "missing_count": len(missing),
        "next_actions": _next_actions(missing),
        "calibration": {
            "schema": "octopus.browser_desktop_runtime_contract_calibration.v1",
            "cold_start_semantics": (
                "A complete contract proves the local control plane is present "
                "and can self-bootstrap a live probe, but it does not replace "
                "fresh runtime evidence for strict browser/desktop advantage."
            ),
            "compares_to": {
                "codex": (
                    "native Browser Use, Chrome extension, Computer Use, and "
                    "Record & Replay surfaces with mature product integration"
                ),
            },
            "octopus_edge": (
                "API-visible session health, desktop preview tokens, lease "
                "ownership, replay queues, deterministic repair gates, and a "
                "persisted runtime evidence snapshot"
            ),
        },
    }


def _check_status(
    base: Path,
    check: BrowserDesktopRuntimeContractCheck,
) -> dict[str, Any]:
    path = base / check.path
    text = _read_text(path).lower() if path.exists() else ""
    missing_terms = [
        term
        for term in check.required_terms
        if term.lower() not in text
    ]
    return {
        "id": check.id,
        "title": check.title,
        "path": check.path,
        "weight": check.weight,
        "exists": path.exists(),
        "passed": path.exists() and not missing_terms,
        "required_terms": list(check.required_terms),
        "missing_terms": missing_terms,
    }


def _next_actions(missing: list[dict[str, Any]]) -> list[str]:
    actions: list[str] = []
    for item in missing:
        if not item["exists"]:
            actions.append(f"Add {item['path']} for {item['title']}.")
        elif item["missing_terms"]:
            actions.append(
                f"Update {item['path']} with {', '.join(item['missing_terms'])}.",
            )
    return actions


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


__all__ = [
    "BrowserDesktopRuntimeContractCheck",
    "CHECKS",
    "SCHEMA",
    "compute_browser_desktop_runtime_contract",
]
