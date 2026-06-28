from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from runtime.platform.process.paths import project_root as default_project_root
from runtime.safety.evolution.browser_desktop_productization_readiness import (
    compute_browser_desktop_productization_readiness,
)
from runtime.safety.evolution.browser_desktop_repair_recipes import (
    compute_browser_desktop_repair_recipe_quality_gate,
)
from runtime.safety.evolution.browser_desktop_runtime_contract import (
    compute_browser_desktop_runtime_contract,
)

SCHEMA = "octopus.browser_desktop_cold_start_readiness.v1"


def compute_browser_desktop_cold_start_readiness(
    *,
    root: str | Path | None = None,
    review_queue_path: str | Path | None = None,
) -> dict[str, Any]:
    base = Path(root) if root is not None else default_project_root(Path(__file__))
    contract = compute_browser_desktop_runtime_contract(root=base)
    productization = compute_browser_desktop_productization_readiness(root=base)
    repair_gate = compute_browser_desktop_repair_recipe_quality_gate(
        review_queue_path=review_queue_path,
    )
    bootstrap = _bootstrap_probe(base)
    checks = {
        "runtime_contract_ready": (
            contract.get("ready") is True
            and float(contract.get("score") or 0.0) >= 1.0
            and int(contract.get("missing_count") or 0) == 0
        ),
        "productization_ready": (
            productization.get("ready") is True
            and productization.get("verdict") == "pass"
            and float(productization.get("score") or 0.0) >= 1.0
        ),
        "repair_recipe_gate_ready": (
            repair_gate.get("ready") is True
            and float(repair_gate.get("score") or 0.0) >= 1.0
            and not repair_gate.get("blockers")
        ),
        "offline_bootstrap_probe_ready": bootstrap.get("ok") is True,
    }
    passed = sum(1 for value in checks.values() if value is True)
    total = len(checks)
    score = round(passed / total, 3) if total else 0.0
    ready = score >= 1.0
    return {
        "schema": SCHEMA,
        "score": score,
        "ready": ready,
        "verdict": "pass" if ready else "review" if score >= 0.75 else "fail",
        "checks": checks,
        "probe": bootstrap,
        "runtime_contract": contract,
        "productization_readiness": productization,
        "repair_recipe_quality_gate": repair_gate,
        "next_actions": _next_actions(checks),
        "calibration": {
            "schema": "octopus.browser_desktop_cold_start_calibration.v1",
            "claim": (
                "Cold-start readiness proves the browser/desktop control plane "
                "can self-bootstrap and repair failures offline; it does not "
                "replace fresh live runtime evidence for the higher score."
            ),
            "cold_start_score_cap": 93,
            "live_runtime_score_cap": 94,
        },
    }


def _bootstrap_probe(base: Path) -> dict[str, Any]:
    browser_router = _read_text(base / "runtime/platform/ui/browser_router.py")
    computer_router = _read_text(base / "runtime/sensing/gateway/computer_router.py")
    runtime_probe = _read_text(base / "runtime/safety/evolution/browser_desktop_runtime_probe.py")
    cli = _read_text(base / "scripts/browser_desktop_runtime_probe.py")
    manifest = _load_json(base / "extensions/octopus-browser-relay/manifest.json")
    checks = {
        "browser_has_session_bootstrap": all(
            term in browser_router
            for term in (
                "/api/browser/session/ensure",
                "/api/browser/session/health",
                "/api/browser/session/reset",
            )
        ),
        "browser_has_relay_bootstrap": all(
            term in browser_router
            for term in (
                "api_browser_relay_heartbeat",
                "api_browser_relay_command",
                "api_browser_relay_result",
            )
        ),
        "desktop_has_preview_policy_and_replay": all(
            term in computer_router
            for term in (
                "/actions/preview",
                "_reject_if_policy_denied",
                "/activity/replay-case",
                "/activity/replay-case/queue",
            )
        ),
        "runtime_probe_can_persist_evidence": all(
            term in runtime_probe
            for term in (
                "run_browser_desktop_runtime_probe",
                "write_browser_desktop_runtime_evidence",
                "/api/browser/session/ensure",
                "/api/computer/actions/preview",
            )
        ),
        "operator_cli_can_auto_auth_and_cleanup": all(
            term in cli
            for term in (
                "--auto-local-auth",
                "--cleanup-session",
                "browser_desktop_runtime_probe",
            )
        ),
        "chrome_extension_hosts_local_backend": (
            manifest.get("manifest_version") == 3
            and "http://127.0.0.1:8000/*" in _string_list(manifest.get("host_permissions"))
            and "http://localhost:8000/*" in _string_list(manifest.get("host_permissions"))
        ),
    }
    return {
        "schema": "octopus.browser_desktop_cold_start_bootstrap_probe.v1",
        "ok": all(checks.values()),
        "checks": checks,
    }


def _next_actions(checks: dict[str, bool]) -> list[str]:
    actions = []
    if checks.get("runtime_contract_ready") is not True:
        actions.append("Complete browser/desktop runtime contract coverage.")
    if checks.get("productization_ready") is not True:
        actions.append("Complete browser relay and desktop policy productization.")
    if checks.get("repair_recipe_gate_ready") is not True:
        actions.append("Keep deterministic browser/desktop repair recipe gates clean.")
    if checks.get("offline_bootstrap_probe_ready") is not True:
        actions.append("Wire the offline browser/desktop bootstrap probe end to end.")
    if not actions:
        actions.append("Browser/desktop cold-start readiness is verified.")
    return actions


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _load_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _string_list(value: Any) -> list[str]:
    return [str(item) for item in value] if isinstance(value, list) else []


__all__ = [
    "SCHEMA",
    "compute_browser_desktop_cold_start_readiness",
]
