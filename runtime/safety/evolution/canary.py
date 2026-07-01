from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

_LOG = logging.getLogger("octopus.evolution.canary")


class CanaryPhase(StrEnum):
    SHADOW = "shadow"
    CANARY_5 = "canary_5"
    CANARY_25 = "canary_25"
    CANARY_50 = "canary_50"
    FULL = "full"
    ROLLED_BACK = "rolled_back"


@dataclass
class CanaryConfig:
    shadow_runs: int = 10
    shadow_pass_rate: float = 0.70
    promotion_thresholds: dict[str, float] = field(default_factory=lambda: {
        "canary_5": 0.80,
        "canary_25": 0.80,
        "canary_50": 0.85,
        "full": 0.90,
    })
    sample_window: int = 20
    rollback_threshold: float = 0.50
    state_dir: str = "data/canary_states"
    auto_rollback_reason: str = "canary threshold breached"
    rollback_handler: Callable[[str, CanaryState, str], Any] | None = None


@dataclass
class CanaryState:
    skill_name: str
    phase: CanaryPhase
    entered_ts: str
    sample_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    current_rate: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


_PHASE_ORDER = [
    CanaryPhase.SHADOW,
    CanaryPhase.CANARY_5,
    CanaryPhase.CANARY_25,
    CanaryPhase.CANARY_50,
    CanaryPhase.FULL,
]


class CanaryManager:
    def __init__(self, config: CanaryConfig | None = None) -> None:
        self.config = config or CanaryConfig()
        self._states: dict[str, CanaryState] = {}
        self._lock = threading.RLock()
        self._state_dir = Path(self.config.state_dir)
        self._state_dir.mkdir(parents=True, exist_ok=True)
        self._load_states()

    def register(
        self,
        skill_name: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> CanaryState:
        with self._lock:
            if skill_name in self._states:
                state = self._states[skill_name]
                if metadata:
                    state.metadata.update(metadata)
                    self._persist_state(state)
                return state
            state = CanaryState(
                skill_name=skill_name,
                phase=CanaryPhase.SHADOW,
                entered_ts=datetime.now().isoformat(timespec="seconds"),
                metadata=metadata or {},
            )
            self._states[skill_name] = state
            self._persist_state(state)
            return state

    def record_outcome(self, skill_name: str, success: bool) -> CanaryState | None:
        with self._lock:
            state = self._states.get(skill_name)
            if state is None:
                return None
            if state.phase == CanaryPhase.ROLLED_BACK:
                self._persist_state(state)
                return state
            self._record_windowed_outcome(state, success)

            if state.current_rate < self.config.rollback_threshold and state.sample_count >= 5:
                state.phase = CanaryPhase.ROLLED_BACK
                state.entered_ts = datetime.now().isoformat(timespec="seconds")
                state.metadata["last_rollback_reason"] = self.config.auto_rollback_reason
                _LOG.warning(
                    "canary ROLLBACK for %s: rate=%.2f < threshold=%.2f",
                    skill_name, state.current_rate, self.config.rollback_threshold,
                )
                self._persist_state(state)
                handler = self.config.rollback_handler
                if handler is not None:
                    try:
                        handler(skill_name, state, self.config.auto_rollback_reason)
                    except Exception as exc:  # noqa: BLE001
                        _LOG.warning("canary rollback handler failed for %s: %s", skill_name, exc)
                return state

            threshold = self._promotion_threshold(state.phase)
            if state.current_rate >= threshold and state.sample_count >= self._min_samples(state.phase):
                self._promote(state)

            self._persist_state(state)
            return state

    def get_state(self, skill_name: str) -> CanaryState | None:
        with self._lock:
            return self._states.get(skill_name)

    def should_route_to_skill(self, skill_name: str) -> bool:
        with self._lock:
            state = self._states.get(skill_name)
            if state is None:
                return True
            if state.phase == CanaryPhase.ROLLED_BACK:
                return False
            if state.phase == CanaryPhase.FULL:
                return True

            import random
            traffic_pct = self._traffic_percent(state.phase)
            return random.random() < traffic_pct

    def list_active(self) -> list[CanaryState]:
        with self._lock:
            return [
                s for s in self._states.values()
                if s.phase not in (CanaryPhase.FULL, CanaryPhase.ROLLED_BACK)
            ]

    def list_all(self) -> list[CanaryState]:
        with self._lock:
            return list(self._states.values())

    def force_rollback(
        self,
        skill_name: str,
        *,
        reason: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> CanaryState | None:
        with self._lock:
            state = self._states.get(skill_name)
            if state is None:
                return None
            state.phase = CanaryPhase.ROLLED_BACK
            state.entered_ts = datetime.now().isoformat(timespec="seconds")
            state.metadata["last_rollback_reason"] = (
                reason
                or state.metadata.get("last_rollback_reason")
                or "operator rollback"
            )
            if metadata:
                state.metadata.update(metadata)
            self._persist_state(state)
            return state

    def _promote(self, state: CanaryState) -> None:
        idx = _PHASE_ORDER.index(state.phase) if state.phase in _PHASE_ORDER else -1
        if idx < len(_PHASE_ORDER) - 1:
            old_phase = state.phase
            state.phase = _PHASE_ORDER[idx + 1]
            state.entered_ts = datetime.now().isoformat(timespec="seconds")
            state.sample_count = 0
            state.success_count = 0
            state.failure_count = 0
            state.current_rate = 0.0
            state.metadata["outcome_window"] = []
            _LOG.info(
                "canary PROMOTE %s: %s -> %s",
                state.skill_name, old_phase.value, state.phase.value,
            )

    @staticmethod
    def _traffic_percent(phase: CanaryPhase) -> float:
        traffic = {
            CanaryPhase.SHADOW: 0.0,
            CanaryPhase.CANARY_5: 0.05,
            CanaryPhase.CANARY_25: 0.25,
            CanaryPhase.CANARY_50: 0.50,
            CanaryPhase.FULL: 1.0,
            CanaryPhase.ROLLED_BACK: 0.0,
        }
        return traffic.get(phase, 0.0)

    @staticmethod
    def _min_samples(phase: CanaryPhase) -> int:
        minimums = {
            CanaryPhase.SHADOW: 10,
            CanaryPhase.CANARY_5: 20,
            CanaryPhase.CANARY_25: 40,
            CanaryPhase.CANARY_50: 60,
        }
        return minimums.get(phase, 10)

    def _promotion_threshold(self, phase: CanaryPhase) -> float:
        if phase == CanaryPhase.SHADOW:
            return self.config.shadow_pass_rate
        return self.config.promotion_thresholds.get(phase.value, 0.80)

    def _record_windowed_outcome(self, state: CanaryState, success: bool) -> None:
        window = self._outcome_window(state)
        window.append(bool(success))
        sample_window = max(1, int(self.config.sample_window or 1))
        if len(window) > sample_window:
            window = window[-sample_window:]
        state.metadata["outcome_window"] = window
        self._sync_counts_from_window(state)

    @staticmethod
    def _outcome_window(state: CanaryState) -> list[bool]:
        raw = state.metadata.get("outcome_window") if isinstance(state.metadata, dict) else None
        if isinstance(raw, list):
            return [bool(item) for item in raw]
        if state.sample_count <= 0:
            return []
        successes = max(0, min(state.success_count, state.sample_count))
        failures = max(0, min(state.failure_count, state.sample_count - successes))
        return [True] * successes + [False] * failures

    @staticmethod
    def _sync_counts_from_window(state: CanaryState) -> None:
        window = CanaryManager._outcome_window(state)
        state.sample_count = len(window)
        state.success_count = sum(1 for item in window if item)
        state.failure_count = state.sample_count - state.success_count
        state.current_rate = state.success_count / max(1, state.sample_count)

    def _persist_state(self, state: CanaryState) -> None:
        path = self._state_dir / f"{state.skill_name}.json"
        try:
            path.write_text(
                json.dumps(asdict(state), ensure_ascii=False, default=str, indent=2),
                encoding="utf-8",
            )
        except OSError as exc:
            _LOG.warning("persist canary state failed: %s", exc)

    def _load_states(self) -> None:
        if not self._state_dir.exists():
            return
        for path in self._state_dir.glob("*.json"):
            try:
                d = json.loads(path.read_text(encoding="utf-8"))
                name = d.get("skill_name", path.stem)
                self._states[name] = CanaryState(
                    skill_name=name,
                    phase=CanaryPhase(d.get("phase", "shadow")),
                    entered_ts=d.get("entered_ts", ""),
                    sample_count=int(d.get("sample_count", 0) or 0),
                    success_count=int(d.get("success_count", 0) or 0),
                    failure_count=int(d.get("failure_count", 0) or 0),
                    current_rate=float(d.get("current_rate", 0.0) or 0.0),
                    metadata=d.get("metadata") or {},
                )
                self._sync_counts_from_window(self._states[name])
            except Exception as _exc:
                _LOG.debug("canary result parse failed: %s", _exc)
                continue


__all__ = [
    "CanaryConfig",
    "CanaryManager",
    "CanaryPhase",
    "CanaryState",
]
