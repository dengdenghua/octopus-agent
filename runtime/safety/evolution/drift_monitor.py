from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

_LOG = logging.getLogger


def _publish_drift_events(events: list[DriftEvent]) -> None:
    from runtime.platform.process.eventbus import DriftDetected, publish_event
    for ev in events:
        publish_event(DriftDetected(
            event_type="drift.detected",
            drift_kind=ev.kind,
            severity=ev.severity,
            detail=ev.detail,
        ), logger=_LOG)


_LOG = logging.getLogger("octopus.evolution.drift_monitor")


@dataclass
class DriftConfig:
    check_interval_sec: int = 300
    score_window: int = 20
    score_drop_threshold: float = 0.15
    soul_change_cooldown_sec: int = 60
    genome_dir: str = "data/genome"


@dataclass
class DriftEvent:
    kind: str
    severity: str
    detail: str
    ts: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class DriftReport:
    agent_id: str
    ts: str
    events: list[DriftEvent]
    has_drift: bool
    max_severity: str


class DriftMonitor:
    def __init__(
        self,
        agent_id: str,
        config: DriftConfig | None = None,
    ) -> None:
        self.agent_id = agent_id
        self.config = config or DriftConfig()
        self._last_soul_hash: str | None = None
        self._last_genome_version: int | None = None
        self._last_check_ts: float = 0.0
        self._baseline_score: float | None = None

    def check(self) -> DriftReport:
        events: list[DriftEvent] = []
        now = datetime.now().isoformat(timespec="seconds")

        soul_event = self._check_soul_drift(now)
        if soul_event is not None:
            events.append(soul_event)

        genome_event = self._check_genome_drift(now)
        if genome_event is not None:
            events.append(genome_event)

        score_event = self._check_score_drift(now)
        if score_event is not None:
            events.append(score_event)

        has_drift = len(events) > 0
        severities = [e.severity for e in events]
        if "critical" in severities:
            max_severity = "critical"
        elif "warning" in severities:
            max_severity = "warning"
        elif "info" in severities:
            max_severity = "info"
        else:
            max_severity = "none"

        _publish_drift_events(events)
        return DriftReport(
            agent_id=self.agent_id,
            ts=now,
            events=events,
            has_drift=has_drift,
            max_severity=max_severity,
        )

    def _check_soul_drift(self, now: str) -> DriftEvent | None:

        project_root = Path(__file__).resolve().parents[3]
        soul_path = project_root / "agents" / self.agent_id / "agent-core" / "SOUL.md"
        if not soul_path.exists():
            return None

        try:
            current_hash = hashlib.md5(soul_path.read_bytes()).hexdigest()[:8]
        except Exception as _exc:
            _LOG.debug("drift check failed: %s", _exc)
            return None

        if self._last_soul_hash is None:
            self._last_soul_hash = current_hash
            return None

        if current_hash != self._last_soul_hash:
            old_hash = self._last_soul_hash
            self._last_soul_hash = current_hash
            return DriftEvent(
                kind="soul_change",
                severity="info",
                detail=f"SOUL.md changed: {old_hash} -> {current_hash}",
                ts=now,
                metadata={"old_hash": old_hash, "new_hash": current_hash},
            )

        return None

    def _check_genome_drift(self, now: str) -> DriftEvent | None:
        try:
            from runtime.safety.recovery.genome_registry import GenomeRegistry

            registry = GenomeRegistry(
                config=__import__(
                    "runtime.safety.recovery.genome_registry",
                    fromlist=["GenomeRegistryConfig"],
                ).GenomeRegistryConfig(genome_dir=self.config.genome_dir),
            )
            current_version = registry.latest_version()
        except Exception as _exc:
            _LOG.debug("drift check failed: %s", _exc)
            return None

        if self._last_genome_version is None:
            self._last_genome_version = current_version
            return None

        if current_version != self._last_genome_version:
            old_v = self._last_genome_version
            self._last_genome_version = current_version
            return DriftEvent(
                kind="genome_change",
                severity="info",
                detail=f"Genome version changed: v{old_v} -> v{current_version}",
                ts=now,
                metadata={"old_version": old_v, "new_version": current_version},
            )

        return None

    def _check_score_drift(self, now: str) -> DriftEvent | None:
        from runtime.memory.learning.turn_scoring import read_recent_scores

        scores = read_recent_scores(self.agent_id, limit=self.config.score_window)
        if len(scores) < 5:
            return None

        current_avg = sum(s.score for s in scores) / len(scores)

        if self._baseline_score is None:
            self._baseline_score = current_avg
            return None

        delta = current_avg - self._baseline_score
        if delta < -self.config.score_drop_threshold:
            severity = "critical" if delta < -0.3 else "warning"
            event = DriftEvent(
                kind="score_regression",
                severity=severity,
                detail=(
                    f"Score dropped {abs(delta):.2f} "
                    f"({self._baseline_score:.2f} -> {current_avg:.2f})"
                ),
                ts=now,
                metadata={
                    "baseline": round(self._baseline_score, 3),
                    "current": round(current_avg, 3),
                    "delta": round(delta, 3),
                },
            )
            self._baseline_score = current_avg
            return event

        if delta > self.config.score_drop_threshold:
            self._baseline_score = current_avg

        return None


__all__ = [
    "DriftConfig",
    "DriftEvent",
    "DriftMonitor",
    "DriftReport",
]
