"""Operator-declared capability flags from ``custom_models.json``.

This is the layer-neutral source of truth used by both the core context
budgeting path and sensing adapters.
"""

from __future__ import annotations

import json
from typing import Any


def read_custom_models() -> dict[str, Any] | None:
    try:
        from runtime.platform.process.paths import app_paths

        path = app_paths().custom_models_path
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError, ImportError, TypeError):
        return None


def entry_matches_model(entry: Any, model: str) -> bool:
    if not isinstance(entry, dict):
        return False
    target = (model or "").strip()
    if not target:
        return False
    target = target.removesuffix("::1m")
    candidates = {
        str(value).strip()
        for value in (
            entry.get("id"),
            entry.get("name"),
            entry.get("model"),
            entry.get("display_name"),
        )
        if isinstance(value, str) and value.strip()
    }
    raw_models = entry.get("models")
    if isinstance(raw_models, list):
        candidates.update(
            str(value).strip() for value in raw_models if isinstance(value, str) and value.strip()
        )
    return target in candidates


def custom_model_entry_for(model: str) -> dict[str, Any] | None:
    data = read_custom_models()
    if not isinstance(data, dict):
        return None
    for entry in data.values():
        if entry_matches_model(entry, model):
            return entry
    return None


def model_supports_tool_use(model: str) -> bool:
    """Return whether the operator permits native function calling."""

    data = read_custom_models()
    if not isinstance(data, dict):
        return True
    for entry in data.values():
        if entry_matches_model(entry, model) and entry.get("supports_tool_use") is False:
            return False
    return True


def model_omits_sampling_parameters(model: str) -> bool:
    """Return whether sampling knobs must be omitted for this model."""

    data = read_custom_models()
    if not isinstance(data, dict):
        return False
    for entry in data.values():
        if entry_matches_model(entry, model):
            return bool(entry.get("omit_sampling_parameters"))
    return False


def custom_model_supports_thinking(model: str) -> bool:
    data = read_custom_models()
    if not isinstance(data, dict):
        return False
    for entry in data.values():
        if entry_matches_model(entry, model):
            return bool(entry.get("supports_thinking"))
    return False


def model_context_window(model: str) -> int | None:
    """Return the operator-declared input window for a custom model."""

    entry = custom_model_entry_for(model)
    if not isinstance(entry, dict):
        return None
    if model.strip().endswith("::1m"):
        return 1_000_000
    try:
        value = int(entry.get("context_window"))
    except (TypeError, ValueError):
        return None
    return value if 8_192 <= value <= 2_000_000 else 256_000


__all__ = [
    "custom_model_entry_for",
    "custom_model_supports_thinking",
    "entry_matches_model",
    "model_context_window",
    "model_omits_sampling_parameters",
    "model_supports_tool_use",
    "read_custom_models",
]
