from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from .schema import AgentConfig

try:
    import yaml  # type: ignore[import-untyped]

    YAML_AVAILABLE = True
except ImportError:  # pragma: no cover
    YAML_AVAILABLE = False
    yaml = None  # type: ignore[assignment]


_ENV_PATTERN = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)\}|\$([A-Z_][A-Z0-9_]*)")


class ConfigLoadError(ValueError):
    pass


def _interpolate_env(value: Any) -> Any:
    if isinstance(value, str):

        def _sub(m: re.Match[str]) -> str:
            name = m.group(1) or m.group(2)
            return os.environ.get(name, "")

        return _ENV_PATTERN.sub(_sub, value)
    if isinstance(value, dict):
        return {k: _interpolate_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_interpolate_env(v) for v in value]
    return value


def load_from_dict(data: dict[str, Any]) -> AgentConfig:
    resolved = _interpolate_env(data)
    try:
        return AgentConfig.model_validate(resolved)
    except Exception as e:
        raise ConfigLoadError(f"schema validation failed: {e}") from e


def load_from_yaml(path: str | Path) -> AgentConfig:
    if not YAML_AVAILABLE:
        raise ConfigLoadError("PyYAML not installed · `pip install PyYAML` or use load_from_dict()")
    p = Path(path)
    if not p.exists():
        raise ConfigLoadError(f"config file not found: {p}")
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise ConfigLoadError(f"YAML parse failed in {p}: {e}") from e
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ConfigLoadError(f"top-level YAML must be a mapping, got {type(raw).__name__}")
    return load_from_dict(raw)
