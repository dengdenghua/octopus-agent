from __future__ import annotations

import concurrent.futures as _cf
import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from runtime.memory.control_sessions import ControlSessionStore
from runtime.platform.process.paths import app_paths
from runtime.sensing.model_router.models import Message, ModelRequest

_SCHEMA = "octopus.kimi_swarm_load_test.v1"
_STEP_SCHEMA = "octopus.kimi_swarm_load_step.v1"
_SUMMARY_EVIDENCE_SCHEMA = "octopus.kimi_swarm_load_test_summary.v1"
_PREFLIGHT_SCHEMA = "octopus.kimi_swarm_load_test_preflight.v1"
_STAGE_PLAN_SCHEMA = "octopus.kimi_swarm_load_stage_plan.v1"
_PROOF_BUNDLE_SCHEMA = "octopus.kimi_swarm_proof_bundle.v1"
_NEXT_STAGE_SCHEMA = "octopus.kimi_swarm_next_stage.v1"
_RESUME_PLAN_SCHEMA = "octopus.kimi_swarm_resume_plan.v1"
_COMPOSITE_PROOF_SCHEMA = "octopus.kimi_swarm_composite_proof.v1"
_QUOTA_PROBE_SCHEMA = "octopus.kimi_swarm_quota_probe.v1"
_DEFAULT_AGENT_COUNT = 300
_DEFAULT_STEP_COUNT = 4000
_DEFAULT_MAX_CONCURRENCY = 32
_DEFAULT_REFERENCE_PROVIDER_ID = "kimi_coding"
_DEFAULT_REFERENCE_MODEL = "kimi-for-coding"
_DEFAULT_PROVIDER_OUTPUT_TOKENS_PER_STEP = 512
_DEFAULT_RESUME_CHUNK_STEP_COUNT = 64
_DEFAULT_RESUME_CHUNK_CONCURRENCY = 2
_PROVIDER_STEP_ATTEMPTS = 3

ProviderCaller = Callable[[ModelRequest], Any]


@dataclass(frozen=True)
class KimiSwarmLoadTestConfig:
    session_id: str = "kimi-swarm-load-test"
    provider_id: str = "dry_run"
    model: str = "dry-run-swarm"
    agent_count: int = _DEFAULT_AGENT_COUNT
    step_count: int = _DEFAULT_STEP_COUNT
    max_concurrency: int = _DEFAULT_MAX_CONCURRENCY
    real_provider: bool = False
    confirm_real_provider: bool = False
    record_every_step: bool = True
    max_provider_calls: int = 0
    estimated_max_tokens: int = 0
    stage_id: str = "auto"
    resume_from_session_id: str = ""
    resume_step_ranges: tuple[dict[str, int], ...] = ()


@dataclass(frozen=True)
class KimiSwarmQuotaProbeConfig:
    session_id: str = "kimi-swarm-quota-probe"
    provider_id: str = _DEFAULT_REFERENCE_PROVIDER_ID
    model: str = _DEFAULT_REFERENCE_MODEL
    confirm_real_provider: bool = False
    max_tokens: int = 16


def build_kimi_swarm_load_test_preflight(
    *,
    config: KimiSwarmLoadTestConfig | None = None,
    provider_configured: bool | None = None,
    store: ControlSessionStore | None = None,
    data_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Return a no-side-effect readiness report for a Kimi-scale load test."""
    cfg = config or KimiSwarmLoadTestConfig()
    agent_count, step_count, max_concurrency = _normalize_counts(cfg)
    provider_needed = bool(cfg.real_provider)
    configured = (not provider_needed) if provider_configured is None else bool(provider_configured)
    selected_stage = _resolve_stage(
        config=cfg,
        requested_agent_count=agent_count,
        requested_step_count=step_count,
        requested_max_concurrency=max_concurrency,
    )
    selected_step_count = int(selected_stage["step_count"])
    if selected_stage.get("id") == "provider_full_reference_resume":
        selected_step_count = len(
            _indices_from_ranges(
                list(cfg.resume_step_ranges),
                upper_bound=step_count,
            )
        )
        if selected_step_count <= 0 and cfg.resume_from_session_id:
            selected_step_count = 1
    previous_stage = _previous_stage_id(str(selected_stage["id"]))
    previous_stage_ready = True
    previous_stage_proof: dict[str, Any] | None = None
    if provider_needed and previous_stage:
        previous_stage_proof = latest_successful_stage_proof(
            provider_id=cfg.provider_id,
            model=cfg.model,
            requested_agent_count=agent_count,
            requested_step_count=step_count,
            stage_id=previous_stage,
            store=store,
            data_dir=data_dir,
        )
        previous_stage_ready = previous_stage_proof is not None
    checks = [
        {
            "id": "agent_count_positive",
            "title": "Agent count is positive",
            "passed": agent_count >= 1,
            "value": agent_count,
            "blocking": True,
        },
        {
            "id": "step_count_positive",
            "title": "Step count is positive",
            "passed": step_count >= 1,
            "value": step_count,
            "blocking": True,
        },
        {
            "id": "bounded_concurrency",
            "title": "Concurrency is bounded for provider safety",
            "passed": max_concurrency <= (64 if provider_needed else step_count),
            "value": max_concurrency,
            "limit": 64 if provider_needed else step_count,
            "blocking": True,
        },
        {
            "id": "real_provider_confirmed",
            "title": "Real provider run is explicitly confirmed",
            "passed": (not provider_needed) or bool(cfg.confirm_real_provider),
            "value": bool(cfg.confirm_real_provider),
            "blocking": provider_needed,
        },
        {
            "id": "provider_configured",
            "title": "A custom model router is configured",
            "passed": (not provider_needed) or configured,
            "value": configured,
            "blocking": provider_needed,
        },
        {
            "id": "provider_call_budget",
            "title": "Provider call budget covers every step",
            "passed": (not provider_needed)
            or int(cfg.max_provider_calls or 0) >= selected_step_count,
            "value": int(cfg.max_provider_calls or 0),
            "required": selected_step_count,
            "blocking": provider_needed,
        },
        {
            "id": "token_budget",
            "title": "Token budget is explicitly declared",
            "passed": (not provider_needed)
            or int(cfg.estimated_max_tokens or 0) >= selected_step_count,
            "value": int(cfg.estimated_max_tokens or 0),
            "required": selected_step_count,
            "blocking": provider_needed,
        },
        {
            "id": "kimi_reference_size",
            "title": "Requested run reaches Kimi reference scale",
            "passed": agent_count >= 300 and step_count >= 4000,
            "value": {"agent_count": agent_count, "step_count": step_count},
            "required": {"agent_count": 300, "step_count": 4000},
            "blocking": False,
        },
        {
            "id": "previous_stage_ready",
            "title": "Previous provider stage succeeded",
            "passed": previous_stage_ready,
            "value": previous_stage,
            "blocking": provider_needed and bool(previous_stage),
        },
    ]
    blocking_failures = [
        check for check in checks if check["blocking"] and not bool(check["passed"])
    ]
    stage_plan = _stage_plan(
        agent_count=agent_count,
        step_count=step_count,
        max_concurrency=max_concurrency,
        real_provider=provider_needed,
    )
    return {
        "schema": _PREFLIGHT_SCHEMA,
        "ready": not blocking_failures,
        "provider_ready": (not provider_needed) or (
            bool(cfg.confirm_real_provider)
            and configured
            and int(cfg.max_provider_calls or 0) >= selected_step_count
            and int(cfg.estimated_max_tokens or 0) >= selected_step_count
            and max_concurrency <= 64
            and previous_stage_ready
        ),
        "reference_ready": agent_count >= 300 and step_count >= 4000,
        "mode": "real_provider" if provider_needed else "dry_run",
        "model": cfg.model,
        "provider_id": cfg.provider_id,
        "agent_count": agent_count,
        "step_count": step_count,
        "max_concurrency": max_concurrency,
        "max_provider_calls": int(cfg.max_provider_calls or 0),
        "estimated_max_tokens": int(cfg.estimated_max_tokens or 0),
        "selected_stage": selected_stage,
        "previous_stage": previous_stage,
        "previous_stage_ready": previous_stage_ready,
        "previous_stage_proof": previous_stage_proof,
        "checks": checks,
        "blocking_failures": blocking_failures,
        "stage_plan": stage_plan,
        "next_action": (
            "Run the load test."
            if not blocking_failures
            else "Resolve blocking preflight checks before running the load test."
        ),
    }


def run_kimi_swarm_quota_probe(
    *,
    config: KimiSwarmQuotaProbeConfig | None = None,
    store: ControlSessionStore | None = None,
    provider_caller: ProviderCaller | None = None,
) -> dict[str, Any]:
    cfg = config or KimiSwarmQuotaProbeConfig()
    if not cfg.confirm_real_provider:
        raise ValueError("confirm_real_provider=True is required for quota probes")
    if provider_caller is None:
        raise ValueError("quota probe requires provider_caller")
    control_store = store or ControlSessionStore(app_paths().data_dir / "control_sessions")
    session = control_store.upsert_session(
        session_id=cfg.session_id,
        owner_id="kimi_swarm_quota_probe",
        owner_label="Kimi Swarm Quota Probe",
        surface="backend_preview",
        target_id="agent-collaboration",
        status="running",
        metadata={
            "schema": _QUOTA_PROBE_SCHEMA,
            "provider_id": cfg.provider_id,
            "model": cfg.model,
            "confirm_real_provider": True,
            "max_tokens": max(1, int(cfg.max_tokens)),
        },
    )
    action = control_store.append_action(
        cfg.session_id,
        action_id=f"{cfg.session_id}:probe",
        action_type="kimi_swarm_quota_probe",
        status="running",
        descriptor={
            "schema": _QUOTA_PROBE_SCHEMA,
            "provider_id": cfg.provider_id,
            "model": cfg.model,
            "max_tokens": max(1, int(cfg.max_tokens)),
        },
    )
    started = time.perf_counter()
    ok = False
    error = ""
    input_tokens = 0
    output_tokens = 0
    output_preview = ""
    try:
        response = provider_caller(
            ModelRequest(
                model=cfg.model,
                system_provider=cfg.provider_id,
                max_tokens=max(1, int(cfg.max_tokens)),
                messages=[
                    Message(
                        role="user",
                        content="Quota probe. Reply with compact JSON: {\"ok\":true}.",
                    )
                ],
            )
        )
        ok = True
        output_preview = str(getattr(response, "text", "") or "")[:240]
        input_tokens = int(getattr(response, "input_tokens", 0) or 0)
        output_tokens = int(getattr(response, "output_tokens", 0) or 0)
    except Exception as exc:  # noqa: BLE001 - probe reports provider errors
        error = f"{type(exc).__name__}: {exc}"
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    category = "" if ok else _failure_category(error)
    result = {
        "schema": _QUOTA_PROBE_SCHEMA,
        "session_id": cfg.session_id,
        "provider_id": cfg.provider_id,
        "model": cfg.model,
        "ok": ok,
        "can_resume_provider_load_test": ok,
        "provider_quota_limited": category == "provider_quota_limit",
        "provider_rate_limited": category == "provider_rate_limit",
        "failure_category": category,
        "error": error,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "output_preview": output_preview,
        "elapsed_ms": elapsed_ms,
        "control_session_replay": {
            "session_id": cfg.session_id,
            "action_id": action["action_id"],
            "surface": session["surface"],
        },
    }
    control_store.append_evidence(
        cfg.session_id,
        action_id=str(action["action_id"]),
        evidence_id=f"{cfg.session_id}:result",
        kind="result",
        action="kimi_swarm_quota_probe",
        ok=ok,
        summary=(
            "Kimi quota probe succeeded"
            if ok
            else f"Kimi quota probe failed: {category or 'provider_error'}"
        ),
        detail=result,
    )
    control_store.update_action(
        cfg.session_id,
        str(action["action_id"]),
        status="done" if ok else "failed",
        result=result,
        error=error,
    )
    control_store.set_session_state(
        cfg.session_id,
        status="idle" if ok else "paused",
        metadata={"last_kimi_swarm_quota_probe": result},
    )
    return result


def run_kimi_swarm_load_test(
    *,
    config: KimiSwarmLoadTestConfig | None = None,
    store: ControlSessionStore | None = None,
    provider_caller: ProviderCaller | None = None,
) -> dict[str, Any]:
    """Run a Kimi Swarm reference load test and persist replay evidence.

    The default mode is intentionally a dry-run: it proves the 300-agent /
    4000-step control-session replay, metrics, pagination, and export path
    without spending model tokens. Passing ``real_provider=True`` requires an
    explicit ``provider_caller`` and records every provider call result with the
    same replay schema.
    """
    cfg = config or KimiSwarmLoadTestConfig()
    requested_agent_count, requested_step_count, requested_max_concurrency = (
        _normalize_counts(cfg)
    )
    stage = _resolve_stage(
        config=cfg,
        requested_agent_count=requested_agent_count,
        requested_step_count=requested_step_count,
        requested_max_concurrency=requested_max_concurrency,
    )
    agent_count = int(stage["agent_count"])
    step_count = int(stage["step_count"])
    max_concurrency = int(stage["max_concurrency"])
    control_store = store or ControlSessionStore(app_paths().data_dir / "control_sessions")
    execution_indices = list(range(step_count))
    if str(stage.get("id") or "") == "provider_full_reference_resume":
        execution_indices = _resume_execution_indices(
            cfg,
            control_store=control_store,
            requested_step_count=requested_step_count,
        )
        step_count = len(execution_indices)
        if step_count <= 0:
            raise ValueError("provider_full_reference_resume has no remaining steps")
    if cfg.real_provider and provider_caller is None:
        raise ValueError("real_provider=True requires provider_caller")
    if cfg.real_provider:
        if not cfg.confirm_real_provider:
            raise ValueError("confirm_real_provider=True is required for real_provider runs")
        max_provider_calls = int(cfg.max_provider_calls or 0)
        estimated_max_tokens = int(cfg.estimated_max_tokens or 0)
        if max_provider_calls < step_count:
            raise ValueError(
                "max_provider_calls must be >= executed stage step_count for real_provider runs"
            )
        if estimated_max_tokens <= 0:
            raise ValueError("estimated_max_tokens is required for real_provider runs")
        if estimated_max_tokens < step_count:
            raise ValueError("estimated_max_tokens must cover every provider call in the stage")
    session = control_store.upsert_session(
        session_id=cfg.session_id,
        owner_id="kimi_swarm_load_test",
        owner_label="Kimi Swarm Load Test",
        surface="backend_preview",
        target_id="agent-collaboration",
        status="running",
        metadata={
            "schema": _SCHEMA,
            "provider_id": cfg.provider_id,
            "model": cfg.model,
            "stage_id": stage["id"],
            "stage_title": stage["title"],
            "agent_count": agent_count,
            "step_count": step_count,
            "reference_step_count": requested_step_count,
            "max_concurrency": max_concurrency,
            "requested_agent_count": requested_agent_count,
            "requested_step_count": requested_step_count,
            "requested_max_concurrency": requested_max_concurrency,
            "resume_from_session_id": cfg.resume_from_session_id,
            "resume_step_ranges": list(cfg.resume_step_ranges),
            "real_provider": bool(cfg.real_provider),
            "confirm_real_provider": bool(cfg.confirm_real_provider),
            "record_every_step": bool(cfg.record_every_step),
            "max_provider_calls": int(cfg.max_provider_calls or 0),
            "estimated_max_tokens": int(cfg.estimated_max_tokens or 0),
            "reference": {
                "kimi_subagents": 300,
                "kimi_tool_calls": 4000,
            },
        },
    )
    action = control_store.append_action(
        cfg.session_id,
        action_id=f"{cfg.session_id}:load-test",
        action_type="kimi_swarm_load_test",
        status="running",
        descriptor={
            "schema": _SCHEMA,
            "stage": stage,
            "agent_count": agent_count,
            "step_count": step_count,
            "reference_step_count": requested_step_count,
            "max_concurrency": max_concurrency,
            "requested_agent_count": requested_agent_count,
            "requested_step_count": requested_step_count,
            "requested_max_concurrency": requested_max_concurrency,
            "resume_from_session_id": cfg.resume_from_session_id,
            "resume_step_ranges": list(cfg.resume_step_ranges),
            "provider_id": cfg.provider_id,
            "model": cfg.model,
            "real_provider": bool(cfg.real_provider),
            "confirm_real_provider": bool(cfg.confirm_real_provider),
            "max_provider_calls": int(cfg.max_provider_calls or 0),
            "estimated_max_tokens": int(cfg.estimated_max_tokens or 0),
        },
    )
    started = time.perf_counter()
    step_records: list[dict[str, Any]] = []
    failures = 0
    total_input_tokens = 0
    total_output_tokens = 0
    per_step_output_budget = (
        max(1, int(cfg.estimated_max_tokens or 0) // max(1, step_count))
        if cfg.real_provider
        else None
    )
    control_store.append_evidence(
        cfg.session_id,
        action_id=str(action["action_id"]),
        evidence_id=f"{cfg.session_id}:stage:{stage['id']}",
        kind="log",
        action="kimi_swarm_load_stage_start",
        ok=True,
        summary=(
            f"{stage['title']}: {agent_count} agents / {step_count} steps / "
            f"concurrency {max_concurrency}"
        ),
        detail={
            "schema": "octopus.kimi_swarm_load_stage.v1",
            "stage": stage,
            "requested": {
                "agent_count": requested_agent_count,
                "step_count": requested_step_count,
                "max_concurrency": requested_max_concurrency,
            },
        },
    )

    def _run_step(index: int) -> dict[str, Any]:
        agent_index = index % agent_count
        agent_id = f"agent-{agent_index:03d}"
        step_id = f"step-{index:04d}"
        prompt = (
            "Kimi Swarm load-test step. Reply with one compact JSON-like status. "
            f"agent={agent_id} step={index}"
        )
        step_started = time.perf_counter()
        ok = True
        text = "dry-run-ok"
        error = ""
        input_tokens = 0
        output_tokens = 0
        attempts: list[dict[str, Any]] = []
        if cfg.real_provider:
            for attempt in range(1, _PROVIDER_STEP_ATTEMPTS + 1):
                try:
                    response = provider_caller(  # type: ignore[misc]
                        ModelRequest(
                            model=cfg.model,
                            system_provider=cfg.provider_id,
                            max_tokens=per_step_output_budget,
                            messages=[Message(role="user", content=prompt)],
                        )
                    )
                    text = str(getattr(response, "text", "") or "")
                    input_tokens = int(getattr(response, "input_tokens", 0) or 0)
                    output_tokens = int(getattr(response, "output_tokens", 0) or 0)
                    attempts.append(
                        {
                            "attempt": attempt,
                            "ok": True,
                            "input_tokens": input_tokens,
                            "output_tokens": output_tokens,
                        }
                    )
                    if (
                        per_step_output_budget is not None
                        and output_tokens > per_step_output_budget
                    ):
                        ok = False
                        error = (
                            "provider exceeded per-step output budget: "
                            f"{output_tokens}>{per_step_output_budget}"
                        )
                    else:
                        ok = True
                        error = ""
                    break
                except Exception as exc:  # noqa: BLE001 - load tests record isolated failures
                    ok = False
                    error = f"{type(exc).__name__}: {exc}"
                    attempts.append(
                        {
                            "attempt": attempt,
                            "ok": False,
                            "error": error,
                            "retryable": _is_retryable_provider_error(error),
                        }
                    )
                    if attempt >= _PROVIDER_STEP_ATTEMPTS or not _is_retryable_provider_error(
                        error,
                    ):
                        break
                    time.sleep(min(2.0, 0.25 * attempt))
        else:
            input_tokens = max(1, len(prompt) // 4)
            output_tokens = 3
        elapsed_ms = int((time.perf_counter() - step_started) * 1000)
        return {
            "schema": _STEP_SCHEMA,
            "step_id": step_id,
            "step_index": index,
            "agent_id": agent_id,
            "ok": ok,
            "error": error,
            "output_preview": text[:240],
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "max_tokens": per_step_output_budget,
            "attempt_count": len(attempts) if cfg.real_provider else 1,
            "attempts": attempts,
            "elapsed_ms": elapsed_ms,
            "real_provider": bool(cfg.real_provider),
        }

    with _cf.ThreadPoolExecutor(
        max_workers=max_concurrency,
        thread_name_prefix="kimi-swarm-load",
    ) as pool:
        futures = [pool.submit(_run_step, index) for index in execution_indices]
        for future in _cf.as_completed(futures):
            record = future.result()
            step_records.append(record)
            if not bool(record["ok"]):
                failures += 1
            total_input_tokens += int(record["input_tokens"])
            total_output_tokens += int(record["output_tokens"])

    step_records.sort(key=lambda row: int(row["step_index"]))
    recorded_step_evidence_count = 0
    if cfg.record_every_step:
        for record in step_records:
            control_store.append_evidence(
                cfg.session_id,
                action_id=str(action["action_id"]),
                evidence_id=f"{cfg.session_id}:{record['step_id']}",
                kind="log",
                action="kimi_swarm_load_step",
                ok=bool(record["ok"]),
                summary=(
                    f"{record['agent_id']} {record['step_id']} "
                    f"{'ok' if record['ok'] else 'failed'}"
                ),
                detail=record,
            )
            recorded_step_evidence_count += 1

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    success_count = step_count - failures
    failure_summary = _failure_summary_from_step_records(step_records)
    summary = {
        "schema": _SCHEMA,
        "session_id": cfg.session_id,
        "provider_id": cfg.provider_id,
        "model": cfg.model,
        "stage_id": stage["id"],
        "stage_title": stage["title"],
        "stage_plan": _stage_plan(
            agent_count=requested_agent_count,
            step_count=requested_step_count,
            max_concurrency=requested_max_concurrency,
            real_provider=bool(cfg.real_provider),
        ),
        "real_provider": bool(cfg.real_provider),
        "confirm_real_provider": bool(cfg.confirm_real_provider),
        "max_provider_calls": int(cfg.max_provider_calls or 0),
        "estimated_max_tokens": int(cfg.estimated_max_tokens or 0),
        "agent_count": agent_count,
        "step_count": step_count,
        "reference_step_count": requested_step_count,
        "max_concurrency": max_concurrency,
        "requested_agent_count": requested_agent_count,
        "requested_step_count": requested_step_count,
        "requested_max_concurrency": requested_max_concurrency,
        "resume_from_session_id": cfg.resume_from_session_id,
        "resume_step_ranges": list(cfg.resume_step_ranges),
        "record_every_step": bool(cfg.record_every_step),
        "recorded_step_evidence_count": recorded_step_evidence_count,
        "successful_steps": success_count,
        "failed_steps": failures,
        "failure_rate": round(failures / max(1, step_count), 6),
        "failure_summary": failure_summary,
        "total_input_tokens": total_input_tokens,
        "total_output_tokens": total_output_tokens,
        "per_step_output_budget": per_step_output_budget,
        "elapsed_ms": elapsed_ms,
        "meets_kimi_reference": (
            stage["id"] == "provider_full_reference"
            and agent_count >= 300
            and step_count >= 4000
        )
        or (
            not cfg.real_provider
            and agent_count >= 300
            and step_count >= 4000
        ),
        "provider_backed": bool(cfg.real_provider),
        "control_session_replay": {
            "session_id": cfg.session_id,
            "action_id": action["action_id"],
            "surface": session["surface"],
        },
    }
    control_store.append_evidence(
        cfg.session_id,
        action_id=str(action["action_id"]),
        evidence_id=f"{cfg.session_id}:summary",
        kind="result",
        action="kimi_swarm_load_test_summary",
        ok=failures == 0,
        summary=(
            f"Kimi swarm load test: {success_count}/{step_count} steps across "
            f"{agent_count} agents"
        ),
        detail={**summary, "schema": _SUMMARY_EVIDENCE_SCHEMA},
    )
    control_store.update_action(
        cfg.session_id,
        str(action["action_id"]),
        status="done" if failures == 0 else "failed",
        result=summary,
        error="" if failures == 0 else f"{failures} step(s) failed",
    )
    control_store.set_session_state(
        cfg.session_id,
        status="idle" if failures == 0 else "paused",
        metadata={
            "last_kimi_swarm_load_test": summary,
        },
    )
    return summary


def latest_kimi_swarm_load_test(
    *,
    store: ControlSessionStore | None = None,
    data_dir: str | Path | None = None,
) -> dict[str, Any] | None:
    history = kimi_swarm_load_test_history(store=store, data_dir=data_dir)
    return history[0] if history else None


def kimi_swarm_load_test_history(
    *,
    store: ControlSessionStore | None = None,
    data_dir: str | Path | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    control_store = store or ControlSessionStore(
        (Path(data_dir) / "control_sessions") if data_dir is not None else None
    )
    sessions = control_store.list_sessions(surface="backend_preview", limit=limit)
    candidates = [
        session
        for session in sessions
        if isinstance(session.get("metadata"), dict)
        and (session["metadata"].get("schema") == _SCHEMA)
    ]
    summaries: list[dict[str, Any]] = []
    for session in candidates:
        summary = _summary_for_session(control_store, session)
        if summary is not None:
            summaries.append(summary)
    return sorted(
        summaries,
        key=lambda row: float((row.get("session") or {}).get("updated_at") or 0.0),
        reverse=True,
    )


def best_kimi_swarm_load_test_proof(
    *,
    store: ControlSessionStore | None = None,
    data_dir: str | Path | None = None,
) -> dict[str, Any] | None:
    control_store = store or ControlSessionStore(
        (Path(data_dir) / "control_sessions") if data_dir is not None else None
    )
    history = kimi_swarm_load_test_history(store=control_store)
    eligible = [
        row
        for row in history
        if _real_provider_stage_proof_eligible(row)
        and str(row.get("stage_id") or "") == "provider_full_reference"
        and int(row.get("agent_count") or 0) >= 300
        and int(row.get("step_count") or 0) >= 4000
        and int(row.get("successful_steps") or 0) >= 4000
        and int(row.get("actual_recorded_step_evidence_count") or 0)
        >= int(row.get("step_count") or 0)
        and bool(row.get("replay_evidence_verified"))
        and int(row.get("failed_steps") or 0) == 0
        and bool(row.get("meets_kimi_reference"))
    ]
    composite = _best_composite_full_reference_proof(
        history=history,
        control_store=control_store,
    )
    candidates = eligible + ([composite] if composite is not None else [])
    if not candidates:
        return None
    return max(candidates, key=_proof_rank)


def latest_successful_stage_proof(
    *,
    provider_id: str,
    model: str,
    requested_agent_count: int,
    requested_step_count: int,
    stage_id: str,
    store: ControlSessionStore | None = None,
    data_dir: str | Path | None = None,
) -> dict[str, Any] | None:
    history = kimi_swarm_load_test_history(store=store, data_dir=data_dir)
    matches = [
        row
        for row in history
        if _real_provider_stage_proof_eligible(row)
        and str(row.get("provider_id") or "") == str(provider_id or "")
        and str(row.get("model") or "") == str(model or "")
        and str(row.get("stage_id") or "") == str(stage_id or "")
        and int(row.get("requested_agent_count") or 0) == int(requested_agent_count)
        and int(row.get("requested_step_count") or 0) == int(requested_step_count)
        and int(row.get("failed_steps") or 0) == 0
        and int(row.get("successful_steps") or 0) == int(row.get("step_count") or 0)
        and int(row.get("actual_recorded_step_evidence_count") or 0)
        >= int(row.get("step_count") or 0)
        and bool(row.get("replay_evidence_verified"))
    ]
    if not matches:
        return None
    return max(matches, key=lambda row: float((row.get("session") or {}).get("updated_at") or 0.0))


def _best_composite_full_reference_proof(
    *,
    history: list[dict[str, Any]],
    control_store: ControlSessionStore,
) -> dict[str, Any] | None:
    candidates: list[dict[str, Any]] = []
    for source in history:
        if (
            not _real_provider_stage_proof_eligible(source)
            or str(source.get("stage_id") or "") != "provider_full_reference"
            or int(source.get("agent_count") or 0) < 300
            or int(source.get("step_count") or 0) < 4000
            or not bool(source.get("meets_kimi_reference"))
        ):
            continue
        composite = _composite_proof_for_source(
            source,
            history=history,
            control_store=control_store,
        )
        if composite is not None:
            candidates.append(composite)
    if not candidates:
        return None
    return max(candidates, key=_proof_rank)


def _composite_proof_for_source(
    source: dict[str, Any],
    *,
    history: list[dict[str, Any]],
    control_store: ControlSessionStore,
) -> dict[str, Any] | None:
    source_session_id = str(source.get("session_id") or "")
    requested_step_count = int(source.get("requested_step_count") or source.get("step_count") or 0)
    if not source_session_id or requested_step_count <= 0:
        return None
    session_ids = [source_session_id]
    resume_rows = _resume_rows_for_source(history=history, source=source)
    session_ids.extend(str(row.get("session_id") or "") for row in resume_rows)
    success_by_step, failed_by_step, total_step_evidence = _step_coverage_for_sessions(
        control_store,
        session_ids,
        requested_step_count=requested_step_count,
    )
    missing = sorted(set(range(requested_step_count)) - set(success_by_step))
    if missing:
        return None
    resume_session_ids = [
        str(row.get("session_id") or "")
        for row in resume_rows
        if str(row.get("session_id") or "")
    ]
    updated_at = max(
        [float((source.get("session") or {}).get("updated_at") or 0.0)]
        + [float((row.get("session") or {}).get("updated_at") or 0.0) for row in resume_rows],
    )
    return {
        "schema": _COMPOSITE_PROOF_SCHEMA,
        "composite": True,
        "provider_backed": True,
        "provider_id": source.get("provider_id"),
        "model": source.get("model"),
        "session_id": source_session_id,
        "source_session_id": source_session_id,
        "resume_session_ids": resume_session_ids,
        "source_session_ids": [source_session_id, *resume_session_ids],
        "stage_id": "provider_full_reference",
        "agent_count": int(source.get("agent_count") or 0),
        "step_count": requested_step_count,
        "requested_agent_count": int(source.get("requested_agent_count") or 0),
        "requested_step_count": requested_step_count,
        "successful_steps": requested_step_count,
        "failed_steps": 0,
        "actual_recorded_step_evidence_count": len(success_by_step),
        "raw_recorded_step_evidence_count": total_step_evidence,
        "replay_evidence_verified": True,
        "meets_kimi_reference": (
            int(source.get("agent_count") or 0) >= 300 and requested_step_count >= 4000
        ),
        "total_input_tokens": sum(int(row.get("total_input_tokens") or 0) for row in [source, *resume_rows]),
        "total_output_tokens": sum(int(row.get("total_output_tokens") or 0) for row in [source, *resume_rows]),
        "estimated_max_tokens": sum(int(row.get("estimated_max_tokens") or 0) for row in [source, *resume_rows]),
        "updated_at": updated_at,
        "coverage": {
            "schema": "octopus.kimi_swarm_composite_coverage.v1",
            "covered_step_count": len(success_by_step),
            "missing_step_count": 0,
            "source_successful_steps": int(source.get("successful_steps") or 0),
            "resume_successful_steps": sum(int(row.get("successful_steps") or 0) for row in resume_rows),
            "resume_failed_step_count": len(failed_by_step),
        },
    }


def _resume_rows_for_source(
    *,
    history: list[dict[str, Any]],
    source: dict[str, Any],
) -> list[dict[str, Any]]:
    source_session_id = str(source.get("session_id") or "")
    rows = [
        row
        for row in history
        if _real_provider_stage_proof_eligible(row)
        and str(row.get("stage_id") or "") == "provider_full_reference_resume"
        and str(row.get("resume_from_session_id") or "") == source_session_id
        and str(row.get("provider_id") or "") == str(source.get("provider_id") or "")
        and str(row.get("model") or "") == str(source.get("model") or "")
    ]
    rows.sort(key=lambda row: float((row.get("session") or {}).get("updated_at") or 0.0))
    return rows


def _step_coverage_for_sessions(
    control_store: ControlSessionStore,
    session_ids: list[str],
    *,
    requested_step_count: int,
) -> tuple[dict[int, dict[str, Any]], dict[int, dict[str, Any]], int]:
    success_by_step: dict[int, dict[str, Any]] = {}
    failed_by_step: dict[int, dict[str, Any]] = {}
    total_step_evidence = 0
    for session_id in session_ids:
        if not session_id:
            continue
        try:
            replay = control_store.replay(session_id, limit=max(5000, requested_step_count + 10))
        except (KeyError, ValueError):
            continue
        for item in replay.get("evidence") or []:
            if not isinstance(item, dict) or item.get("action") != "kimi_swarm_load_step":
                continue
            detail = item.get("detail") if isinstance(item.get("detail"), dict) else {}
            try:
                index = int(detail.get("step_index"))
            except (TypeError, ValueError):
                continue
            if index < 0 or index >= requested_step_count:
                continue
            total_step_evidence += 1
            if bool(detail.get("ok")):
                success_by_step[index] = {
                    "session_id": session_id,
                    "evidence_id": item.get("evidence_id"),
                    "step_index": index,
                }
                failed_by_step.pop(index, None)
            elif index not in success_by_step:
                failed_by_step[index] = {
                    "session_id": session_id,
                    "evidence_id": item.get("evidence_id"),
                    "step_index": index,
                    "error": detail.get("error"),
                }
    return success_by_step, failed_by_step, total_step_evidence


def _proof_rank(row: dict[str, Any]) -> tuple[int, int, float]:
    return (
        int(row.get("successful_steps") or 0),
        int(row.get("agent_count") or 0),
        float(row.get("updated_at") or (row.get("session") or {}).get("updated_at") or 0.0),
    )


def _real_provider_stage_proof_eligible(row: dict[str, Any]) -> bool:
    if not bool(row.get("provider_backed")):
        return False
    estimated = int(row.get("estimated_max_tokens") or 0)
    total_output = int(row.get("total_output_tokens") or 0)
    return (
        int(row.get("per_step_output_budget") or 0) > 0
        and estimated > 0
        and total_output <= estimated
    )


def _is_retryable_provider_error(error: str) -> bool:
    if _is_quota_limit_error(error) or _is_rate_limit_error(error):
        return False
    normalized = str(error or "").lower()
    retryable_markers = (
        "connecterror",
        "connection",
        "unexpected_eof",
        "eof occurred",
        "timeout",
        "temporarily unavailable",
        "http_500",
        "http_502",
        "http_503",
        "http_504",
        "ssl",
    )
    return any(marker in normalized for marker in retryable_markers)


def _is_quota_limit_error(error: str) -> bool:
    normalized = str(error or "").lower()
    return (
        "usage limit" in normalized
        or "quota" in normalized
        or "limit-upgrade" in normalized
        or "limit upgrade" in normalized
        or "refreshed in the next period" in normalized
        or "upgrade to get more" in normalized
    )


def _is_rate_limit_error(error: str) -> bool:
    normalized = str(error or "").lower()
    return (
        "http_429" in normalized
        or "too many requests" in normalized
        or "rate limit" in normalized
        or "rate_limit" in normalized
    )


def _failure_category(error: str) -> str:
    normalized = str(error or "").lower()
    if not normalized:
        return "unknown"
    if _is_quota_limit_error(normalized):
        return "provider_quota_limit"
    if _is_rate_limit_error(normalized):
        return "provider_rate_limit"
    if "exceeded per-step output budget" in normalized:
        return "token_budget_exceeded"
    if _is_retryable_provider_error(normalized):
        return "provider_transient"
    return "provider_error"


def _failure_summary_from_step_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    top_errors: dict[str, int] = {}
    failed_steps = 0
    retried_steps = 0
    for record in records:
        if int(record.get("attempt_count") or 0) > 1:
            retried_steps += 1
        if bool(record.get("ok")):
            continue
        failed_steps += 1
        error = str(record.get("error") or "")
        category = _failure_category(error)
        counts[category] = counts.get(category, 0) + 1
        if error:
            top_errors[error] = top_errors.get(error, 0) + 1
    primary_category = ""
    if counts:
        primary_category = max(counts, key=lambda key: counts[key])
    return {
        "schema": "octopus.kimi_swarm_failure_summary.v1",
        "failed_steps": failed_steps,
        "retried_steps": retried_steps,
        "categories": dict(sorted(counts.items())),
        "primary_category": primary_category,
        "provider_quota_limited": counts.get("provider_quota_limit", 0) > 0,
        "provider_rate_limited": counts.get("provider_rate_limit", 0) > 0,
        "top_errors": [
            {"error": error, "count": count}
            for error, count in sorted(
                top_errors.items(),
                key=lambda item: item[1],
                reverse=True,
            )[:5]
        ],
    }


def _failure_summary_from_replay(replay: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(replay, dict):
        return _failure_summary_from_step_records([])
    records = [
        item.get("detail") or {}
        for item in replay.get("evidence") or []
        if isinstance(item, dict) and item.get("action") == "kimi_swarm_load_step"
    ]
    return _failure_summary_from_step_records(
        [record for record in records if isinstance(record, dict)],
    )


def export_kimi_swarm_proof_bundle(
    *,
    store: ControlSessionStore | None = None,
    data_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Build a tamper-evident proof bundle for the best full-reference run."""
    control_store = store or ControlSessionStore(
        (Path(data_dir) / "control_sessions") if data_dir is not None else None
    )
    proof = best_kimi_swarm_load_test_proof(store=control_store)
    if proof is None:
        return {
            "schema": _PROOF_BUNDLE_SCHEMA,
            "ready": False,
            "reason": "no provider_full_reference proof with complete replay evidence",
            "proof": None,
            "step_evidence_count": 0,
            "timeline_count": 0,
            "sha256": "",
        }
    if bool(proof.get("composite")):
        return _export_composite_proof_bundle(control_store, proof)
    session_id = str(proof["session_id"])
    replay = control_store.replay(session_id, limit=5000)
    step_evidence = [
        item
        for item in replay.get("evidence") or []
        if isinstance(item, dict) and item.get("action") == "kimi_swarm_load_step"
    ]
    timeline_items = list((replay.get("timeline") or {}).get("items") or [])
    payload = {
        "schema": _PROOF_BUNDLE_SCHEMA,
        "ready": True,
        "proof": _proof_without_session(proof),
        "session": replay.get("session"),
        "action_count": len(replay.get("actions") or []),
        "step_evidence_count": len(step_evidence),
        "timeline_count": len(timeline_items),
        "timeline_digest": _digest_json(timeline_items),
        "step_evidence_digest": _digest_json(step_evidence),
        "replay_href": f"/api/control-sessions/{session_id}/replay",
        "timeline_href": f"/api/control-sessions/{session_id}/timeline",
    }
    return {
        **payload,
        "sha256": _digest_json(payload),
    }


def _export_composite_proof_bundle(
    control_store: ControlSessionStore,
    proof: dict[str, Any],
) -> dict[str, Any]:
    session_ids = [
        str(session_id)
        for session_id in proof.get("source_session_ids") or []
        if str(session_id or "")
    ]
    replays: list[dict[str, Any]] = []
    all_step_evidence: list[dict[str, Any]] = []
    all_timeline_items: list[dict[str, Any]] = []
    action_count = 0
    for session_id in session_ids:
        replay = control_store.replay(session_id, limit=5000)
        replays.append(replay)
        action_count += len(replay.get("actions") or [])
        all_step_evidence.extend(
            item
            for item in replay.get("evidence") or []
            if isinstance(item, dict) and item.get("action") == "kimi_swarm_load_step"
        )
        all_timeline_items.extend(list((replay.get("timeline") or {}).get("items") or []))
    payload = {
        "schema": _PROOF_BUNDLE_SCHEMA,
        "ready": True,
        "proof": _proof_without_session(proof),
        "composite": True,
        "sessions": [replay.get("session") for replay in replays],
        "action_count": action_count,
        "step_evidence_count": int(proof.get("actual_recorded_step_evidence_count") or 0),
        "raw_step_evidence_count": len(all_step_evidence),
        "timeline_count": len(all_timeline_items),
        "timeline_digest": _digest_json(all_timeline_items),
        "step_evidence_digest": _digest_json(all_step_evidence),
        "replay_hrefs": [
            f"/api/control-sessions/{session_id}/replay" for session_id in session_ids
        ],
        "timeline_hrefs": [
            f"/api/control-sessions/{session_id}/timeline" for session_id in session_ids
        ],
    }
    return {
        **payload,
        "sha256": _digest_json(payload),
    }


def build_kimi_swarm_resume_plan(
    *,
    provider_id: str = _DEFAULT_REFERENCE_PROVIDER_ID,
    model: str = _DEFAULT_REFERENCE_MODEL,
    agent_count: int = _DEFAULT_AGENT_COUNT,
    step_count: int = _DEFAULT_STEP_COUNT,
    max_concurrency: int = _DEFAULT_MAX_CONCURRENCY,
    store: ControlSessionStore | None = None,
    data_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Return a replay-backed plan to resume a failed full-reference run."""
    requested_agent_count = max(1, int(agent_count))
    requested_step_count = max(1, int(step_count))
    requested_max_concurrency = max(
        1,
        min(int(max_concurrency), requested_agent_count, requested_step_count),
    )
    control_store = store or ControlSessionStore(
        (Path(data_dir) / "control_sessions") if data_dir is not None else None
    )
    candidate = _latest_failed_full_reference_run(
        provider_id=provider_id,
        model=model,
        requested_agent_count=requested_agent_count,
        requested_step_count=requested_step_count,
        store=control_store,
    )
    if candidate is None:
        return {
            "schema": _RESUME_PLAN_SCHEMA,
            "ready": False,
            "reason": "no failed provider_full_reference run to resume",
            "provider_id": provider_id,
            "model": model,
            "source_session_id": "",
            "successful_step_count": 0,
            "remaining_step_count": 0,
            "remaining_step_ranges": [],
            "recommended_payload": None,
        }
    session_id = str(candidate.get("session_id") or "")
    history = kimi_swarm_load_test_history(store=control_store)
    resume_rows = _resume_rows_for_source(history=history, source=candidate)
    resume_session_ids = [
        str(row.get("session_id") or "")
        for row in resume_rows
        if str(row.get("session_id") or "")
    ]
    success_by_step, failed_by_step, raw_step_evidence_count = _step_coverage_for_sessions(
        control_store,
        [session_id, *resume_session_ids],
        requested_step_count=requested_step_count,
    )
    successful_indices = set(success_by_step)
    failed_indices = set(failed_by_step)
    all_indices = set(range(requested_step_count))
    remaining_indices = sorted((all_indices - successful_indices) | failed_indices)
    per_step_budget = _DEFAULT_PROVIDER_OUTPUT_TOKENS_PER_STEP
    payload = None
    chunk_payload = None
    if remaining_indices:
        payload = {
            "provider_id": provider_id,
            "model": model,
            "agent_count": requested_agent_count,
            "step_count": requested_step_count,
            "max_concurrency": requested_max_concurrency,
            "real_provider": True,
            "confirm_real_provider": True,
            "record_every_step": True,
            "stage_id": "provider_full_reference_resume",
            "resume_from_session_id": session_id,
            "resume_step_count": len(remaining_indices),
            "resume_step_ranges": _compact_ranges(remaining_indices),
            "max_provider_calls": len(remaining_indices),
            "estimated_max_tokens": len(remaining_indices) * per_step_budget,
        }
        chunk_indices = remaining_indices[
            : min(len(remaining_indices), _DEFAULT_RESUME_CHUNK_STEP_COUNT)
        ]
        chunk_payload = {
            **payload,
            "max_concurrency": min(
                requested_max_concurrency,
                _DEFAULT_RESUME_CHUNK_CONCURRENCY,
                len(chunk_indices),
            ),
            "resume_step_count": len(chunk_indices),
            "resume_step_ranges": _compact_ranges(chunk_indices),
            "max_provider_calls": len(chunk_indices),
            "estimated_max_tokens": len(chunk_indices) * per_step_budget,
            "chunked": len(chunk_indices) < len(remaining_indices),
            "total_remaining_step_count": len(remaining_indices),
        }
    failure_summary = candidate.get("failure_summary")
    return {
        "schema": _RESUME_PLAN_SCHEMA,
        "ready": bool(remaining_indices),
        "reason": "" if remaining_indices else "source run already has full success coverage",
        "provider_id": provider_id,
        "model": model,
        "source_session_id": session_id,
        "source_stage_id": candidate.get("stage_id"),
        "partial_resume_session_ids": resume_session_ids,
        "requested": {
            "agent_count": requested_agent_count,
            "step_count": requested_step_count,
            "max_concurrency": requested_max_concurrency,
        },
        "successful_step_count": len(successful_indices),
        "failed_step_count": len(failed_indices),
        "covered_step_count": len(successful_indices),
        "remaining_step_count": len(remaining_indices),
        "remaining_step_ranges": _compact_ranges(remaining_indices),
        "raw_step_evidence_count": raw_step_evidence_count,
        "failure_summary": failure_summary if isinstance(failure_summary, dict) else None,
        "recommended_payload": payload,
        "recommended_chunk_payload": chunk_payload,
    }


def recommend_kimi_swarm_next_stage(
    *,
    provider_id: str = _DEFAULT_REFERENCE_PROVIDER_ID,
    model: str = _DEFAULT_REFERENCE_MODEL,
    agent_count: int = _DEFAULT_AGENT_COUNT,
    step_count: int = _DEFAULT_STEP_COUNT,
    max_concurrency: int = _DEFAULT_MAX_CONCURRENCY,
    provider_configured: bool | None = None,
    store: ControlSessionStore | None = None,
    data_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Return the next safe stage payload needed to reach full proof."""
    requested_agent_count = max(1, int(agent_count))
    requested_step_count = max(1, int(step_count))
    requested_max_concurrency = max(
        1,
        min(int(max_concurrency), requested_agent_count, requested_step_count),
    )
    stages = ("provider_canary", "provider_ramp", "provider_full_reference")
    proofs = {
        stage: latest_successful_stage_proof(
            provider_id=provider_id,
            model=model,
            requested_agent_count=requested_agent_count,
            requested_step_count=requested_step_count,
            stage_id=stage,
            store=store,
            data_dir=data_dir,
        )
        for stage in stages
    }
    if proofs["provider_full_reference"] is None:
        best_full = best_kimi_swarm_load_test_proof(store=store, data_dir=data_dir)
        if (
            isinstance(best_full, dict)
            and str(best_full.get("provider_id") or "") == str(provider_id or "")
            and str(best_full.get("model") or "") == str(model or "")
            and int(best_full.get("requested_agent_count") or 0)
            == requested_agent_count
            and int(best_full.get("requested_step_count") or 0)
            == requested_step_count
        ):
            proofs["provider_full_reference"] = best_full
    if proofs["provider_full_reference"] is not None:
        next_stage = "complete"
    elif proofs["provider_ramp"] is not None:
        next_stage = "provider_full_reference"
    elif proofs["provider_canary"] is not None:
        next_stage = "provider_ramp"
    else:
        next_stage = "provider_canary"
    blocking_failure = (
        None
        if next_stage == "complete"
        else _latest_stage_blocking_failure(
            provider_id=provider_id,
            model=model,
            requested_agent_count=requested_agent_count,
            requested_step_count=requested_step_count,
            stage_id=next_stage,
            store=store,
            data_dir=data_dir,
        )
    )
    preflight: dict[str, Any] | None = None
    resume_plan: dict[str, Any] | None = None
    if next_stage == "complete":
        payload = None
    else:
        stage_config = KimiSwarmLoadTestConfig(
            provider_id=provider_id,
            model=model,
            agent_count=requested_agent_count,
            step_count=requested_step_count,
            max_concurrency=requested_max_concurrency,
            real_provider=True,
            confirm_real_provider=True,
            stage_id=next_stage,
        )
        selected = _resolve_stage(
            config=stage_config,
            requested_agent_count=requested_agent_count,
            requested_step_count=requested_step_count,
            requested_max_concurrency=requested_max_concurrency,
        )
        payload = {
            "provider_id": provider_id,
            "model": model,
            "agent_count": requested_agent_count,
            "step_count": requested_step_count,
            "max_concurrency": requested_max_concurrency,
            "real_provider": True,
            "confirm_real_provider": True,
            "record_every_step": True,
            "stage_id": next_stage,
            "max_provider_calls": int(selected["step_count"]),
            "estimated_max_tokens": (
                int(selected["step_count"]) * _DEFAULT_PROVIDER_OUTPUT_TOKENS_PER_STEP
            ),
        }
        if next_stage == "provider_full_reference":
            resume_plan = build_kimi_swarm_resume_plan(
                provider_id=provider_id,
                model=model,
                agent_count=requested_agent_count,
                step_count=requested_step_count,
                max_concurrency=requested_max_concurrency,
                store=store,
                data_dir=data_dir,
            )
            if resume_plan.get("ready") and isinstance(
                resume_plan.get("recommended_payload"),
                dict,
            ):
                payload = dict(resume_plan["recommended_payload"])
                if isinstance(resume_plan.get("recommended_chunk_payload"), dict):
                    payload = dict(resume_plan["recommended_chunk_payload"])
        preflight = build_kimi_swarm_load_test_preflight(
            config=KimiSwarmLoadTestConfig(
                provider_id=provider_id,
                model=model,
                agent_count=requested_agent_count,
                step_count=requested_step_count,
                max_concurrency=requested_max_concurrency,
                real_provider=True,
                confirm_real_provider=True,
                record_every_step=True,
                stage_id=next_stage,
                max_provider_calls=int(selected["step_count"]),
                estimated_max_tokens=(
                    int(selected["step_count"]) * _DEFAULT_PROVIDER_OUTPUT_TOKENS_PER_STEP
                ),
            ),
            provider_configured=(True if provider_configured is None else provider_configured),
            store=store,
            data_dir=data_dir,
        )
    if isinstance(resume_plan, dict) and resume_plan.get("ready"):
        preflight = _resume_preflight_from_plan(
            resume_plan,
            provider_configured=provider_configured,
        )
    quota_probe_payload = None
    if (
        isinstance(blocking_failure, dict)
        and str(blocking_failure.get("category") or "") == "provider_quota_limit"
    ):
        quota_probe_payload = {
            "provider_id": provider_id,
            "model": model,
            "confirm_real_provider": True,
            "max_tokens": 16,
        }
    proof_ready = next_stage == "complete"
    can_run = (
        not proof_ready
        and provider_configured is True
        and isinstance(preflight, dict)
        and bool(preflight.get("ready"))
        and blocking_failure is None
    )
    provider_state = (
        "unknown"
        if provider_configured is None
        else ("configured" if provider_configured else "missing")
    )
    return {
        "schema": _NEXT_STAGE_SCHEMA,
        "ready": proof_ready,
        "proof_ready": proof_ready,
        "next_stage": next_stage,
        "provider_id": provider_id,
        "model": model,
        "provider_configured": provider_configured,
        "provider_configuration_state": provider_state,
        "requested": {
            "agent_count": requested_agent_count,
            "step_count": requested_step_count,
            "max_concurrency": requested_max_concurrency,
        },
        "stage_proofs": {
            key: _proof_without_session(value) if value else None
            for key, value in proofs.items()
        },
        "recommended_payload": payload,
        "recommended_preflight": preflight,
        "resume_plan": resume_plan,
        "recommended_chunk_payload": (
            resume_plan.get("recommended_chunk_payload")
            if isinstance(resume_plan, dict)
            else None
        ),
        "quota_probe_payload": quota_probe_payload,
        "latest_blocking_failure": blocking_failure,
        "can_run_recommended_payload": can_run,
        "next_action": _next_stage_action(
            next_stage=next_stage,
            provider_state=provider_state,
            can_run=can_run,
            blocking_failure=blocking_failure,
            resume_plan=resume_plan,
        ),
    }


def _next_stage_action(
    *,
    next_stage: str,
    provider_state: str,
    can_run: bool,
    blocking_failure: dict[str, Any] | None = None,
    resume_plan: dict[str, Any] | None = None,
) -> str:
    if next_stage == "complete":
        return "Full provider-backed Kimi-reference proof is complete."
    if blocking_failure:
        category = str(blocking_failure.get("category") or "provider_failure")
        if category == "provider_quota_limit":
            if isinstance(resume_plan, dict) and resume_plan.get("ready"):
                return (
                    "Kimi provider quota is exhausted; run the quota probe after "
                    "refresh, then resume "
                    f"{resume_plan.get('remaining_step_count')} remaining full-reference steps "
                    "instead of rerunning all 4000."
                )
            return (
                "Kimi provider quota is exhausted for the latest "
                f"{next_stage} attempt; run the quota probe after refresh before rerun."
            )
        if category == "provider_rate_limit":
            chunk = resume_plan.get("recommended_chunk_payload") if isinstance(resume_plan, dict) else None
            if isinstance(chunk, dict):
                return (
                    "Kimi provider is rate-limiting; wait briefly, then run the "
                    f"throttled resume chunk for {chunk.get('resume_step_count')} "
                    f"of {resume_plan.get('remaining_step_count')} remaining steps."
                )
            return (
                "Kimi provider is rate-limiting; wait briefly and rerun with lower "
                "resume concurrency."
            )
        if category == "token_budget_exceeded":
            return (
                f"Increase the recommended {next_stage} token budget before rerun."
            )
        return f"Resolve the latest {next_stage} provider failure before rerun."
    if provider_state == "missing":
        return (
            "Configure the Kimi Coding custom model, then run the recommended "
            f"{next_stage} payload."
        )
    if provider_state == "unknown":
        return (
            "Check custom model configuration, then run the recommended "
            f"{next_stage} payload."
        )
    if can_run and isinstance(resume_plan, dict) and resume_plan.get("ready"):
        chunk = resume_plan.get("recommended_chunk_payload")
        if isinstance(chunk, dict) and chunk.get("chunked"):
            return (
                f"Run the throttled resume chunk for {chunk.get('resume_step_count')} "
                f"of {resume_plan.get('remaining_step_count')} remaining {next_stage} steps."
            )
        return (
            f"Run the resume payload for {resume_plan.get('remaining_step_count')} "
            f"remaining {next_stage} steps."
        )
    if can_run:
        return f"Run the recommended {next_stage} payload."
    return f"Resolve the recommended {next_stage} preflight blockers."


def _latest_stage_blocking_failure(
    *,
    provider_id: str,
    model: str,
    requested_agent_count: int,
    requested_step_count: int,
    stage_id: str,
    store: ControlSessionStore | None = None,
    data_dir: str | Path | None = None,
) -> dict[str, Any] | None:
    for row in kimi_swarm_load_test_history(store=store, data_dir=data_dir):
        if (
            str(row.get("provider_id") or "") != str(provider_id or "")
            or str(row.get("model") or "") != str(model or "")
            or str(row.get("stage_id") or "") != str(stage_id or "")
            or int(row.get("requested_agent_count") or 0) != int(requested_agent_count)
            or int(row.get("requested_step_count") or 0) != int(requested_step_count)
        ):
            continue
        if int(row.get("failed_steps") or 0) <= 0:
            return None
        failure_summary = row.get("failure_summary")
        if not isinstance(failure_summary, dict):
            return None
        category = str(failure_summary.get("primary_category") or "")
        if category not in {
            "provider_quota_limit",
            "provider_rate_limit",
            "token_budget_exceeded",
        }:
            return None
        return {
            "schema": "octopus.kimi_swarm_stage_blocking_failure.v1",
            "category": category,
            "stage_id": stage_id,
            "session_id": row.get("session_id"),
            "failed_steps": row.get("failed_steps"),
            "successful_steps": row.get("successful_steps"),
            "failure_summary": failure_summary,
        }
    return None


def _latest_failed_full_reference_run(
    *,
    provider_id: str,
    model: str,
    requested_agent_count: int,
    requested_step_count: int,
    store: ControlSessionStore,
) -> dict[str, Any] | None:
    for row in kimi_swarm_load_test_history(store=store):
        if (
            bool(row.get("provider_backed"))
            and str(row.get("provider_id") or "") == str(provider_id or "")
            and str(row.get("model") or "") == str(model or "")
            and str(row.get("stage_id") or "") == "provider_full_reference"
            and int(row.get("requested_agent_count") or 0) == int(requested_agent_count)
            and int(row.get("requested_step_count") or 0) == int(requested_step_count)
            and int(row.get("failed_steps") or 0) > 0
        ):
            return row
    return None


def _compact_ranges(indices: list[int]) -> list[dict[str, int]]:
    if not indices:
        return []
    ranges: list[dict[str, int]] = []
    start = prev = int(indices[0])
    for raw in indices[1:]:
        current = int(raw)
        if current == prev + 1:
            prev = current
            continue
        ranges.append({"start": start, "end": prev, "count": prev - start + 1})
        start = prev = current
    ranges.append({"start": start, "end": prev, "count": prev - start + 1})
    return ranges


def _resume_execution_indices(
    config: KimiSwarmLoadTestConfig,
    *,
    control_store: ControlSessionStore,
    requested_step_count: int,
) -> list[int]:
    indices = _indices_from_ranges(
        list(config.resume_step_ranges),
        upper_bound=requested_step_count,
    )
    if indices:
        return indices
    source_session_id = str(config.resume_from_session_id or "").strip()
    if not source_session_id:
        raise ValueError("resume_from_session_id is required for provider_full_reference_resume")
    try:
        replay = control_store.replay(source_session_id, limit=max(5000, requested_step_count + 10))
    except (KeyError, ValueError) as exc:
        raise ValueError(f"cannot load resume source session: {source_session_id}") from exc
    successful: set[int] = set()
    failed: set[int] = set()
    for item in replay.get("evidence") or []:
        if not isinstance(item, dict) or item.get("action") != "kimi_swarm_load_step":
            continue
        detail = item.get("detail") if isinstance(item.get("detail"), dict) else {}
        try:
            index = int(detail.get("step_index"))
        except (TypeError, ValueError):
            continue
        if bool(detail.get("ok")):
            successful.add(index)
            failed.discard(index)
        elif index not in successful:
            failed.add(index)
    return sorted((set(range(requested_step_count)) - successful) | failed)


def _indices_from_ranges(
    ranges: list[dict[str, int]],
    *,
    upper_bound: int,
) -> list[int]:
    out: set[int] = set()
    for item in ranges:
        if not isinstance(item, dict):
            continue
        try:
            start = int(item.get("start"))
            end = int(item.get("end"))
        except (TypeError, ValueError):
            continue
        start = max(0, start)
        end = min(max(0, upper_bound - 1), end)
        if end < start:
            continue
        out.update(range(start, end + 1))
    return sorted(out)


def _resume_preflight_from_plan(
    plan: dict[str, Any],
    *,
    provider_configured: bool | None,
) -> dict[str, Any]:
    payload = plan.get("recommended_chunk_payload") or plan.get("recommended_payload")
    payload = payload if isinstance(payload, dict) else {}
    selected_steps = int(
        payload.get("resume_step_count") or plan.get("remaining_step_count") or 0
    )
    configured = True if provider_configured is None else bool(provider_configured)
    checks = [
        {
            "id": "provider_configured",
            "title": "A custom model router is configured",
            "passed": configured,
            "value": configured,
            "blocking": True,
        },
        {
            "id": "provider_call_budget",
            "title": "Provider call budget covers selected resume steps",
            "passed": int(payload.get("max_provider_calls") or 0) >= selected_steps,
            "value": int(payload.get("max_provider_calls") or 0),
            "required": selected_steps,
            "blocking": True,
        },
        {
            "id": "token_budget",
            "title": "Token budget covers selected resume steps",
            "passed": int(payload.get("estimated_max_tokens") or 0) >= selected_steps,
            "value": int(payload.get("estimated_max_tokens") or 0),
            "required": selected_steps,
            "blocking": True,
        },
    ]
    blocking = [check for check in checks if check["blocking"] and not check["passed"]]
    return {
        "schema": _PREFLIGHT_SCHEMA,
        "ready": not blocking,
        "provider_ready": not blocking,
        "reference_ready": True,
        "mode": "real_provider_resume",
        "model": plan.get("model"),
        "provider_id": plan.get("provider_id"),
        "agent_count": (plan.get("requested") or {}).get("agent_count"),
        "step_count": (plan.get("requested") or {}).get("step_count"),
        "max_concurrency": (plan.get("requested") or {}).get("max_concurrency"),
        "selected_stage": {
            "id": "provider_full_reference_resume",
            "title": "Provider full Kimi-reference resume",
            "step_count": selected_steps,
            "requires_confirmation": True,
        },
        "resume_plan": {
            "schema": plan.get("schema"),
            "source_session_id": plan.get("source_session_id"),
            "remaining_step_count": plan.get("remaining_step_count"),
            "selected_step_count": selected_steps,
            "remaining_step_ranges": plan.get("remaining_step_ranges"),
            "selected_step_ranges": payload.get("resume_step_ranges"),
            "chunked": payload.get("chunked", False),
        },
        "checks": checks,
        "blocking_failures": blocking,
        "next_action": (
            "Run the resume payload."
            if not blocking
            else "Resolve blocking resume preflight checks before running."
        ),
    }


def _summary_for_session(
    control_store: ControlSessionStore,
    session: dict[str, Any],
) -> dict[str, Any] | None:
    metadata = session.get("metadata") if isinstance(session.get("metadata"), dict) else {}
    summary = metadata.get("last_kimi_swarm_load_test")
    replay: dict[str, Any] | None = None
    if not isinstance(summary, dict):
        try:
            replay = control_store.replay(str(session["session_id"]), limit=5000)
        except (KeyError, ValueError):
            return None
        for evidence in reversed(replay.get("evidence") or []):
            detail = evidence.get("detail") if isinstance(evidence, dict) else {}
            if isinstance(detail, dict) and detail.get("schema") == _SUMMARY_EVIDENCE_SCHEMA:
                summary = {k: v for k, v in detail.items() if k != "schema"}
                break
    if not isinstance(summary, dict):
        return None
    if replay is None:
        try:
            replay = control_store.replay(str(session["session_id"]), limit=5000)
        except (KeyError, ValueError):
            replay = {}
    actual_step_evidence_count = _actual_step_evidence_count(replay)
    failure_summary = summary.get("failure_summary")
    if not isinstance(failure_summary, dict):
        failure_summary = _failure_summary_from_replay(replay)
    return {
        "schema": _SUMMARY_EVIDENCE_SCHEMA,
        **summary,
        "failure_summary": failure_summary,
        "quota_limited": bool(failure_summary.get("provider_quota_limited")),
        "actual_recorded_step_evidence_count": actual_step_evidence_count,
        "replay_evidence_verified": (
            actual_step_evidence_count >= int(summary.get("step_count") or 0)
        ),
        "session": session,
    }


def _actual_step_evidence_count(replay: dict[str, Any] | None) -> int:
    if not isinstance(replay, dict):
        return 0
    return sum(
        1
        for item in replay.get("evidence") or []
        if isinstance(item, dict) and item.get("action") == "kimi_swarm_load_step"
    )


def _proof_without_session(proof: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in proof.items()
        if key not in {"session"}
    }


def _digest_json(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()
    return hashlib.sha256(raw).hexdigest()


def _normalize_counts(config: KimiSwarmLoadTestConfig) -> tuple[int, int, int]:
    agent_count = max(1, int(config.agent_count))
    step_count = max(1, int(config.step_count))
    max_concurrency = max(1, min(int(config.max_concurrency), agent_count, step_count))
    return agent_count, step_count, max_concurrency


def _resolve_stage(
    *,
    config: KimiSwarmLoadTestConfig,
    requested_agent_count: int,
    requested_step_count: int,
    requested_max_concurrency: int,
) -> dict[str, Any]:
    plan = _stage_plan(
        agent_count=requested_agent_count,
        step_count=requested_step_count,
        max_concurrency=requested_max_concurrency,
        real_provider=bool(config.real_provider),
    )
    stages = [stage for stage in plan["stages"] if isinstance(stage, dict)]
    requested_stage = str(config.stage_id or "auto").strip() or "auto"
    if requested_stage == "auto":
        requested_stage = "provider_full_reference" if config.real_provider else "dry_replay"
    if requested_stage == "provider_full_reference_resume":
        for stage in stages:
            if stage.get("id") == "provider_full_reference":
                return {
                    **dict(stage),
                    "id": "provider_full_reference_resume",
                    "source_stage_id": "provider_full_reference",
                    "title": "Provider full Kimi-reference resume",
                }
    for stage in stages:
        if stage.get("id") == requested_stage:
            return dict(stage)
    raise ValueError(f"unknown kimi swarm load-test stage_id: {requested_stage}")


def _previous_stage_id(stage_id: str) -> str:
    if stage_id == "provider_ramp":
        return "provider_canary"
    if stage_id == "provider_full_reference":
        return "provider_ramp"
    return ""


def _stage_plan(
    *,
    agent_count: int,
    step_count: int,
    max_concurrency: int,
    real_provider: bool,
) -> dict[str, Any]:
    if not real_provider:
        stages = [
            {
                "id": "dry_replay",
                "title": "Dry replay proof",
                "agent_count": agent_count,
                "step_count": step_count,
                "max_concurrency": max_concurrency,
                "requires_confirmation": False,
                "default": True,
            }
        ]
    else:
        canary_steps = min(step_count, 10)
        ramp_steps = min(step_count, max(canary_steps, 300))
        stages = [
            {
                "id": "provider_canary",
                "title": "Provider canary",
                "agent_count": min(agent_count, 10),
                "step_count": canary_steps,
                "max_concurrency": min(max_concurrency, 4),
                "requires_confirmation": True,
                "default": False,
            },
            {
                "id": "provider_ramp",
                "title": "Provider ramp",
                "agent_count": min(agent_count, 64),
                "step_count": ramp_steps,
                "max_concurrency": min(max_concurrency, 16),
                "requires_confirmation": True,
                "default": False,
            },
            {
                "id": "provider_full_reference",
                "title": "Provider full Kimi-reference proof",
                "agent_count": agent_count,
                "step_count": step_count,
                "max_concurrency": max_concurrency,
                "requires_confirmation": True,
                "default": True,
            },
        ]
    return {
        "schema": _STAGE_PLAN_SCHEMA,
        "stages": stages,
        "total_stages": len(stages),
    }


__all__ = [
    "KimiSwarmLoadTestConfig",
    "KimiSwarmQuotaProbeConfig",
    "best_kimi_swarm_load_test_proof",
    "build_kimi_swarm_load_test_preflight",
    "build_kimi_swarm_resume_plan",
    "export_kimi_swarm_proof_bundle",
    "kimi_swarm_load_test_history",
    "latest_successful_stage_proof",
    "latest_kimi_swarm_load_test",
    "recommend_kimi_swarm_next_stage",
    "run_kimi_swarm_load_test",
    "run_kimi_swarm_quota_probe",
]
