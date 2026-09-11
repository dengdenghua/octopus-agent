"""Native planner exports, loaded only when a caller actually requests them.

Host policy helpers under this package are also used by external engines.
Importing those helpers must not construct the native planner dependency tree.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .llm_planner import LLMPlanner
    from .planner import PlannerError, StaticPlanner

__all__ = ["LLMPlanner", "PlannerError", "StaticPlanner"]


def __getattr__(name: str) -> Any:
    if name in __all__:
        from importlib import import_module

        module = ".llm_planner" if name == "LLMPlanner" else ".planner"
        value = getattr(import_module(module, __name__), name)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
