from __future__ import annotations

import contextlib
import threading
from collections.abc import Callable, Sized
from datetime import datetime
from typing import Any, cast

from runtime.adapters.instrumentation import trace_stage
from runtime.memory.journal import Journal
from runtime.memory.journal.journal import (
    JournalEvent,
    JournalEventType,
)
from runtime.platform.models import TaskId
from runtime.safety.auth.scope import TenantScope

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
        durable_event = self._inner.canonicalize_event(event)
        self._inner.write(durable_event)
        self._broadcast(durable_event)

    def canonicalize_event(self, event: JournalEvent) -> JournalEvent:
        return self._inner.canonicalize_event(event)

    def read_all(self, *, scope: TenantScope | None = None) -> list[JournalEvent]:
        return self._inner.read_all(scope=scope)

    def read_by_task(
        self,
        task_id: TaskId,
        *,
        scope: TenantScope | None = None,
    ) -> list[JournalEvent]:
        return self._inner.read_by_task(task_id, scope=scope)

    def read_by_type(
        self,
        event_type: JournalEventType,
        *,
        scope: TenantScope | None = None,
    ) -> list[JournalEvent]:
        return self._inner.read_by_type(event_type, scope=scope)

    def read_since(self, ts: datetime) -> list[JournalEvent]:
        return self._inner.read_since(ts)

    def __len__(self) -> int:
        return len(cast(Sized, self._inner))

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
