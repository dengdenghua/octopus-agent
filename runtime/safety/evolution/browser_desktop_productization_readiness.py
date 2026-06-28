from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from runtime.platform.process.paths import project_root as default_project_root
from runtime.platform.runtime_policy.computer_automation import (
    app_permission_decision,
    load_computer_automation_policy,
    save_computer_automation_policy,
)

SCHEMA = "octopus.browser_desktop_productization_readiness.v1"
PROBE_SCHEMA = "octopus.browser_desktop_productization_probe.v1"


@dataclass(frozen=True)
class BrowserDesktopProductizationCheck:
    id: str
    title: str
    paths: tuple[str, ...]
    required_terms: tuple[str, ...]
    weight: int = 1


CHECKS: tuple[BrowserDesktopProductizationCheck, ...] = (
    BrowserDesktopProductizationCheck(
        id="chrome_relay_extension_surface",
        title="Chrome relay extension surface",
        paths=(
            "extensions/octopus-browser-relay/manifest.json",
            "extensions/octopus-browser-relay/background.js",
            "extensions/octopus-browser-relay/content.js",
        ),
        required_terms=(
            "manifest_version",
            "tabs",
            "activeTab",
            "scripting",
            "chrome.tabs.captureVisibleTab",
            "/api/browser/relay/heartbeat",
            "/api/browser/relay/result",
            "API_BASES",
        ),
        weight=3,
    ),
    BrowserDesktopProductizationCheck(
        id="chrome_relay_backend_control_plane",
        title="Chrome relay backend control plane",
        paths=("runtime/platform/ui/browser_router.py",),
        required_terms=(
            "/api/browser/relay/status",
            "/api/browser/relay/heartbeat",
            "/api/browser/relay/command",
            "/api/browser/relay/result",
            "/api/browser/relay/bookmarklet.js",
            "/api/browser/open-extension-folder",
            "/api/browser/extension-path",
            "connection_mode must be one of playwright, extension, cdp",
        ),
        weight=3,
    ),
    BrowserDesktopProductizationCheck(
        id="signed_in_browser_fallback",
        title="Signed-in browser fallback",
        paths=(
            "extensions/octopus-browser-relay/bookmarklet.js",
            "extensions/octopus-browser-relay/README.md",
            "runtime/platform/ui/browser_router.py",
        ),
        required_terms=(
            "bookmarklet mode",
            "bookmarklet mode does not support screenshots",
            "pageAgent",
            "bookmarklet-poll",
            "bookmarklet-result",
        ),
        weight=2,
    ),
    BrowserDesktopProductizationCheck(
        id="desktop_app_permission_policy",
        title="Desktop app permission policy",
        paths=(
            "runtime/platform/runtime_policy/computer_automation.py",
            "runtime/sensing/gateway/computer_router.py",
            "runtime/platform/process/paths.py",
        ),
        required_terms=(
            "octopus.computer_automation_policy.v1",
            "allowed_apps",
            "denied_apps",
            "app_permission_decision",
            "/policy",
            "policy_decision",
            "preview_rejected",
            "computer_automation_policy_path",
        ),
        weight=3,
    ),
    BrowserDesktopProductizationCheck(
        id="desktop_preview_execute_product_loop",
        title="Desktop preview, execute, lease product loop",
        paths=("runtime/sensing/gateway/computer_router.py",),
        required_terms=(
            "/actions/preview",
            "/actions/plan",
            "/actions/ground",
            "/actions/vision",
            "/actions/execute",
            "/lease/release",
            "preview-confirm-execute-with-lease",
            "lease_owner_id",
        ),
        weight=3,
    ),
    BrowserDesktopProductizationCheck(
        id="desktop_grounding_modes",
        title="Desktop UIA and vision grounding modes",
        paths=(
            "runtime/sensing/gateway/computer_router.py",
            "runtime/execution/suckers/computer_uia_skills.py",
            "tests/test_computer_router.py",
        ),
        required_terms=(
            "computer_uia_find",
            "replay_assertion",
            "vision-output-adapter",
            "vision-model",
            "OCTOPUS_COMPUTER_VISION_MODEL",
            "matched_control",
        ),
        weight=2,
    ),
    BrowserDesktopProductizationCheck(
        id="browser_desktop_product_tests",
        title="Browser/desktop productization regression tests",
        paths=(
            "tests/test_browser_router.py",
            "tests/test_computer_router.py",
            "tests/test_browser_desktop_productization_readiness.py",
        ),
        required_terms=(
            "test_browser_relay_heartbeat_and_status",
            "test_computer_policy_blocks_denied_target_app",
            "compute_browser_desktop_productization_readiness",
        ),
        weight=2,
    ),
)


def compute_browser_desktop_productization_readiness(
    *,
    root: str | Path | None = None,
    include_probe: bool = True,
) -> dict[str, Any]:
    base = Path(root) if root is not None else default_project_root(Path(__file__))
    checks = [_check_status(base, check) for check in CHECKS]
    probe = run_browser_desktop_productization_probe(root=base) if include_probe else _skipped_probe()
    checks.extend(_probe_checks(probe))
    total_weight = sum(int(row["weight"]) for row in checks)
    passed_weight = sum(int(row["weight"]) for row in checks if row["passed"])
    score = round(passed_weight / total_weight, 3) if total_weight else 0.0
    missing = [row for row in checks if not row["passed"]]
    return {
        "schema": SCHEMA,
        "score": score,
        "ready": score >= 1.0 and not missing,
        "verdict": "pass" if score >= 1.0 and not missing else "review",
        "passed": len(checks) - len(missing),
        "total": len(checks),
        "passed_weight": passed_weight,
        "total_weight": total_weight,
        "missing_count": len(missing),
        "checks": checks,
        "probe": probe,
        "next_actions": _next_actions(missing),
        "calibration": {
            "schema": "octopus.browser_desktop_productization_calibration.v1",
            "compares_to": {
                "codex": (
                    "Chrome extension signed-in browser control, Computer Use "
                    "app permissions, developer-mode browser diagnostics, and "
                    "productized Record & Replay."
                ),
            },
            "octopus_edge": (
                "local Chrome relay plus bookmarklet fallback, desktop "
                "preview-confirm-execute leases, app allow/deny policy, UIA/vision "
                "grounding, and replay evidence hooks exposed as backend gates"
            ),
        },
    }


def run_browser_desktop_productization_probe(
    *,
    root: str | Path | None = None,
) -> dict[str, Any]:
    base = Path(root) if root is not None else default_project_root(Path(__file__))
    manifest = _load_json(base / "extensions/octopus-browser-relay/manifest.json")
    permissions = set(_string_list(manifest.get("permissions")))
    host_permissions = set(_string_list(manifest.get("host_permissions")))
    manifest_ready = (
        manifest.get("manifest_version") == 3
        and {"tabs", "activeTab", "scripting"}.issubset(permissions)
        and "http://127.0.0.1:8000/*" in host_permissions
        and "http://localhost:8000/*" in host_permissions
    )
    background = _read_text(base / "extensions/octopus-browser-relay/background.js")
    relay_loop_ready = all(
        term in background
        for term in (
            "postHeartbeat",
            "processCommands",
            "reportResult",
            "chrome.tabs.captureVisibleTab",
            "chrome.scripting.executeScript",
        )
    )
    policy_probe = _policy_probe()
    router_text = _read_text(base / "runtime/sensing/gateway/computer_router.py")
    computer_policy_endpoint_ready = all(
        term in router_text
        for term in (
            "@router.get(\"/policy\")",
            "@router.put(\"/policy\")",
            "_reject_if_policy_denied",
            "policy_decision",
        )
    )
    browser_router_text = _read_text(base / "runtime/platform/ui/browser_router.py")
    chrome_control_plane_ready = all(
        term in browser_router_text
        for term in (
            "api_browser_relay_status",
            "api_browser_relay_heartbeat",
            "api_browser_relay_command",
            "api_browser_relay_result",
            "api_browser_relay_bookmarklet_js",
        )
    )
    ok = (
        manifest_ready
        and relay_loop_ready
        and policy_probe["ok"]
        and computer_policy_endpoint_ready
        and chrome_control_plane_ready
    )
    return {
        "schema": PROBE_SCHEMA,
        "ok": ok,
        "manifest_ready": manifest_ready,
        "relay_loop_ready": relay_loop_ready,
        "chrome_control_plane_ready": chrome_control_plane_ready,
        "computer_policy_endpoint_ready": computer_policy_endpoint_ready,
        "policy_probe": policy_probe,
        "secrets_redacted": _no_secret_literals(background),
    }


def _policy_probe() -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "computer_policy.json"
        saved = save_computer_automation_policy(
            {
                "allowed_apps": ["Chrome"],
                "denied_apps": ["Keychain Access"],
                "preview_required": True,
                "lease_required": True,
            },
            path=path,
        )
        loaded = load_computer_automation_policy(path)
    allowed = app_permission_decision(loaded, target_app="Chrome")
    denied = app_permission_decision(loaded, target_app="Keychain Access")
    prompt = app_permission_decision(loaded, target_app="Preview")
    return {
        "schema": "octopus.computer_automation_policy_probe.v1",
        "ok": (
            saved.get("schema") == "octopus.computer_automation_policy.v1"
            and loaded.get("schema") == "octopus.computer_automation_policy.v1"
            and loaded.get("persisted") is True
            and allowed.get("decision") == "allowed"
            and denied.get("decision") == "denied"
            and prompt.get("decision") == "prompt"
            and loaded.get("preview_required") is True
            and loaded.get("lease_required") is True
        ),
        "allowed_decision": allowed,
        "denied_decision": denied,
        "prompt_decision": prompt,
    }


def _probe_checks(probe: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        _dynamic_check(
            "chrome_manifest_probe",
            "Chrome relay manifest probe",
            bool(probe.get("manifest_ready")),
            "Manifest declares MV3 tabs/activeTab/scripting permissions and localhost hosts.",
            weight=2,
        ),
        _dynamic_check(
            "chrome_relay_loop_probe",
            "Chrome relay command-loop probe",
            bool(probe.get("relay_loop_ready") and probe.get("chrome_control_plane_ready")),
            "Relay heartbeat, command, result, screenshot, and script-execution loops are wired.",
            weight=2,
        ),
        _dynamic_check(
            "desktop_policy_probe",
            "Desktop automation policy probe",
            bool(
                probe.get("computer_policy_endpoint_ready")
                and isinstance(probe.get("policy_probe"), dict)
                and probe["policy_probe"].get("ok") is True
            ),
            "Desktop app allow/deny/prompt policy round-trips and is used by the router.",
            weight=3,
        ),
        _dynamic_check(
            "browser_desktop_secret_hygiene_probe",
            "Browser/desktop secret hygiene probe",
            bool(probe.get("secrets_redacted")),
            "Relay product files do not embed API key literals.",
            weight=1,
        ),
    ]


def _check_status(
    base: Path,
    check: BrowserDesktopProductizationCheck,
) -> dict[str, Any]:
    paths = [
        {"path": path, "exists": (base / path).exists()}
        for path in check.paths
    ]
    text = "\n".join(
        _read_text(base / str(row["path"]))
        for row in paths
        if row["exists"]
    )
    lowered = text.lower()
    missing_paths = [
        str(row["path"])
        for row in paths
        if not row["exists"]
    ]
    missing_terms = [
        term
        for term in check.required_terms
        if term.lower() not in lowered
    ]
    return {
        "id": check.id,
        "title": check.title,
        "weight": check.weight,
        "passed": not missing_paths and not missing_terms,
        "paths": paths,
        "missing_paths": missing_paths,
        "required_terms": list(check.required_terms),
        "missing_terms": missing_terms,
        "next_action": f"Complete browser/desktop productization check: {check.title}.",
    }


def _dynamic_check(
    check_id: str,
    title: str,
    passed: bool,
    detail: str,
    *,
    weight: int,
) -> dict[str, Any]:
    return {
        "id": check_id,
        "title": title,
        "weight": weight,
        "passed": passed,
        "paths": [],
        "missing_paths": [],
        "required_terms": [],
        "missing_terms": [] if passed else [detail],
        "next_action": detail,
    }


def _skipped_probe() -> dict[str, Any]:
    return {
        "schema": PROBE_SCHEMA,
        "ok": False,
        "skipped": True,
    }


def _next_actions(missing: list[dict[str, Any]]) -> list[str]:
    if not missing:
        return ["Browser/desktop productization checks are ready."]
    return [str(row.get("next_action")) for row in missing if row.get("next_action")]


def _load_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _string_list(value: Any) -> list[str]:
    return [str(item) for item in value] if isinstance(value, list) else []


def _no_secret_literals(text: str) -> bool:
    lowered = text.lower()
    return "sk-" not in lowered and "api_key" not in lowered and "authorization" not in lowered


__all__ = [
    "BrowserDesktopProductizationCheck",
    "CHECKS",
    "PROBE_SCHEMA",
    "SCHEMA",
    "compute_browser_desktop_productization_readiness",
    "run_browser_desktop_productization_probe",
]
