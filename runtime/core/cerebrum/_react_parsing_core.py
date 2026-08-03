"""Core ReAct text parsing + incremental Thought streaming.

Extracted from ``react_parsing.py``. Owns the display/observation
summarising helpers (``_summarize_observation`` / ``_escape_md_brackets``
/ ``_safe_for_streamdown``), incremental Thought streaming
(``extract_streamable_thought``), the step-text regexes and
``_parse_step`` / ``_extract_final_answer`` /
``_parse_reasoning_action_fallback``, and the unfinished-work /
special-envelope predicates.

Depends only on ``react_types`` and the ``_react_parsing_tools`` leaf.
"""

from __future__ import annotations

import re

from runtime.core.cerebrum._react_parsing_tools import (
    _SPECIAL_TOOL_ENVELOPE_MARKERS,
    _extract_tool_action_from_loose_output,
    _extract_tool_actions_from_loose_output,
    _format_action,
    _parse_action,
)
from runtime.core.cerebrum.react_types import ReActStep

_OBS_DISPLAY_MAX = 280
_OBS_HTML_INDICATOR = "<html"
_OBS_JSON_CONTENT_KEY_RE = re.compile(
    r'"content"\s*:\s*"',
    re.IGNORECASE,
)
_OBS_FAILURE_MARKERS = (
    " failed",
    "error",
    "traceback",
    "timed_out",
    "timeout after",
    '"exit_code": 1',
    '"success": false',
    "失败",
    "超时",
)


def _summarize_observation(text: str) -> str:
    if not text:
        return text
    t = text

    if _OBS_HTML_INDICATOR in t and '"content"' in t:
        t = _OBS_JSON_CONTENT_KEY_RE.sub(
            '"content": "[HTML 正文已省略 · 查 Journal 看原文] ", _sentinel:"',
            t,
            count=1,
        )
        idx = t.find(', _sentinel:"')
        if idx != -1:
            t = t[:idx] + "}"  # Implementation note.

    if len(t) > _OBS_DISPLAY_MAX:
        lowered = t.lower()
        if any(marker in lowered for marker in _OBS_FAILURE_MARKERS):
            # Failure diagnostics commonly put the assertion/traceback summary
            # at the end. Keeping only the head hid the exact failing check and
            # sent agents into environment-probing loops. Preserve both ends.
            head = t[:160].rstrip()
            tail = t[-120:].lstrip()
            t = f"{head} …(中间已截断)\n{tail}"
        else:
            t = t[:_OBS_DISPLAY_MAX] + " …(已截断)"

    return t


def _escape_md_brackets(text: str) -> str:
    if not text:
        return text
    return text.replace("[", "\\[").replace("]", "\\]")


def _safe_for_streamdown(text: str) -> str:
    if not text:
        return text
    stripped = text.rstrip()
    m = re.search(r"\[([^\[\]]+)\]\(([^)\n]*)$", stripped)
    if m:
        return stripped + ")"
    m = re.search(r"(^|[^\\])\[([^\]\n]*)$", stripped)
    if m:
        return stripped + "]"
    return text


_FINAL_RE = re.compile(
    r"(?:"
    r"Final\s*Answer\s*:\s*"
    r"|\*\*\s*Final\s*Answer\s*:?\s*\*\*\s*:?\s*"
    r"|__\s*Final\s*Answer\s*:?\s*__\s*:?\s*"
    r"|^\s*#{1,6}\s*Final\s*Answer\s*:?\s*"
    r"|^\s*Final\s*Answer\s*(?:\r?\n)+"
    r")(.+)",
    re.IGNORECASE | re.DOTALL | re.MULTILINE,
)
_XML_FINAL_RE = re.compile(
    r"<final_answer\s*>\s*(?P<body>.*?)\s*</final_answer\s*>",
    re.IGNORECASE | re.DOTALL,
)
_THOUGHT_RE = re.compile(
    r"Thought\s*:\s*(.+?)(?:\n\s*(?:Update|Progress)|\n\s*Action|\n\s*Final|\n\n|$)",
    re.IGNORECASE | re.DOTALL,
)
_PUBLIC_UPDATE_RE = re.compile(
    r"(?:Update|Progress)\s*:\s*(.+?)(?:\n\s*Action|\n\s*Observation|"
    r"\n\s*Thought|\n\s*Final|\n\n|$)",
    re.IGNORECASE | re.DOTALL,
)
_ACTION_RE = re.compile(
    r"Action\s*:\s*(.+?)(?:\n\s*Observation|\n\s*Thought|\n\s*(?:Update|Progress)|\n\s*Final|\n\n|$)",
    re.IGNORECASE | re.DOTALL,
)
_OBS_RE = re.compile(
    r"Observation\s*:\s*(.+?)(?:\n\s*Thought|\n\s*Final|\n\n|$)",
    re.IGNORECASE | re.DOTALL,
)

# ── Incremental Thought streaming ─────────────────────────────
#
# The ReAct text protocol buffers everything before the Final Answer
# anchor so Thought/Action markup never leaks into the visible answer —
# but that also hides the Thought prose until the whole loop ends (the
# TTFT bottleneck for tool-heavy turns). The Thought prose itself is safe
# to surface (the UI renders it as a collapsible reasoning block), so the
# loop pulls it out of the growing buffer incrementally with the helper
# below. Emitted spans mirror what ``_THOUGHT_RE`` would later call the
# step's thought; Action blocks and tool envelopes are never emitted.

_THOUGHT_MARKER_RE = re.compile(r"Thought\s*:\s*", re.IGNORECASE)

# Terminators ending a Thought segment: ``_THOUGHT_RE``'s stop conditions
# plus the tool envelopes the loop treats as implicit actions. Matched
# case-insensitively against the lowered buffer.
_THOUGHT_STREAM_TERMINATORS = (
    "\naction",
    "\nobservation",
    "\nfinal",
    "\nupdate",
    "\nprogress",
    "\n\n",
    "<tool_call>",
    "<tool_invocation",
    "<function=",
)

# Unterminated tail chars held back while a Thought segment is still open.
# Must exceed the longest terminator (~16 chars) so a terminator split
# across chunk boundaries can never half-leak into the reasoning stream.
THOUGHT_STREAM_TAIL_MARGIN = 48


def extract_streamable_thought(
    joined: str,
    cursor: int,
    in_thought: bool,
    *,
    tail_margin: int = THOUGHT_STREAM_TAIL_MARGIN,
) -> tuple[str, int, bool]:
    """Pull newly decodable Thought prose out of a growing LLM buffer.

    Called once per streamed text chunk with the full pre-anchor buffer
    (``joined``) and the carry state from the previous call. Returns
    ``(new_text, new_cursor, new_in_thought)`` — feed the latter two back
    in with the next chunk. Only ``Thought: …terminator`` spans are
    emitted; everything else (Action blocks, tool envelopes, stray prose)
    is skipped, so the visible answer can never receive markup. An
    unterminated trailing segment emits all but its last ``tail_margin``
    chars, keeping split terminators atomic.
    """
    out: list[str] = []
    pos = cursor
    open_segment = in_thought
    lowered = joined.lower()
    length = len(joined)
    while pos < length:
        if not open_segment:
            marker = _THOUGHT_MARKER_RE.search(joined, pos)
            if marker is None:
                break
            pos = marker.end()
            open_segment = True
            continue
        end = length
        terminated = False
        for term in _THOUGHT_STREAM_TERMINATORS:
            idx = lowered.find(term, pos)
            if idx != -1 and idx < end:
                end = idx
                terminated = True
        if terminated:
            if end > pos:
                out.append(joined[pos:end])
            pos = end
            open_segment = False
            continue
        safe_end = max(pos, length - tail_margin)
        if safe_end > pos:
            out.append(joined[pos:safe_end])
        pos = safe_end
        break
    return "".join(out), pos, open_segment


_UNFINISHED_WORK_RE = re.compile(
    r"(?:"
    r"\b(?:still\s+need|not\s+yet|remaining\s+work|unfinished|incomplete)\b"
    r"|\b(?:need|needs|must|have)\s+to\s+"
    r"(?:fix|repair|implement|write|run|verify|complete|change|update)\b"
    r"|(?:需要|还需|尚需|必须|立即)(?:先|再)?"
    r"(?:修复|实现|重写|补充|运行|验证|完成|修改|更新)"
    r"|(?:尚未|还没有|未能)(?:修复|实现|写入|运行|验证|完成)"
    r"|存在[^\n。]{0,80}(?:bug|缺陷|死锁)"
    r")",
    re.IGNORECASE,
)


def _looks_like_unfinished_work(text: str) -> bool:
    """Whether free-form model prose explicitly says implementation remains.

    Zero-anchor recovery may safely salvage a completed chat-style answer, but
    must not turn an implementation diagnosis such as "need to fix the deadlock"
    into a terminal reply.  Keep this deliberately narrow and action-oriented.
    """

    return bool(_UNFINISHED_WORK_RE.search(str(text or "")))


def _looks_like_special_tool_envelope(text: str) -> bool:
    """Return whether provider text claims to be a tool-call envelope.

    Compatible endpoints occasionally surface private sentinels or generic
    ``<tool_calls><invoke ...>`` XML as assistant text.  The content may be
    incomplete rather than executable, but it must never be streamed or
    accepted as a normal final answer because that silently skips the request.
    """
    lowered = (text or "").lower()
    return any(marker in lowered for marker in _SPECIAL_TOOL_ENVELOPE_MARKERS)


def _split_action_lines(action_block: str) -> list[str]:
    """Split a multi-line Action block into individual tool calls.

    The legacy single-line shape (``read_file({...})``) returns a
    single-element list. The multi-action shape allows the model to
    write one call per line:

        Action:
            read_file({"path": "a"})
            read_file({"path": "b"})

    so the runtime can dispatch them concurrently. Lines that don't
    look like a tool call (blank, comment, prose) are ignored — this
    keeps `Action: none` and free-form notes working unchanged.
    """
    if not action_block:
        return []
    raw = action_block.strip()
    if not raw:
        return []
    lines: list[str] = []
    for ln in raw.splitlines():
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        if s.startswith("- "):
            s = s[2:].strip()
        # Some providers repeat the wire label before every call inside one
        # Action block. Never dispatch the literal label as a tool named
        # ``Action:``; strip it and keep the actual call when present.
        if re.fullmatch(r"Action\s*: ?", s, flags=re.IGNORECASE):
            continue
        s = re.sub(r"^Action\s*:\s*", "", s, flags=re.IGNORECASE)
        if not s:
            continue
        # `none`, `n/a`, plain identifiers without parens, and
        # `name({...})` shapes all parse via _parse_action; keep them.
        lines.append(s)
    if not lines:
        return [raw]
    return lines


def _parse_step(text: str, iteration: int) -> tuple[ReActStep, str | None]:
    step = ReActStep(iteration=iteration, raw_llm_output=text)

    thought_m = _THOUGHT_RE.search(text)
    if thought_m:
        step.thought = thought_m.group(1).strip()

    public_update_m = _PUBLIC_UPDATE_RE.search(text)
    if public_update_m:
        step.public_update = public_update_m.group(1).strip()

    action_m = _ACTION_RE.search(text)
    if action_m:
        action_block = action_m.group(1).strip()
        action_lines = _split_action_lines(action_block)
        # Each candidate line must parse via _parse_action to count
        # as a real call; otherwise we fall back to single-action
        # behavior (treat the whole block as one action string).
        parsed_actions: list[str] = []
        for ln in action_lines:
            p = _parse_action(ln)
            if p is None:
                parsed_actions = []
                break
            parsed_actions.append(_format_action(p[0], p[1]))
        if len(parsed_actions) > 1:
            step.actions = parsed_actions
            step.action = "; ".join(parsed_actions)
        else:
            step.action = action_block
            step.actions = [action_block] if action_block else []
    else:
        loose_actions = _extract_tool_actions_from_loose_output(text)
        if loose_actions:
            step.action = "; ".join(loose_actions)
            step.actions = loose_actions

    obs_m = _OBS_RE.search(text)
    if obs_m:
        step.observation = obs_m.group(1).strip()

    final_answer = _extract_final_answer(text)
    if step.action and final_answer and _extract_tool_action_from_loose_output(final_answer):
        final_answer = None

    return step, final_answer


def _extract_final_answer(text: str) -> str | None:
    """Extract standard ReAct or provider XML terminal answers."""
    final_m = _FINAL_RE.search(text or "")
    if final_m:
        return final_m.group(1).strip()
    xml_final_m = _XML_FINAL_RE.search(text or "")
    if xml_final_m:
        return xml_final_m.group("body").strip()
    return None


def _parse_reasoning_action_fallback(text: str, iteration: int) -> ReActStep | None:
    """Recover the last syntactically valid Action from reasoning-only output.

    Some OpenAI-compatible reasoning models put their complete ReAct response
    in ``reasoning_content`` and leave the assistant text empty.  Parsing the
    entire reasoning blob with ``_parse_step`` is too eager: deliberation may
    mention several rejected Action candidates.  Walk candidates backwards
    and accept only a block whose actions all parse as real tool calls.
    """
    if not isinstance(text, str) or not text.strip():
        return None
    for match in reversed(list(_ACTION_RE.finditer(text))):
        action_block = match.group(1).strip()
        candidate, _final = _parse_step(
            f"Action: {action_block}",
            iteration=iteration,
        )
        if not candidate.actions:
            continue
        if not all(_parse_action(action) is not None for action in candidate.actions):
            continue
        candidate.raw_llm_output = text
        return candidate

    # Reuse the conservative loose-envelope parser for reasoning-only
    # responses too.  Providers such as Kimi occasionally place a complete
    # ``<action>...tool({...})...</action>`` block in reasoning_content while
    # leaving assistant text empty.  _parse_step already accepts that exact
    # explicit execution boundary; failing to do the same here makes the
    # loop treat valid calls as a zero-anchor response and end the turn.
    loose_actions = _extract_tool_actions_from_loose_output(text)
    if loose_actions and all(_parse_action(action) is not None for action in loose_actions):
        return ReActStep(
            iteration=iteration,
            action="; ".join(loose_actions),
            actions=loose_actions,
            raw_llm_output=text,
        )
    return None
