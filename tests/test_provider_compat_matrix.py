from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from runtime.safety.recovery.evolution_dataset import EvolutionDatasetBuilder
from runtime.sensing.model_router.models import ModelResponse, ModelStreamEvent, ToolCall
from runtime.sensing.model_router.provider_compat_matrix import (
    append_provider_compatibility_history,
    build_provider_compatibility_matrix,
    compute_provider_profile_coverage,
    export_provider_compatibility_failures,
    extract_provider_compatibility_failures,
    summarize_provider_compatibility_history,
)

ROOT = Path(__file__).resolve().parents[1]


def _sample_entries() -> dict[str, dict[str, object]]:
    return {
        "kimi-code": {
            "id": "kimi-code",
            "name": "Kimi Code",
            "provider": "openai",
            "base_url": "https://user:pass@api.kimi.com/coding/v1?token=secret",
            "api_key": "sk-secret-kimi",
            "models": ["kimi-for-coding"],
            "supports_thinking": True,
            "supports_tool_use": True,
        },
        "qwen-bad-url": {
            "id": "qwen-bad-url",
            "name": "Qwen Bad URL",
            "provider": "openai",
            "base_url": "https://dashscope.aliyuncs.com/api/v1",
            "api_key": "sk-secret-qwen",
            "models": ["qwen-plus"],
            "supports_tool_use": True,
        },
    }


class _LiveOkRouter:
    def call(self, request):
        tool_calls = []
        if request.tools:
            tool_calls = [ToolCall(id="probe", name="probe_tool", input={"ok": True})]
        return ModelResponse(
            text="OK",
            thinking="brief thought" if request.enable_thinking else "",
            tool_calls=tool_calls,
            model=request.model,
            provider="test",
        )

    def call_stream(self, request):
        yield ModelStreamEvent(type="text_delta", delta="O")
        yield ModelStreamEvent(
            type="done",
            final=ModelResponse(text="OK", model=request.model, provider="test"),
        )


class _LiveFailRouter:
    def call(self, request):
        raise RuntimeError("upstream rejected sk-secret-kimi token=secret")

    def call_stream(self, request):
        raise RuntimeError("stream failed sk-secret-kimi")


def _run_script(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "scripts/provider_compat_matrix.py", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )


def test_provider_compat_matrix_flags_domestic_provider_quirks_without_secrets():
    report = build_provider_compatibility_matrix(entries=_sample_entries())
    payload = report.to_dict()
    rows = {row["id"]: row for row in payload["rows"]}

    assert payload["verdict"] == "review"
    assert rows["kimi-code"]["profile"] == "kimi_coding"
    assert rows["kimi-code"]["base_url"] == "https://api.kimi.com/coding/v1"
    assert rows["kimi-code"]["has_api_key"] is True
    assert {
        finding["code"] for finding in rows["kimi-code"]["findings"]
    } == {"kimi_coding_sampling_knobs"}
    assert rows["qwen-bad-url"]["profile"] == "qwen_dashscope"
    assert {
        finding["code"] for finding in rows["qwen-bad-url"]["findings"]
    } == {"qwen_base_url_not_compatible_mode"}

    serialized = json.dumps(payload, ensure_ascii=False)
    assert "sk-secret" not in serialized
    assert "user:pass" not in serialized
    assert "token=secret" not in serialized


def test_provider_compat_matrix_flags_non_kimi_domestic_thinking_profiles():
    report = build_provider_compatibility_matrix(
        entries={
            "qwen-thinking": {
                "id": "qwen-thinking",
                "provider": "openai",
                "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                "api_key": "sk-secret-qwen",
                "models": ["qwen3-max"],
                "supports_thinking": True,
                "thinking_wire_format": "openai",
            },
            "deepseek-reasoner": {
                "id": "deepseek-reasoner",
                "provider": "openai",
                "base_url": "https://api.deepseek.com/v1",
                "api_key": "sk-secret-deepseek",
                "models": ["deepseek-reasoner"],
                "supports_thinking": True,
                "thinking_wire_format": "openai",
            },
            "glm-code": {
                "id": "glm-code",
                "provider": "openai",
                "base_url": "https://open.bigmodel.cn/api/paas/v4",
                "api_key": "sk-secret-glm",
                "models": ["glm-5.1-code"],
                "omit_system_messages": False,
            },
            "ark-doubao": {
                "id": "ark-doubao",
                "provider": "openai",
                "base_url": "https://ark.cn-beijing.volces.com/bad-path",
                "api_key": "sk-secret-ark",
                "models": ["doubao-seed"],
            },
        },
    )
    rows = {row.id: row.to_dict() for row in report.rows}

    assert rows["qwen-thinking"]["profile"] == "qwen_dashscope"
    assert rows["qwen-thinking"]["capabilities"]["thinking_wire_format"] == "openai"
    assert {
        finding["code"] for finding in rows["qwen-thinking"]["findings"]
    } == {"thinking_wire_format_mismatch"}
    assert rows["deepseek-reasoner"]["profile"] == "deepseek_reasoner"
    assert {
        finding["code"] for finding in rows["deepseek-reasoner"]["findings"]
    } == {"thinking_wire_format_mismatch"}
    assert rows["glm-code"]["profile"] == "glm_strict"
    assert {
        finding["code"] for finding in rows["glm-code"]["findings"]
    } == {"glm_system_message_strictness"}
    assert rows["ark-doubao"]["profile"] == "volcengine_ark"
    assert {
        finding["code"] for finding in rows["ark-doubao"]["findings"]
    } == {"volcengine_ark_base_url_review"}


def test_provider_profile_coverage_separates_builtin_support_from_configured_models():
    coverage = compute_provider_profile_coverage()
    payload = coverage.to_dict()

    assert payload["schema"] == "octopus.provider_profile_coverage.v1"
    assert payload["ready"] is True
    assert payload["coverage_rate"] == 1.0
    assert payload["missing_profiles"] == []
    assert set(payload["required_profiles"]) == {
        "kimi_coding",
        "kimi",
        "qwen_dashscope",
        "deepseek_reasoner",
        "deepseek",
        "glm_strict",
        "glm",
        "minimax",
        "qianfan",
        "volcengine_ark",
        "baichuan",
    }
    assert "strict_sampling_knob_check" in payload["checks"]["kimi_coding"]
    assert "qwen_thinking_wire_format_check" in payload["checks"]["qwen_dashscope"]
    assert "compatible_base_url_review" in payload["checks"]["volcengine_ark"]


def test_provider_compat_matrix_script_outputs_json_and_text(tmp_path: Path):
    path = tmp_path / "custom_models.json"
    path.write_text(json.dumps(_sample_entries()), encoding="utf-8")

    result = _run_script("--path", str(path))
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    payload = json.loads(result.stdout)
    assert payload["schema"] == "octopus.provider_compatibility_matrix.v1"
    assert payload["source"] == str(path)
    assert payload["verdict"] == "review"
    assert "sk-secret" not in result.stdout

    text = _run_script("--path", str(path), "--format", "text")
    assert text.returncode == 0, f"stdout={text.stdout}\nstderr={text.stderr}"
    assert "provider_compatibility_matrix: review" in text.stdout
    assert "kimi-code: review" in text.stdout
    assert "qwen_base_url_not_compatible_mode" in text.stdout
    assert "sk-secret" not in text.stdout


def test_provider_compat_matrix_strict_mode_fails_on_review(tmp_path: Path):
    path = tmp_path / "custom_models.json"
    path.write_text(json.dumps(_sample_entries()), encoding="utf-8")

    result = _run_script("--path", str(path), "--strict")

    assert result.returncode == 1


def test_provider_compat_matrix_live_probe_success_uses_sanitized_shape():
    report = build_provider_compatibility_matrix(
        entries={
            "kimi-code": {
                **_sample_entries()["kimi-code"],
                "omit_sampling_parameters": True,
            }
        },
        live=True,
        router_factory=lambda _entry, _model, _timeout: _LiveOkRouter(),
    )
    payload = report.to_dict()
    row = payload["rows"][0]

    assert payload["live_mode"] is True
    assert payload["verdict"] == "pass"
    assert row["live"]["status"] == "pass"
    assert [step["name"] for step in row["live"]["steps"]] == [
        "basic_chat",
        "stream",
        "tool_wire",
        "thinking",
    ]
    assert all(step["status"] == "pass" for step in row["live"]["steps"])
    assert "sk-secret" not in json.dumps(payload)


def test_provider_compat_matrix_live_probe_failure_redacts_secrets():
    report = build_provider_compatibility_matrix(
        entries={
            "kimi-code": {
                **_sample_entries()["kimi-code"],
                "omit_sampling_parameters": True,
            }
        },
        live=True,
        router_factory=lambda _entry, _model, _timeout: _LiveFailRouter(),
    )
    payload = report.to_dict()
    row = payload["rows"][0]

    assert payload["verdict"] == "fail"
    assert row["live"]["status"] == "fail"
    assert row["findings"][0]["code"] == "live_basic_chat_failed"
    serialized = json.dumps(payload, ensure_ascii=False)
    assert "sk-secret" not in serialized
    assert "token=secret" not in serialized
    assert "[redacted]" in serialized


def test_provider_compat_history_records_redacted_trend(tmp_path: Path):
    path = tmp_path / "provider_compat_history.jsonl"
    report = build_provider_compatibility_matrix(
        entries={
            "kimi-code": {
                **_sample_entries()["kimi-code"],
                "omit_sampling_parameters": True,
            }
        },
        live=True,
        router_factory=lambda _entry, _model, _timeout: _LiveFailRouter(),
    )

    written = append_provider_compatibility_history(report, path=path)
    summary = summarize_provider_compatibility_history(path=path)

    assert written == path
    assert summary.total_runs == 1
    assert summary.pass_rate == 0
    assert summary.latest_verdict == "fail"
    assert summary.latest_rows == [{
        "id": "kimi-code",
        "profile": "kimi_coding",
        "score": 29,
        "verdict": "fail",
        "live_status": "fail",
    }]
    content = path.read_text(encoding="utf-8")
    assert "sk-secret" not in content
    assert "token=secret" not in content
    assert "[redacted]" in content


def test_provider_compat_matrix_script_records_and_reads_history(tmp_path: Path):
    path = tmp_path / "custom_models.json"
    history = tmp_path / "history.jsonl"
    path.write_text(
        json.dumps({
            "kimi-code": {
                **_sample_entries()["kimi-code"],
                "omit_sampling_parameters": True,
            }
        }),
        encoding="utf-8",
    )

    record = _run_script(
        "--path",
        str(path),
        "--record",
        "--history-path",
        str(history),
    )
    assert record.returncode == 0, f"stdout={record.stdout}\nstderr={record.stderr}"
    assert history.exists()
    assert "sk-secret" not in history.read_text(encoding="utf-8")

    result = _run_script(
        "--history",
        "--history-path",
        str(history),
        "--format",
        "text",
    )
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    assert "provider_compatibility_history: runs=1" in result.stdout
    assert "latest=pass" in result.stdout
    assert "kimi-code: pass" in result.stdout
    assert "sk-secret" not in result.stdout


def test_provider_compat_failures_export_as_evolution_samples(tmp_path: Path):
    history = tmp_path / "history.jsonl"
    out = tmp_path / "failures.jsonl"
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
    written = export_provider_compatibility_failures(out, history_path=history)
    dataset = EvolutionDatasetBuilder(
        synthetic_variants_per_failure=0,
    ).build_from_failure_samples(samples)

    assert written == out
    assert len(samples) == 1
    assert samples[0]["source"] == "provider_compatibility"
    assert samples[0]["failure_source"] == "provider_compatibility_matrix"
    assert samples[0]["profile"] == "qwen_dashscope"
    assert samples[0]["primary_repair_route"] == "provider_thinking_protocol"
    assert "thinking_wire_format_mismatch" in samples[0]["last_error"]
    assert dataset.all_examples[0].category == "provider_thinking_protocol"
    content = out.read_text(encoding="utf-8")
    assert "sk-secret" not in content
    assert "token=secret" not in content


def test_provider_compat_matrix_script_prints_and_exports_failures(tmp_path: Path):
    path = tmp_path / "custom_models.json"
    history = tmp_path / "history.jsonl"
    out = tmp_path / "failures.jsonl"
    path.write_text(
        json.dumps({
            "qwen-thinking": {
                "id": "qwen-thinking",
                "provider": "openai",
                "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                "api_key": "sk-secret-qwen",
                "models": ["qwen3-max"],
                "supports_thinking": True,
                "thinking_wire_format": "openai",
            }
        }),
        encoding="utf-8",
    )

    record = _run_script(
        "--path",
        str(path),
        "--record",
        "--history-path",
        str(history),
    )
    assert record.returncode == 0, f"stdout={record.stdout}\nstderr={record.stderr}"
    result = _run_script(
        "--failures",
        "--export-failures",
        str(out),
        "--history-path",
        str(history),
        "--format",
        "text",
    )

    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    assert "provider_compatibility_failures: count=1" in result.stdout
    assert "qwen-thinking" in result.stdout
    assert out.exists()
    assert "sk-secret" not in out.read_text(encoding="utf-8")
