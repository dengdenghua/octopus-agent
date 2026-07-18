"""Crash-safe tool effect receipts for durable agent turns.

The journal already records a completed :class:`StepEvent`, but a process can
die after a handler mutates external state and before that event is appended.
This module adds a write-ahead intent and a small in-memory coordinator:

* committed calls are replayed without invoking the handler again;
* an unfinished side-effecting intent is reported as indeterminate instead of
  being retried blindly;
* concurrent deliveries of the same logical step wait for the owner and then
  reuse its receipt.

The identity is scoped to ``task_id + step_id + tool + canonical arguments``.
New user actions get a new task or step, so normal repeated tool use is not
mistaken for transport/recovery duplication.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from dataclasses import dataclass
from typing import Any, Literal

from runtime.memory.journal import Journal, StepEvent, ToolEffectIntentEvent
from runtime.platform.models import CostEntry, ExecutionResult, Step, ToolCall, now_utc

_SIDE_EFFECT_AFFINITIES = frozenset({"write", "edit", "exec", "delete", "dangerous"})


def args_fingerprint(args: dict[str, Any]) -> str:
    encoded = json.dumps(
        args,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=_stable_default,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def effect_key(
    task_id: Any,
    step_id: int,
    sucker_id: Any,
    args: dict[str, Any],
) -> str:
    material = f"{task_id}\0{step_id}\0{sucker_id}\0{args_fingerprint(args)}"
    return "effect:v1:" + hashlib.sha256(material.encode("utf-8")).hexdigest()


def is_side_effecting(affinity: list[str] | None) -> bool:
    """Fail closed for unknown affinity; known read-only tags may retry."""

    if affinity is None:
        return True
    return bool(set(affinity) & _SIDE_EFFECT_AFFINITIES)


@dataclass(frozen=True)
class EffectResolution:
    kind: Literal["execute", "replay", "indeterminate"]
    key: str
    args_fingerprint: str
    step: Step | None = None
    reason: str = ""


class ToolEffectReceiptIndex:
    """Journal-backed receipt index with in-process duplicate coordination."""

    def __init__(self, journal: Journal, *, wait_timeout_s: float = 30.0) -> None:
        self._journal = journal
        self._wait_timeout_s = max(0.0, float(wait_timeout_s))
        self._condition = threading.Condition(threading.RLock())
        self._loaded = False
        self._intents: dict[str, ToolEffectIntentEvent] = {}
        self._committed: dict[str, Step] = {}
        self._live: set[str] = set()

    def begin(
        self,
        *,
        task_id: Any,
        step_id: int,
        sucker_id: Any,
        args: dict[str, Any],
        side_effecting: bool,
    ) -> EffectResolution:
        fingerprint = args_fingerprint(args)
        key = effect_key(task_id, step_id, sucker_id, args)
        deadline = time.monotonic() + self._wait_timeout_s
        with self._condition:
            self._ensure_loaded()
            while key in self._live:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return EffectResolution(
                        "indeterminate",
                        key,
                        fingerprint,
                        reason="another delivery is still executing this tool effect",
                    )
                self._condition.wait(timeout=remaining)

            committed = self._committed.get(key)
            if committed is not None:
                return EffectResolution(
                    "replay",
                    key,
                    fingerprint,
                    step=_replayed_step(committed),
                )

            intent = self._intents.get(key)
            if intent is not None and (side_effecting or intent.side_effecting):
                return EffectResolution(
                    "indeterminate",
                    key,
                    fingerprint,
                    reason=(
                        "a previous process entered this side-effecting tool but did not "
                        "durably record its result"
                    ),
                )

            self._live.add(key)
            return EffectResolution("execute", key, fingerprint)

    def mark_intent(self, event: ToolEffectIntentEvent) -> None:
        with self._condition:
            self._ensure_loaded()
            self._intents[event.effect_key] = event

    def finish(self, resolution: EffectResolution, step: Step) -> None:
        with self._condition:
            if step.success:
                self._committed[resolution.key] = step
            elif not self._intent_is_side_effecting(resolution.key):
                self._intents.pop(resolution.key, None)
            self._live.discard(resolution.key)
            self._condition.notify_all()

    def abandon(self, resolution: EffectResolution) -> None:
        """Release an execution claim while retaining any durable intent."""

        with self._condition:
            self._live.discard(resolution.key)
            self._condition.notify_all()

    def _intent_is_side_effecting(self, key: str) -> bool:
        intent = self._intents.get(key)
        return bool(intent and intent.side_effecting)

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        events = self._journal.read_all()
        steps_by_call_id: dict[str, Step] = {}
        for event in events:
            if isinstance(event, StepEvent):
                steps_by_call_id[str(event.step.action.call_id)] = event.step
            elif isinstance(event, ToolEffectIntentEvent):
                self._intents[event.effect_key] = event
        for key, intent in self._intents.items():
            step = steps_by_call_id.get(intent.call_id)
            if step is not None and step.success:
                self._committed[key] = step
        self._loaded = True


def indeterminate_step(
    *,
    step_id: int,
    node_id: str,
    call: ToolCall,
    reason: str,
) -> Step:
    result = ExecutionResult(
        call_id=call.call_id,
        status="failed",
        output={
            "error": reason,
            "status": "indeterminate",
            "side_effect_may_have_happened": True,
            "retry_safe": False,
        },
        error_type="indeterminate_side_effect",
        stderr_tags=["durable_effect_indeterminate", "manual_reconciliation_required"],
        cost=CostEntry(),
    )
    return Step(
        step_id=step_id,
        node_id=node_id,
        action=call,
        result=result,
        immune_verdict="allow",
    )


def _replayed_step(step: Step) -> Step:
    tags = list(step.result.stderr_tags)
    if "durable_effect_replay" not in tags:
        tags.append("durable_effect_replay")
    result = step.result.model_copy(
        update={
            "stderr_tags": tags,
            "cost": CostEntry(),
            "ts": now_utc(),
        }
    )
    return step.model_copy(update={"result": result, "ts": now_utc()})


def _stable_default(value: Any) -> str:
    if hasattr(value, "model_dump"):
        return json.dumps(
            value.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    return str(value)


__all__ = [
    "EffectResolution",
    "ToolEffectReceiptIndex",
    "args_fingerprint",
    "effect_key",
    "indeterminate_step",
    "is_side_effecting",
]
