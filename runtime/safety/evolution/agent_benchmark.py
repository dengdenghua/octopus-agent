from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from runtime.platform.process.paths import project_root as default_project_root


@dataclass(frozen=True)
class AgentBenchmarkCase:
    id: str
    title: str
    dimension: str
    weight: int
    paths: tuple[str, ...]
    required_terms: tuple[str, ...]
    next_action: str


BENCHMARK_CASES: tuple[AgentBenchmarkCase, ...] = (
    AgentBenchmarkCase(
        id="unified_control_session_replay",
        title="Unified control session, action, and replay substrate",
        dimension="browser_computer_automation",
        weight=12,
        paths=(
            "runtime/memory/control_sessions.py",
            "runtime/sensing/gateway/control_sessions_router.py",
            "frontend/src/core/control-session.ts",
            "extensions/octopus-browser-relay/background.js",
            "tests/test_control_sessions.py",
            "tests/test_chrome_sidepanel_extension.py",
        ),
        required_terms=(
            "octopus.control_session_replay.v1",
            "control_events",
            "/api/control-sessions",
            "takeover",
            "appendControlEvidence",
            "playwright_script",
        ),
        next_action="Keep every browser, Chrome, webview, and computer action on the same replay timeline.",
    ),
    AgentBenchmarkCase(
        id="computer_preview_confirm_loop",
        title="Computer workbench preview-confirm-execute loop",
        dimension="computer_automation",
        weight=12,
        paths=(
            "runtime/sensing/gateway/computer_router.py",
            "frontend/src/core/computer/api.ts",
            "frontend/src/app/workspace/computer/page.tsx",
            "tests/test_computer_router.py",
            "frontend/src/app/workspace/computer/page.test.tsx",
        ),
        required_terms=(
            "control_session_id",
            "control_action_id",
            "preview_token",
            "Agent 循环预演",
            "octopus.control_session_replay.v1",
        ),
        next_action="Run the computer loop through a live human-confirmed scenario before promotion.",
    ),
    AgentBenchmarkCase(
        id="collaboration_store_cutover",
        title="Cowork, team task, and Project OS write-path cutover",
        dimension="multi_agent_orchestration",
        weight=12,
        paths=(
            "runtime/memory/cowork/collaboration_store.py",
            "runtime/sensing/gateway/projects_router.py",
            "runtime/projectos/store.py",
            "tests/test_collaboration_store_cutover.py",
        ),
        required_terms=(
            "project_tasks_for_project",
            "upsert_project_task",
            "thread_for_project",
            "kind",
            "lease",
            "artifacts",
        ),
        next_action="Move team-task routers to write CollaborationStore first, then keep legacy JSON as projection.",
    ),
    AgentBenchmarkCase(
        id="non_code_guard_and_sandbox",
        title="All-mode guard coverage and shell-safe container writes",
        dimension="security",
        weight=11,
        paths=(
            "runtime/core/cerebrum/react_loop.py",
            "runtime/core/cerebrum/react_guards.py",
            "runtime/safety/sandboxing/container_sandbox.py",
            "tests/test_react_guard_registry.py",
            "tests/test_container_sandbox.py",
        ),
        required_terms=(
            "evaluate_guards",
            "_format_violation_bail_at",
            "sys.stdin.read",
            "test_write_file_uses_docker_exec_stdin_without_shell",
        ),
        next_action="Add streaming pre-emit guard tests for non-code final answers.",
    ),
    AgentBenchmarkCase(
        id="runtime_stability_regressions",
        title="Runtime stability leases, context pressure, and planner usage",
        dimension="stability",
        weight=10,
        paths=(
            "runtime/memory/cowork/store.py",
            "runtime/core/cerebrum/llm_planner.py",
            "runtime/core/cerebrum/react_loop_controls.py",
            "tests/test_dispatcher_context_capability.py",
            "tests/test_context_pressure.py",
            "tests/test_llm_planner.py",
        ),
        required_terms=(
            "synthesis_timeout_seconds",
            "last_plan_usage",
            "test_last_plan_usage_is_thread_local",
            "_estimate_context_fullness",
            "_compress_context",
        ),
        next_action="Keep context compression and planner usage telemetry in the same budget model.",
    ),
    AgentBenchmarkCase(
        id="domestic_provider_probe_matrix",
        title="Domestic provider capability and compatibility matrix",
        dimension="domestic_model_compat",
        weight=10,
        paths=(
            "runtime/sensing/model_router/capability_probe.py",
            "runtime/sensing/model_router/openai_compat_providers.py",
            "runtime/sensing/model_router/openai_compat_smoke_matrix.py",
            "tests/test_provider_probe_matrix.py",
            "tests/test_openai_compat_providers.py",
        ),
        required_terms=(
            "octopus.provider_capability_probe.v1",
            "unsupported_fields",
            "kimi_coding",
            "deepseek",
            "qwen",
            "doubao",
        ),
        next_action="Surface latest probe status beside each model setting row.",
    ),
    AgentBenchmarkCase(
        id="coding_agent_verifier_loop",
        title="Coding agent edit, verify, and repair loop",
        dimension="coding_agent",
        weight=10,
        paths=(
            "runtime/safety/evolution/auto_verifier.py",
            "runtime/safety/evolution/repair_route_quality.py",
            "runtime/sensing/gateway/realtime_turn_outcome.py",
            "tests/test_auto_verifier_metrics.py",
            "tests/test_repair_route_quality.py",
            "tests/test_post_write_diagnostics.py",
        ),
        required_terms=(
            "auto_verifier",
            "repair_route",
            "post_write",
            "verification_plan",
        ),
        next_action="Tie every promoted code edit to a verifier or repair-route record.",
    ),
    AgentBenchmarkCase(
        id="digital_employee_project_os",
        title="Digital employee Project OS process timeline",
        dimension="digital_employee",
        weight=9,
        paths=(
            "runtime/projectos/engine.py",
            "runtime/projectos/cowork_bridge.py",
            "runtime/projectos/timeline.py",
            "runtime/sensing/gateway/projects_router.py",
            "tests/test_projectos.py",
            "tests/test_projectos_cowork.py",
        ),
        required_terms=(
            "ProjectEngine",
            "cowork_bridge",
            "process_timeline",
            "run_project_from_group",
        ),
        next_action="Make project-mode turns create/run/tick through one visible worker timeline.",
    ),
    AgentBenchmarkCase(
        id="general_agent_turn_trace",
        title="General agent turn routing, trace, and recovery",
        dimension="general_agent",
        weight=8,
        paths=(
            "runtime/sensing/gateway/realtime_turn_lifecycle.py",
            "runtime/sensing/gateway/realtime_turn_routing.py",
            "runtime/core/cerebrum/react_loop.py",
            "tests/test_realtime_cerebrum.py",
            "tests/test_react_loop.py",
        ),
        required_terms=(
            "_drive_local_partner",
            "_drive_group_fanout",
            "_drive_swarm_mesh",
            "evaluate_guards",
        ),
        next_action="Keep general, browser, computer, and code turns on a single trace vocabulary.",
    ),
    AgentBenchmarkCase(
        id="clear_global_frontend_settings",
        title="Clear global settings and non-dead frontend controls",
        dimension="ux",
        weight=6,
        paths=(
            "frontend/src/components/workspace/settings/appearance-settings-page.tsx",
            "frontend/src/components/browser/liquid-glass.tsx",
            "frontend/src/app/browser/page.tsx",
            "frontend/src/components/browser/browser-home.tsx",
            "frontend/src/components/browser/url-bar.tsx",
            "frontend/src/components/workspace/settings/settings-dialog.tsx",
            "frontend/src/app/workspace/computer/page.tsx",
        ),
        required_terms=(
            "materialTheme",
            "octo-liquid-glass",
            "disabled:pointer-events-none",
            "disabledReason",
        ),
        next_action="Remove remaining decorative aurora/wallpaper presets and make glass/radius variables fully global.",
    ),
)


def compute_agent_benchmark(
    *,
    root: str | Path | None = None,
) -> dict[str, Any]:
    base = Path(root) if root is not None else default_project_root(Path(__file__))
    cases = [_case_row(base, case) for case in BENCHMARK_CASES]
    total_weight = sum(int(row["weight"]) for row in cases)
    passed_weight = sum(int(row["weight"]) for row in cases if row["passed"])
    by_dimension: dict[str, dict[str, Any]] = {}
    for row in cases:
        bucket = by_dimension.setdefault(
            str(row["dimension"]),
            {"passed": 0, "total": 0, "passed_weight": 0, "total_weight": 0},
        )
        bucket["total"] += 1
        bucket["total_weight"] += int(row["weight"])
        if row["passed"]:
            bucket["passed"] += 1
            bucket["passed_weight"] += int(row["weight"])
    for bucket in by_dimension.values():
        bucket["score"] = round(
            bucket["passed_weight"] / max(1, bucket["total_weight"]),
            3,
        )
    missing = [row for row in cases if not row["passed"]]
    return {
        "schema": "octopus.agent_benchmark.v1",
        "score": round(passed_weight / max(1, total_weight), 3),
        "passed": sum(1 for row in cases if row["passed"]),
        "total": len(cases),
        "ready": all(row["passed"] for row in cases),
        "cases": cases,
        "by_dimension": dict(sorted(by_dimension.items())),
        "next_actions": [str(row["next_action"]) for row in missing],
    }


def _case_row(base: Path, case: AgentBenchmarkCase) -> dict[str, Any]:
    path_rows = [{"path": path, "exists": (base / path).exists()} for path in case.paths]
    haystack = "\n".join(
        _read_text(base / str(row["path"])) for row in path_rows if row["exists"]
    ).lower()
    missing_paths = [str(row["path"]) for row in path_rows if not row["exists"]]
    missing_terms = [
        term for term in case.required_terms if term.lower() not in haystack
    ]
    return {
        "id": case.id,
        "title": case.title,
        "dimension": case.dimension,
        "weight": case.weight,
        "passed": not missing_paths and not missing_terms,
        "paths": path_rows,
        "required_terms": list(case.required_terms),
        "missing_paths": missing_paths,
        "missing_terms": missing_terms,
        "next_action": case.next_action,
    }


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


__all__ = [
    "AgentBenchmarkCase",
    "BENCHMARK_CASES",
    "compute_agent_benchmark",
]
