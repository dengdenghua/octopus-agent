"""Dependency-light model failover policy shared by execution layers.

This module lives in ``platform.models`` because both the core ReAct loop and
the sensing routers consume it. Keeping the policy below those layers avoids
making the core depend on the transport-facing sensing package.
"""

from __future__ import annotations

import json


def is_retryable_model_error(exc: BaseException) -> bool:
    """Return whether another configured provider may recover this call."""

    text = f"{type(exc).__name__}: {exc}".lower()
    return any(
        marker in text
        for marker in (
            "http_402",
            "http_408",
            "http_429",
            "http_500",
            "http_502",
            "http_503",
            "http_504",
            "insufficient_balance",
            "insufficient account balance",
            "模型账户余额不足",
            "rate limit",
            "too many requests",
            "readtimeout",
            "connecttimeout",
            "connection reset",
            "connection refused",
            "temporarily unavailable",
            "service unavailable",
            "upstream timeout",
        )
    )


def model_rescue_quality(model_id: str) -> int:
    """Return a deterministic name-only quality score for rescue ordering."""

    name = str(model_id or "").lower()
    score = 0
    if "codex" in name:
        score += 120
    if "code" in name or "coder" in name:
        score += 100
    if "pro" in name:
        score += 90
    if "reason" in name or "thinking" in name:
        score += 80
    if "chat" in name:
        score += 40
    if "flash" in name or "mini" in name:
        score += 10
    return score


def next_custom_model_fallback(
    current_model: str,
    attempted: set[str],
    *,
    require_tool_use: bool = True,
) -> str | None:
    """Pick the strongest untried model from the live custom-model config."""

    try:
        from runtime.platform.process.paths import app_paths

        data = json.loads(app_paths().custom_models_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - rescue must remain optional
        return None
    if not isinstance(data, dict):
        return None

    candidates: list[str] = []
    for entry in data.values():
        if not isinstance(entry, dict):
            continue
        if require_tool_use and entry.get("supports_tool_use") is not True:
            continue
        raw_models = entry.get("models")
        if isinstance(raw_models, list):
            candidates.extend(
                str(model).strip() for model in raw_models if str(model or "").strip()
            )
            continue
        fallback_id = str(entry.get("model") or entry.get("id") or "").strip()
        if fallback_id:
            candidates.append(fallback_id)

    indexed = list(enumerate(dict.fromkeys(candidates)))
    ordered = [
        model
        for _idx, model in sorted(
            indexed,
            key=lambda row: (-model_rescue_quality(row[1]), row[0]),
        )
    ]
    excluded = {str(model or "").strip() for model in attempted}
    excluded.add(str(current_model or "").strip())
    return next((model for model in ordered if model not in excluded), None)


__all__ = [
    "is_retryable_model_error",
    "model_rescue_quality",
    "next_custom_model_fallback",
]
