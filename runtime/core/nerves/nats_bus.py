from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any, TypeVar

from runtime.core.nerves.bus import (
    AbstractEventBus,
    NervesEvent,
)

logger = logging.getLogger(__name__)

E = TypeVar("E", bound=NervesEvent)

_nats_available = False
try:
    import nats
    _nats_available = True
except ImportError:  # noqa: BLE001 — nats optional dep
    pass


class NATSEventBus(AbstractEventBus):

    def __init__(
        self,
        *,
        nats_url: str = "nats://localhost:4222",
        subject_prefix: str = "octopus.nerves",
        queue_group: str = "octopus-agents",
        crash_resilient: bool = True,
    ) -> None:
        if not _nats_available:
            raise ImportError(
                "nats-py package required for NATSEventBus: pip install nats-py"
            )
        self._nats_url = nats_url
        self._subject_prefix = subject_prefix
        self._queue_group = queue_group
        self._crash_resilient = crash_resilient

        self._subs: dict[type, list[Callable]] = {}
        self._lock = threading.RLock()
        self._nc: Any = None
        self._subscriptions: list[Any] = []

    async def _connect(self) -> None:
        self._nc = await nats.connect(self._nats_url)
        for ev_cls in list(self._subs.keys()):
            subject = f"{self._subject_prefix}.{ev_cls.__name__}"
            sub = await self._nc.subscribe(
                subject, queue=self._queue_group, cb=self._make_handler(ev_cls)
            )
            self._subscriptions.append(sub)
        logger.info(
            "NATSEventBus connected to %s · prefix=%s queue=%s",
            self._nats_url, self._subject_prefix, self._queue_group,
        )

    def _make_handler(self, ev_cls: type):
        async def _handler(msg: Any) -> None:
            try:
                event = ev_cls.model_validate_json(msg.data.decode())
            except Exception:
                logger.warning("failed to deserialize %s", ev_cls.__name__)
                return
            with self._lock:
                handlers = list(self._subs.get(ev_cls, []))
            for handler in handlers:
                try:
                    handler(event)
                except Exception:
                    if self._crash_resilient:
                        logger.warning(
                            "subscriber %r raised on %s", handler, ev_cls.__name__
                        )
                    else:
                        raise
        return _handler

    def start(self) -> None:
        import asyncio
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            threading.Thread(target=loop.run_forever, daemon=True).start()
        asyncio.run_coroutine_threadsafe(self._connect(), loop)

    def subscribe(
        self,
        event_type: type[E],
        handler: Callable[[E], None],
    ) -> None:
        if not isinstance(event_type, type) or not issubclass(event_type, NervesEvent):
            raise TypeError(
                f"event_type must be subclass of NervesEvent · got {event_type!r}"
            )
        with self._lock:
            subs = self._subs.setdefault(event_type, [])
            if handler not in subs:
                subs.append(handler)

    def unsubscribe(
        self,
        event_type: type[E],
        handler: Callable[[E], None],
    ) -> bool:
        with self._lock:
            subs = self._subs.get(event_type, [])
            if handler in subs:
                subs.remove(handler)
                if not subs:
                    del self._subs[event_type]
                return True
            return False

    def subscriber_count(self, event_type: type[E]) -> int:
        with self._lock:
            return len(self._subs.get(event_type, []))

    def publish(self, event: NervesEvent) -> int:
        if not isinstance(event, NervesEvent):
            raise TypeError(
                f"event must be NervesEvent · got {type(event).__name__}",
            )
        if self._nc is None:
            logger.warning("NATSEventBus not connected · cannot publish")
            return 0
        import asyncio
        event_json = event.model_dump_json()
        subject = f"{self._subject_prefix}.{type(event).__name__}"
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
        future = asyncio.run_coroutine_threadsafe(
            self._nc.publish(subject, event_json.encode()), loop
        )
        try:
            future.result(timeout=5)
            return 1
        except Exception:
            logger.exception("NATSEventBus publish failed")
            return 0

    def __repr__(self) -> str:
        with self._lock:
            types = len(self._subs)
        return (
            f"NATSEventBus(url={self._nats_url}, "
            f"prefix={self._subject_prefix}, event_types={types})"
        )
