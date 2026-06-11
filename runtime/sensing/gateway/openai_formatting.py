"""
Pure-function formatters for the OpenAI-compat gateway.

Extracted from ``openai_gateway.py`` as part of the file's gradual
decomposition. Hosts the 5 formatting helpers that turn Step /
ArmResult / Trajectory objects into the strings and dicts the
gateway streams to the client:

    _summarize_step_for_stream  · single-step human-readable line
    _pick_preview_keys          · prioritize input-arg keys for display
    _pick_output_keys           · prioritize output keys for display
    _short                      · string truncation with ellipsis
    _chat_completion_envelope   · non-streaming ChatCompletion shape

Zero runtime dependencies · zero I/O · testable in isolation. This
separation lets ``test_openai_formatting.py`` pin the display-layer
shape without spinning up a full FastAPI stack.

Why not collapse them into one big format() method:
    The 5 functions compose in different orders in different
    contexts (stream chunk line · non-stream envelope · fallback
    reply). Keeping them as tiny building blocks is what lets
    each call site pick what it needs. Inlining would duplicate
    the prioritization rules.
"""
from __future__ import annotations

import time
from typing import Any
from uuid import uuid4

# Per-key priority ordering for the "first 3 most-interesting" args
# display. Hand-curated over time as different skills showed up in
# demos — the ones at the top are what users were clicking to see
# first. Unordered keys round out the remaining slots.
_ARGS_PRIORITY = (
    "text", "path", "url", "query", "command", "keys", "key",
    "x", "y", "duration", "direction", "amount", "content",
)

_OUTPUT_PRIORITY = (
    "result", "reply", "answer", "text", "ok", "success",
    "count", "items", "path", "hash", "word_count", "bytes",
    "error", "triggered", "clicked", "moved", "typed_chars",
    "image_size", "screen_size",
)


def _short(v: Any, max_len: int = 60) -> str:
    """Stringify and truncate with a single ``…`` sentinel when over."""
    s = str(v)
    return s if len(s) <= max_len else s[: max_len - 1] + "…"


def _pick_preview_keys(d: dict[str, Any]) -> list[tuple[str, Any]]:
    """Pick up to 3 args keys in priority order, then filler.

    Sorting rule: anything in ``_ARGS_PRIORITY`` wins (in declared
    priority order); remaining slots go to other keys in insertion
    order. This gives the UI a deterministic "here's what matters"
    preview even when the skill's args grow over time.
    """
    picked: list[tuple[str, Any]] = []
    for k in _ARGS_PRIORITY:
        if k in d:
            picked.append((k, d[k]))
    for k, v in d.items():
        if len(picked) >= 3:
            break
        if k not in _ARGS_PRIORITY:
            picked.append((k, v))
    return picked[:3]


def _pick_output_keys(d: dict[str, Any]) -> list[tuple[str, Any]]:
    """Pick up to 2 output keys in priority order.

    Outputs get a tighter cap than args (2 vs 3) because most
    useful outputs are one or two concrete values — a long
    preview chain was visually noisy in the frontend. Underscore-
    prefixed keys ("_status" / "_raw") are skipped as internal.
    """
    picked: list[tuple[str, Any]] = []
    for k in _OUTPUT_PRIORITY:
        if k in d:
            picked.append((k, d[k]))
    for k, v in d.items():
        if len(picked) >= 2:
            break
        if k not in _OUTPUT_PRIORITY and not k.startswith("_"):
            picked.append((k, v))
    return picked[:2]


def _output_indicates_error(output: Any) -> bool:
    """Return True when a tool encoded failure in its normal payload."""
    if isinstance(output, dict):
        err = output.get("error")
        if isinstance(err, str):
            return bool(err.strip())
        return err is not None and err is not False
    return False


def step_effective_success(step: Any) -> bool:
    """Display-layer success: executor success plus no payload error."""
    return bool(getattr(step, "success", False)) and not _output_indicates_error(
        getattr(getattr(step, "result", None), "output", None),
    )


def summarize_step_for_stream(step: Any) -> str:
    """Render a single Step as a single line for SSE streaming.

    Layout (both present): ``✓ skill(arg=v, …)  →  out=v, …``
    Args only:             ``✓ skill(arg=v)``
    Output only:           ``✓ skill → out=v``
    Neither:               ``✓ skill()``

    The ``✓`` / ``✗`` marker reflects step.success · drives the
    UI's per-step status icon.
    """
    marker = "✓" if step_effective_success(step) else "✗"
    skill = step.action.sucker_id
    # Input args · prioritized
    args = getattr(step.action, "args", None) or {}
    args_preview = ""
    if isinstance(args, dict) and args:
        prioritized = _pick_preview_keys(args)
        args_preview = ", ".join(
            f"{k}={_short(v)}" for k, v in prioritized
        )
    # Output summary
    out = step.result.output
    out_preview = ""
    if isinstance(out, dict) and out:
        out_prio = _pick_output_keys(out)
        out_preview = ", ".join(
            f"{k}={_short(v)}" for k, v in out_prio
        )
    elif isinstance(out, str) and out:
        out_preview = _short(out, max_len=80)

    if args_preview and out_preview:
        return f"{marker} {skill}({args_preview})  →  {out_preview}"
    if args_preview:
        return f"{marker} {skill}({args_preview})"
    if out_preview:
        return f"{marker} {skill} → {out_preview}"
    return f"{marker} {skill}()"


def chat_completion_envelope(
    reply: str,
    *,
    model: str,
    actor: str | None = None,
    agent: Any = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Wrap a plain assistant reply string in the OpenAI-compat
    ``chat.completion`` response shape.

    Used by the gateway when the planner can't build a TaskGraph
    and we fall back to direct LLM · the response needs to look
    like a "normal" openai completion so clients don't 400. The
    ``octopus`` meta field flags that this was a fallback ·
    frontend debug panels read it to distinguish "plan was empty"
    from "plan ran but produced nothing".
    """
    meta: dict[str, Any] = {
        "strategy": "direct_llm_fallback",
        "step_count": 0,
        "success": True,
    }
    if actor is not None:
        meta["actor"] = actor
    if agent is not None:
        meta["agent"] = agent.agent_id
    if extra:
        meta.update(extra)
    return {
        "id": f"chatcmpl-{uuid4().hex[:16]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": reply},
            "finish_reason": "stop",
        }],
        "usage": {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        },
        "octopus": meta,
    }


__all__ = [
    "summarize_step_for_stream",
    "chat_completion_envelope",
    # Underscore-prefixed helpers exported so tests can exercise
    # them directly · callers outside this module should prefer
    # the two public names above.
    "_short",
    "_pick_preview_keys",
    "_pick_output_keys",
    "step_effective_success",
    "_ARGS_PRIORITY",
    "_OUTPUT_PRIORITY",
]
