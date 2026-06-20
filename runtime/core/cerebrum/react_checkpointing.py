"""Periodic auto-checkpoint + distributed mirror for the ReAct loop.

Moved from ``react_loop.py``: the iteration-interval knob
(``OCTOPUS_CHECKPOINT_EVERY_N``), the Redis-shaped cross-machine
checkpoint mirror (``OCTOPUS_CHECKPOINT_MIRROR_URL``), and the
message-rehydration bridge used when resuming from a checkpoint whose
``messages_snapshot`` predates its ``steps_snapshot``.
"""

from __future__ import annotations

import contextlib
import logging
from typing import Any

from runtime.core.cerebrum.react_types import ReActStep

_logger = logging.getLogger(__name__)

# ── Periodic auto-checkpoint (P3 — long-task durability) ──────────
# Existing checkpoints fire only on explicit pause or final-answer.
# When a process is hard-killed (SIGKILL, OOM, container restart) the
# turn loses everything between the last checkpoint and the kill.
# Periodic auto-checkpoint plugs that gap: every N iterations the
# loop writes the same shape of checkpoint that pause writes, so a
# resume request can pick up at the last completed iteration.
#
# On by default (every 10 iterations). Override via
# ``OCTOPUS_CHECKPOINT_EVERY_N`` env var (e.g. "5" for more frequent,
# "0" to disable). Errors during checkpoint write are swallowed; turn
# proceeds normally.

_DEFAULT_CHECKPOINT_INTERVAL = 10  # every 10 iterations by default


def _checkpoint_interval() -> int:
    """How often (in iterations) to write an auto-checkpoint.

    Reads ``OCTOPUS_CHECKPOINT_EVERY_N`` fresh on each call so an
    operator can flip the knob without a restart. On by default
    (every ``_DEFAULT_CHECKPOINT_INTERVAL`` iterations); an explicit
    ``"0"`` disables it. Missing, blank, negative, or unparseable
    values fall back to the default rather than silently disabling.
    """
    import os

    raw = os.environ.get("OCTOPUS_CHECKPOINT_EVERY_N", "").strip()
    if not raw:
        return _DEFAULT_CHECKPOINT_INTERVAL
    try:
        n = int(raw)
    except ValueError:
        return _DEFAULT_CHECKPOINT_INTERVAL
    if n < 0:
        return _DEFAULT_CHECKPOINT_INTERVAL
    return n  # n == 0 explicitly disables; n > 0 sets the interval


def _should_auto_checkpoint(iteration: int, interval: int) -> bool:
    """Whether iteration ``iteration`` should trigger an auto-checkpoint.

    Centralised so tests can drive it without spinning up the full
    react_loop. Returns False when ``interval <= 0`` (feature off) or
    when ``iteration <= 0`` (we never write a checkpoint at iteration
    0 — there's nothing to resume to). Otherwise fires when iteration
    is a non-zero multiple of ``interval``.
    """
    if interval <= 0 or iteration <= 0:
        return False
    return iteration % interval == 0


# ── Distributed checkpoint mirror (P3 cross-machine durability) ────
# Optional layer on top of the local journal: each auto-checkpoint
# also pushes a JSON snapshot to a shared KV store (Redis-shaped) so
# another machine can pick up the task. Off by default. Turn on via
# ``OCTOPUS_CHECKPOINT_MIRROR_URL=redis://...`` env var.

_CHECKPOINT_MIRROR_SINGLETON: Any = None
_CHECKPOINT_MIRROR_INIT_DONE = False


def _checkpoint_mirror() -> Any:
    """Return the shared ``CheckpointMirror`` instance, or None.

    Disabled when ``OCTOPUS_CHECKPOINT_MIRROR_URL`` is unset / empty.
    Build failures (redis package missing, bad URL) silently disable
    the mirror — the local journal is the source of truth, mirroring
    is a best-effort overlay.
    """
    global _CHECKPOINT_MIRROR_SINGLETON, _CHECKPOINT_MIRROR_INIT_DONE
    import os

    if not _CHECKPOINT_MIRROR_INIT_DONE:
        _CHECKPOINT_MIRROR_INIT_DONE = True
        url = os.environ.get("OCTOPUS_CHECKPOINT_MIRROR_URL", "").strip()
        if not url:
            _CHECKPOINT_MIRROR_SINGLETON = None
        else:
            try:
                from runtime.core.cerebrum.checkpoint_mirror import (
                    build_checkpoint_mirror_from_url,
                )

                _CHECKPOINT_MIRROR_SINGLETON = build_checkpoint_mirror_from_url(url)
            except Exception as _exc:  # noqa: BLE001 — fail-soft
                _logger.debug("checkpoint mirror init failed: %s", _exc)
                _CHECKPOINT_MIRROR_SINGLETON = None
    return _CHECKPOINT_MIRROR_SINGLETON


def _reset_checkpoint_mirror_for_tests() -> None:
    """Reset the cached mirror singleton — used by tests for isolation."""
    global _CHECKPOINT_MIRROR_SINGLETON, _CHECKPOINT_MIRROR_INIT_DONE
    _CHECKPOINT_MIRROR_SINGLETON = None
    _CHECKPOINT_MIRROR_INIT_DONE = False


def _mirror_checkpoint(task_id: Any, checkpoint_dict: dict[str, Any]) -> None:
    """Best-effort write to the distributed mirror. Errors swallowed."""
    mirror = _checkpoint_mirror()
    if mirror is None:
        return
    with contextlib.suppress(Exception):
        mirror.put(str(task_id), checkpoint_dict)


def _rehydrate_messages_from_steps(messages: list, steps: list[ReActStep]) -> list:
    """Append missing step transcript when resuming from a checkpoint.

    Periodic checkpoints are written at a point where ``steps_snapshot``
    already includes the completed iteration, but ``messages_snapshot``
    may still be the pre-step conversation. Without this bridge a
    killed process can resume with the internal step list restored while
    the model cannot see the last Action/Observation in its prompt.
    """
    if not steps:
        return messages
    from runtime.platform.models.llm import Message

    existing = "\n".join(str(getattr(message, "content", "") or "") for message in messages)
    hydrated = list(messages)
    for step in steps:
        action = (step.action or "").strip()
        observation = (step.observation or "").strip()
        thought = (step.thought or "").strip()
        if not action and not observation:
            continue
        if action and action in existing and (not observation or observation in existing):
            continue
        assistant_lines: list[str] = []
        if thought:
            assistant_lines.append(f"Thought: {thought}")
        if action:
            assistant_lines.append(f"Action: {action}")
        if assistant_lines:
            assistant_content = "\n".join(assistant_lines)
            hydrated.append(Message(role="assistant", content=assistant_content))
            existing += "\n" + assistant_content
        if observation and observation not in existing:
            # TokenJuice on rehydration too — when resuming a
            # paused/checkpointed thread, prior tool observations
            # have to ride into the new prompt. Compressing them
            # saves tokens proportional to history depth.
            _obs_text = observation
            try:
                from runtime.core.cerebrum.token_juicer import (
                    is_enabled as _juice_enabled,
                )
                from runtime.core.cerebrum.token_juicer import (
                    juice as _juice,
                )

                if _juice_enabled():
                    _juiced, _stats = _juice(observation)
                    if _stats.passes:
                        _obs_text = _juiced
            except (ImportError, ValueError, TypeError):  # noqa: BLE001 — juice is best-effort, fall back to raw
                pass
            user_content = f"Observation: {_obs_text}\n\n继续下一轮推理。"
            hydrated.append(Message(role="user", content=user_content))
            existing += "\n" + user_content
    return hydrated
