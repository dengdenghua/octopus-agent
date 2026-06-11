
from __future__ import annotations

import fnmatch
import threading
from collections.abc import Callable
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from runtime.platform.models import now_utc
from runtime.safety.invariants import AppendOnlyList

TOPIC_ARM_BUSY = "arm.busy"
"""Arm 开始处理任务。payload 建议：{task_id, sucker_id}。"""

TOPIC_ARM_IDLE = "arm.idle"
"""Arm 任务完成。payload 建议：{task_id, outcome}。"""

TOPIC_SUCKER_GRABBED = "sucker.grabbed"
"""Arm 占用某资源（配合 Boids 仲裁）。payload 建议：{resource_uri, arm_id}。"""

TOPIC_ALERT_BUDGET = "alert.budget"
"""预算告急。payload 建议：{budget_status, remaining}。"""

TOPIC_ALERT_LOOP = "alert.loop"
"""死循环检测。payload 建议：{task_id, pattern}。"""


STANDARD_TOPICS: frozenset[str] = frozenset({
    TOPIC_ARM_BUSY,
    TOPIC_ARM_IDLE,
    TOPIC_SUCKER_GRABBED,
    TOPIC_ALERT_BUDGET,
    TOPIC_ALERT_LOOP,
})


# ─── SignalEvent ───────────────────────────────────────────

class SignalEvent(BaseModel):

    model_config = ConfigDict(frozen=True)

    topic: str = Field(..., min_length=1)
    payload: dict
    publisher: str = Field(default="system", min_length=1)
    ts: datetime



class _Subscription:

    __slots__ = ("sid", "topic_pattern", "handler")

    def __init__(
        self,
        sid: int,
        topic_pattern: str,
        handler: Callable[[SignalEvent], None],
    ) -> None:
        self.sid = sid
        self.topic_pattern = topic_pattern
        self.handler = handler


# ─── SignalBus ─────────────────────────────────────────────

class SignalBus:

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subs: dict[int, _Subscription] = {}
        self._next_sid: int = 1
        self._history: AppendOnlyList[SignalEvent] = AppendOnlyList(
            rule_id="SIGNAL_BUS_HISTORY"
        )
        self._errors: AppendOnlyList[str] = AppendOnlyList(
            rule_id="SIGNAL_BUS_ERRORS"
        )

    # ─── publish ──────────────────────────────────────────

    def publish(
        self,
        topic: str,
        payload: dict,
        publisher: str = "system",
    ) -> SignalEvent:
        event = SignalEvent(
            topic=topic,
            payload=dict(payload),
            publisher=publisher,
            ts=now_utc(),
        )
        with self._lock:
            self._history.append(event)
            matches = [
                sub for sub in self._subs.values()
                if fnmatch.fnmatchcase(topic, sub.topic_pattern)
            ]

        for sub in matches:
            try:
                sub.handler(event)
            except Exception as exc:  # Implementation note.
                err_text = (
                    f"handler sid={sub.sid} pattern={sub.topic_pattern!r} "
                    f"on topic={topic!r}: {type(exc).__name__}: {exc}"
                )
                with self._lock:
                    self._errors.append(err_text)

        return event

    # ─── subscribe / unsubscribe ──────────────────────────

    def subscribe(
        self,
        topic_pattern: str,
        handler: Callable[[SignalEvent], None],
    ) -> int:
        if not topic_pattern:
            raise ValueError("topic_pattern must be non-empty")
        if not callable(handler):
            raise TypeError("handler must be callable")
        with self._lock:
            sid = self._next_sid
            self._next_sid += 1
            self._subs[sid] = _Subscription(sid, topic_pattern, handler)
        return sid

    def unsubscribe(self, subscription_id: int) -> bool:
        with self._lock:
            return self._subs.pop(subscription_id, None) is not None

    # ─── history / errors ────────────────────────────────

    def history(self) -> list[SignalEvent]:
        with self._lock:
            return self._history.snapshot()

    @property
    def handler_errors(self) -> list[str]:
        with self._lock:
            return self._errors.snapshot()


    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subs)
