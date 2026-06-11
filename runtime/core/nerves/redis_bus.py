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

_redis_available = False
try:
    import redis.asyncio as aioredis
    _redis_available = True
except ImportError:  # noqa: BLE001 — redis optional dep
    pass


class RedisEventBus(AbstractEventBus):

    def __init__(
        self,
        *,
        redis_url: str = "redis://localhost:6379/0",
        stream_key: str = "octopus:nerves:events",
        consumer_group: str = "octopus-agents",
        consumer_name: str = "worker-0",
        crash_resilient: bool = True,
    ) -> None:
        if not _redis_available:
            raise ImportError(
                "redis package required for RedisEventBus: pip install redis[hiredis]"
            )
        self._redis_url = redis_url
        self._stream_key = stream_key
        self._consumer_group = consumer_group
        self._consumer_name = consumer_name
        self._crash_resilient = crash_resilient

        self._subs: dict[type, list[Callable]] = {}
        self._lock = threading.RLock()
        self._client: Any = None
        self._listener_task: Any = None

    def _get_client(self) -> Any:
        if self._client is None:
            self._client = aioredis.from_url(self._redis_url)
        return self._client

    async def _ensure_group(self) -> None:
        client = self._get_client()
        try:  # noqa: SIM105
            await client.xgroup_create(
                self._stream_key, self._consumer_group, id="0", mkstream=True
            )
        except Exception:  # noqa: BLE001 — redis publish best-effort
            pass

    async def _start_listening(self) -> None:
        import asyncio

        client = self._get_client()
        await self._ensure_group()
        logger.info(
            "RedisEventBus listening on %s · group=%s consumer=%s",
            self._stream_key, self._consumer_group, self._consumer_name,
        )
        while True:
            try:
                messages = await client.xreadgroup(
                    groupname=self._consumer_group,
                    consumername=self._consumer_name,
                    streams={self._stream_key: ">"},
                    count=10,
                    block=1000,
                )
                for _stream, msgs in messages:
                    for msg_id, fields in msgs:
                        await self._dispatch(fields)
                        await client.xack(
                            self._stream_key, self._consumer_group, msg_id
                        )
            except asyncio.CancelledError:
                break
            except Exception:
                if self._crash_resilient:
                    logger.exception("RedisEventBus listener error · retrying")
                    await asyncio.sleep(1)
                else:
                    raise

    async def _dispatch(self, fields: dict) -> None:
        event_type_name = fields.get(b"event_type", b"").decode()
        event_json = fields.get(b"event_data", b"{}").decode()
        for ev_cls in list(self._subs.keys()):
            if ev_cls.__name__ == event_type_name:
                try:
                    event = ev_cls.model_validate_json(event_json)
                except Exception:
                    logger.warning("failed to deserialize %s", event_type_name)
                    return
                with self._lock:
                    handlers = list(self._subs.get(ev_cls, []))
                for handler in handlers:
                    try:
                        handler(event)
                    except Exception:
                        if self._crash_resilient:
                            logger.warning(
                                "subscriber %r raised on %s", handler, event_type_name
                            )
                        else:
                            raise
                return

    def start(self) -> None:
        import asyncio
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            threading.Thread(target=loop.run_forever, daemon=True).start()
        self._listener_task = asyncio.run_coroutine_threadsafe(
            self._start_listening(), loop
        )

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
        import asyncio
        event_json = event.model_dump_json()
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
        future = asyncio.run_coroutine_threadsafe(
            self._publish_async(event_json, type(event).__name__), loop
        )
        try:
            return future.result(timeout=5)
        except Exception:
            logger.exception("RedisEventBus publish failed")
            return 0

    async def _publish_async(self, event_json: str, event_type_name: str) -> int:
        client = self._get_client()
        msg_id = await client.xadd(
            self._stream_key,
            {"event_type": event_type_name, "event_data": event_json},
            maxlen=10_000,
        )
        return 1 if msg_id else 0

    def __repr__(self) -> str:
        with self._lock:
            types = len(self._subs)
        return (
            f"RedisEventBus(stream={self._stream_key}, "
            f"group={self._consumer_group}, event_types={types})"
        )
