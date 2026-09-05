"""Bounded device telemetry, health assessment and realtime event fan-out."""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from .base import Heartbeat


class FaultKind(StrEnum):
    CONNECTIVITY = "connectivity"
    SOFTWARE = "software"
    PHYSICAL = "physical"
    SENSOR = "sensor"
    SAFETY = "safety"
    CONTENTION = "contention"
    UNKNOWN = "unknown"


class HealthLevel(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    OFFLINE = "offline"


@dataclass(frozen=True, slots=True)
class TelemetrySample:
    device_id: str
    metric: str
    value: Any
    timestamp: float
    unit: str | None = None
    source: str = "device"
    quality: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "device_id": self.device_id,
            "metric": self.metric,
            "value": self.value,
            "timestamp": self.timestamp,
            "unit": self.unit,
            "source": self.source,
            "quality": self.quality,
        }


@dataclass(frozen=True, slots=True)
class FaultEvent:
    device_id: str
    kind: FaultKind
    message: str
    timestamp: float
    action: str | None = None
    receipt_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "device_id": self.device_id,
            "kind": self.kind.value,
            "message": self.message,
            "timestamp": self.timestamp,
            "action": self.action,
            "receipt_id": self.receipt_id,
        }


def classify_fault(error_code: int | None, message: str | None) -> FaultKind:
    text = (message or "").lower()
    if error_code in {-32011, -32013, -32017} or any(
        word in text for word in ("offline", "disconnected", "timeout", "lease expired")
    ):
        return FaultKind.CONNECTIVITY
    if error_code == -32016 or "lease is held" in text or "contention" in text:
        return FaultKind.CONTENTION
    if error_code in {-32004, -32005} or any(
        word in text for word in ("safety", "forbidden", "approval", "interlock", "limit")
    ):
        return FaultKind.SAFETY
    if any(word in text for word in ("sensor", "calibration", "invalid reading")):
        return FaultKind.SENSOR
    if any(word in text for word in ("collision", "jammed", "overheat", "pressure", "foaming")):
        return FaultKind.PHYSICAL
    if error_code is not None or text:
        return FaultKind.SOFTWARE
    return FaultKind.UNKNOWN


class TelemetryHub:
    def __init__(self, *, samples_per_device: int = 2_000, faults_per_device: int = 200) -> None:
        self._samples: dict[str, deque[TelemetrySample]] = defaultdict(
            lambda: deque(maxlen=samples_per_device)
        )
        self._faults: dict[str, deque[FaultEvent]] = defaultdict(
            lambda: deque(maxlen=faults_per_device)
        )
        self._last_heartbeat: dict[str, Heartbeat] = {}
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()

    def publish(self, event_type: str, device_id: str, data: dict[str, Any]) -> None:
        event = {"event": event_type, "device_id": device_id, "timestamp": time.time(), **data}
        for queue in tuple(self._subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                try:
                    queue.get_nowait()
                    queue.put_nowait(event)
                except (asyncio.QueueEmpty, asyncio.QueueFull):
                    self._subscribers.discard(queue)

    def subscribe(self, max_queue: int = 256) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=max_queue)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._subscribers.discard(queue)

    def record_sample(self, sample: TelemetrySample) -> None:
        self._samples[sample.device_id].append(sample)
        self.publish("telemetry.sample", sample.device_id, {"sample": sample.to_dict()})

    def record_heartbeat(self, heartbeat: Heartbeat) -> None:
        self._last_heartbeat[heartbeat.tentacle_id] = heartbeat
        timestamp = heartbeat.ts / 1000 if heartbeat.ts else time.time()
        for metric, value, unit in (
            ("online", heartbeat.online, None),
            ("battery", heartbeat.battery, "percent"),
            ("running_tasks", heartbeat.running_tasks, "count"),
        ):
            if value is not None:
                self.record_sample(
                    TelemetrySample(heartbeat.tentacle_id, metric, value, timestamp, unit=unit)
                )
        self.publish("device.heartbeat", heartbeat.tentacle_id, {"heartbeat": heartbeat.to_dict()})

    def record_receipt(self, receipt: Any) -> None:
        for metric, value, unit in (
            (
                "action_duration_ms",
                max(0.0, (receipt.finished_at - receipt.started_at) * 1000),
                "ms",
            ),
            ("action_success", bool(receipt.success), None),
        ):
            self.record_sample(
                TelemetrySample(
                    receipt.device_id,
                    metric,
                    value,
                    receipt.finished_at,
                    unit=unit,
                    source="runtime",
                )
            )
        if not receipt.success:
            fault = FaultEvent(
                receipt.device_id,
                classify_fault(receipt.error_code, receipt.error_message),
                receipt.error_message or "device action failed",
                receipt.finished_at,
                action=receipt.action,
                receipt_id=receipt.receipt_id,
            )
            self._faults[receipt.device_id].append(fault)
            self.publish("device.fault", receipt.device_id, {"fault": fault.to_dict()})
        self.publish(
            "device.execution",
            receipt.device_id,
            {
                "receipt_id": receipt.receipt_id,
                "action": receipt.action,
                "success": receipt.success,
            },
        )

    def samples(
        self, device_id: str, *, metric: str | None = None, limit: int = 200
    ) -> list[dict[str, Any]]:
        items = reversed(self._samples.get(device_id, ()))
        selected = (item for item in items if metric is None or item.metric == metric)
        return [item.to_dict() for item in list(selected)[: max(0, limit)]]

    def faults(self, device_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
        return [
            item.to_dict()
            for item in list(reversed(self._faults.get(device_id, ())))[: max(0, limit)]
        ]

    def health(self, device_id: str, *, stale_after_s: float = 90.0) -> dict[str, Any]:
        heartbeat = self._last_heartbeat.get(device_id)
        if heartbeat is None or not heartbeat.online:
            return {
                "device_id": device_id,
                "level": HealthLevel.OFFLINE.value,
                "score": 0,
                "reasons": ["no online heartbeat"],
            }
        now = time.time()
        heartbeat_age = max(0.0, now - heartbeat.ts / 1000)
        recent = [
            item
            for item in self._samples.get(device_id, ())
            if item.metric == "action_success" and now - item.timestamp <= 300
        ]
        failures = sum(1 for item in recent if not item.value)
        score = 100
        reasons: list[str] = []
        if heartbeat_age > stale_after_s:
            score -= 50
            reasons.append("heartbeat is stale")
        if recent:
            score -= round(failures / len(recent) * 60)
            if failures:
                reasons.append(f"{failures}/{len(recent)} recent actions failed")
        if heartbeat.battery is not None and heartbeat.battery < 10 and not heartbeat.is_charging:
            score -= 20
            reasons.append("battery is critically low")
        score = max(0, score)
        level = (
            HealthLevel.HEALTHY
            if score >= 80
            else HealthLevel.DEGRADED
            if score >= 40
            else HealthLevel.UNHEALTHY
        )
        return {
            "device_id": device_id,
            "level": level.value,
            "score": score,
            "reasons": reasons,
            "heartbeat_age_s": round(heartbeat_age, 1),
        }
