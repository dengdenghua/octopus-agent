from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Any

_LOG = logging.getLogger("octopus.evolution.auto_trigger")


@dataclass
class AutoTriggerConfig:
    enabled: bool = True
    check_interval_sec: int = 120
    fitness_threshold: float = 0.5
    fitness_window: int = 20
    evolve_dry_run: bool = True
    evolve_max_rounds: int = 1
    drift_critical_auto_rollback: bool = True
    feature_flag: str = "evolution.auto_trigger"


class EvolutionAutoTrigger:
    _instance: EvolutionAutoTrigger | None = None
    _lock: threading.Lock = threading.Lock()

    @classmethod
    def get(cls) -> EvolutionAutoTrigger:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Stop the worker thread (if running) and drop the singleton.

        For test isolation only — production code keeps a single
        EvolutionAutoTrigger alive for the process lifetime.
        """
        with cls._lock:
            inst = cls._instance
            cls._instance = None
        if inst is not None:
            try:  # noqa: SIM105
                inst.stop(timeout=2.0)
            except Exception:  # noqa: BLE001 — reset must never raise
                pass

    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._config = AutoTriggerConfig()
        self._stack: Any = None
        self._tick_count = 0

    def start(self, stack: Any, config: AutoTriggerConfig | None = None) -> None:
        self._wire_events()
        if config is not None:
            self._config = config
        self._stack = stack
        if not self._config.enabled:
            _LOG.info("evolution auto-trigger disabled by config")
            return
        try:
            from runtime.platform import feature_flags as _ff

            if not _ff.is_on(self._config.feature_flag):
                _LOG.info("evolution auto-trigger disabled by feature flag")
                return
        except Exception:  # noqa: BLE001 — feature-flag check best-effort
            pass
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="evolution-auto-trigger",
            daemon=True,
        )
        self._thread.start()
        _LOG.info(
            "evolution auto-trigger started · interval=%ds fitness_threshold=%.2f",
            self._config.check_interval_sec,
            self._config.fitness_threshold,
        )

    def stop(self, timeout: float = 5.0) -> None:
        self._stop_event.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=timeout)

    def status(self) -> dict[str, Any]:
        return {
            "running": bool(self._thread and self._thread.is_alive()),
            "tick_count": self._tick_count,
            "config": {
                "enabled": self._config.enabled,
                "check_interval_sec": self._config.check_interval_sec,
                "fitness_threshold": self._config.fitness_threshold,
            },
        }

    def _run_loop(self) -> None:
        if self._stop_event.wait(timeout=30):
            return
        while not self._stop_event.is_set():
            try:
                self._tick()
            except Exception as exc:
                _LOG.warning("evolution auto-trigger tick failed: %s", exc)
            if self._stop_event.wait(timeout=self._config.check_interval_sec):
                return

    def _tick(self) -> None:
        self._tick_count += 1
        agent_id = getattr(
            getattr(self._stack, "config", None),
            "name",
            "default",
        )

        from runtime.safety.evolution.fitness import FitnessConfig, compute_fitness

        report = compute_fitness(agent_id, FitnessConfig(window=self._config.fitness_window))

        if report.combined < self._config.fitness_threshold:
            _LOG.warning(
                "fitness below threshold: %.2f < %.2f · triggering deep_evolve for %s",
                report.combined,
                self._config.fitness_threshold,
                agent_id,
            )
            self._trigger_evolve(agent_id)

        if self._config.drift_critical_auto_rollback:
            from runtime.safety.evolution.drift_monitor import DriftMonitor

            drift = DriftMonitor(agent_id).check()
            if drift.has_drift and drift.max_severity == "critical":
                _LOG.warning(
                    "critical drift detected for %s · triggering auto-rollback",
                    agent_id,
                )
                self._trigger_rollback(agent_id, drift)

    def _wire_events(self) -> None:
        try:
            from runtime.platform.process.eventbus import get_eventbus

            bus = get_eventbus()
            bus.subscribe("fitness.computed", self._on_fitness_event)
            bus.subscribe("drift.detected", self._on_drift_event)
        except Exception as _exc:
            _LOG.debug("event wire failed: %s", _exc)

    def _on_fitness_event(self, event: Any) -> None:
        score = getattr(event, "combined_score", 1.0)
        agent_id = getattr(event, "agent_id", "")
        if score < self._config.fitness_threshold:
            _LOG.warning(
                "fitness event below threshold: %.2f < %.2f for %s",
                score,
                self._config.fitness_threshold,
                agent_id,
            )
            self._trigger_evolve(agent_id)

    def _on_drift_event(self, event: Any) -> None:
        severity = getattr(event, "severity", "")
        agent_id = getattr(event, "agent_id", "")
        if self._config.drift_critical_auto_rollback and severity == "critical":
            _LOG.warning("critical drift event for %s", agent_id)
            self._trigger_rollback_from_event(event)

    def _trigger_rollback_from_event(self, event: Any) -> None:
        drift_kind = getattr(event, "drift_kind", "")
        agent_id = getattr(event, "agent_id", "")
        if drift_kind == "genome_change":
            try:
                from runtime.safety.recovery.genome_registry import GenomeRegistry

                registry = GenomeRegistry()
                latest = registry.latest_version()
                if latest and latest > 1:
                    registry.rollback(latest - 1)
                    _LOG.info("auto-rolled back genome to v%d", latest - 1)
                    try:
                        from runtime.platform.process.eventbus import GenomeRolledBack, get_eventbus

                        get_eventbus().publish(
                            GenomeRolledBack(
                                event_type="genome.rolled_back",
                                from_version=latest,
                                to_version=latest - 1,
                                agent_id=agent_id,
                            )
                        )
                    except Exception as _exc:
                        _LOG.debug("genome rollback event publish failed: %s", _exc)
            except Exception as exc:
                _LOG.warning("genome rollback failed: %s", exc)

        if drift_kind == "soul_change":
            try:
                from runtime.execution.suckers.memory_skills import _revert_soul

                _revert_soul(steps_back=1, reason="auto-rollback: critical soul drift")
                _LOG.info("auto-reverted SOUL.md by 1 step")
            except Exception as exc:
                _LOG.warning("SOUL revert failed: %s", exc)

    def _trigger_evolve(self, agent_id: str) -> None:
        try:
            from runtime.memory.learning.deep_evolution import deep_evolve

            result = deep_evolve(
                agent_id=agent_id,
                window=self._config.fitness_window,
                max_rounds=self._config.evolve_max_rounds,
                dry_run=self._config.evolve_dry_run,
            )
            try:
                from runtime.platform.process.eventbus import EvolutionCompleted, get_eventbus

                get_eventbus().publish(
                    EvolutionCompleted(
                        event_type="evolution.completed",
                        rounds_run=result.get("rounds_run", 0),
                        applied_count=len(result.get("applied", [])),
                        ok=result.get("ok", False),
                        agent_id=agent_id,
                    )
                )
            except Exception:  # noqa: BLE001 — event publish best-effort
                pass
            applied_n = len(result.get("applied", []))
            if result.get("ok") and applied_n == 0:
                # Expected when the judge rejected every proposal — log it
                # distinctly so a persistent no-op isn't mistaken for either
                # a failure or an effective evolution.
                _LOG.info(
                    "auto-evolve: no changes applied for %s "
                    "(rounds=%s · all proposals rejected by judge)",
                    agent_id,
                    result.get("rounds_run"),
                )
            else:
                _LOG.info(
                    "auto-evolve result: ok=%s rounds=%s applied=%d",
                    result.get("ok"),
                    result.get("rounds_run"),
                    applied_n,
                )
        except Exception as exc:
            _LOG.warning("auto-evolve failed: %s", exc)

    def _trigger_rollback(self, agent_id: str, drift_report: Any) -> None:
        for event in drift_report.events:
            if event.kind == "genome_change" and event.severity == "critical":
                try:
                    from runtime.safety.recovery.genome_registry import GenomeRegistry

                    registry = GenomeRegistry()
                    latest = registry.latest_version()
                    if latest and latest > 1:
                        registry.rollback(latest - 1)
                        _LOG.info("auto-rolled back genome to v%d", latest - 1)
                except Exception as exc:
                    _LOG.warning("genome rollback failed: %s", exc)

            if event.kind == "soul_change" and event.severity == "critical":
                try:
                    from runtime.execution.suckers.memory_skills import _revert_soul

                    _revert_soul(steps_back=1, reason="auto-rollback: critical soul drift")
                    _LOG.info("auto-reverted SOUL.md by 1 step")
                except Exception as exc:
                    _LOG.warning("SOUL revert failed: %s", exc)


def get_auto_trigger() -> EvolutionAutoTrigger:
    return EvolutionAutoTrigger.get()


__all__ = [
    "AutoTriggerConfig",
    "EvolutionAutoTrigger",
    "get_auto_trigger",
]
