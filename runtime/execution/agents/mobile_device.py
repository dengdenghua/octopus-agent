"""Mobile-device registry — phones as remote team members.

A phone running octopus-mobile connects to this gateway (via its "OctopusAgent"
channel), announces itself, then long-polls for device tasks and posts results
back. To the team it looks just like a local CLI partner, only reached over HTTP
instead of a subprocess:

  phone ──register──▶ registry ──(shows in roster)──▶ team
  team task (assignee ``mobile_<id>``) ──dispatch──▶ queue ──next──▶ phone
  phone runs the device action ──result──▶ registry ──▶ team task artifact

The registry is process-global and in-memory (mirrors ``team_tasks`` state):
device presence is ephemeral by design — a phone is "present" only while it
heartbeats.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass
from threading import Condition, Lock
from typing import Any

# A device counts as online if it heartbeat within this window (register or
# next-task poll both refresh last_seen).
ONLINE_WINDOW_SECONDS = 45.0


@dataclass
class MobileDevice:
    device_id: str
    name: str
    model: str
    registered_at: float
    last_seen: float


def _agent_id(device_id: str) -> str:
    """Roster/member id for a device — the ``mobile_*`` key the team routes on."""
    cleaned = "".join(c if (c.isalnum() or c in "-_") else "_" for c in device_id)
    return f"mobile_{cleaned}"


class MobileDeviceRegistry:
    """Thread-safe registry of connected phones + their task queues/results."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._cond = Condition(self._lock)
        self._devices: dict[str, MobileDevice] = {}
        self._queues: dict[str, deque[dict[str, Any]]] = defaultdict(deque)
        self._results: dict[str, dict[str, Any]] = {}

    # ── phone side ──────────────────────────────────────────────────
    def register(self, device_id: str, name: str, model: str, *, now: float | None = None) -> dict[str, Any]:
        """Upsert a device + refresh its heartbeat. Returns its roster shape."""
        ts = time.time() if now is None else now
        with self._lock:
            existing = self._devices.get(device_id)
            if existing is None:
                self._devices[device_id] = MobileDevice(device_id, name, model, ts, ts)
            else:
                existing.name = name or existing.name
                existing.model = model or existing.model
                existing.last_seen = ts
            return self._roster_entry(self._devices[device_id], now=ts)

    def next_task(self, device_id: str, *, now: float | None = None) -> dict[str, Any] | None:
        """Pop the oldest queued task for the phone (also a heartbeat). ``None``
        if nothing is queued."""
        ts = time.time() if now is None else now
        with self._lock:
            dev = self._devices.get(device_id)
            if dev is not None:
                dev.last_seen = ts
            queue = self._queues.get(device_id)
            if not queue:
                return None
            return queue.popleft()

    def post_result(
        self, device_id: str, task_id: str, *, ok: bool, output: str = "", error: str | None = None
    ) -> None:
        ts = time.time()
        with self._cond:
            dev = self._devices.get(device_id)
            if dev is not None:
                dev.last_seen = ts
            self._results[task_id] = {
                "device_id": device_id,
                "task_id": task_id,
                "ok": bool(ok),
                "output": output or "",
                "error": error,
                "at": ts,
            }
            self._cond.notify_all()

    # ── team / agent side ───────────────────────────────────────────
    def dispatch(self, device_id: str, task_id: str, goal: str) -> bool:
        """Queue a device task for the phone. ``False`` if the device is unknown."""
        with self._lock:
            if device_id not in self._devices:
                return False
            self._queues[device_id].append({"task_id": task_id, "goal": goal})
            return True

    def await_result(self, task_id: str, *, timeout: float = 240.0) -> dict[str, Any] | None:
        """Block until the phone posts a result for ``task_id`` (or timeout)."""
        deadline = time.time() + timeout
        with self._cond:
            while task_id not in self._results:
                remaining = deadline - time.time()
                if remaining <= 0:
                    return None
                self._cond.wait(timeout=remaining)
            return self._results.pop(task_id)

    def list_devices(self, *, now: float | None = None) -> list[dict[str, Any]]:
        ts = time.time() if now is None else now
        with self._lock:
            return [self._roster_entry(d, now=ts) for d in self._devices.values()]

    def _roster_entry(self, dev: MobileDevice, *, now: float) -> dict[str, Any]:
        return {
            "device_id": dev.device_id,
            "agent_id": _agent_id(dev.device_id),
            "name": dev.name,
            "model": dev.model,
            "online": (now - dev.last_seen) <= ONLINE_WINDOW_SECONDS,
            "last_seen": dev.last_seen,
        }


# Process-global registry shared by the router + team-task dispatcher.
_REGISTRY = MobileDeviceRegistry()


def get_mobile_registry() -> MobileDeviceRegistry:
    return _REGISTRY


def mobile_members_from_assignees(
    assignee_refs: list[str] | None, *, registry: MobileDeviceRegistry | None = None
) -> list[dict[str, Any]]:
    """Of the registered phones, return those whose ``mobile_*`` agent_id is in
    ``assignee_refs`` (the team task's mobile assignees). Empty → no mobile work."""
    wanted = {str(r).strip() for r in (assignee_refs or []) if str(r).strip()}
    if not wanted:
        return []
    reg = registry or _REGISTRY
    return [d for d in reg.list_devices() if d["agent_id"] in wanted]
