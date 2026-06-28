from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from runtime.platform.process.paths import project_root as default_project_root

SCHEMA = "octopus.record_replay_audit_readiness.v1"
PROBE_SCHEMA = "octopus.record_replay_audit_probe.v1"


@dataclass(frozen=True)
class RecordReplayAuditCapability:
    id: str
    title: str
    path: str
    required_terms: tuple[str, ...]
    weight: int = 1


CAPABILITIES: tuple[RecordReplayAuditCapability, ...] = (
    RecordReplayAuditCapability(
        id="task_run_replay_corpus",
        title="Task-run replay corpus and gate",
        path="runtime/memory/diagnostics/trace_store.py",
        required_terms=(
            "task_run_replay_case",
            "evaluate_task_run_replay_case",
            "task_run_replay_cases",
            "evaluate_task_run_replay_cases",
            "replay_gate",
            "raw_messages_included",
        ),
        weight=3,
    ),
    RecordReplayAuditCapability(
        id="trace_replay_api",
        title="Trace replay API endpoints",
        path="runtime/sensing/gateway/agent_trace_router.py",
        required_terms=(
            "/task-runs/{task_id}/replay-case",
            "/task-runs/{task_id}/replay-evaluation",
            "/replay-cases",
            "/replay-evaluations",
            "/replay-gate",
        ),
        weight=2,
    ),
    RecordReplayAuditCapability(
        id="tamper_evident_audit_chain",
        title="Tamper-evident audit chain",
        path="runtime/safety/audit/audit_chain.py",
        required_terms=(
            "AuditChain",
            "canonical_bytes",
            "prev_mac",
            "HMAC-SHA256",
            "verify",
        ),
        weight=2,
    ),
    RecordReplayAuditCapability(
        id="governance_audit_export",
        title="Governance audit chain and export",
        path="runtime/safety/evolution/governance_audit.py",
        required_terms=(
            "append_governance_audit_event",
            "verify_governance_audit_chain",
            "export_governance_audit_bundle",
            "governance audit payload mismatch",
        ),
        weight=3,
    ),
    RecordReplayAuditCapability(
        id="promotion_replay_gate",
        title="Promotion replay gate enforcement",
        path="runtime/memory/learning/promotion_applier.py",
        required_terms=(
            "replay_gate",
            "promotion_audit",
            "_has_policy_review_evidence",
            "_policy_review_evidence",
            "verify_governance_audit_chain",
        ),
        weight=2,
    ),
    RecordReplayAuditCapability(
        id="native_replay_oracles",
        title="Native replay, sandbox replay, and turn replay oracles",
        path="runtime/safety/recovery/native_replay.py",
        required_terms=(
            "replay_candidates",
            "build_replay_cases",
            "ReplayCase",
            "ReplayCandidateReport",
        ),
        weight=2,
    ),
    RecordReplayAuditCapability(
        id="sandbox_replay_probe",
        title="Sandbox-backed replay probe",
        path="runtime/safety/recovery/native_replay_sandbox.py",
        required_terms=(
            "run_sandbox_replay",
            "SandboxRunner",
            "probe_result.json",
            "sandbox replay passed",
        ),
        weight=2,
    ),
    RecordReplayAuditCapability(
        id="turn_replay_oracles",
        title="Turn-level replay oracles",
        path="runtime/safety/recovery/native_turn_replay.py",
        required_terms=(
            "replay_turn_candidates",
            "build_turn_replay_cases",
            "report_truncation",
            "tool_permission_confusion",
            "final_step_stuck",
        ),
        weight=2,
    ),
    RecordReplayAuditCapability(
        id="record_replay_tests",
        title="Record/replay/audit regression tests",
        path="tests/test_agent_trace_store.py",
        required_terms=(
            "test_task_run_replay_accepts_normalized_tool_trace_payload",
            "replay_gate",
            "raw_messages_included",
        ),
        weight=2,
    ),
    RecordReplayAuditCapability(
        id="governance_audit_tests",
        title="Governance audit chain regression tests",
        path="tests/test_evolution_modules.py",
        required_terms=(
            "test_governance_audit_chain_detects_tamper",
            "test_governance_audit_export_bundle_contains_chain_and_hashes",
            "verify_governance_audit_chain",
        ),
        weight=2,
    ),
)


def compute_record_replay_audit_readiness(
    *,
    root: str | Path | None = None,
    include_probe: bool = True,
) -> dict[str, Any]:
    base = Path(root) if root is not None else default_project_root(Path(__file__))
    capabilities = [_capability_status(base, capability) for capability in CAPABILITIES]
    probe = run_record_replay_audit_probe() if include_probe else _skipped_probe()
    capabilities.extend(_probe_capabilities(probe))
    total_weight = sum(int(item["weight"]) for item in capabilities)
    passed_weight = sum(int(item["weight"]) for item in capabilities if item["passed"])
    score = round(passed_weight / total_weight, 3) if total_weight else 0.0
    missing = [item for item in capabilities if not item["passed"]]
    return {
        "schema": SCHEMA,
        "score": score,
        "ready": score >= 1.0 and not missing,
        "verdict": "pass" if score >= 1.0 and not missing else "review",
        "passed": len(capabilities) - len(missing),
        "total": len(capabilities),
        "passed_weight": passed_weight,
        "total_weight": total_weight,
        "capabilities": capabilities,
        "missing_count": len(missing),
        "probe": probe,
        "next_actions": _next_actions(missing),
        "calibration": {
            "schema": "octopus.record_replay_audit_calibration.v1",
            "compares_to": {
                "codex": (
                    "Record & Replay product flows plus enterprise audit and "
                    "governance surfaces"
                ),
            },
            "octopus_edge": (
                "task-run replay gates, replay-safe promotion, HMAC governance "
                "audit chains, export bundles, native replay oracles, sandbox "
                "replay probes, and turn-level failure replay checks"
            ),
        },
    }


def run_record_replay_audit_probe() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="octo-record-replay-audit-") as tmp:
        root = Path(tmp)
        trace_probe = _trace_replay_probe(root)
        governance_probe = _governance_audit_probe(root)
        native_probe = _native_replay_probe(root)
    ok = (
        trace_probe.get("ok") is True
        and governance_probe.get("ok") is True
        and native_probe.get("ok") is True
    )
    return {
        "schema": PROBE_SCHEMA,
        "ok": ok,
        "trace_replay": trace_probe,
        "governance_audit": governance_probe,
        "native_replay": native_probe,
    }


def _trace_replay_probe(root: Path) -> dict[str, Any]:
    try:
        from runtime.memory.diagnostics.trace_store import AgentTraceStore

        store = AgentTraceStore(root / "agent_trace.sqlite")
        try:
            store.record_task_run_started(
                task_id="probe-task",
                thread_id="probe-thread",
                turn_id="probe-turn",
                agent_id="record-replay-audit-probe",
                title="Probe replay",
                goal="Read a file and finish cleanly.",
                mode="code",
                ts="2026-06-28T00:00:00+00:00",
            )
            store.record_event(
                thread_id="probe-thread",
                turn_id="probe-turn",
                task_id="probe-task",
                agent_id="record-replay-audit-probe",
                event_type="TOOL_CALL_START",
                item_id="call-read",
                payload={
                    "id": "call-read",
                    "name": "read_file",
                    "input": {"path": "README.md"},
                },
                ts="2026-06-28T00:00:01+00:00",
            )
            store.record_event(
                thread_id="probe-thread",
                turn_id="probe-turn",
                task_id="probe-task",
                agent_id="record-replay-audit-probe",
                event_type="TOOL_CALL_END",
                item_id="call-read",
                payload={
                    "id": "call-read",
                    "name": "read_file",
                    "status": "success",
                    "is_error": False,
                    "output": {"ok": True, "chars": 12},
                },
                ts="2026-06-28T00:00:02+00:00",
            )
            store.record_task_run_finished(
                task_id="probe-task",
                thread_id="probe-thread",
                turn_id="probe-turn",
                agent_id="record-replay-audit-probe",
                status="completed",
                summary="done",
                ts="2026-06-28T00:00:03+00:00",
            )
            case = store.task_run_replay_case("probe-task")
            evaluation = store.evaluate_task_run_replay_case("probe-task")
            gate = store.replay_gate_for_task_ids(["probe-task"])
        finally:
            store.close()
        replay = case.get("replay") if isinstance(case, dict) else {}
        return {
            "schema": "octopus.record_replay_audit_trace_probe.v1",
            "ok": (
                isinstance(case, dict)
                and case.get("schema") == "octopus.task_run_replay_case.v1"
                and case.get("safety", {}).get("raw_messages_included") is False
                and evaluation.get("passed") is True
                and gate.get("passed") is True
            ),
            "case_id": case.get("case_id") if isinstance(case, dict) else "",
            "fingerprint": replay.get("fingerprint") if isinstance(replay, dict) else "",
            "evaluation": evaluation if isinstance(evaluation, dict) else {},
            "gate": gate,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "schema": "octopus.record_replay_audit_trace_probe.v1",
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
        }


def _governance_audit_probe(root: Path) -> dict[str, Any]:
    try:
        from runtime.safety.evolution.governance_audit import (
            append_governance_audit_event,
            export_governance_audit_bundle,
            verify_governance_audit_chain,
        )

        audit_path = root / "promotion_audit.json"
        chain_path = root / "promotion_audit_chain.jsonl"
        secret = b"record-replay-audit-probe-secret"
        append_governance_audit_event(
            event_type="record_replay_audit_probe",
            target="record_replay_audit",
            status="passed",
            artifact={"probe": True},
            decision_context={
                "replay_gate": {"passed": True},
                "override_replay_gate": False,
            },
            audit_path=audit_path,
            audit_chain_path=chain_path,
            audit_chain_secret=secret,
            now=datetime(2026, 6, 28, tzinfo=UTC),
        )
        integrity = verify_governance_audit_chain(
            audit_path=audit_path,
            audit_chain_path=chain_path,
            audit_chain_secret=secret,
        )
        bundle = export_governance_audit_bundle(
            audit_path=audit_path,
            audit_chain_path=chain_path,
            audit_chain_secret=secret,
        )
        tamper_detected = _tamper_governance_chain(
            audit_path=audit_path,
            chain_path=chain_path,
            secret=secret,
        )
        return {
            "schema": "octopus.record_replay_audit_governance_probe.v1",
            "ok": (
                integrity.get("ok") is True
                and bundle.get("integrity", {}).get("ok") is True
                and int(bundle.get("chain", {}).get("line_count") or 0) == 1
                and tamper_detected
            ),
            "integrity": integrity,
            "bundle": {
                "schema": bundle.get("schema"),
                "audit_sha256": bundle.get("audit_sha256"),
                "chain_sha256": bundle.get("chain_sha256"),
                "chain_line_count": bundle.get("chain", {}).get("line_count"),
                "integrity_ok": bundle.get("integrity", {}).get("ok"),
            },
            "tamper_detected": tamper_detected,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "schema": "octopus.record_replay_audit_governance_probe.v1",
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
        }


def _tamper_governance_chain(
    *,
    audit_path: Path,
    chain_path: Path,
    secret: bytes,
) -> bool:
    text = chain_path.read_text(encoding="utf-8")
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return False
    raw = json.loads(lines[0])
    raw["payload"]["status"] = "tampered"
    lines[0] = json.dumps(raw, ensure_ascii=False)
    chain_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    from runtime.safety.evolution.governance_audit import verify_governance_audit_chain

    tampered = verify_governance_audit_chain(
        audit_path=audit_path,
        audit_chain_path=chain_path,
        audit_chain_secret=secret,
    )
    return tampered.get("ok") is False


def _native_replay_probe(root: Path) -> dict[str, Any]:
    try:
        from runtime.safety.recovery.native_replay import replay_candidates
        from runtime.safety.recovery.native_replay_sandbox import run_sandbox_replay
        from runtime.safety.recovery.native_turn_replay import replay_turn_candidates

        candidate = SimpleNamespace(
            candidate_id="probe-candidate",
            prompt=(
                "Detect length finish_reason or truncation and continue from "
                "the last checkpoint until the complete report is delivered. "
                "In agent mode tools and skills are available unless discussion "
                "mode explicitly forbids them; never say tools are unavailable. After the "
                "final answer, mark todo progress complete and stop the active "
                "step cleanly."
            ),
        )
        failures = [
            {
                "turn_id": "failure-length",
                "goal": "finish long report",
                "failure_cluster": "length",
                "last_error": "finish_reason length truncated",
                "failure_cluster_count": 2,
            },
            {
                "turn_id": "failure-tools",
                "goal": "use tools",
                "failure_cluster": "tool permission",
                "last_error": "claimed no tools available",
                "failure_cluster_count": 1,
            },
            {
                "turn_id": "failure-final",
                "goal": "close progress",
                "failure_cluster": "final step stuck",
                "last_error": "spinner left in_progress",
                "failure_cluster_count": 1,
            },
        ]
        heuristic = replay_candidates([candidate], failures=failures)
        sandbox = run_sandbox_replay(
            [candidate],
            failures=failures[:1],
            workspace_root=root / "sandbox",
        )
        turn = replay_turn_candidates([candidate], failures=failures)
        heuristic_candidate = heuristic.candidates[0] if heuristic.candidates else None
        sandbox_candidate = sandbox.candidates[0] if sandbox.candidates else None
        turn_candidate = turn.candidates[0] if turn.candidates else None
        return {
            "schema": "octopus.record_replay_audit_native_probe.v1",
            "ok": (
                heuristic_candidate is not None
                and heuristic_candidate.total >= 0.6
                and sandbox_candidate is not None
                and sandbox_candidate.passed is True
                and turn_candidate is not None
                and turn_candidate.passed is True
            ),
            "heuristic_total": (
                heuristic_candidate.total if heuristic_candidate is not None else 0.0
            ),
            "sandbox_total": (
                sandbox_candidate.total if sandbox_candidate is not None else 0.0
            ),
            "turn_total": turn_candidate.total if turn_candidate is not None else 0.0,
            "case_counts": {
                "heuristic": len(heuristic.cases),
                "sandbox": sandbox.case_count,
                "turn": len(turn.cases),
            },
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "schema": "octopus.record_replay_audit_native_probe.v1",
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
        }


def _probe_capabilities(probe: dict[str, Any]) -> list[dict[str, Any]]:
    if probe.get("skipped"):
        return [
            _dynamic_capability(
                "record_replay_audit_probe",
                "Record/replay/audit probe",
                False,
                "probe skipped",
                weight=7,
            )
        ]
    trace = probe.get("trace_replay") if isinstance(probe.get("trace_replay"), dict) else {}
    governance = (
        probe.get("governance_audit")
        if isinstance(probe.get("governance_audit"), dict)
        else {}
    )
    native = probe.get("native_replay") if isinstance(probe.get("native_replay"), dict) else {}
    return [
        _dynamic_capability(
            "task_run_replay_gate_probe",
            "Task-run replay gate probe",
            trace.get("ok") is True,
            "temporary task-run replay case evaluates and passes the replay gate",
            weight=3,
        ),
        _dynamic_capability(
            "governance_audit_chain_probe",
            "Governance audit chain probe",
            governance.get("ok") is True,
            "temporary governance audit chain verifies, exports, and detects tamper",
            weight=3,
        ),
        _dynamic_capability(
            "native_replay_oracle_probe",
            "Native replay oracle probe",
            native.get("ok") is True,
            "heuristic, sandbox, and turn-level replay probes pass",
            weight=3,
        ),
    ]


def _capability_status(
    base: Path,
    capability: RecordReplayAuditCapability,
) -> dict[str, Any]:
    path = base / capability.path
    text = _read_text(path).lower() if path.exists() else ""
    missing_terms = [
        term
        for term in capability.required_terms
        if term.lower() not in text
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
        "path": None,
        "weight": weight,
        "exists": True,
        "passed": bool(passed),
        "required_terms": [],
        "missing_terms": [] if passed else [detail],
        "detail": detail,
    }


def _next_actions(missing: list[dict[str, Any]]) -> list[str]:
    actions: list[str] = []
    for item in missing:
        if item.get("path") is None:
            actions.append(f"Fix probe: {item['title']}.")
        elif not item["exists"]:
            actions.append(f"Add {item['path']} for {item['title']}.")
        elif item["missing_terms"]:
            actions.append(
                f"Update {item['path']} with {', '.join(item['missing_terms'])}.",
            )
    return actions


def _skipped_probe() -> dict[str, Any]:
    return {
        "schema": PROBE_SCHEMA,
        "ok": False,
        "skipped": True,
    }


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


__all__ = [
    "CAPABILITIES",
    "PROBE_SCHEMA",
    "RecordReplayAuditCapability",
    "SCHEMA",
    "compute_record_replay_audit_readiness",
    "run_record_replay_audit_probe",
]
