"""Offline provider-compatibility readiness checks.

The check is deliberately offline: it inspects custom-model configuration and
known OpenAI-compatible quirks without calling upstream model providers. Live
provider canaries remain explicit CLI actions because they may spend tokens.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from runtime.platform.observability.health import HealthCheck, HealthStatus
from runtime.sensing.model_router.provider_compat_matrix import (
    ProviderCompatibilityMatrixReport,
    build_provider_compatibility_matrix,
)


def provider_compatibility_check(
    *,
    name: str = "provider_compatibility",
    timeout_seconds: float = 2.0,
    critical: bool = False,
    custom_models_path: str | Path | None = None,
) -> HealthCheck:
    """Return a soft readiness check for custom provider configuration."""
    return HealthCheck(
        name=name,
        check=lambda: run_provider_compatibility_probe(
            name=name,
            custom_models_path=custom_models_path,
        ),
        kind="readiness",
        timeout_seconds=timeout_seconds,
        critical=critical,
    )


def run_provider_compatibility_probe(
    *,
    name: str = "provider_compatibility",
    custom_models_path: str | Path | None = None,
) -> HealthStatus:
    try:
        report = build_provider_compatibility_matrix(
            custom_models_path=custom_models_path,
        )
    except (OSError, TypeError, ValueError) as exc:
        return HealthStatus(
            name=name,
            status="fail",
            detail=f"{type(exc).__name__}: {exc}",
        )

    metadata = _report_metadata(report)
    if report.verdict == "pass":
        return HealthStatus(name=name, status="pass", metadata=metadata)
    detail = (
        f"provider matrix {report.verdict} score={report.score} "
        f"review_rows={metadata['review_rows']} fail_rows={metadata['fail_rows']}"
    )
    return HealthStatus(
        name=name,
        status="warn" if report.verdict == "review" else "fail",
        detail=detail,
        metadata=metadata,
    )


def _report_metadata(report: ProviderCompatibilityMatrixReport) -> dict[str, Any]:
    rows = []
    review_rows = 0
    fail_rows = 0
    for row in report.rows:
        if row.verdict == "review":
            review_rows += 1
        elif row.verdict == "fail":
            fail_rows += 1
        rows.append({
            "id": row.id,
            "profile": row.profile,
            "score": row.score,
            "verdict": row.verdict,
            "finding_codes": [finding.code for finding in row.findings],
            "capabilities": {
                key: row.capabilities.get(key)
                for key in (
                    "supports_tool_use",
                    "supports_thinking",
                    "omit_sampling_parameters",
                    "omit_system_messages",
                    "thinking_wire_format",
                )
                if key in row.capabilities
            },
        })
    return {
        "score": report.score,
        "verdict": report.verdict,
        "row_count": len(report.rows),
        "review_rows": review_rows,
        "fail_rows": fail_rows,
        "rows": rows,
    }


__all__ = [
    "provider_compatibility_check",
    "run_provider_compatibility_probe",
]
