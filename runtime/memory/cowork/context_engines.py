"""Discovery and registration for safe cowork context-selection engines."""

from __future__ import annotations

import os
import re
import threading
import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from importlib import metadata
from typing import Any

from runtime.memory.cowork.context_steward import CoworkContextCandidate

_ENGINE_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_ENTRY_POINT_GROUP = "octopus.cowork_context_engines"
_LOCK = threading.Lock()
_FACTORIES: dict[str, Callable[[], Any]] = {}
_HOST_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="cowork-context-engine")
_LATIN_TERM_RE = re.compile(r"[a-z0-9][a-z0-9_+.#/-]{1,}", re.IGNORECASE)
_CJK_RUN_RE = re.compile(r"[\u3400-\u9fff]{2,}")
_DEEP_RECALL_INTENT_RE = re.compile(
    r"(?:之前|以前|上次|历史|当时|最初|原来|还记得|回顾|复盘|为何|为什么|"
    r"怎么决定|prior|previous|earlier|history|remember|recall|original|why\s+did)",
    re.IGNORECASE,
)
_KIND_WEIGHT = {
    "objective": 1.0,
    "constraint": 0.95,
    "decision": 0.9,
    "risk": 0.85,
    "artifact": 0.7,
    "task": 0.55,
    "fact": 0.4,
    "conversation": 0.25,
}


def _semantic_terms(text: str) -> frozenset[str]:
    lowered = str(text or "").lower()
    terms = set(_LATIN_TERM_RE.findall(lowered))
    for run in _CJK_RUN_RE.findall(lowered):
        bounded = run[:120]
        terms.update(bounded[index : index + 2] for index in range(len(bounded) - 1))
    return frozenset(terms)


def _jaccard(left: frozenset[str], right: frozenset[str]) -> float:
    if not left or not right:
        return 0.0
    union = left | right
    return len(left & right) / len(union) if union else 0.0


class HybridCoworkContextEngine:
    """Budget-aware relevance, recency, importance and diversity selector.

    This is a deterministic MMR-style engine: it preserves high-value project
    contracts while penalising near-duplicate chat records so a fixed context
    budget covers more independent facts. It sees only host-authorized
    candidates and returns only their opaque ids.
    """

    name = "hybrid-mmr"
    api_version = "1"
    capabilities = frozenset({"assemble"})

    def select_context(
        self,
        *,
        candidates: tuple[CoworkContextCandidate, ...],
        budget_tokens: int,
        section: str = "",
        **_kwargs: Any,
    ) -> Sequence[str]:
        return self._select_context(
            candidates=candidates,
            budget_tokens=budget_tokens,
            section=section,
            deep_recall=False,
        )

    def _select_context(
        self,
        *,
        candidates: tuple[CoworkContextCandidate, ...],
        budget_tokens: int,
        section: str,
        deep_recall: bool,
    ) -> Sequence[str]:
        remaining = max(0, int(budget_tokens))
        if not candidates or remaining <= 0:
            return []
        maximum_score = max((max(0.0, float(item.score)) for item in candidates), default=1.0)
        maximum_order = max((item.order for item in candidates), default=0)
        minimum_order = min((item.order for item in candidates), default=0)
        order_span = max(1, maximum_order - minimum_order)
        terms = {item.source_id: _semantic_terms(item.content) for item in candidates}
        pending = list(candidates)
        selected: list[CoworkContextCandidate] = []

        while pending and remaining > 0:
            ranked: list[tuple[float, int, str, CoworkContextCandidate]] = []
            for item in pending:
                cost = max(1, int(item.estimated_tokens))
                if cost > remaining:
                    continue
                relevance = max(0.0, float(item.score)) / maximum_score if maximum_score else 0.0
                recency = (item.order - minimum_order) / order_span
                importance = _KIND_WEIGHT.get(item.kind, 0.3)
                redundancy = max(
                    (
                        _jaccard(terms[item.source_id], terms[chosen.source_id])
                        for chosen in selected
                    ),
                    default=0.0,
                )
                if deep_recall:
                    # A historical/causal question needs an older decision or
                    # constraint even when the newest chat rows are lexically
                    # denser. Retain relevance, but deliberately spend part of
                    # the budget on importance and temporal coverage.
                    historical = 1.0 - recency
                    utility = (
                        0.34 * relevance + 0.40 * importance + 0.20 * historical + 0.04 * recency
                    )
                elif section == "durable_project_state":
                    utility = 0.48 * relevance + 0.36 * importance + 0.10 * recency
                else:
                    utility = 0.58 * relevance + 0.14 * importance + 0.20 * recency
                utility -= 0.42 * redundancy
                # Prefer more useful information per token without starving a
                # moderately long objective/constraint record.
                density = utility / max(1.0, cost**0.35)
                ranked.append((density, item.order, item.source_id, item))
            if not ranked:
                break
            _density, _order, _source_id, chosen = max(ranked)
            selected.append(chosen)
            remaining -= max(1, int(chosen.estimated_tokens))
            pending.remove(chosen)
        return [item.source_id for item in selected]


class AdaptiveRecallCoworkContextEngine(HybridCoworkContextEngine):
    """Hybrid-MMR with an intent-gated long-horizon recall lane.

    Ordinary turns use the fast deterministic selector unchanged. Historical,
    temporal, and causal questions switch weighting inside the same authorized
    candidate set so older decisions and constraints compete fairly with fresh
    chat. The host still owns authorization and reapplies the hard budget.
    """

    name = "adaptive-recall-mmr"

    def select_context(
        self,
        *,
        candidates: tuple[CoworkContextCandidate, ...],
        budget_tokens: int,
        section: str = "",
        message: str = "",
        **_kwargs: Any,
    ) -> Sequence[str]:
        return self._select_context(
            candidates=candidates,
            budget_tokens=budget_tokens,
            section=section,
            deep_recall=bool(_DEEP_RECALL_INTENT_RE.search(str(message or ""))),
        )


class RecencyCoworkContextEngine:
    """Built-in selector that prefers the newest authorized candidate."""

    name = "recency"
    api_version = "1"
    capabilities = frozenset({"assemble"})

    def select_context(
        self,
        *,
        candidates: tuple[CoworkContextCandidate, ...],
        **_kwargs: Any,
    ) -> Sequence[str]:
        return [item.source_id for item in sorted(candidates, key=lambda item: -item.order)]


class CoworkContextEngineUnavailable(RuntimeError):
    """Raised when a selected engine is timed out, broken, or quarantined."""


class CoworkContextEngineHost:
    """Versioned, bounded host for context-engine lifecycle plugins.

    Only ``assemble`` may influence prompt selection, and its output is still
    resolved against host-authorized opaque source ids by the steward. Other
    hooks maintain plugin-owned state; their return values never enter model
    context. Calls are time bounded and a repeatedly failing engine is
    quarantined without exposing exception bodies in trace metadata.
    """

    _octopus_lifecycle_host = True
    _SUPPORTED_API_VERSIONS = frozenset({"1", "octopus.cowork_context_engine.v1"})
    _OPTIONAL_HOOKS = frozenset(
        {
            "bootstrap",
            "ingest",
            "compact",
            "commit_turn",
            "maintain",
            "on_member_start",
            "on_member_end",
        }
    )

    def __init__(
        self,
        engine: Any,
        *,
        timeout_seconds: float | None = None,
        quarantine_after: int = 3,
    ) -> None:
        self.engine = engine
        self.name = _normalize_name(
            str(getattr(engine, "name", "") or type(engine).__name__).strip().lower()
        )
        raw_version = str(getattr(engine, "api_version", "") or "legacy").strip()
        if raw_version != "legacy" and raw_version not in self._SUPPORTED_API_VERSIONS:
            raise ValueError(f"unsupported cowork context engine api version: {raw_version}")
        if not callable(getattr(engine, "assemble", None)) and not callable(
            getattr(engine, "select_context", None)
        ):
            raise TypeError("cowork context engine must define assemble or select_context")
        self.api_version = raw_version
        declared = getattr(engine, "capabilities", ())
        declared_values = declared if isinstance(declared, (list, tuple, set, frozenset)) else ()
        self.capabilities = tuple(
            sorted(
                {
                    str(item).strip()
                    for item in list(declared_values)[:32]
                    if _ENGINE_NAME_RE.fullmatch(str(item or "").strip())
                }
                | {hook for hook in self._OPTIONAL_HOOKS if callable(getattr(engine, hook, None))}
                | {"assemble"}
            )
        )
        configured_timeout = os.environ.get("OCTOPUS_COWORK_CONTEXT_ENGINE_TIMEOUT_SECONDS")
        try:
            resolved_timeout = float(configured_timeout) if configured_timeout else 2.0
        except ValueError:
            resolved_timeout = 2.0
        self.timeout_seconds = max(
            0.01,
            min(30.0, resolved_timeout if timeout_seconds is None else float(timeout_seconds)),
        )
        self.quarantine_after = max(1, int(quarantine_after))
        self._lock = threading.RLock()
        self._calls = 0
        self._failures = 0
        self._timeouts = 0
        self._consecutive_failures = 0
        self._quarantined = False
        self._last_error_type: str | None = None
        self._bootstrapped_sessions: set[str] = set()

    def _record_success(self) -> None:
        with self._lock:
            self._calls += 1
            self._consecutive_failures = 0

    def _record_failure(self, error_type: str, *, timed_out: bool = False) -> None:
        with self._lock:
            self._calls += 1
            self._failures += 1
            self._timeouts += int(timed_out)
            self._consecutive_failures += 1
            self._last_error_type = error_type
            if self._consecutive_failures >= self.quarantine_after:
                self._quarantined = True

    def _invoke(self, hook: str, kwargs: dict[str, Any]) -> tuple[Any, dict[str, Any]]:
        with self._lock:
            if self._quarantined:
                raise CoworkContextEngineUnavailable("context engine is quarantined")
        method = getattr(self.engine, hook, None)
        if hook == "assemble" and not callable(method):
            method = getattr(self.engine, "select_context", None)
        if not callable(method):
            return None, {"hook": hook, "status": "unsupported", "duration_ms": 0}
        started = time.monotonic()
        future = _HOST_EXECUTOR.submit(method, **kwargs)
        try:
            value = future.result(timeout=self.timeout_seconds)
        except FutureTimeoutError as exc:
            future.cancel()
            self._record_failure("TimeoutError", timed_out=True)
            raise CoworkContextEngineUnavailable("context engine hook timed out") from exc
        except Exception as exc:  # noqa: BLE001 - sanitize at the plugin boundary
            error_type = type(exc).__name__
            self._record_failure(error_type)
            raise CoworkContextEngineUnavailable(
                f"context engine hook failed: {error_type}"
            ) from exc
        self._record_success()
        return value, {
            "hook": hook,
            "status": "completed",
            "duration_ms": max(0, int((time.monotonic() - started) * 1000)),
        }

    def select_context(self, **kwargs: Any) -> Sequence[str]:
        """Run the v1 ``assemble`` hook (or legacy selector adapter)."""

        value, _report = self._invoke("assemble", dict(kwargs))
        if isinstance(value, dict):
            value = value.get("selected_source_ids")
        if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
            raise CoworkContextEngineUnavailable("context engine assemble must return source ids")
        return value

    def invoke_hook(self, hook: str, **kwargs: Any) -> dict[str, Any]:
        """Invoke a non-authoritative hook and return body-free diagnostics."""

        if hook not in self._OPTIONAL_HOOKS:
            raise ValueError(f"unsupported cowork context lifecycle hook: {hook}")
        try:
            _value, report = self._invoke(hook, dict(kwargs))
            return report
        except CoworkContextEngineUnavailable:
            snapshot = self.describe()
            return {
                "hook": hook,
                "status": "quarantined" if snapshot["quarantined"] else "failed",
                "duration_ms": 0,
                "error_type": snapshot.get("last_error_type") or "Unavailable",
            }

    def bootstrap_session(self, session_id: str) -> dict[str, Any]:
        """Bootstrap a plugin session at most once per live host instance."""

        normalized = str(session_id or "").strip()
        with self._lock:
            if normalized in self._bootstrapped_sessions:
                return {
                    "hook": "bootstrap",
                    "status": "already_bootstrapped",
                    "duration_ms": 0,
                }
            self._bootstrapped_sessions.add(normalized)
        report = self.invoke_hook(
            "bootstrap",
            session_id=normalized,
            api_version=self.api_version,
        )
        if report["status"] not in {"completed", "unsupported"}:
            with self._lock:
                self._bootstrapped_sessions.discard(normalized)
        return report

    def describe(self) -> dict[str, Any]:
        with self._lock:
            return {
                "schema": "octopus.cowork_context_engine_host.v1",
                "name": self.name,
                "api_version": self.api_version,
                "capabilities": list(self.capabilities),
                "timeout_ms": int(self.timeout_seconds * 1000),
                "quarantined": self._quarantined,
                "calls": self._calls,
                "failures": self._failures,
                "timeouts": self._timeouts,
                "last_error_type": self._last_error_type,
            }


def _normalize_name(name: str) -> str:
    normalized = str(name or "").strip().lower()
    if not _ENGINE_NAME_RE.fullmatch(normalized):
        raise ValueError("invalid cowork context engine name")
    return normalized


def register_cowork_context_engine(
    name: str,
    factory: Callable[[], Any],
    *,
    replace: bool = False,
) -> None:
    """Register a process-local engine factory under a bounded name."""

    normalized = _normalize_name(name)
    if not callable(factory):
        raise TypeError("cowork context engine factory must be callable")
    with _LOCK:
        if normalized in _FACTORIES and not replace:
            raise ValueError(f"cowork context engine already registered: {normalized}")
        _FACTORIES[normalized] = factory


def _entry_point_factory(name: str) -> Callable[[], Any] | None:
    points = metadata.entry_points()
    matches = (
        points.select(group=_ENTRY_POINT_GROUP, name=name)
        if hasattr(points, "select")
        else [
            point
            for point in points.get(_ENTRY_POINT_GROUP, [])  # type: ignore[union-attr]
            if point.name == name
        ]
    )
    match_list = list(matches)
    if not match_list:
        return None
    if len(match_list) != 1:
        raise ValueError(f"multiple cowork context engine plugins named {name!r}")
    loaded = match_list[0].load()
    if isinstance(loaded, type):
        return loaded
    if callable(loaded):
        return loaded
    return lambda: loaded


def load_cowork_context_engine(name: str | None = None) -> Any | None:
    """Load the selected engine; use the safe built-in hybrid by default.

    ``OCTOPUS_COWORK_CONTEXT_ENGINE`` is read only when ``name`` is omitted.
    Third-party code is never imported merely by being installed. Operators
    can select ``deterministic`` or ``none`` to retain the legacy host order.
    """

    selected = str(
        name if name is not None else os.environ.get("OCTOPUS_COWORK_CONTEXT_ENGINE", "")
    ).strip()
    if not selected or selected.lower() == "default":
        selected = "adaptive"
    if selected.lower() in {"deterministic", "none"}:
        return None
    normalized = _normalize_name(selected)
    with _LOCK:
        factory = _FACTORIES.get(normalized)
    factory = factory or _entry_point_factory(normalized)
    if factory is None:
        raise LookupError(f"unknown cowork context engine: {normalized}")
    engine = factory()
    if not callable(getattr(engine, "assemble", None)) and not callable(
        getattr(engine, "select_context", None)
    ):
        raise TypeError("cowork context engine must define assemble or select_context")
    # Validate the declared protocol before the engine reaches a realtime turn.
    CoworkContextEngineHost(engine)
    return engine


register_cowork_context_engine("recency", RecencyCoworkContextEngine)
register_cowork_context_engine("hybrid", HybridCoworkContextEngine)
register_cowork_context_engine("adaptive", AdaptiveRecallCoworkContextEngine)


__all__ = [
    "AdaptiveRecallCoworkContextEngine",
    "CoworkContextEngineHost",
    "CoworkContextEngineUnavailable",
    "HybridCoworkContextEngine",
    "RecencyCoworkContextEngine",
    "load_cowork_context_engine",
    "register_cowork_context_engine",
]
