from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from runtime.platform.process.paths import app_paths
from runtime.platform.process.paths import project_root as default_project_root
from runtime.safety.evolution.browser_desktop_runtime_evidence import (
    DEFAULT_MAX_AGE_S,
    load_browser_desktop_runtime_evidence,
)
from runtime.safety.evolution.browser_desktop_runtime_contract import (
    compute_browser_desktop_runtime_contract,
)
from runtime.safety.evolution.browser_desktop_runtime_readiness import (
    compute_browser_desktop_runtime_readiness,
)
from runtime.safety.evolution.browser_desktop_productization_readiness import (
    compute_browser_desktop_productization_readiness,
)
from runtime.safety.evolution.browser_desktop_cold_start_readiness import (
    compute_browser_desktop_cold_start_readiness,
)
from runtime.safety.evolution.browser_desktop_capability_canary import (
    compute_browser_desktop_capability_canary,
)


@dataclass(frozen=True)
class BrowserDesktopCheck:
    id: str
    title: str
    paths: tuple[str, ...]
    required_terms: tuple[str, ...]
    weight: int = 1


CHECKS: tuple[BrowserDesktopCheck, ...] = (
    BrowserDesktopCheck(
        id="browser_session_lifecycle",
        title="Browser session lifecycle",
        paths=(
            "runtime/platform/ui/browser_router.py",
            "runtime/platform/runtime_policy/browser_sessions.py",
            "tests/test_browser_router.py",
            "tests/test_browser_sessions.py",
        ),
        required_terms=(
            "session/status",
            "session/ensure",
            "session/health",
            "session/replay-case",
            "session/replay-case/queue",
            "browser-session:",
            "fingerprint",
            "case_id",
            "recovered_from_crash",
            "review_queue",
        ),
    ),
    BrowserDesktopCheck(
        id="browser_pixel_replay_gate",
        title="Browser pixel replay gate",
        paths=(
            "runtime/safety/replay/browser_pixel_assertions.py",
            "runtime/execution/suckers/browser_act_skills.py",
            "tests/test_browser_pixel_assertions.py",
            "tests/test_browser_artifact.py",
        ),
        required_terms=(
            "browser_pixel_replay_gate_case",
            "replay_gate_case",
            "browser_pixel_evidence_failed",
            "ReviewQueue",
            "browser_pixel_replay_gate",
        ),
    ),
    BrowserDesktopCheck(
        id="desktop_preview_execute_lease",
        title="Desktop preview, execute, and lease safety",
        paths=(
            "runtime/sensing/gateway/computer_router.py",
            "tests/test_computer_router.py",
        ),
        required_terms=(
            "actions/preview",
            "actions/execute",
            "computer_activity",
            "activity/replay-case",
            "activity/replay-case/queue",
            "computer-activity:",
            "fingerprint",
            "case_id",
            "recent_activity",
            "lease_owner_id",
            "review_queue",
        ),
    ),
    BrowserDesktopCheck(
        id="desktop_uia_grounding",
        title="Desktop UIA grounding",
        paths=(
            "runtime/execution/suckers/computer_uia_skills.py",
            "runtime/sensing/gateway/computer_router.py",
            "tests/test_computer_uia_skills.py",
            "tests/test_computer_router.py",
        ),
        required_terms=(
            "uia",
            "matched_control",
            "automation_id",
            "computer_uia_replay_assertion",
            "replay_assertion",
        ),
    ),
    BrowserDesktopCheck(
        id="operator_visibility",
        title="Operator-visible browser and desktop health",
        paths=(
            "frontend/src/components/workspace/agent-operator-panel.tsx",
            "frontend/src/components/workspace/agent-operator-panel.test.tsx",
            "frontend/src/components/workspace/browser-preview-panel.tsx",
            "frontend/src/components/workspace/embedded-browser/browser-panel.tsx",
        ),
        required_terms=(
            "browser",
            "certified",
            "sessionHealth",
            "Plugin health",
        ),
    ),
    BrowserDesktopCheck(
        id="deterministic_repair_recipe_gate",
        title="Deterministic browser/desktop repair recipe gate",
        paths=(
            "runtime/safety/evolution/browser_desktop_repair_recipes.py",
            "runtime/sensing/gateway/evolution_router.py",
            "tests/test_computer_use_record.py",
            "tests/test_evolution_router.py",
        ),
        required_terms=(
            "browser_desktop_repair_recipe_gate",
            "requires_replay_rerun",
            "rerun_browser_desktop_repair_recipe_batch",
            "compute_browser_desktop_repair_recipe_quality_gate",
        ),
        weight=2,
    ),
)


def compute_browser_desktop_quality(
    *,
    root: str | Path | None = None,
    review_queue_path: str | Path | None = None,
    browser_health: dict[str, Any] | None = None,
    computer_status: dict[str, Any] | None = None,
    computer_preview: dict[str, Any] | None = None,
    computer_execute: dict[str, Any] | None = None,
    computer_replay_case: dict[str, Any] | None = None,
    chrome_relay_handshake: dict[str, Any] | None = None,
    real_chrome_relay_probe: dict[str, Any] | None = None,
    auth_status: dict[str, Any] | None = None,
    operation_status: dict[str, Any] | None = None,
    cleanup_status: dict[str, Any] | None = None,
    include_runtime_probe: bool = False,
    api_base_url: str = "http://127.0.0.1:8000",
    bearer_token: str = "",
    auto_local_auth: bool = False,
    local_auth_username: str = "runtime-probe",
    local_auth_password: str = "",
    use_runtime_evidence_cache: bool = True,
    refresh_runtime_evidence_if_stale: bool = False,
    runtime_evidence_path: str | Path | None = None,
    runtime_evidence_max_age_s: int = DEFAULT_MAX_AGE_S,
    real_chrome_relay: bool = False,
    open_real_chrome_relay: bool = False,
) -> dict[str, Any]:
    base = Path(root) if root is not None else default_project_root(Path(__file__))
    runtime_probe: dict[str, Any] | None = None
    runtime_evidence = {
        "schema": "octopus.browser_desktop_runtime_evidence_lookup.v1",
        "available": False,
        "usable": False,
        "fresh": False,
        "reason": "runtime evidence cache was not checked",
    }
    if include_runtime_probe and (browser_health is None or computer_status is None):
        try:
            from runtime.safety.evolution.browser_desktop_runtime_probe import (
                run_browser_desktop_runtime_probe,
            )

            runtime_probe = run_browser_desktop_runtime_probe(
                api_base_url=api_base_url,
                review_queue_path=review_queue_path,
                bearer_token=bearer_token,
                auto_local_auth=auto_local_auth,
                local_auth_username=local_auth_username,
                local_auth_password=local_auth_password,
                real_chrome_relay=real_chrome_relay,
                open_real_chrome_relay=open_real_chrome_relay,
                evidence_path=runtime_evidence_path,
            )
            probe_browser = runtime_probe.get("browser_health")
            probe_computer = runtime_probe.get("computer_status")
            probe_preview = runtime_probe.get("computer_preview")
            probe_execute = runtime_probe.get("computer_execute")
            probe_replay_case = runtime_probe.get("computer_replay_case")
            probe_auth = runtime_probe.get("auth")
            probe_operations = runtime_probe.get("operation_status")
            probe_cleanup = runtime_probe.get("cleanup")
            probe_relay = runtime_probe.get("chrome_relay_handshake")
            probe_real_relay = runtime_probe.get("real_chrome_relay_probe")
            if browser_health is None and isinstance(probe_browser, dict):
                browser_health = probe_browser
            if computer_status is None and isinstance(probe_computer, dict):
                computer_status = probe_computer
            if computer_preview is None and isinstance(probe_preview, dict):
                computer_preview = probe_preview
            if computer_execute is None and isinstance(probe_execute, dict):
                computer_execute = probe_execute
            if computer_replay_case is None and isinstance(probe_replay_case, dict):
                computer_replay_case = probe_replay_case
            if auth_status is None and isinstance(probe_auth, dict):
                auth_status = probe_auth
            if operation_status is None and isinstance(probe_operations, dict):
                operation_status = probe_operations
            if cleanup_status is None and isinstance(probe_cleanup, dict):
                cleanup_status = probe_cleanup
            if chrome_relay_handshake is None and isinstance(probe_relay, dict):
                chrome_relay_handshake = probe_relay
            if real_chrome_relay_probe is None and isinstance(probe_real_relay, dict):
                real_chrome_relay_probe = probe_real_relay
            probe_evidence = runtime_probe.get("runtime_evidence_snapshot")
            if isinstance(probe_evidence, dict):
                runtime_evidence = probe_evidence
        except Exception as exc:  # noqa: BLE001
            runtime_probe = {
                "schema": "octopus.browser_desktop_runtime_probe.v1",
                "ok": False,
                "error": str(exc),
            }
    elif (
        use_runtime_evidence_cache
        and (browser_health is None or computer_status is None)
    ):
        runtime_evidence = load_browser_desktop_runtime_evidence(
            path=runtime_evidence_path,
            max_age_s=runtime_evidence_max_age_s,
        )
        if (
            runtime_evidence.get("usable") is not True
            and refresh_runtime_evidence_if_stale
        ):
            try:
                from runtime.safety.evolution.browser_desktop_runtime_probe import (
                    run_browser_desktop_runtime_probe,
                )

                runtime_probe = run_browser_desktop_runtime_probe(
                    api_base_url=api_base_url,
                    review_queue_path=review_queue_path,
                    bearer_token=bearer_token,
                    auto_local_auth=auto_local_auth,
                    local_auth_username=local_auth_username,
                    local_auth_password=local_auth_password,
                    real_chrome_relay=real_chrome_relay,
                    open_real_chrome_relay=open_real_chrome_relay,
                    evidence_path=runtime_evidence_path,
                )
                probe_evidence = runtime_probe.get("runtime_evidence_snapshot")
                if isinstance(probe_evidence, dict):
                    runtime_evidence = probe_evidence
            except Exception as exc:  # noqa: BLE001
                runtime_probe = {
                    "schema": "octopus.browser_desktop_runtime_probe.v1",
                    "ok": False,
                    "error": str(exc),
                    "refresh_reason": str(runtime_evidence.get("reason") or ""),
                }
        evidence = (
            runtime_evidence.get("evidence")
            if isinstance(runtime_evidence.get("evidence"), dict)
            else {}
        )
        if runtime_evidence.get("usable") is True:
            cached_browser = evidence.get("browser_health")
            cached_computer = evidence.get("computer_status")
            cached_preview = evidence.get("computer_preview")
            cached_execute = evidence.get("computer_execute")
            cached_replay_case = evidence.get("computer_replay_case")
            cached_auth = evidence.get("auth")
            cached_operations = evidence.get("operation_status")
            cached_cleanup = evidence.get("cleanup")
            cached_relay = evidence.get("chrome_relay_handshake")
            cached_real_relay = evidence.get("real_chrome_relay_probe")
            if browser_health is None and isinstance(cached_browser, dict):
                browser_health = cached_browser
            if computer_status is None and isinstance(cached_computer, dict):
                computer_status = cached_computer
            if computer_preview is None and isinstance(cached_preview, dict):
                computer_preview = cached_preview
            if computer_execute is None and isinstance(cached_execute, dict):
                computer_execute = cached_execute
            if computer_replay_case is None and isinstance(cached_replay_case, dict):
                computer_replay_case = cached_replay_case
            if auth_status is None and isinstance(cached_auth, dict):
                auth_status = cached_auth
            if operation_status is None and isinstance(cached_operations, dict):
                operation_status = cached_operations
            if cleanup_status is None and isinstance(cached_cleanup, dict):
                cleanup_status = cached_cleanup
            if chrome_relay_handshake is None and isinstance(cached_relay, dict):
                chrome_relay_handshake = cached_relay
            if real_chrome_relay_probe is None and isinstance(cached_real_relay, dict):
                real_chrome_relay_probe = cached_real_relay
    checks = [_check_row(base, check) for check in CHECKS]
    total_weight = sum(int(row["weight"]) for row in checks)
    passed_weight = sum(int(row["weight"]) for row in checks if row["passed"])
    score = round(passed_weight / max(1, total_weight), 3)
    runtime_contract = compute_browser_desktop_runtime_contract(root=base)
    runtime_readiness = compute_browser_desktop_runtime_readiness(
        browser_health=browser_health,
        computer_status=computer_status,
        computer_preview=computer_preview,
        computer_execute=computer_execute,
        computer_replay_case=computer_replay_case,
        auth_status=auth_status,
        operation_status=operation_status,
        cleanup_status=cleanup_status,
        review_queue_path=review_queue_path,
    )
    productization_readiness = compute_browser_desktop_productization_readiness(
        root=base,
    )
    cold_start_readiness = compute_browser_desktop_cold_start_readiness(
        root=base,
        review_queue_path=review_queue_path,
    )
    replay_trends = _browser_replay_trends(review_queue_path)
    repair_gate = _repair_recipe_quality_gate(review_queue_path)
    capability_canary = compute_browser_desktop_capability_canary(
        browser_health=browser_health,
        computer_status=computer_status,
        computer_preview=computer_preview,
        computer_execute=computer_execute,
        computer_replay_case=computer_replay_case,
        chrome_relay_handshake=chrome_relay_handshake,
        real_chrome_relay_probe=real_chrome_relay_probe,
        operation_status=operation_status,
        cleanup_status=cleanup_status,
        runtime_readiness=runtime_readiness,
        productization_readiness=productization_readiness,
        cold_start_readiness=cold_start_readiness,
        repair_recipe_quality_gate=repair_gate,
        review_queue_path=review_queue_path,
    )
    next_actions = [
        str(row["next_action"])
        for row in checks
        if not row["passed"]
    ]
    if runtime_readiness.get("ready") is not True:
        next_actions.extend(
            str(action)
            for action in runtime_readiness.get("next_actions", [])
            if str(action)
        )
    if runtime_contract.get("ready") is not True:
        next_actions.extend(
            str(action)
            for action in runtime_contract.get("next_actions", [])
            if str(action)
        )
    if productization_readiness.get("ready") is not True:
        next_actions.extend(
            str(action)
            for action in productization_readiness.get("next_actions", [])
            if str(action)
        )
    effective_score = _effective_browser_desktop_score(
        static_score=score,
        runtime_score=float(runtime_readiness.get("score") or 0.0),
        runtime_ready=runtime_readiness.get("ready") is True,
        runtime_contract=runtime_contract,
        productization_score=float(productization_readiness.get("score") or 0.0),
    )
    return {
        "schema": "octopus.browser_desktop_quality.v1",
        "score": score,
        "passed": sum(1 for row in checks if row["passed"]),
        "total": len(checks),
        "ready": (
            all(row["passed"] for row in checks)
            and runtime_readiness.get("ready") is True
            and productization_readiness.get("ready") is True
            and capability_canary.get("ready") is True
        ),
        "checks": checks,
        "static_ready": all(row["passed"] for row in checks),
        "static_score": score,
        "productization_readiness": productization_readiness,
        "productization_ready": productization_readiness.get("ready") is True,
        "productization_score": productization_readiness.get("score"),
        "cold_start_readiness": cold_start_readiness,
        "cold_start_ready": cold_start_readiness.get("ready") is True,
        "cold_start_score": cold_start_readiness.get("score"),
        "runtime_contract": runtime_contract,
        "runtime_contract_ready": runtime_contract.get("ready") is True,
        "runtime_contract_score": runtime_contract.get("score"),
        "runtime_readiness": runtime_readiness,
        "runtime_probe": runtime_probe,
        "runtime_evidence": runtime_evidence,
        "runtime_score": runtime_readiness.get("score"),
        "capability_canary": capability_canary,
        "capability_canary_ready": capability_canary.get("ready") is True,
        "effective_score": effective_score,
        "replay_trends": replay_trends,
        "repair_recipe_quality_gate": repair_gate,
        "next_actions": next_actions,
    }


def _effective_browser_desktop_score(
    *,
    static_score: float,
    runtime_score: float,
    runtime_ready: bool,
    runtime_contract: dict[str, Any],
    productization_score: float,
) -> float:
    contract_score = float(runtime_contract.get("score") or 0.0)
    score = (
        (0.35 * float(static_score))
        + (0.30 * runtime_score)
        + (0.20 * contract_score)
        + (0.15 * productization_score)
    )
    if runtime_ready:
        return round(score, 3)
    if static_score >= 1.0 and runtime_contract.get("ready") is True:
        return round(max(score, 0.82), 3)
    return round(score, 3)


def _check_row(base: Path, check: BrowserDesktopCheck) -> dict[str, Any]:
    paths = [
        {"path": path, "exists": (base / path).exists()}
        for path in check.paths
    ]
    text = "\n".join(
        _read_text(base / row["path"])
        for row in paths
        if row["exists"]
    ).lower()
    missing_paths = [
        str(row["path"])
        for row in paths
        if not row["exists"]
    ]
    missing_terms = [
        term
        for term in check.required_terms
        if term.lower() not in text
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
        "next_action": f"Complete browser/desktop quality check: {check.title}.",
    }


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _browser_replay_trends(
    review_queue_path: str | Path | None,
) -> dict[str, Any]:
    try:
        from runtime.memory.learning.review_queue import ReviewQueue

        queue = ReviewQueue(
            Path(review_queue_path)
            if review_queue_path is not None
            else app_paths().review_queue_path,
        )
        rows = queue.items(target_bucket="browser_desktop_replay", limit=1000)["items"]
    except Exception:  # noqa: BLE001
        rows = []
    by_status: dict[str, int] = {}
    by_candidate_kind: dict[str, int] = {}
    stale_source_artifact_count = 0
    for row in rows:
        status = str(row.get("status") or "pending")
        by_status[status] = by_status.get(status, 0) + 1
        kind = str(row.get("candidate_kind") or "unknown")
        by_candidate_kind[kind] = by_candidate_kind.get(kind, 0) + 1
        if status == "pending" and _has_stale_source_artifact(row):
            stale_source_artifact_count += 1
    pending = by_status.get("pending", 0)
    promoted = by_status.get("promoted", 0)
    rejected = by_status.get("rejected", 0)
    total = len(rows)
    reviewed = promoted + rejected + by_status.get("archived", 0)
    review_rate = round(reviewed / total, 3) if total else 0.0
    repair_recipe_summary = _browser_repair_recipe_summary(review_queue_path)
    return {
        "schema": "octopus.browser_desktop_replay_trends.v1",
        "total": total,
        "pending_count": pending,
        "reviewed_count": reviewed,
        "promoted_count": promoted,
        "rejected_count": rejected,
        "review_rate": review_rate,
        "stale_source_artifact_count": stale_source_artifact_count,
        "by_status": dict(sorted(by_status.items())),
        "by_candidate_kind": dict(sorted(by_candidate_kind.items())),
        "repair_recipe_summary": repair_recipe_summary,
        "latest": [
            {
                "id": row.get("id"),
                "title": row.get("title"),
                "status": row.get("status"),
                "candidate_kind": row.get("candidate_kind"),
                "updated_at": row.get("updated_at"),
            }
            for row in rows[:5]
        ],
        "next_actions": _browser_replay_next_actions(
            pending=pending,
            total=total,
            review_rate=review_rate,
            stale_source_artifact_count=stale_source_artifact_count,
        ),
    }


def _has_stale_source_artifact(row: dict[str, Any]) -> bool:
    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    artifact = metadata.get("artifact") if isinstance(metadata.get("artifact"), dict) else {}
    local_path = str(artifact.get("local_path") or "").strip()
    return bool(local_path) and not Path(local_path).is_file()


def _browser_repair_recipe_summary(
    review_queue_path: str | Path | None,
) -> dict[str, Any]:
    try:
        from runtime.safety.evolution.browser_desktop_repair_recipes import (
            compute_browser_desktop_repair_recipes,
        )

        report = compute_browser_desktop_repair_recipes(
            review_queue_path=review_queue_path,
            limit=1000,
        )
        recipes = report.get("recipes") if isinstance(report.get("recipes"), list) else []
    except Exception:  # noqa: BLE001
        report = {}
        recipes = []
    return {
        "schema": "octopus.browser_desktop_repair_recipe_summary.v1",
        "recipe_count": int(report.get("recipe_count") or 0),
        "total_pending_cases": int(report.get("total_pending_cases") or 0),
        "top_recipes": [
            {
                "recipe_id": recipe.get("recipe_id"),
                "title": recipe.get("title"),
                "priority": recipe.get("priority"),
                "occurrences": recipe.get("occurrences"),
                "candidate_kind": recipe.get("candidate_kind"),
            }
            for recipe in recipes[:3]
            if isinstance(recipe, dict)
        ],
    }


def _repair_recipe_quality_gate(
    review_queue_path: str | Path | None,
) -> dict[str, Any]:
    try:
        from runtime.safety.evolution.browser_desktop_repair_recipes import (
            compute_browser_desktop_repair_recipe_quality_gate,
        )

        report = compute_browser_desktop_repair_recipe_quality_gate(
            review_queue_path=review_queue_path,
            limit=1000,
        )
        return report if isinstance(report, dict) else _empty_repair_quality_gate()
    except Exception as exc:  # noqa: BLE001
        gate = _empty_repair_quality_gate()
        gate["error"] = str(exc)
        return gate


def _empty_repair_quality_gate() -> dict[str, Any]:
    return {
        "schema": "octopus.browser_desktop_repair_recipe_quality_gate.v1",
        "score": 0.0,
        "ready": False,
        "blockers": ["quality_gate_unavailable"],
        "signals": {},
    }


def _browser_replay_next_actions(
    *,
    pending: int,
    total: int,
    review_rate: float,
    stale_source_artifact_count: int,
) -> list[str]:
    if stale_source_artifact_count:
        return [
            f"Regenerate or reject {stale_source_artifact_count} stale browser/desktop replay artifact(s).",
        ]
    if pending:
        return [
            f"Review {pending} pending browser/desktop replay case(s) before promotion.",
        ]
    if total and review_rate >= 0.8:
        return ["Browser/desktop replay review trend is healthy."]
    return ["Capture browser/desktop replay cases from the next visual automation run."]


__all__ = [
    "BrowserDesktopCheck",
    "CHECKS",
    "compute_browser_desktop_quality",
]
