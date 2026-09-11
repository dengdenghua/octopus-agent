"""Configuration types and loaders; stack assembly is loaded on demand."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .builder import BuiltStack, build_from_config
from .loader import ConfigLoadError, load_from_dict, load_from_yaml
from .presets import apply_preset, get_preset_description, list_presets
from .schema import (
    AgentConfig,
    BudgetConfig,
    EvolveConfig,
    ExecutionConfig,
    ImmunityConfig,
    IntelSourceConfig,
    LearnConfig,
    MCPServerConfigEntry,
    PlannerConfig,
    ToolEffectsConfig,
)

__all__ = [
    "AgentConfig",
    "BudgetConfig",
    "BuiltStack",
    "ConfigLoadError",
    "ImmunityConfig",
    "IntelSourceConfig",
    "LearnConfig",
    "MCPServerConfigEntry",
    "EvolveConfig",
    "ExecutionConfig",
    "PlannerConfig",
    "ToolEffectsConfig",
    "apply_preset",
    "get_preset_description",
    "list_presets",
    "build_from_config",
    "load_from_dict",
    "load_from_yaml",
]


def __getattr__(name: str) -> Any:
    if name in {"BuiltStack", "build_from_config"}:
        from importlib import import_module

        value = getattr(import_module(".builder", __name__), name)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
