"""LLM-backed summariser for thread compaction.

Bridges :mod:`runtime.memory.threads.compaction` with the Eye layer
(``ModelRouter``). Handed a list of stale ``Turn`` objects, it produces
a single prose summary suitable as the compacted turn's sole item.

Design rules that differ from the mechanical default:

* **Structured in, prose out.** We hand the model a compact, bounded
  transcript — *not* the raw turn objects (pydantic dump would be huge
  and litter the prompt with ``createdAt`` stamps). The transcript
  compression is deterministic; only the summarisation itself is the
  non-deterministic part.
* **Cheap by default.** We pin a small model strength and a strict
  ``max_tokens`` because the summary is later stored as a plain
  ``AgentMessageItem`` — making it verbose defeats the whole point.
* **Fail-soft.** If the router raises, we fall back to the mechanical
  default so the turn still gets compacted (never block the runtime
  because summarisation failed — a best-effort summary is better than
  unbounded context).

Used as a ``CompactionPolicy.custom_summariser`` by the realtime
runtime. See the wiring in ``CerebrumRuntime.start_turn``.
"""
from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from runtime.memory.threads.compaction import Summariser
from runtime.protocol.items import (
    AgentMessageItem,
    CommandExecutionItem,
    ErrorItem,
    FileChangeItem,
    McpToolCallItem,
    PlanItem,
    ReasoningItem,
    TodoListItem,
    Turn,
    UserMessageItem,
)
from runtime.sensing.model_router.models import (
    Message,
    ModelRequest,
    ModelResponse,
    ModelRouter,
)

_logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You condense earlier turns of a developer assistant session into a "
    "short note the assistant can re-read to stay coherent. "
    "Focus on: what the user asked, what was decided, what was built or "
    "changed (files, commands), unresolved items and known gotchas. "
    "Drop greetings, filler, and any content that will not matter in the "
    "next turn. "
    "Write in the assistant's voice, plain prose. Max 10 short bullet "
    "points across the whole range — no preamble, no closing."
)


@dataclass(frozen=True, slots=True)
class LlmSummariserConfig:
    """How the router is invoked.

    ``model`` names the upstream model id — use the user's preferred
    small / cheap one (e.g. ``claude-haiku-4-5-20251001``). ``max_tokens``
    caps the summary length; remember this shows up verbatim inside
    every future turn's context.
    """

    model: str = "claude-haiku-4-5-20251001"
    system_provider: str = "anthropic"
    max_tokens: int = 600
    temperature: float = 0.2
    transcript_char_budget: int = 24_000
    """Hard cap on characters sent to the model per compaction. We
    trim the tail first (older turns are kept, newer stale turns
    are the first to be summarised — trimming loses less)."""


def make_llm_summariser(
    router: ModelRouter,
    *,
    config: LlmSummariserConfig | None = None,
    fallback: Summariser | None = None,
) -> Summariser:
    """Return a ``Summariser`` closure bound to ``router``.

    ``fallback`` is invoked when the router raises. Supply the
    mechanical default summariser from :mod:`runtime.memory.threads.compaction`.
    """
    cfg = config or LlmSummariserConfig()

    def summarise(turns: Sequence[Turn]) -> str:
        transcript = _render_transcript(turns, cfg.transcript_char_budget)
        request = ModelRequest(
            model=cfg.model,
            system_provider=cfg.system_provider,
            max_tokens=cfg.max_tokens,
            temperature=cfg.temperature,
            messages=[
                Message(role="system", content=_SYSTEM_PROMPT),
                Message(role="user", content=transcript),
            ],
        )
        try:
            response: ModelResponse = router.call(request)
        except Exception as exc:  # noqa: BLE001
            _logger.warning(
                "compaction LLM summariser failed (%s); falling back",
                exc.__class__.__name__,
            )
            if fallback is None:
                raise
            return fallback(turns)
        text = (response.text or "").strip()
        if not text:
            # The router returned an empty body — almost always a
            # safety-filter trip. Don't save an empty summary.
            if fallback is None:
                return "(summary unavailable)"
            return fallback(turns)
        return text

    return summarise


# ── Transcript rendering ──────────────────────────────────────
#
# The input to the LLM is deliberately NOT a pydantic dump. That
# shape is verbose (ISO timestamps, alias keys, enum values) and
# the model would waste tokens re-parsing it. Instead we render a
# compact markdown-like transcript.


def _render_transcript(turns: Sequence[Turn], char_budget: int) -> str:
    sections: list[str] = []
    for idx, turn in enumerate(turns, start=1):
        sections.append(_render_turn(idx, len(turns), turn))
    joined = "\n\n".join(sections)
    if len(joined) <= char_budget:
        return joined
    # Trim older turns first — we're summarising older content;
    # losing the very oldest turn's detail is less valuable than
    # losing what happened just before the kept-recent window.
    trimmed_sections: list[str] = []
    remaining = char_budget
    for section in reversed(sections):
        if len(section) > remaining:
            break
        trimmed_sections.append(section)
        remaining -= len(section) + 2  # "\n\n"
    trimmed_sections.reverse()
    if not trimmed_sections:
        # Single section is itself too large — hard truncate it.
        return sections[-1][: char_budget - 1].rstrip() + "…"
    return "\n\n".join(trimmed_sections)


def _render_turn(idx: int, total: int, turn: Turn) -> str:
    lines: list[str] = [f"## Turn {idx}/{total} · {turn.status.value}"]
    for item in turn.items:
        rendered = _render_item(item)
        if rendered:
            lines.append(rendered)
    return "\n".join(lines)


def _render_item(item: Any) -> str:
    if isinstance(item, UserMessageItem):
        return f"**user:** {_clip(item.text, 400)}"
    if isinstance(item, AgentMessageItem):
        return f"**assistant:** {_clip(item.text, 600)}"
    if isinstance(item, ReasoningItem):
        # Reasoning is noisy at summarisation time — the model doesn't
        # need a copy of its own scratch; skip unless there's nothing
        # else (e.g. a turn that only reasoned).
        return ""
    if isinstance(item, CommandExecutionItem):
        out = f"**$ {_clip(item.command, 160)}**"
        if item.aggregated_output:
            out += f"\n  → {_clip(item.aggregated_output, 200)}"
        return out
    if isinstance(item, McpToolCallItem):
        label = f"**mcp:{_clip(item.server, 80)}/{_clip(item.tool, 80)}**"
        if item.error:
            return f"{label}\n  error: {_clip(item.error, 200)}"
        if item.result is not None:
            return f"{label}\n  result: {_clip(str(item.result), 240)}"
        return label
    if isinstance(item, PlanItem):
        return f"**plan:** {_clip(item.text, 500)}"
    if isinstance(item, TodoListItem):
        todos = [f"{entry.status}: {entry.title}" for entry in item.plan[:8]]
        extra = ""
        if len(item.plan) > 8:
            extra = f" (+{len(item.plan) - 8} more)"
        body = "; ".join(todos) if todos else (item.explanation or "")
        return f"**todos:** {_clip(body, 500)}{extra}"
    if isinstance(item, FileChangeItem):
        paths = [f"{c.op} {c.path}" for c in item.changes][:6]
        extra = ""
        if len(item.changes) > 6:
            extra = f" (+{len(item.changes) - 6} more)"
        return "**files:** " + ", ".join(paths) + extra
    if isinstance(item, ErrorItem):
        return f"**error:** {_clip(item.message, 400)}"
    return ""


def _clip(text: str, n: int) -> str:
    t = " ".join((text or "").split())
    return t if len(t) <= n else t[: n - 1].rstrip() + "…"


__all__ = [
    "LlmSummariserConfig",
    "make_llm_summariser",
]
