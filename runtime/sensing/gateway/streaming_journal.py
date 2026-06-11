
from __future__ import annotations

import contextlib
import threading
from collections.abc import Callable
from datetime import datetime
from typing import Any

from runtime.adapters.instrumentation import trace_stage
from runtime.memory.journal import Journal
from runtime.memory.journal.journal import (
    JournalEvent,
    JournalEventType,
)
from runtime.platform.models import TaskId

Subscriber = Callable[[JournalEvent], None]


class StreamingJournal(Journal):

    def __init__(self, inner: Journal) -> None:
        self._inner = inner
        self._subscribers: list[Subscriber] = []
        self._lock = threading.RLock()


    def subscribe(self, callback: Subscriber) -> Callable[[], None]:
        with self._lock:
            self._subscribers.append(callback)

        def unsubscribe() -> None:
            with self._lock:
                if callback in self._subscribers:
                    self._subscribers.remove(callback)

        return unsubscribe

    @property
    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subscribers)


    def write(self, event: JournalEvent) -> None:
        self._inner.write(event)
        self._broadcast(event)

    def read_all(self) -> list[JournalEvent]:
        return self._inner.read_all()

    def read_by_task(self, task_id: TaskId) -> list[JournalEvent]:
        return self._inner.read_by_task(task_id)

    def read_by_type(self, event_type: JournalEventType) -> list[JournalEvent]:
        return self._inner.read_by_type(event_type)

    def read_since(self, ts: datetime) -> list[JournalEvent]:
        return self._inner.read_since(ts)

    def __len__(self) -> int:
        return len(self._inner)


    def _broadcast(self, event: JournalEvent) -> None:
        with self._lock:
            subs = list(self._subscribers)  # Implementation note.
        with trace_stage("siphon.broadcast") as span:
            span.set_attribute("octopus.siphon.subscribers", len(subs))
            span.set_attribute("octopus.siphon.event_type", event.event_type)
            for cb in subs:
                with contextlib.suppress(Exception):
                    cb(event)


    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)
