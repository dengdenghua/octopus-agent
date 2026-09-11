"""Shared state container for the observability router endpoint groups.

Pure structural extraction from ``_observability_router_factory.py`` (no
logic changes). Bundles the runtime state that the factory captured in its
closure — journal, registry, planner, effect store, identity store and the
auth parameters — so the extracted endpoint builder functions can receive
one coherent context instead of a long positional list.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass
class ObservabilityContext:
    """Shared runtime state threaded through the observability builders."""

    journal: Any
    registry: Any
    planner: Any = None
    effect_store: Any = None
    identity_store: Any = None
    require_auth: bool = False
    jwt_secret: str | None = None
    jwt_issuer: str | None = None
    jwt_audience: str | None = None
    planner_provider: Callable[[], Any] | None = None

    def get_planner(self) -> Any:
        return self.planner_provider() if self.planner_provider is not None else self.planner


__all__ = ["ObservabilityContext"]
