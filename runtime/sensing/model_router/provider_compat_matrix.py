"""Offline compatibility matrix for custom LLM providers.

The matrix is intentionally offline: it inspects custom-model configuration and
known OpenAI-compatible protocol quirks without sending a request to any model
provider. Live probes can build on the same report shape later.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit, urlunsplit

from .openai_router import resolve_openai_compat_model_capabilities

FindingSeverity = Literal["info", "warning", "error"]
ProviderVerdict = Literal["pass", "review", "fail"]
LiveStepStatus = Literal["pass", "fail", "skip"]
LiveRouterFactory = Callable[[dict[str, Any], str, float], Any]

_BUILTIN_DOMESTIC_PROFILE_CHECKS: dict[str, tuple[str, ...]] = {
    "kimi_coding": (
        "profile_inference",
        "strict_sampling_knob_check",
        "openai_compat_capability_snapshot",
    ),
    "kimi": (
        "profile_inference",
        "openai_compat_capability_snapshot",
    ),
    "qwen_dashscope": (
        "profile_inference",
        "compatible_mode_base_url_check",
        "qwen_thinking_wire_format_check",
    ),
    "deepseek_reasoner": (
        "profile_inference",
        "implicit_reasoning_wire_format_check",
    ),
    "deepseek": (
        "profile_inference",
        "openai_compat_capability_snapshot",
    ),
    "glm_strict": (
        "profile_inference",
        "strict_system_message_check",
    ),
    "glm": (
        "profile_inference",
        "openai_compat_capability_snapshot",
    ),
    "minimax": (
        "profile_inference",
        "provider_specific_thinking_review",
    ),
    "qianfan": (
        "profile_inference",
        "compatible_base_url_review",
    ),
    "volcengine_ark": (
        "profile_inference",
        "compatible_base_url_review",
    ),
    "baichuan": (
        "profile_inference",
        "openai_compat_capability_snapshot",
    ),
}


@dataclass(frozen=True, slots=True)
class ProviderCompatibilityFinding:
    severity: FindingSeverity
    code: str
    message: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ProviderLiveProbeStep:
    name: str
    status: LiveStepStatus
    detail: str = ""
    duration_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "detail": self.detail,
            "duration_ms": round(self.duration_ms, 2),
        }


@dataclass(frozen=True, slots=True)
class ProviderLiveProbeResult:
    enabled: bool = False
    status: ProviderVerdict = "pass"
    steps: list[ProviderLiveProbeStep] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "status": self.status,
            "steps": [step.to_dict() for step in self.steps],
        }


@dataclass(frozen=True, slots=True)
class ProviderCompatibilityRow:
    id: str
    provider: str
    display_name: str
    base_url: str
    models: list[str]
    profile: str
    has_api_key: bool
    capabilities: dict[str, Any]
    findings: list[ProviderCompatibilityFinding] = field(default_factory=list)
    live: ProviderLiveProbeResult | None = None
    score: int = 100
    verdict: ProviderVerdict = "pass"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "provider": self.provider,
            "display_name": self.display_name,
            "base_url": self.base_url,
            "models": list(self.models),
            "profile": self.profile,
            "has_api_key": self.has_api_key,
            "capabilities": dict(self.capabilities),
            "findings": [finding.to_dict() for finding in self.findings],
            "live": self.live.to_dict() if self.live is not None else None,
            "score": self.score,
            "verdict": self.verdict,
        }


@dataclass(frozen=True, slots=True)
class ProviderCompatibilityMatrixReport:
    schema: str = "octopus.provider_compatibility_matrix.v1"
    rows: list[ProviderCompatibilityRow] = field(default_factory=list)
    source: str = ""
    live_mode: bool = False

    @property
    def score(self) -> int:
        if not self.rows:
            return 100
        return round(sum(row.score for row in self.rows) / len(self.rows))

    @property
    def verdict(self) -> ProviderVerdict:
        if any(row.verdict == "fail" for row in self.rows):
            return "fail"
        if any(row.verdict == "review" for row in self.rows):
            return "review"
        return "pass"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "source": self.source,
            "live_mode": self.live_mode,
            "score": self.score,
            "verdict": self.verdict,
            "rows": [row.to_dict() for row in self.rows],
        }


@dataclass(frozen=True, slots=True)
class ProviderCompatibilityHistorySummary:
    path: str
    total_runs: int
    pass_rate: float
    latest_verdict: ProviderVerdict | str = ""
    latest_score: int | None = None
    latest_recorded_at: float | None = None
    latest_rows: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "octopus.provider_compatibility_history_summary.v1",
            "path": self.path,
            "total_runs": self.total_runs,
            "pass_rate": round(self.pass_rate, 4),
            "latest_verdict": self.latest_verdict,
            "latest_score": self.latest_score,
            "latest_recorded_at": self.latest_recorded_at,
            "latest_rows": list(self.latest_rows),
        }


@dataclass(frozen=True, slots=True)
class ProviderProfileCoverage:
    required_profiles: list[str]
    covered_profiles: list[str]
    missing_profiles: list[str]
    coverage_rate: float
    checks: dict[str, list[str]]

    @property
    def ready(self) -> bool:
        return not self.missing_profiles and self.coverage_rate >= 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "octopus.provider_profile_coverage.v1",
            "ready": self.ready,
            "required_profiles": list(self.required_profiles),
            "covered_profiles": list(self.covered_profiles),
            "missing_profiles": list(self.missing_profiles),
            "coverage_rate": round(self.coverage_rate, 4),
            "checks": {key: list(value) for key, value in self.checks.items()},
        }


def build_provider_compatibility_matrix(
    *,
    custom_models_path: str | Path | None = None,
    entries: dict[str, Any] | None = None,
    live: bool = False,
    router_factory: LiveRouterFactory | None = None,
    timeout_seconds: float = 15.0,
) -> ProviderCompatibilityMatrixReport:
    source = ""
    if entries is None:
        entries, source = _load_custom_models(custom_models_path)
    else:
        source = "<memory>"
    rows = [
        _build_row(
            model_id,
            entry,
            live=live,
            router_factory=router_factory,
            timeout_seconds=timeout_seconds,
        )
        for model_id, entry in sorted(entries.items())
        if isinstance(entry, dict)
    ]
    return ProviderCompatibilityMatrixReport(rows=rows, source=source, live_mode=live)


def compute_provider_profile_coverage(
    *,
    required_profiles: list[str] | tuple[str, ...] | None = None,
) -> ProviderProfileCoverage:
    required = list(required_profiles or _BUILTIN_DOMESTIC_PROFILE_CHECKS)
    checks = {
        profile: list(_BUILTIN_DOMESTIC_PROFILE_CHECKS.get(profile, ()))
        for profile in required
    }
    covered = [
        profile for profile in required
        if checks.get(profile)
    ]
    missing = [
        profile for profile in required
        if profile not in covered
    ]
    coverage_rate = len(covered) / len(required) if required else 1.0
    return ProviderProfileCoverage(
        required_profiles=required,
        covered_profiles=covered,
        missing_profiles=missing,
        coverage_rate=coverage_rate,
        checks=checks,
    )


def append_provider_compatibility_history(
    report: ProviderCompatibilityMatrixReport,
    *,
    path: str | Path | None = None,
) -> Path:
    history_path = _history_path(path)
    history_path.parent.mkdir(parents=True, exist_ok=True)
    record = _history_record(report)
    with history_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    return history_path


def read_provider_compatibility_history(
    *,
    path: str | Path | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    history_path = _history_path(path)
    if not history_path.exists():
        return []
    records: list[dict[str, Any]] = []
    try:
        for line in history_path.read_text(encoding="utf-8").splitlines():
            raw = line.strip()
            if not raw:
                continue
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                records.append(parsed)
    except OSError:
        return []
    if limit <= 0:
        return []
    return records[-limit:]


def extract_provider_compatibility_failures(
    *,
    path: str | Path | None = None,
    records: list[dict[str, Any]] | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Convert compatibility history rows into evolution failure samples."""
    source_records = records
    if source_records is None:
        source_records = read_provider_compatibility_history(path=path, limit=limit)
    samples: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for record in reversed(source_records):
        if not isinstance(record, dict):
            continue
        recorded_at = record.get("recorded_at")
        for row in record.get("rows", []):
            if not isinstance(row, dict) or str(row.get("verdict") or "") == "pass":
                continue
            sample = _failure_sample_from_row(row, recorded_at=recorded_at)
            if sample is None:
                continue
            signature = (
                str(sample.get("provider_id") or ""),
                str(sample.get("profile") or ""),
                str(sample.get("last_error") or "")[:160],
            )
            if signature in seen:
                continue
            seen.add(signature)
            samples.append(sample)
            if len(samples) >= max(0, int(limit)):
                return samples
    return samples


def export_provider_compatibility_failures(
    out_path: str | Path,
    *,
    history_path: str | Path | None = None,
    records: list[dict[str, Any]] | None = None,
    limit: int = 50,
) -> Path:
    samples = extract_provider_compatibility_failures(
        path=history_path,
        records=records,
        limit=limit,
    )
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for sample in samples:
            fh.write(json.dumps(_redact_payload(sample), ensure_ascii=False, sort_keys=True) + "\n")
    return path


def summarize_provider_compatibility_history(
    *,
    path: str | Path | None = None,
    limit: int = 50,
) -> ProviderCompatibilityHistorySummary:
    history_path = _history_path(path)
    records = read_provider_compatibility_history(path=history_path, limit=limit)
    if not records:
        return ProviderCompatibilityHistorySummary(
            path=str(history_path),
            total_runs=0,
            pass_rate=0.0,
        )
    pass_count = sum(1 for rec in records if rec.get("verdict") == "pass")
    latest = records[-1]
    latest_rows = []
    for row in latest.get("rows", []):
        if not isinstance(row, dict):
            continue
        live = row.get("live") if isinstance(row.get("live"), dict) else {}
        latest_rows.append({
            "id": row.get("id"),
            "profile": row.get("profile"),
            "score": row.get("score"),
            "verdict": row.get("verdict"),
            "live_status": live.get("status") if live else None,
        })
    return ProviderCompatibilityHistorySummary(
        path=str(history_path),
        total_runs=len(records),
        pass_rate=pass_count / len(records),
        latest_verdict=str(latest.get("verdict") or ""),
        latest_score=(
            int(latest["score"])
            if isinstance(latest.get("score"), int)
            else None
        ),
        latest_recorded_at=(
            float(latest["recorded_at"])
            if isinstance(latest.get("recorded_at"), int | float)
            else None
        ),
        latest_rows=latest_rows,
    )


def _history_path(path: str | Path | None) -> Path:
    if path is not None:
        return Path(path)
    from runtime.platform.process.paths import app_paths

    return app_paths().data_dir / "provider_compat_history.jsonl"


def _history_record(report: ProviderCompatibilityMatrixReport) -> dict[str, Any]:
    payload = report.to_dict()
    record = {
        "schema": "octopus.provider_compatibility_history.v1",
        "recorded_at": time.time(),
        "score": payload.get("score"),
        "verdict": payload.get("verdict"),
        "live_mode": payload.get("live_mode"),
        "source": payload.get("source"),
        "rows": payload.get("rows", []),
    }
    return _redact_payload(record)


def _failure_sample_from_row(
    row: dict[str, Any],
    *,
    recorded_at: Any = None,
) -> dict[str, Any] | None:
    provider_id = str(row.get("id") or "").strip()
    if not provider_id:
        return None
    profile = str(row.get("profile") or "openai_compat").strip() or "openai_compat"
    findings = [
        finding for finding in row.get("findings", [])
        if isinstance(finding, dict)
    ]
    live = row.get("live") if isinstance(row.get("live"), dict) else {}
    live_steps = [
        step for step in live.get("steps", [])
        if isinstance(step, dict) and step.get("status") == "fail"
    ] if live else []
    issue_parts = _row_issue_parts(findings, live_steps)
    if not issue_parts:
        issue_parts.append(
            f"Provider compatibility row ended with verdict={row.get('verdict')}"
        )
    repair_routes = _repair_routes_for_provider_row(row, findings, live_steps)
    primary_route = str(repair_routes[0].get("route") or "") if repair_routes else ""
    sample = {
        "goal": (
            f"Stabilize provider compatibility for {provider_id} "
            f"({profile}) without leaking secrets."
        ),
        "last_error": "; ".join(issue_parts),
        "step_count": max(1, len(issue_parts)),
        "source": "provider_compatibility",
        "failure_source": "provider_compatibility_matrix",
        "failure_cluster": f"provider_compatibility:{profile}",
        "provider_id": provider_id,
        "profile": profile,
        "verdict": row.get("verdict"),
        "score": row.get("score"),
        "live_status": live.get("status") if live else None,
        "recorded_at": recorded_at,
        "primary_repair_route": primary_route,
        "repair_routes": repair_routes,
        "capabilities": row.get("capabilities") if isinstance(row.get("capabilities"), dict) else {},
        "models": row.get("models") if isinstance(row.get("models"), list) else [],
    }
    return _redact_payload(sample)


def _row_issue_parts(
    findings: list[dict[str, Any]],
    live_steps: list[dict[str, Any]],
) -> list[str]:
    parts: list[str] = []
    for finding in findings:
        code = str(finding.get("code") or "").strip()
        severity = str(finding.get("severity") or "").strip()
        message = str(finding.get("message") or "").strip()
        if not code and not message:
            continue
        prefix = f"{severity}:{code}".strip(":")
        parts.append(f"{prefix} {message}".strip())
    for step in live_steps:
        name = str(step.get("name") or "").strip()
        detail = str(step.get("detail") or "").strip()
        parts.append(f"live:{name} {detail}".strip())
    return [_compact(part, 260) for part in parts if part]


def _repair_routes_for_provider_row(
    row: dict[str, Any],
    findings: list[dict[str, Any]],
    live_steps: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    routes: list[dict[str, Any]] = []
    codes = {
        str(finding.get("code") or "").strip()
        for finding in findings
        if isinstance(finding, dict)
    }
    live_names = {
        str(step.get("name") or "").strip()
        for step in live_steps
        if isinstance(step, dict)
    }
    profile = str(row.get("profile") or "").strip()
    if any(code in codes for code in {
        "missing_base_url",
        "missing_api_key",
        "unknown_provider",
        "qwen_base_url_not_compatible_mode",
        "kimi_coding_sampling_knobs",
        "glm_system_message_strictness",
    }):
        routes.append(_provider_repair_route(
            "provider_config",
            "Fix provider configuration flags, endpoint, model id, or credentials.",
            evidence=sorted(codes),
        ))
    if "thinking_wire_format_mismatch" in codes or "thinking" in live_names:
        routes.append(_provider_repair_route(
            "provider_thinking_protocol",
            "Adjust thinking_wire_format or disable unsupported thinking extensions.",
            evidence=sorted(codes | live_names),
        ))
    if "tool_wire" in live_names or "tool_use_disabled" in codes:
        routes.append(_provider_repair_route(
            "provider_tool_wire",
            "Verify tool schema support and tool_choice behavior.",
            evidence=sorted(codes | live_names),
        ))
    if "stream" in live_names:
        routes.append(_provider_repair_route(
            "provider_streaming",
            "Verify SSE stream parsing, read timeouts, and DONE handling.",
            evidence=sorted(live_names),
        ))
    if "basic_chat" in live_names:
        routes.append(_provider_repair_route(
            "provider_basic_chat",
            "Fix base request shape before testing optional agent features.",
            evidence=sorted(live_names),
        ))
    if not routes:
        routes.append(_provider_repair_route(
            f"provider_profile_{profile}" if profile else "provider_protocol",
            "Re-run live canary and tighten provider capability profile.",
            evidence=sorted(codes | live_names),
        ))
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for route in routes:
        route_id = str(route.get("route") or "")
        if route_id in seen:
            continue
        seen.add(route_id)
        deduped.append(route)
    return deduped


def _provider_repair_route(
    route: str,
    rationale: str,
    *,
    evidence: list[str],
) -> dict[str, Any]:
    return {
        "route": route,
        "rationale": rationale,
        "evidence": [item for item in evidence if item],
    }


def _load_custom_models(
    custom_models_path: str | Path | None,
) -> tuple[dict[str, Any], str]:
    if custom_models_path is None:
        from runtime.platform.process.paths import app_paths

        path = app_paths().custom_models_path
    else:
        path = Path(custom_models_path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return (data if isinstance(data, dict) else {}), str(path)
    except (OSError, json.JSONDecodeError, TypeError):
        return {}, str(path)


def _build_row(
    model_id: str,
    entry: dict[str, Any],
    *,
    live: bool,
    router_factory: LiveRouterFactory | None,
    timeout_seconds: float,
) -> ProviderCompatibilityRow:
    provider = str(entry.get("provider") or "openai").strip().lower() or "openai"
    models = _entry_models(entry, model_id)
    default_model = models[0] if models else model_id
    base_url = _redact_url(str(entry.get("base_url") or ""))
    profile = _infer_profile(entry, provider=provider, default_model=default_model)
    findings: list[ProviderCompatibilityFinding] = []
    capabilities = _capability_snapshot(
        entry,
        provider=provider,
        default_model=default_model,
    )

    if provider in {"openai", "openai-compatible", "openai_compat", ""}:
        findings.extend(_openai_compat_findings(entry, base_url, default_model, profile))
    elif provider in {"anthropic", "claude", "gemini", "google"}:
        if not entry.get("api_key"):
            findings.append(_finding("warning", "missing_api_key", "API key is not configured."))
    else:
        findings.append(_finding(
            "warning",
            "unknown_provider",
            f"Provider {provider!r} has no built-in compatibility profile.",
        ))

    if not models:
        findings.append(_finding("error", "missing_models", "No upstream model id is configured."))

    live_result: ProviderLiveProbeResult | None = None
    if live:
        live_result, live_findings = _run_live_probe(
            entry,
            provider=provider,
            default_model=default_model,
            capabilities=capabilities,
            router_factory=router_factory,
            timeout_seconds=timeout_seconds,
        )
        findings.extend(live_findings)

    score = _score(findings)
    verdict = _verdict(score, findings)
    return ProviderCompatibilityRow(
        id=str(entry.get("id") or model_id),
        provider=provider,
        display_name=str(entry.get("display_name") or entry.get("name") or model_id),
        base_url=base_url,
        models=models,
        profile=profile,
        has_api_key=bool(str(entry.get("api_key") or "").strip()),
        capabilities=capabilities,
        findings=findings,
        live=live_result,
        score=score,
        verdict=verdict,
    )


def _run_live_probe(
    entry: dict[str, Any],
    *,
    provider: str,
    default_model: str,
    capabilities: dict[str, Any],
    router_factory: LiveRouterFactory | None,
    timeout_seconds: float,
) -> tuple[ProviderLiveProbeResult, list[ProviderCompatibilityFinding]]:
    findings: list[ProviderCompatibilityFinding] = []
    if provider not in {"openai", "openai-compatible", "openai_compat", ""}:
        return (
            ProviderLiveProbeResult(
                enabled=True,
                status="review",
                steps=[ProviderLiveProbeStep(
                    name="live_supported",
                    status="skip",
                    detail=f"live canary is not implemented for provider {provider}",
                )],
            ),
            [_finding(
                "warning",
                "live_probe_not_implemented",
                f"Live canary is not implemented for provider {provider}.",
            )],
        )
    if not entry.get("base_url") or not entry.get("api_key"):
        return (
            ProviderLiveProbeResult(
                enabled=True,
                status="review",
                steps=[ProviderLiveProbeStep(
                    name="live_config",
                    status="skip",
                    detail="base_url or api_key missing",
                )],
            ),
            [],
        )

    factory = router_factory or _default_live_router_factory
    try:
        router = factory(entry, default_model, timeout_seconds)
    except Exception as exc:  # noqa: BLE001
        detail = _safe_exception_detail(exc, entry)
        findings.append(_finding("error", "live_router_init_failed", detail))
        return (
            ProviderLiveProbeResult(
                enabled=True,
                status="fail",
                steps=[ProviderLiveProbeStep(
                    name="router_init",
                    status="fail",
                    detail=detail,
                )],
            ),
            findings,
        )

    steps = [_live_basic_chat(router, default_model, entry)]
    if capabilities.get("supports_streaming"):
        steps.append(_live_stream(router, default_model, entry))
    if capabilities.get("supports_tool_use"):
        steps.append(_live_tool_wire(router, default_model, entry))
    if capabilities.get("supports_thinking"):
        steps.append(_live_thinking(router, default_model, entry))

    for step in steps:
        if step.status != "fail":
            continue
        severity: FindingSeverity = "error" if step.name == "basic_chat" else "warning"
        findings.append(_finding(severity, f"live_{step.name}_failed", step.detail))
    status: ProviderVerdict
    if any(step.status == "fail" and step.name == "basic_chat" for step in steps):
        status = "fail"
    elif any(step.status == "fail" for step in steps):
        status = "review"
    else:
        status = "pass"
    return ProviderLiveProbeResult(enabled=True, status=status, steps=steps), findings


def _default_live_router_factory(
    entry: dict[str, Any],
    default_model: str,
    timeout_seconds: float,
) -> Any:
    from .openai_router import OpenAIModelRouter

    headers = entry.get("default_headers") if isinstance(entry.get("default_headers"), dict) else {}
    return OpenAIModelRouter(
        base_url=str(entry.get("base_url") or ""),
        api_key=str(entry.get("api_key") or ""),
        default_model=default_model,
        extra_headers=dict(headers or {}),
        timeout_seconds=timeout_seconds,
    )


def _live_basic_chat(router: Any, model: str, entry: dict[str, Any]) -> ProviderLiveProbeStep:
    from .models import Message, ModelRequest

    def _run() -> str:
        response = router.call(ModelRequest(
            model=model,
            messages=[
                Message(role="system", content="Reply briefly."),
                Message(role="user", content="Reply with OK."),
            ],
            max_tokens=16,
            temperature=0.0,
        ))
        text = str(getattr(response, "text", "") or "").strip()
        return "response accepted" if text else "response accepted with empty text"

    return _timed_live_step("basic_chat", _run, entry)


def _live_stream(router: Any, model: str, entry: dict[str, Any]) -> ProviderLiveProbeStep:
    from .models import Message, ModelRequest

    def _run() -> str:
        events = []
        for index, event in enumerate(router.call_stream(ModelRequest(
            model=model,
            messages=[Message(role="user", content="Reply with OK.")],
            max_tokens=16,
            temperature=0.0,
        ))):
            events.append(str(getattr(event, "type", "") or ""))
            if index >= 64:
                break
        if not events:
            raise RuntimeError("stream returned no events")
        return "events=" + ",".join(events[:6])

    return _timed_live_step("stream", _run, entry)


def _live_tool_wire(router: Any, model: str, entry: dict[str, Any]) -> ProviderLiveProbeStep:
    from .models import Message, ModelRequest, ToolSpec

    def _run() -> str:
        response = router.call(ModelRequest(
            model=model,
            messages=[
                Message(
                    role="user",
                    content="If tool calling is available, call probe_tool once.",
                )
            ],
            max_tokens=64,
            temperature=0.0,
            tools=[ToolSpec(
                name="probe_tool",
                description="Compatibility canary tool.",
                input_schema={
                    "type": "object",
                    "properties": {"ok": {"type": "boolean"}},
                    "additionalProperties": True,
                },
            )],
        ))
        calls = list(getattr(response, "tool_calls", []) or [])
        return f"tools schema accepted; tool_calls={len(calls)}"

    return _timed_live_step("tool_wire", _run, entry)


def _live_thinking(router: Any, model: str, entry: dict[str, Any]) -> ProviderLiveProbeStep:
    from .models import Message, ModelRequest

    def _run() -> str:
        response = router.call(ModelRequest(
            model=model,
            messages=[Message(role="user", content="Think briefly, then reply OK.")],
            max_tokens=128,
            temperature=0.0,
            enable_thinking=True,
            reasoning_effort="low",
        ))
        thinking = str(getattr(response, "thinking", "") or "").strip()
        return "thinking emitted" if thinking else "thinking request accepted"

    return _timed_live_step("thinking", _run, entry)


def _timed_live_step(
    name: str,
    fn: Callable[[], str],
    entry: dict[str, Any],
) -> ProviderLiveProbeStep:
    started = time.perf_counter()
    try:
        detail = fn()
        return ProviderLiveProbeStep(
            name=name,
            status="pass",
            detail=_redact_secret_text(str(detail), entry),
            duration_ms=(time.perf_counter() - started) * 1000,
        )
    except Exception as exc:  # noqa: BLE001
        return ProviderLiveProbeStep(
            name=name,
            status="fail",
            detail=_safe_exception_detail(exc, entry),
            duration_ms=(time.perf_counter() - started) * 1000,
        )


def _entry_models(entry: dict[str, Any], model_id: str) -> list[str]:
    raw = entry.get("models")
    if isinstance(raw, list):
        models = [str(model).strip() for model in raw if str(model or "").strip()]
        if models:
            return models
    legacy = entry.get("model")
    if isinstance(legacy, str) and legacy.strip():
        return [legacy.strip()]
    return [model_id] if model_id else []


def _capability_snapshot(
    entry: dict[str, Any],
    *,
    provider: str,
    default_model: str,
) -> dict[str, Any]:
    if provider in {"openai", "openai-compatible", "openai_compat", ""}:
        caps = resolve_openai_compat_model_capabilities(default_model, entry)
        return {
            "supports_streaming": True,
            "supports_tool_use": caps.supports_tool_use,
            "supports_thinking": caps.supports_thinking,
            "supports_vision": bool(entry.get("supports_vision", False)),
            "omit_sampling_parameters": caps.omit_sampling_parameters,
            "omit_system_messages": caps.omit_system_messages,
            "thinking_wire_format": caps.thinking_wire_format,
        }
    if provider in {"anthropic", "claude"}:
        return {
            "supports_streaming": True,
            "supports_tool_use": True,
            "supports_thinking": bool(entry.get("supports_thinking", True)),
            "supports_vision": bool(entry.get("supports_vision", False)),
        }
    if provider in {"gemini", "google"}:
        return {
            "supports_streaming": True,
            "supports_tool_use": True,
            "supports_thinking": bool(entry.get("supports_thinking", False)),
            "supports_vision": bool(entry.get("supports_vision", True)),
        }
    return {
        "supports_streaming": bool(entry.get("supports_streaming", False)),
        "supports_tool_use": bool(entry.get("supports_tool_use", False)),
        "supports_thinking": bool(entry.get("supports_thinking", False)),
        "supports_vision": bool(entry.get("supports_vision", False)),
    }


def _openai_compat_findings(
    entry: dict[str, Any],
    base_url: str,
    default_model: str,
    profile: str,
) -> list[ProviderCompatibilityFinding]:
    findings: list[ProviderCompatibilityFinding] = []
    if not base_url:
        findings.append(_finding("error", "missing_base_url", "OpenAI-compatible models need base_url."))
    if not entry.get("api_key"):
        findings.append(_finding("warning", "missing_api_key", "API key is not configured."))
    caps = resolve_openai_compat_model_capabilities(default_model, entry)
    if not caps.supports_tool_use:
        findings.append(_finding(
            "info",
            "tool_use_disabled",
            "Native tool calling is disabled; ReAct text fallback will be used.",
        ))
    if profile == "kimi_coding" and not caps.omit_sampling_parameters:
        findings.append(_finding(
            "warning",
            "kimi_coding_sampling_knobs",
            "Kimi coding endpoints are strict; omit_sampling_parameters is recommended.",
        ))
    if profile == "qwen_dashscope" and "compatible-mode" not in base_url.lower():
        findings.append(_finding(
            "warning",
            "qwen_base_url_not_compatible_mode",
            "Qwen OpenAI-compatible routing should use DashScope compatible-mode /v1.",
        ))
    if profile == "qwen_dashscope" and caps.supports_thinking and caps.thinking_wire_format != "qwen_enable_thinking":
        findings.append(_finding(
            "warning",
            "thinking_wire_format_mismatch",
            "Qwen/DashScope thinking should use thinking_wire_format=qwen_enable_thinking.",
        ))
    if profile == "deepseek_reasoner" and caps.supports_thinking and caps.thinking_wire_format != "implicit":
        findings.append(_finding(
            "warning",
            "thinking_wire_format_mismatch",
            "DeepSeek reasoner-style models should rely on the reasoning model route, not OpenAI thinking extension fields.",
        ))
    if profile == "glm_strict" and not caps.omit_system_messages:
        findings.append(_finding(
            "warning",
            "glm_system_message_strictness",
            "Strict GLM coding models may need omit_system_messages=true.",
        ))
    if profile == "minimax" and caps.supports_thinking and caps.thinking_wire_format == "openai":
        findings.append(_finding(
            "warning",
            "thinking_wire_format_mismatch",
            "MiniMax OpenAI-compatible thinking uses provider-specific behavior; verify thinking_wire_format with a live canary.",
        ))
    if profile in {"qianfan", "volcengine_ark"} and not base_url.endswith("/v1") and "/api/v3" not in base_url:
        findings.append(_finding(
            "warning",
            f"{profile}_base_url_review",
            f"{profile} OpenAI-compatible routing usually needs the documented compatible Chat Completions base URL.",
        ))
    return findings


def _infer_profile(
    entry: dict[str, Any],
    *,
    provider: str,
    default_model: str,
) -> str:
    haystack = " ".join(
        str(value or "")
        for value in [
            provider,
            entry.get("id"),
            entry.get("name"),
            entry.get("display_name"),
            entry.get("base_url"),
            default_model,
        ]
    ).lower()
    if "api.kimi.com/coding" in haystack or ("kimi" in haystack and "coding" in haystack):
        return "kimi_coding"
    if "kimi" in haystack or "moonshot" in haystack:
        return "kimi"
    if "dashscope" in haystack or "qwen" in haystack or "通义" in haystack:
        return "qwen_dashscope"
    if "deepseek-reasoner" in haystack or "deepseek-r1" in haystack:
        return "deepseek_reasoner"
    if "deepseek" in haystack:
        return "deepseek"
    if "glm-5.1" in haystack:
        return "glm_strict"
    if "glm" in haystack or "zhipu" in haystack or "z.ai" in haystack:
        return "glm"
    if "minimax" in haystack:
        return "minimax"
    if "qianfan" in haystack or "wenxin" in haystack or "baidu" in haystack or "文心" in haystack:
        return "qianfan"
    if "volces" in haystack or "volcengine" in haystack or "ark" in haystack or "doubao" in haystack or "豆包" in haystack or "火山" in haystack:
        return "volcengine_ark"
    if "baichuan" in haystack or "百川" in haystack:
        return "baichuan"
    if provider in {"openai", "openai-compatible", "openai_compat", ""}:
        return "openai_compat"
    return provider or "unknown"


def _redact_url(value: str) -> str:
    if not value:
        return ""
    try:
        parts = urlsplit(value)
    except ValueError:
        return value.split("?", 1)[0]
    netloc = parts.hostname or ""
    if parts.port:
        netloc = f"{netloc}:{parts.port}"
    return urlunsplit((parts.scheme, netloc, parts.path.rstrip("/"), "", ""))


def _safe_exception_detail(exc: Exception, entry: dict[str, Any]) -> str:
    return _redact_secret_text(f"{type(exc).__name__}: {exc}", entry)


def _redact_secret_text(value: str, entry: dict[str, Any]) -> str:
    text = value or ""
    for candidate in _secret_candidates(entry):
        if candidate:
            text = text.replace(candidate, "[redacted]")
    text = re.sub(r"Bearer\s+[A-Za-z0-9._~+/=-]+", "Bearer [redacted]", text, flags=re.I)
    text = re.sub(r"sk-[A-Za-z0-9._~/-]{8,}", "sk-[redacted]", text)
    text = re.sub(r"(?i)(api[_-]?key=)[^&\s]+", r"\1[redacted]", text)
    text = re.sub(r"(?i)(token=)[^&\s]+", r"\1[redacted]", text)
    return _compact(text, 260)


def _redact_payload(value: Any) -> Any:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if key_text.lower() in {"api_key", "authorization"}:
                out[key_text] = "[redacted]"
                continue
            out[key_text] = _redact_payload(item)
        return out
    if isinstance(value, list):
        return [_redact_payload(item) for item in value]
    if isinstance(value, str):
        return _redact_secret_text(value, {})
    return value


def _secret_candidates(entry: dict[str, Any]) -> list[str]:
    candidates: list[str] = []
    for key in ("api_key", "base_url"):
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            candidates.append(value.strip())
    base_url = entry.get("base_url")
    if isinstance(base_url, str):
        try:
            parts = urlsplit(base_url)
            if parts.username:
                candidates.append(parts.username)
            if parts.password:
                candidates.append(parts.password)
            if parts.query:
                candidates.append(parts.query)
        except ValueError:
            pass
    return sorted(set(candidates), key=len, reverse=True)


def _compact(value: str, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _finding(
    severity: FindingSeverity,
    code: str,
    message: str,
) -> ProviderCompatibilityFinding:
    return ProviderCompatibilityFinding(severity=severity, code=code, message=message)


def _score(findings: list[ProviderCompatibilityFinding]) -> int:
    score = 100
    for finding in findings:
        if finding.severity == "error":
            score -= 35
        elif finding.severity == "warning":
            score -= 12
    return max(0, score)


def _verdict(
    score: int,
    findings: list[ProviderCompatibilityFinding],
) -> ProviderVerdict:
    if any(finding.severity == "error" for finding in findings) or score < 60:
        return "fail"
    if any(finding.severity == "warning" for finding in findings) or score < 85:
        return "review"
    return "pass"


__all__ = [
    "ProviderCompatibilityFinding",
    "ProviderCompatibilityMatrixReport",
    "ProviderCompatibilityRow",
    "ProviderLiveProbeResult",
    "ProviderLiveProbeStep",
    "append_provider_compatibility_history",
    "build_provider_compatibility_matrix",
    "export_provider_compatibility_failures",
    "extract_provider_compatibility_failures",
    "read_provider_compatibility_history",
    "summarize_provider_compatibility_history",
]
