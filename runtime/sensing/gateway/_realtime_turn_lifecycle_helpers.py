"""Shared helpers for the realtime turn lifecycle.

Unit: visible-output determination (``_turn_has_observable_output``) and
cowork context-authorization / turn-plan injection
(``_inject_cowork_turn_plan``).

Split out of ``realtime_turn_lifecycle.py`` so that orchestrator stays
under the god-file line budget.
"""

from __future__ import annotations

import logging
from typing import Any

from runtime.protocol import ItemType, Turn

_logger = logging.getLogger(__name__)


def _turn_has_observable_output(turn: Turn) -> bool:
    """Return true once the runtime produced anything visible beyond input.

    A turn that only contains the user's message but no agent text, no
    reasoning, no tool/file/artifact/error item is a silent failure. It
    should not be marked completed because the UI has nothing meaningful
    to render and the user sees a stuck/empty answer.
    """
    for item in turn.items:
        item_type = getattr(item, "type", None)
        if item_type in {
            ItemType.USER_MESSAGE,
            ItemType.STEERING_USER_MESSAGE,
        }:
            continue
        if item_type == ItemType.AGENT_MESSAGE:
            if str(getattr(item, "text", "") or "").strip():
                return True
            continue
        if item_type == ItemType.REASONING:
            if str(getattr(item, "content", "") or "").strip() or bool(
                getattr(item, "summary", None)
            ):
                return True
            continue
        if item_type == ItemType.PLAN:
            if str(getattr(item, "text", "") or "").strip():
                return True
            continue
        if item_type == ItemType.TODO_LIST:
            if bool(getattr(item, "plan", None)):
                return True
            continue
        return True
    return False


def _inject_cowork_turn_plan(
    runtime: Any,
    *,
    thread_id: str,
    text: str,
    intent: Any,
) -> None:
    """Attach cowork turn-planning diagnostics to the realtime intent.

    Single-responder plans stay advisory; multi-responder plans are converted
    into the existing ``agent_roster`` shape so the stable group-fanout driver
    can run the selected members in parallel.
    """
    store = getattr(runtime, "_cowork_group_store", None)
    if store is None:
        store = getattr(getattr(runtime, "_app_state", None), "cowork_group_store", None)
    if store is None:
        return
    try:
        from runtime.memory.cowork.turn_plan import plan_turn_for_thread

        plan = plan_turn_for_thread(store, thread_id, text).to_dict()
    except Exception as exc:  # noqa: BLE001
        _logger.debug("cowork turn plan skipped: %s", exc, exc_info=True)
        return
    context = getattr(intent, "user_context", None)
    if not isinstance(context, dict):
        return
    context.setdefault("cowork_plan", plan)
    context.setdefault("cowork_mode", plan.get("mode"))
    context.setdefault("cowork_responders", plan.get("responders") or [])
    context.setdefault("cowork_is_multi", bool(plan.get("is_multi")))
    responders = [
        str(agent_id) for agent_id in (plan.get("responders") or []) if str(agent_id or "").strip()
    ]
    if plan.get("is_multi") and len(responders) > 1:
        context.setdefault(
            "agent_roster",
            [{"agent_id": agent_id, "display_name": agent_id} for agent_id in responders],
        )

    # Enforce the responder's context grant on the single-responder react path.
    # A member pulled in with from_join/range/summary must not see history beyond
    # their grant. The async runner already slices via context_view; this closes
    # the realtime path. (Multi-responder fanout passes only the current message,
    # not history, so there's nothing to leak there.)
    if not plan.get("is_multi") and len(responders) == 1:
        msgs = context.get("conversation_messages")
        if isinstance(msgs, list) and msgs:
            try:
                from runtime.memory.cowork.context_view import (
                    resolve_view,
                    slice_messages,
                )

                view = resolve_view(store.state(thread_id), responders[0], len(msgs))
                if view is not None and view.scope != "all":
                    context["conversation_messages"] = slice_messages(view, msgs)
            except Exception as exc:  # noqa: BLE001 — grant slice is best-effort
                _logger.debug("cowork grant slice skipped: %s", exc, exc_info=True)
