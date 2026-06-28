from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from runtime.platform.process.paths import project_root as default_project_root
from runtime.sensing.model_router.models import Message, ModelRequest
from runtime.sensing.model_router.openai_router import OpenAIModelRouter
from runtime.sensing.model_router.provider_compat_matrix import (
    append_provider_compatibility_history,
    build_provider_compatibility_matrix,
    compute_provider_profile_coverage,
    export_provider_compatibility_failures,
    extract_provider_compatibility_failures,
)

SCHEMA = "octopus.model_provider_runtime_readiness.v1"
PROBE_SCHEMA = "octopus.model_provider_runtime_probe.v1"


@dataclass(frozen=True)
class ModelProviderRuntimeCheck:
    id: str
    title: str
    paths: tuple[str, ...]
    required_terms: tuple[str, ...]
    weight: int = 1


CHECKS: tuple[ModelProviderRuntimeCheck, ...] = (
    ModelProviderRuntimeCheck(
        id="provider_compatibility_matrix",
        title="Provider compatibility matrix",
        paths=(
            "runtime/sensing/model_router/provider_compat_matrix.py",
            "scripts/provider_compat_matrix.py",
            "tests/test_provider_compat_matrix.py",
        ),
        required_terms=(
            "octopus.provider_compatibility_matrix.v1",
            "compute_provider_profile_coverage",
            "extract_provider_compatibility_failures",
            "export_provider_compatibility_failures",
            "_BUILTIN_DOMESTIC_PROFILE_CHECKS",
        ),
        weight=3,
    ),
    ModelProviderRuntimeCheck(
        id="openai_compat_payload_shaping",
        title="OpenAI-compatible payload shaping",
        paths=(
            "runtime/sensing/model_router/openai_router.py",
            "tests/test_openai_router.py",
        ),
        required_terms=(
            "omit_sampling_parameters",
            "omit_system_messages",
            "qwen_enable_thinking",
            "implicit",
            "_should_retry_without_openai_thinking",
            "_sanitize_openai_messages",
        ),
        weight=3,
    ),
    ModelProviderRuntimeCheck(
        id="domestic_profile_coverage",
        title="Domestic provider profile coverage",
        paths=("runtime/sensing/model_router/provider_compat_matrix.py",),
        required_terms=(
            "kimi_coding",
            "qwen_dashscope",
            "deepseek_reasoner",
            "glm_strict",
            "volcengine_ark",
            "baichuan",
        ),
        weight=3,
    ),
    ModelProviderRuntimeCheck(
        id="provider_health_surface",
        title="Provider health surface",
        paths=(
            "runtime/platform/observability/provider_compat_health.py",
            "tests/test_provider_compat_matrix.py",
        ),
        required_terms=(
            "provider_compatibility_check",
            "run_provider_compatibility_probe",
            "finding_codes",
            "capabilities",
        ),
        weight=2,
    ),
    ModelProviderRuntimeCheck(
        id="scorecard_provider_runtime_surface",
        title="Scorecard provider runtime surface",
        paths=(
            "runtime/safety/evolution/agent_competitor_scorecard.py",
            "tests/test_evolution_modules.py",
            "tests/test_evolution_router.py",
        ),
        required_terms=(
            "octopus.agent_scorecard_provider_runtime.v1",
            "model_provider_runtime",
            "builtin_profile_coverage",
            "configured_profile_gaps_are_not_builtin_support_gaps",
        ),
        weight=2,
    ),
)


def compute_model_provider_runtime_readiness(
    *,
    root: str | Path | None = None,
    include_probe: bool = True,
) -> dict[str, Any]:
    base = Path(root) if root is not None else default_project_root(Path(__file__))
    checks = [_check_status(base, check) for check in CHECKS]
    probe = run_model_provider_runtime_probe() if include_probe else _skipped_probe()
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
            "schema": "octopus.model_provider_runtime_calibration.v1",
            "compares_to": {
                "codex": "first-party OpenAI model runtime plus documented Bedrock provider path",
                "kimi_agent_swarm": "strong domestic-model integration with Kimi-first workflows",
            },
            "octopus_edge": (
                "offline compatibility matrix, domestic-provider profile coverage, "
                "OpenAI-compatible payload shaping probes, redacted failure export, "
                "and health/scorecard integration"
            ),
        },
    }


def run_model_provider_runtime_probe() -> dict[str, Any]:
    entries = _probe_entries()
    matrix = build_provider_compatibility_matrix(entries=entries).to_dict()
    coverage = compute_provider_profile_coverage().to_dict()
    payload_probe = _payload_shape_probe(entries)
    failure_probe = _failure_export_probe()
    configured_profiles = {
        str(row.get("profile") or "")
        for row in matrix.get("rows", [])
        if isinstance(row, dict)
    }
    ok = (
        matrix.get("verdict") == "pass"
        and int(matrix.get("score") or 0) == 100
        and coverage.get("ready") is True
        and payload_probe.get("ok") is True
        and failure_probe.get("ok") is True
        and not _contains_secret(matrix)
        and {"kimi_coding", "qwen_dashscope", "deepseek_reasoner", "glm_strict"}.issubset(
            configured_profiles,
        )
    )
    return {
        "schema": PROBE_SCHEMA,
        "ok": ok,
        "matrix_score": matrix.get("score"),
        "matrix_verdict": matrix.get("verdict"),
        "matrix_row_count": len(matrix.get("rows", [])),
        "configured_profiles": sorted(configured_profiles),
        "builtin_profile_coverage": coverage,
        "payload_shape": payload_probe,
        "failure_export": failure_probe,
        "secrets_redacted": not _contains_secret({
            "matrix": matrix,
            "payload_shape": payload_probe,
            "failure_export": failure_probe,
        }),
    }


def _probe_entries() -> dict[str, dict[str, Any]]:
    return {
        "kimi-code": {
            "id": "kimi-code",
            "provider": "openai",
            "base_url": "https://api.kimi.com/coding/v1",
            "api_key": "sk-secret-kimi",
            "models": ["kimi-k2.7-code"],
            "supports_thinking": True,
            "supports_tool_use": True,
            "omit_sampling_parameters": True,
        },
        "qwen-thinking": {
            "id": "qwen-thinking",
            "provider": "openai",
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "api_key": "sk-secret-qwen",
            "models": ["qwen3-max"],
            "supports_thinking": True,
        },
        "deepseek-reasoner": {
            "id": "deepseek-reasoner",
            "provider": "openai",
            "base_url": "https://api.deepseek.com/v1",
            "api_key": "sk-secret-deepseek",
            "models": ["deepseek-reasoner"],
            "supports_thinking": True,
        },
        "glm-strict": {
            "id": "glm-strict",
            "provider": "openai",
            "base_url": "https://open.bigmodel.cn/api/paas/v4",
            "api_key": "sk-secret-glm",
            "models": ["glm-5.1-code"],
            "omit_system_messages": True,
        },
        "deepseek-chat": {
            "id": "deepseek-chat",
            "provider": "openai",
            "base_url": "https://api.deepseek.com/v1",
            "api_key": "sk-secret-deepseek-chat",
            "models": ["deepseek-chat"],
            "supports_tool_use": True,
        },
        "baichuan": {
            "id": "baichuan",
            "provider": "openai",
            "base_url": "https://api.baichuan-ai.com/v1",
            "api_key": "sk-secret-baichuan",
            "models": ["baichuan4"],
        },
    }


def _payload_shape_probe(entries: dict[str, dict[str, Any]]) -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "custom_models.json"
        path.write_text(json.dumps(entries), encoding="utf-8")
        original = _patch_app_paths(path)
        try:
            payloads = {
                "kimi_coding": _payload_for("kimi-k2.7-code"),
                "qwen_dashscope": _payload_for(
                    "qwen3-max",
                    enable_thinking=True,
                    max_tokens=2048,
                ),
                "deepseek_reasoner": _payload_for(
                    "deepseek-reasoner",
                    enable_thinking=True,
                ),
                "glm_strict": _payload_for(
                    "glm-5.1-code",
                    messages=[
                        Message(role="system", content="system policy"),
                        Message(role="user", content="hello"),
                    ],
                ),
            }
        finally:
            _restore_app_paths(original)

    requirements = {
        "kimi_omits_sampling_parameters": (
            "temperature" not in payloads["kimi_coding"]
            and payloads["kimi_coding"].get("max_tokens") == 128
        ),
        "qwen_uses_enable_thinking": (
            payloads["qwen_dashscope"].get("enable_thinking") is True
            and "thinking_budget" in payloads["qwen_dashscope"]
            and "reasoning_effort" not in payloads["qwen_dashscope"]
            and "thinking" not in payloads["qwen_dashscope"]
        ),
        "deepseek_reasoner_uses_implicit_thinking": all(
            key not in payloads["deepseek_reasoner"]
            for key in (
                "enable_thinking",
                "thinking_budget",
                "reasoning_effort",
                "thinking",
            )
        ),
        "glm_strict_omits_system_messages": payloads["glm_strict"].get("messages")
        == [{"role": "user", "content": "hello"}],
    }
    return {
        "schema": "octopus.model_provider_payload_shape_probe.v1",
        "ok": all(requirements.values()),
        "requirements": requirements,
        "payload_keys": {
            name: sorted(payload.keys())
            for name, payload in payloads.items()
        },
    }


def _failure_export_probe() -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmp:
        history = Path(tmp) / "history.jsonl"
        out = Path(tmp) / "failures.jsonl"
        report = build_provider_compatibility_matrix(
            entries={
                "qwen-thinking": {
                    "id": "qwen-thinking",
                    "provider": "openai",
                    "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1?token=secret",
                    "api_key": "sk-secret-qwen",
                    "models": ["qwen3-max"],
                    "supports_thinking": True,
                    "thinking_wire_format": "openai",
                }
            },
        )
        append_provider_compatibility_history(report, path=history)
        samples = extract_provider_compatibility_failures(path=history)
        export_provider_compatibility_failures(out, history_path=history)
        text = out.read_text(encoding="utf-8") if out.exists() else ""
    return {
        "schema": "octopus.model_provider_failure_export_probe.v1",
        "ok": (
            len(samples) == 1
            and samples[0].get("source") == "provider_compatibility"
            and samples[0].get("primary_repair_route") == "provider_thinking_protocol"
            and "thinking_wire_format_mismatch" in str(samples[0].get("last_error") or "")
            and "sk-secret" not in text
            and "token=secret" not in text
        ),
        "sample_count": len(samples),
        "primary_repair_route": samples[0].get("primary_repair_route") if samples else "",
        "secrets_redacted": "sk-secret" not in text and "token=secret" not in text,
    }


def _payload_for(
    model: str,
    *,
    enable_thinking: bool = False,
    max_tokens: int = 128,
    messages: list[Message] | None = None,
) -> dict[str, Any]:
    fake = _CaptureClient()
    router = OpenAIModelRouter(base_url="https://example.invalid/v1", client=fake)
    router.call(
        ModelRequest(
            model=model,
            messages=messages or [Message(role="user", content="hello")],
            max_tokens=max_tokens,
            temperature=0.7,
            enable_thinking=enable_thinking,
            reasoning_effort="low",
        ),
    )
    return fake.calls[0]["json"]


class _CaptureClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def post(self, url: str, *, json: dict[str, Any] | None = None, headers: dict[str, str] | None = None):
        self.calls.append({"url": url, "json": json or {}, "headers": headers or {}})
        return _CaptureResponse()

    def close(self) -> None:
        return None


class _CaptureResponse:
    status_code = 200
    text = '{"choices":[{"message":{"content":"OK"},"finish_reason":"stop"}],"usage":{}}'

    def json(self) -> dict[str, Any]:
        return {
            "choices": [
                {
                    "message": {"role": "assistant", "content": "OK"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {},
        }


def _patch_app_paths(custom_models_path: Path) -> Any:
    import runtime.platform.process.paths as paths_module

    original = paths_module.app_paths
    base = original()

    class _PatchedPaths:
        @property
        def custom_models_path(self) -> Path:
            return custom_models_path

        def __getattr__(self, name: str) -> Any:
            return getattr(base, name)

    paths_module.app_paths = lambda root=None: _PatchedPaths() if root is None else original(root)  # type: ignore[assignment]
    return original


def _restore_app_paths(original: Any) -> None:
    import runtime.platform.process.paths as paths_module

    paths_module.app_paths = original  # type: ignore[assignment]


def _probe_checks(probe: dict[str, Any]) -> list[dict[str, Any]]:
    payload = probe.get("payload_shape") if isinstance(probe.get("payload_shape"), dict) else {}
    failure = probe.get("failure_export") if isinstance(probe.get("failure_export"), dict) else {}
    coverage = (
        probe.get("builtin_profile_coverage")
        if isinstance(probe.get("builtin_profile_coverage"), dict)
        else {}
    )
    return [
        _dynamic_check(
            "provider_matrix_probe",
            "Provider matrix probe",
            probe.get("matrix_verdict") == "pass"
            and int(probe.get("matrix_score") or 0) == 100
            and int(probe.get("matrix_row_count") or 0) >= 4,
            "Matrix probe must pass with strict domestic provider examples.",
            weight=3,
        ),
        _dynamic_check(
            "provider_payload_shape_probe",
            "Provider payload shape probe",
            payload.get("ok") is True,
            "OpenAI-compatible payloads must match Kimi/Qwen/DeepSeek/GLM quirks.",
            weight=4,
        ),
        _dynamic_check(
            "provider_failure_export_probe",
            "Provider failure export probe",
            failure.get("ok") is True and failure.get("secrets_redacted") is True,
            "Provider failure samples must export with redacted secrets and repair routes.",
            weight=3,
        ),
        _dynamic_check(
            "provider_builtin_coverage_probe",
            "Provider built-in coverage probe",
            coverage.get("ready") is True
            and not coverage.get("missing_profiles"),
            "Built-in domestic provider profile coverage must be complete.",
            weight=2,
        ),
        _dynamic_check(
            "provider_secret_hygiene_probe",
            "Provider secret hygiene probe",
            probe.get("secrets_redacted") is True,
            "Provider readiness payload must not contain raw API keys or URL tokens.",
            weight=2,
        ),
    ]


def _check_status(base: Path, check: ModelProviderRuntimeCheck) -> dict[str, Any]:
    paths = [
        {"path": path, "exists": (base / path).exists()}
        for path in check.paths
    ]
    text = "\n".join(
        _read_text(base / str(row["path"]))
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
        "next_action": f"Complete model provider runtime check: {check.title}.",
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
        return ["Model provider runtime checks are ready."]
    return [str(row.get("next_action")) for row in missing if row.get("next_action")]


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _contains_secret(value: Any) -> bool:
    text = json.dumps(value, ensure_ascii=False, default=str).lower()
    return any(token in text for token in ("sk-secret", "token=secret", "user:pass"))


__all__ = [
    "CHECKS",
    "ModelProviderRuntimeCheck",
    "PROBE_SCHEMA",
    "SCHEMA",
    "compute_model_provider_runtime_readiness",
    "run_model_provider_runtime_probe",
]
