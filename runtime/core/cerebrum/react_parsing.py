"""ReAct trajectory parsing + post-step quality checks.

╔══════════════════════════════════════════════════════════════════════════╗
║ react_parsing.py · navigation map (2616 lines, 107 functions).           ║
║                                                                          ║
║ Why one file: every detector reads ``ReActStep`` payloads and emits the  ║
║ same shape (label + offending tokens); they're consumed in lockstep by   ║
║ react_guards.py. Splitting risks importing each detector through 4+      ║
║ test files and 2 production modules. Sections below are cohesive enough  ║
║ to navigate without a split.                                             ║
║                                                                          ║
║   §1  Display / observation summarising            ~L18                  ║
║   §2  Step-text regexes + _parse_step / _parse_action ~L59               ║
║   §3  Format-violation + placeholder observations  ~L246                 ║
║   §4  Todo introspection                           ~L341                 ║
║   §5  Code-write detection + payload extraction    ~L370                 ║
║   §6  Verification trail (test+lint+typecheck+build) ~L551               ║
║   §7  Public-symbol signature change detection     ~L603                 ║
║   §8  Wire-schema / contract-test cross-checks     ~L803                 ║
║   §9  Dependency / import additions                ~L848                 ║
║   §10 Successful-verification observation parsing  ~L915                 ║
║   §11 Comment-only "code" fakeouts                 ~L984                 ║
║   §12 Broad except suppression                     ~L1082                ║
║   §13 tsconfig path validation                     ~L1142                ║
║   §14 Oversized edit detection                     ~L1266                ║
║   §15 Secret leak detection                        ~L1335                ║
║   §16 Destructive call detection (rm -rf, drop ...) ~L1388               ║
║   §17 Sleep-in-loop detection                      ~L1432                ║
║   §18 Full-file rewrite vs surgical edit           ~L1469                ║
║   §19 Weak-test classifiers (no-op, mock-only, ...) ~L1558               ║
║   §20 Print-call leakage                           ~L1662                ║
║   §21 Hardcoded-path detection                     ~L1719                ║
║   §22 Mock-only test detection                     ~L1773                ║
║   §23 Undocumented skip detection                  ~L1841                ║
║   §24 Test deletion / generic test names           ~L1900                ║
║   §25 No-assertion tests                           ~L2004                ║
║   §26 async-without-await                          ~L2092                ║
║   §27 Log swallow detection                        ~L2193                ║
║   §28 Long-function detection                      ~L2258                ║
║   §29 Dynamic exec / eval detection                ~L2337                ║
║   §30 Shell injection detection                    ~L2384                ║
║   §31 Unsafe deserialization                       ~L2427                ║
║   §32 Network-in-loop detection                    ~L2481                ║
║   §33 Repeated-literal / magic-number detection    ~L2532                ║
╚══════════════════════════════════════════════════════════════════════════╝

Each ``_step_introduces_*`` / ``_step_*`` predicate is consumed by
react_guards.py. The pattern is intentional: keep detection logic
(``_payload_*``) pure and deterministic, then layer the step-shape
adapter on top. Tests in tests/test_react_guards_*.py exercise both
layers directly.
"""

from __future__ import annotations

import json
import os as _os
import re
import sys as _sys
from typing import Any

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


_TOOL_CALL_RE = re.compile(
    r"<tool_call>\s*<function\s*=\s*(?P<name>[A-Za-z_][A-Za-z0-9_./:-]*)\s*>"
    r"(?P<body>.*?)</function>\s*</tool_call>",
    re.IGNORECASE | re.DOTALL,
)
_STANDALONE_NAMED_TOOL_CALL_RE = re.compile(
    r"<tool_call\s+name\s*=\s*[\"']?(?P<name>[A-Za-z_][A-Za-z0-9_./:-]*)[\"']?\s*>"
    r"\s*(?P<args>\{.*?\})\s*</tool_call>",
    re.IGNORECASE | re.DOTALL,
)
_FUNCTION_TYPE_CONTAINER_RE = re.compile(
    r"<tool_calls>\s*"
    r"<function_type>\s*(?P<name>[A-Za-z_][A-Za-z0-9_./:-]*)\s*</function_type>\s*"
    r"<function_params>\s*(?P<args>.*?)\s*</function_params>\s*"
    r"</tool_calls>",
    re.IGNORECASE | re.DOTALL,
)
_NAMED_TOOL_CONTAINER_RE = re.compile(
    r"<tool_calls>\s*"
    r"<tool_call\s+name\s*=\s*[\"']?(?P<name>[A-Za-z_][A-Za-z0-9_./:-]*)[\"']?\s*>"
    r"(?P<body>.*?)</tool_calls>",
    re.IGNORECASE | re.DOTALL,
)
_NAMED_TOOL_ARG_RE = re.compile(
    r"<tool_call\s+name\s*=\s*[\"']?(?P<key>[A-Za-z_][A-Za-z0-9_:-]*)[\"']?\s*>"
    r"(?P<value>.*?)</tool_call>",
    re.IGNORECASE | re.DOTALL,
)
_DIRECT_NAMED_TOOL_CONTAINER_RE = re.compile(
    r"<tool_calls>\s*"
    r"<(?P<name>[A-Za-z_][A-Za-z0-9_./:-]*)>\s*"
    r"(?P<body>.*?)\s*"
    r"</(?P=name)>\s*"
    r"</tool_calls>",
    re.IGNORECASE | re.DOTALL,
)
_MAIN_NAMED_TOOL_CONTAINER_RE = re.compile(
    r"<main>\s*"
    r"<(?P<name>[A-Za-z_][A-Za-z0-9_./:-]*)>\s*"
    r"(?P<args>.*?)\s*"
    r"</(?P=name)>\s*"
    r"</main>",
    re.IGNORECASE | re.DOTALL,
)
_BARE_NAMED_TOOL_TAG_RE = re.compile(
    r"<(?P<name>[a-z][a-z0-9]*(?:_[a-z0-9]+)+)>\s*"
    r"(?P<args>\{.*?\})\s*"
    r"</(?P=name)>",
    re.DOTALL,
)
_BARE_TODO_ARRAY_TAG_RE = re.compile(
    r"<todo_write>\s*(?P<args>\[.*?\])\s*</todo_write>",
    re.IGNORECASE | re.DOTALL,
)
_XML_ARG_RE = re.compile(
    r"<(?P<key>[A-Za-z_][A-Za-z0-9_:-]*)>(?P<value>.*?)</(?P=key)>",
    re.IGNORECASE | re.DOTALL,
)
_PARAM_ARG_RE = re.compile(
    r"<parameter\s*=\s*[\"']?(?P<key>[A-Za-z_][A-Za-z0-9_:-]*)[\"']?\s*>"
    r"(?P<value>.*?)</parameter>",
    re.IGNORECASE | re.DOTALL,
)
_NAMED_PARAM_ARG_RE = re.compile(
    r"<parameter\s+name\s*=\s*[\"'](?P<key>[A-Za-z_][A-Za-z0-9_:-]*)[\"']\s*>"
    r"(?P<value>.*?)</parameter>",
    re.IGNORECASE | re.DOTALL,
)
_INVOKE_TOOL_CALL_RE = re.compile(
    r"<invoke\s+name\s*=\s*[\"'](?P<name>[A-Za-z_][A-Za-z0-9_./:-]*)[\"']\s*>"
    r"(?P<body>.*?)</invoke>",
    re.IGNORECASE | re.DOTALL,
)
_FENCED_JSON_RE = re.compile(
    r"```(?:json)?\s*(?P<body>\{.*?\})\s*```",
    re.IGNORECASE | re.DOTALL,
)
_ACTION_XML_CONTAINER_RE = re.compile(
    r"<Action>\s*(?P<body>.*?)\s*</Action>",
    re.IGNORECASE | re.DOTALL,
)
_SPECIAL_TOOL_ENVELOPE_MARKERS = (
    "<|tool_calls_section_begin|>",
    "<|tool_calls_begin|>",
    "<|tool_calls_end|>",
    "<|tool_calls_section_end|>",
    "<tool_calls",
    "<invoke name=",
)


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


def _coerce_xml_arg_value(value: str) -> Any:
    stripped = value.strip()
    if stripped.startswith(("{", "[")):
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            return stripped
    return stripped


def _xml_args_from_body(body: str) -> dict[str, Any]:
    args: dict[str, Any] = {}
    for m in _XML_ARG_RE.finditer(body or ""):
        args[m.group("key")] = _coerce_xml_arg_value(m.group("value"))
    for m in _PARAM_ARG_RE.finditer(body or ""):
        args[m.group("key")] = _coerce_xml_arg_value(m.group("value"))
    for m in _NAMED_PARAM_ARG_RE.finditer(body or ""):
        args[m.group("key")] = _coerce_xml_arg_value(m.group("value"))

    kwargs = args.get("kwargs")
    if isinstance(kwargs, dict):
        return kwargs
    if isinstance(kwargs, str):
        try:
            parsed_kwargs = json.loads(kwargs)
        except json.JSONDecodeError:
            parsed_kwargs = None
        if isinstance(parsed_kwargs, dict):
            return parsed_kwargs
    return args


def _extract_tool_actions_from_loose_output(text: str) -> list[str]:
    actions: list[str] = []
    # DeepSeek-compatible endpoints may expose a complete tool call through a
    # ``<main><tool_name>{json}</tool_name></main>`` envelope.  ``todo_write``
    # commonly carries a top-level JSON array while ordinary tools carry an
    # object.  The explicit outer boundary plus a successful JSON decode keeps
    # this conservative: normal HTML ``<main>`` content is not executable.
    for xml in _MAIN_NAMED_TOOL_CONTAINER_RE.finditer(text):
        try:
            payload = json.loads(xml.group("args"))
        except json.JSONDecodeError:
            continue
        name = _normalize_action_name(xml.group("name").strip())
        if isinstance(payload, list) and name == "todo_write":
            args: dict[str, Any] = {"items": payload}
        elif isinstance(payload, dict):
            args = payload
            if name == "todo_write" and "todos" in args and "items" not in args:
                args["items"] = args.pop("todos")
        else:
            continue
        actions.append(_format_action(name, args))
    if actions:
        return actions

    # Some OpenAI-compatible providers expose their internal function wire
    # format as assistant text:
    # ``<tool_calls><invoke name="fn"><parameter name="arg">...``.
    # A complete, closed invoke is an explicit execution boundary; recover
    # every call in the container rather than treating it as zero-anchor prose.
    for xml in _INVOKE_TOOL_CALL_RE.finditer(text):
        name = _normalize_action_name(xml.group("name").strip())
        args = _xml_args_from_body(xml.group("body") or "")
        if name == "todo_write" and "todos" in args and "items" not in args:
            args["items"] = args.pop("todos")
        actions.append(_format_action(name, args))
    if actions:
        return actions

    for xml in _TOOL_CALL_RE.finditer(text):
        name = _normalize_action_name(xml.group("name").strip())
        args = _xml_args_from_body(xml.group("body") or "")
        actions.append(_format_action(name, args))
    if actions:
        return actions

    # Some reasoning providers emit a complete, standalone named call with
    # a JSON body, without the plural ``<tool_calls>`` wrapper.  Require both
    # an explicit tool name and a closed JSON object so XML examples or
    # incomplete streamed fragments in prose are never executed.
    for xml in _STANDALONE_NAMED_TOOL_CALL_RE.finditer(text):
        try:
            args = json.loads(xml.group("args"))
        except json.JSONDecodeError:
            continue
        if not isinstance(args, dict):
            continue
        name = _normalize_action_name(xml.group("name").strip())
        if name == "todo_write" and "todos" in args and "items" not in args:
            args["items"] = args.pop("todos")
        actions.append(_format_action(name, args))
    if actions:
        return actions

    # A few OpenAI-compatible reasoning providers emit one explicit XML
    # container per call, with a JSON object in ``function_params``.  Keep
    # recovery scoped to the complete container so XML examples in prose do
    # not become executable actions.
    for xml in _FUNCTION_TYPE_CONTAINER_RE.finditer(text):
        try:
            args = json.loads(xml.group("args"))
        except json.JSONDecodeError:
            continue
        if not isinstance(args, dict):
            continue
        name = _normalize_action_name(xml.group("name").strip())
        if name == "todo_write" and "todos" in args and "items" not in args:
            args["items"] = args.pop("todos")
        actions.append(_format_action(name, args))
    if actions:
        return actions

    # Some OpenAI-compatible reasoning models serialize function calls as
    # ``<tool_calls><tool_call name="fn"><tool_call name="arg">...``
    # instead of returning protocol-level tool_calls.  Recover only inside
    # the explicit container so ordinary XML/code examples are not executed.
    for xml in _NAMED_TOOL_CONTAINER_RE.finditer(text):
        name = _normalize_action_name(xml.group("name").strip())
        args = {
            arg.group("key"): _coerce_xml_arg_value(arg.group("value"))
            for arg in _NAMED_TOOL_ARG_RE.finditer(xml.group("body") or "")
        }
        if name == "todo_write" and "todos" in args and "items" not in args:
            args["items"] = args.pop("todos")
        actions.append(_format_action(name, args))
    if actions:
        return actions

    # Kimi-style reasoning occasionally uses the tool name itself as the XML
    # element: ``<tool_calls><glob_files><pattern>…``.  The outer marker is an
    # explicit execution boundary, so recover the named child and its args.
    for xml in _DIRECT_NAMED_TOOL_CONTAINER_RE.finditer(text):
        name = _normalize_action_name(xml.group("name").strip())
        args = _xml_args_from_body(xml.group("body") or "")
        actions.append(_format_action(name, args))
    if actions:
        return actions

    # DeepSeek-style bare tool tags: ``<write_text_file>\n{json}\n
    # </write_text_file>`` with no wrapper at all.  There is no container
    # marker to anchor on, so the gates are strict instead: the tag must be
    # lowercase snake_case (real tool names always carry an underscore —
    # prose XML like ``<summary>`` or ``<Action>`` never matches), the tag
    # must close with the same name, and the body must be one closed JSON
    # object.  This path only runs after every anchored format above found
    # nothing, so ordinary responses never reach it.
    # The checklist tool is the one deliberate array-valued exception.  Keep
    # it in a dedicated, exact-name parser instead of broadening every bare
    # tool tag to array payloads.
    for xml in _BARE_TODO_ARRAY_TAG_RE.finditer(text):
        try:
            items = json.loads(xml.group("args"))
        except json.JSONDecodeError:
            continue
        if not isinstance(items, list):
            continue
        actions.append(_format_action("todo_write", {"items": items}))
    if actions:
        return actions

    for xml in _BARE_NAMED_TOOL_TAG_RE.finditer(text):
        try:
            args = json.loads(xml.group("args"))
        except json.JSONDecodeError:
            continue
        if not isinstance(args, dict):
            continue
        name = _normalize_action_name(xml.group("name").strip())
        if name == "todo_write" and "todos" in args and "items" not in args:
            args["items"] = args.pop("todos")
        actions.append(_format_action(name, args))
    if actions:
        return actions

    # A few reasoning models wrap otherwise-valid ReAct calls in a literal
    # ``<Action>`` block and put one call on each line.  This is still an
    # explicit execution boundary, so recover the lines conservatively; do
    # not scan arbitrary prose for call-looking snippets.
    for container in _ACTION_XML_CONTAINER_RE.finditer(text):
        for line in (container.group("body") or "").splitlines():
            candidate = line.strip().lstrip("-*").strip()
            parsed = _parse_action(candidate)
            if parsed is None:
                continue
            actions.append(_format_action(*parsed))
    if actions:
        return actions

    for fenced in _FENCED_JSON_RE.finditer(text):
        try:
            payload = json.loads(fenced.group("body"))
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        raw_name = (
            payload.get("command")
            or payload.get("tool")
            or payload.get("name")
            or payload.get("action")
        )
        if not isinstance(raw_name, str) or not raw_name.strip():
            continue
        args = payload.get("kwargs") or payload.get("args") or {}
        if not isinstance(args, dict):
            args = {}
        actions.append(_format_action(_normalize_action_name(raw_name.strip()), args))
    return actions


def _extract_tool_action_from_loose_output(text: str) -> str | None:
    """Recover tool calls from common non-ReAct envelopes.

    Some OpenAI-compatible models stream XML-ish tool tags or fenced JSON
    commands instead of the expected ``Action: tool({...})`` line. Treat those
    as an Action so the loop executes the real tool instead of displaying a
    fake tool call as assistant prose.
    """
    actions = _extract_tool_actions_from_loose_output(text)
    return actions[0] if actions else None


def _format_action(name: str, args: dict[str, Any]) -> str:
    return f"{name}({json.dumps(args, ensure_ascii=False)})"


def _is_format_violation(
    step: ReActStep,
    final_answer: str | None,
) -> bool:
    """True when the LLM returned text but produced zero ReAct anchors.

    Signals "the LLM is not following Thought/Action/Final-Answer
    format" — usually because it dumped a JSON plan, a tool-call
    envelope, or free-form prose instead. Two consecutive violations
    means we should stop poking the same rake and hand back to the
    caller's direct-LLM fallback, which doesn't force ReAct format.
    """
    raw = (step.raw_llm_output or "").strip()
    if not raw:
        # Truly empty response is a different failure (network /
        # upstream error); caller's existing exception path handles
        # that.
        return False
    return final_answer is None and not step.thought and not step.action and not step.observation


def _placeholder_observation(action: str) -> str:
    if not action or action.lower() in {"none", "n/a", ""}:
        return "N/A"
    return (
        f"(未执行观察) Action '{action}' 没有解析为可执行的已注册工具调用。"
        "工具系统仍然可用；请检查工具名，并改用 skill_name({JSON}) 格式重试。"
    )


_ACTION_CALL_RE = re.compile(
    r"""
    ^\s*
    (?P<name>[A-Za-z_][A-Za-z0-9_./:-]*)   # skill 名(容许 /、:、.、-)
    \s*
    [\(\[]                                 # ( 或 [
    (?P<args>.*)                           # 参数体
    [\)\]]                                 # ) 或 ]
    \s*$
    """,
    re.VERBOSE | re.DOTALL,
)

_ACTION_NAME_ALIASES = {
    "deep-research_swarm": "deep-research-swarm",
    "deep_research_swarm": "deep-research-swarm",
    "deep_research-swarm": "deep-research-swarm",
    "deep_research": "deep-research",
    "write_file": "write_text_file",
}


def _normalize_action_name(name: str) -> str:
    return _ACTION_NAME_ALIASES.get(name, name)


def _parse_action(action_text: str) -> tuple[str, dict[str, Any]] | None:
    if not action_text:
        return None
    text = action_text.strip().rstrip(".").rstrip(";")
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_./:-]*", text):
        return (_normalize_action_name(text), {})
    m = _ACTION_CALL_RE.match(text)
    if not m:
        return None
    name = _normalize_action_name(m.group("name"))
    args_raw = (m.group("args") or "").strip()
    if not args_raw:
        return (name, {})
    try:
        parsed = json.loads(args_raw)
    except json.JSONDecodeError:
        try:
            kv_pairs: dict[str, Any] = {}
            for pair in re.split(r",(?![^{}\[\]]*[}\]])", args_raw):
                if "=" not in pair:
                    continue
                k, _, v = pair.partition("=")
                kv_pairs[k.strip()] = v.strip().strip("\"'")
            parsed = kv_pairs if kv_pairs else None
        except (TypeError, ValueError):
            parsed = None
    if isinstance(parsed, list) and name == "todo_write":
        parsed = {"items": parsed}
    if not isinstance(parsed, dict):
        return None
    return (name, parsed)


def _latest_todo_items(steps: list[ReActStep]) -> list[dict[str, Any]]:
    """Return the most recent todo_write payload from the trajectory."""
    for step in reversed(steps):
        parsed = _parse_action(step.action)
        if parsed is None:
            continue
        name, args = parsed
        if name != "todo_write":
            continue
        raw_items = args.get("items") or args.get("todos") or []
        items = _coerce_todo_action_items(raw_items)
        if items:
            return [item for item in items if isinstance(item, dict)]
    return []


def _coerce_todo_action_items(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return _coerce_todo_action_items(json.loads(value))
        except json.JSONDecodeError:
            return []
    if isinstance(value, dict):
        return _coerce_todo_action_items(value.get("items") or value.get("todos"))
    return []


def _has_code_write(steps: list[ReActStep]) -> bool:
    return any(_is_code_write_step(step) for step in steps)


# Canonical write-tool set. Kept as a module-level constant so the
# completion guard, the post-write verification guard, and the public
# ``_has_code_write`` helper all stay aligned. Adding a new edit-style
# skill (e.g. ``patch_file_v2``) needs exactly one update here.
_CODE_WRITE_TOOLS: frozenset[str] = frozenset(
    {
        # Legacy text writers
        "write_text_file",
        "append_text_file",
        "edit_text_file",
        # Newer Edit-style skills (octopus optimisation §2.1 / §2.2)
        "edit_file",
        "multi_edit_file",
        # Aliases used by other registries / external integrations
        "edit_code",
        "str_replace",
        "write_file",
        "create_file",
        "apply_patch",
    }
)


def _is_code_write_step(step: ReActStep) -> bool:
    """Whether this step performed a real code-writing action.

    Used by both the final-answer guard and the in-flight "you wrote
    code, now verify it" guard. Centralising the tool-set means
    contributors adding a new edit-style skill only need to register
    it in ``_CODE_WRITE_TOOLS`` above.
    """
    actions = step.actions or ([step.action] if step.action else [])
    for action in actions:
        parsed = _parse_action(action)
        if parsed is not None and parsed[0] in _CODE_WRITE_TOOLS:
            return True
    return False


def _extract_step_path(step: ReActStep) -> str | None:
    """Return the ``path`` / ``file`` / ``file_path`` arg of a write step,
    or ``None`` when the step isn't a write or has no path argument."""
    # Mutation guards share this helper.  Do not let a read-only action that
    # happens to carry the same ``path`` argument masquerade as an edit (for
    # example ``read_file(runtime/protocol/items.py)`` previously tripped the
    # wire-schema-change guard and demanded a contract test).
    if not _is_code_write_step(step):
        return None
    parsed = _parse_action(step.action)
    if parsed is None:
        return None
    _name, args = parsed
    value = args.get("path") or args.get("file") or args.get("file_path")
    return value if isinstance(value, str) else None


def _extract_step_payloads(step: ReActStep) -> tuple[str, str]:
    """Return ``(new_text, old_text)`` for a write step.

    Concatenates ``content`` / ``new_string`` / ``new_str`` (and the
    same fields inside every ``edits`` entry) into ``new_text``, and
    ``old_string`` / ``old_str`` (top-level + per-edit) into ``old_text``.

    Centralises the payload-extraction shape used by every
    ``_step_introduces_*`` / ``_step_replaced_*`` helper. Returns
    ``("", "")`` if the step isn't a write or can't be parsed —
    callers should treat that as "nothing to inspect".
    """
    if not _is_code_write_step(step):
        return ("", "")
    parsed = _parse_action(step.action)
    if parsed is None:
        return ("", "")
    _name, args = parsed
    new_chunks: list[str] = []
    old_chunks: list[str] = []
    for key in ("content", "new_string", "new_str"):
        value = args.get(key)
        if isinstance(value, str):
            new_chunks.append(value)
    for key in ("old_string", "old_str"):
        value = args.get(key)
        if isinstance(value, str):
            old_chunks.append(value)
    edits = args.get("edits")
    if isinstance(edits, list):
        for edit in edits:
            if not isinstance(edit, dict):
                continue
            for key in ("new_string", "new_str", "content"):
                value = edit.get(key)
                if isinstance(value, str):
                    new_chunks.append(value)
            for key in ("old_string", "old_str"):
                value = edit.get(key)
                if isinstance(value, str):
                    old_chunks.append(value)
    return ("\n".join(new_chunks), "\n".join(old_chunks))


_AMBIGUOUS_INFLIGHT_IDENTITY_RE = re.compile(
    r"if\s+(?:self\.)?(?P<map>[A-Za-z_][A-Za-z0-9_]*)\.get\(\s*"
    r"(?P<key>[A-Za-z_][A-Za-z0-9_]*)\s*\)\s+is\s+(?:not\s+)?"
    r"(?P<pending>[A-Za-z_][A-Za-z0-9_]*)\s*:"
)


def _payload_has_inflight_identity_comparison(text: str) -> bool:
    return bool(text and _AMBIGUOUS_INFLIGHT_IDENTITY_RE.search(text))


def _payload_has_ambiguous_inflight_leader_election(text: str) -> bool:
    """Detect re-reading an in-flight map to infer who created its entry.

    Once a shared pending object has been inserted, both its creator and every
    follower read the same object back.  An identity comparison performed
    after leaving the lock therefore cannot elect a leader; all callers can
    take the loader path.  A creator flag captured inside the locked
    ``pending is None`` branch is the auditable form.
    """
    if not text or "pending" not in text.lower() or ".get(" not in text:
        return False
    for match in _AMBIGUOUS_INFLIGHT_IDENTITY_RE.finditer(text):
        map_name = re.escape(match.group("map"))
        key_name = re.escape(match.group("key"))
        pending_name = re.escape(match.group("pending"))
        creates_entry = re.search(
            rf"if\s+{pending_name}\s+is\s+None\s*:"
            rf"[\s\S]{{0,700}}(?:self\.)?{map_name}\[\s*{key_name}\s*\]\s*=\s*"
            rf"{pending_name}\b",
            text,
        )
        explicit_election = re.search(r"\b(?:is_)?leader\s*=", text)
        if creates_entry and not explicit_election:
            return True
    return False


_WAITER_CALL_RE = re.compile(r"\.wait(?:_for)?\s*\([^\n]*\)|\.wait\s*\(\s*\)")
_MAPPING_POP_RE = re.compile(
    r"\.(?:pop)\(\s*(?P<key>[A-Za-z_][A-Za-z0-9_]*)\s*(?:,|\))"
)


def _payload_has_destructive_waiter_result_pop(text: str) -> bool:
    """Whether followers destructively consume one shared load result."""
    if not text or ".pop(" not in text or ".wait" not in text:
        return False
    for wait_match in _WAITER_CALL_RE.finditer(text):
        # Inspect only the follower's post-wait return path.  A later leader
        # branch may legitimately remove the in-flight map entry *after* it
        # publishes result/exception on a mutable object; the old unbounded
        # regex crossed that return boundary and misclassified safe cleanup.
        segment = text[wait_match.end() : wait_match.end() + 1200]
        terminal = re.search(r"\b(?:return|raise)\b", segment)
        if terminal is not None:
            segment = segment[: terminal.end()]
        if _MAPPING_POP_RE.search(segment):
            return True
    return False


_STALE_IMMUTABLE_WAITER_FALLBACK_RE = re.compile(
    r"\.wait(?:_for)?\s*\([^\n]*\)"
    r"[\s\S]{0,1600}?"
    r"(?P<map>(?:self\.)?[A-Za-z_][A-Za-z0-9_]*)\.get\(\s*"
    r"(?P<key>[A-Za-z_][A-Za-z0-9_]*)\s*,\s*"
    r"(?P<snapshot>[A-Za-z_][A-Za-z0-9_]*)\s*\)"
)
_DELETED_PENDING_WAITER_READ_RE = re.compile(
    r"\.wait(?:_for)?\s*\([^\n]*\)"
    r"[\s\S]{0,1600}?"
    r"(?P<map>(?:self\.)?[A-Za-z_][A-Za-z0-9_]*)\[\s*"
    r"(?P<key>[A-Za-z_][A-Za-z0-9_]*)\s*\]"
)


def _payload_has_stale_immutable_waiter_snapshot(text: str) -> bool:
    """Detect a waiter falling back to an immutable pre-wait tuple snapshot.

    Replacing ``pending[key]`` with a new tuple and then deleting the entry is
    not visible through the tuple a follower captured before ``wait()``.  A
    post-wait ``map.get(key, pending)`` therefore falls back to stale
    ``(event, None, None)`` and can return ``None`` or hide an exception.
    Mutable pending objects are safe because the captured object itself is
    updated before the event is signalled.
    """
    if not text or ".wait" not in text or "del " not in text:
        return False
    for match in _STALE_IMMUTABLE_WAITER_FALLBACK_RE.finditer(text):
        map_name = re.escape(match.group("map"))
        key_name = re.escape(match.group("key"))
        snapshot_name = re.escape(match.group("snapshot"))
        tuple_snapshot = re.search(
            rf"(?:[A-Za-z_][A-Za-z0-9_]*\s*,\s*){{2,}}[A-Za-z_][A-Za-z0-9_]*"
            rf"\s*=\s*{snapshot_name}\b",
            text,
        )
        tuple_replacement = re.search(
            rf"{map_name}\[\s*{key_name}\s*\]\s*=\s*\(",
            text,
        )
        deletes_entry = re.search(
            rf"del\s+{map_name}\[\s*{key_name}\s*\]",
            text,
        )
        if tuple_snapshot and tuple_replacement and deletes_entry:
            return True
    for match in _DELETED_PENDING_WAITER_READ_RE.finditer(text):
        map_name = re.escape(match.group("map"))
        key_name = re.escape(match.group("key"))
        tuple_replacement = re.search(
            rf"{map_name}\[\s*{key_name}\s*\]\s*=\s*\(",
            text,
        )
        deletes_entry = re.search(
            rf"del\s+{map_name}\[\s*{key_name}\s*\]",
            text,
        )
        if tuple_replacement and deletes_entry:
            return True
    return False


_TERMINAL_PENDING_TUPLE_RE = re.compile(
    r"(?P<map>(?:self\.)?[A-Za-z_][A-Za-z0-9_]*(?:pending|inflight)[A-Za-z0-9_]*)"
    r"\[\s*(?P<key>[A-Za-z_][A-Za-z0-9_]*)\s*\]\s*=\s*\("
    r"(?P<body>[^\n)]{1,500})\)",
    re.IGNORECASE,
)


def _payload_has_terminal_pending_entry_leak(text: str) -> bool:
    """Detect a completed in-flight tuple that is never removed.

    Keeping a terminal ``pending[key] = (event, value, error)`` entry makes
    every later caller look like a follower.  In a TTL cache that means an
    expired key can keep returning the old completed flight forever; a failed
    flight can likewise poison every retry.  Waiters may retain a mutable
    per-flight object, but the key must leave the *in-flight map* once the
    leader has published terminal state.
    """
    if (
        not text
        or ".wait" not in text
        or ".set(" not in text
        or "loader(" not in text
    ):
        return False
    assignments = list(_TERMINAL_PENDING_TUPLE_RE.finditer(text))
    if len(assignments) < 2:
        return False
    by_slot: dict[tuple[str, str], list[re.Match[str]]] = {}
    for match in assignments:
        slot = (match.group("map"), match.group("key"))
        by_slot.setdefault(slot, []).append(match)
    for (map_name, key_name), slot_assignments in by_slot.items():
        bodies = [match.group("body") for match in slot_assignments]
        has_initial_state = any(body.count("None") >= 2 for body in bodies)
        has_terminal_state = any(body.count("None") < 2 for body in bodies)
        if not (has_initial_state and has_terminal_state):
            continue
        escaped_map = re.escape(map_name)
        escaped_key = re.escape(key_name)
        removes_slot = re.search(
            rf"(?:del\s+{escaped_map}\[\s*{escaped_key}\s*\]"
            rf"|{escaped_map}\.pop\(\s*{escaped_key}\b)",
            text,
        )
        if not removes_slot:
            return True
    return False


def _payload_has_loader_barrier_deadlock(text: str) -> bool:
    """Detect a test loader waiting alone on a ``threading.Barrier``.

    In a single-flight test only the elected leader enters ``loader``;
    followers wait on the flight event.  A barrier placed inside that loader
    can therefore never collect the follower threads and deadlocks the test.
    Synchronising workers *before* ``get_or_load`` is the valid pattern.
    """
    if not text or "Barrier(" not in text or "get_or_load" not in text:
        return False
    lines = text.splitlines()
    for index, line in enumerate(lines):
        definition = re.match(
            r"^(?P<indent>[ \t]+)def\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*\(",
            line,
            re.IGNORECASE,
        )
        if definition is None or "loader" not in definition.group("name").lower():
            continue
        indent_width = len(definition.group("indent").expandtabs(4))
        body_lines: list[str] = []
        for candidate in lines[index + 1 :]:
            if not candidate.strip():
                body_lines.append(candidate)
                continue
            candidate_indent = len(candidate) - len(candidate.lstrip(" \t"))
            if candidate_indent <= indent_width:
                break
            body_lines.append(candidate)
        body = "\n".join(body_lines)
        for wait in re.finditer(
            r"(?P<barrier>[A-Za-z_][A-Za-z0-9_]*)\.wait\s*\(",
            body,
        ):
            barrier = wait.group("barrier")
            assignment = re.search(
                rf"\b{re.escape(barrier)}\s*=\s*(?:threading\.)?Barrier\s*\("
                r"\s*(?P<parties>\d+)",
                text,
            )
            if assignment is None:
                continue
            total_waits = len(
                re.findall(rf"\b{re.escape(barrier)}\.wait\s*\(", text)
            )
            loader_name = re.escape(definition.group("name"))
            passed_to_cache = re.search(
                rf"get_or_load\s*\([^\n]{{0,300}}\b{loader_name}\b",
                text,
            )
            parties = int(assignment.group("parties"))
            # The only bounded loader-barrier shape we tolerate is an
            # explicit two-party rendezvous between the elected loader and
            # one controller thread.  With N>2, extra static wait sites do
            # not prove N runtime participants (v31 had Barrier(5) but only
            # loader + main thread could ever reach it).  Worker threads in a
            # single-flight test wait on the flight event, not in loader.
            if passed_to_cache and not (parties == 2 and total_waits >= 2):
                return True
    return False


def _payload_has_wait_while_lock_held(text: str) -> bool:
    """Detect blocking on an event/future while retaining a map mutex."""
    if not text or ".wait(" not in text or "lock" not in text.lower():
        return False
    lines = text.splitlines()
    for index, line in enumerate(lines):
        context = re.match(
            r"^(?P<indent>[ \t]*)with\s+(?P<lock>(?:self\.)?[A-Za-z_][A-Za-z0-9_]*lock[A-Za-z0-9_]*)\s*:",
            line,
            re.IGNORECASE,
        )
        if context is None:
            continue
        indent_width = len(context.group("indent").expandtabs(4))
        body_lines: list[str] = []
        for candidate in lines[index + 1 :]:
            if not candidate.strip():
                body_lines.append(candidate)
                continue
            candidate_indent = len(candidate) - len(candidate.lstrip(" \t"))
            if candidate_indent <= indent_width:
                break
            body_lines.append(candidate)
        body = "\n".join(body_lines)
        if re.search(r"\b[A-Za-z_][A-Za-z0-9_.]*\.wait\s*\(", body):
            return True
    for acquire in re.finditer(
        r"(?P<lock>(?:self\.)?[A-Za-z_][A-Za-z0-9_]*lock[A-Za-z0-9_]*)"
        r"\.acquire\s*\(",
        text,
        re.IGNORECASE,
    ):
        lock_name = re.escape(acquire.group("lock"))
        release = re.search(rf"{lock_name}\.release\s*\(", text[acquire.end() :])
        segment_end = acquire.end() + (release.start() if release is not None else 1600)
        segment = text[acquire.end() : segment_end]
        if re.search(r"\b[A-Za-z_][A-Za-z0-9_.]*\.wait\s*\(", segment):
            return True
    return False


_SINGLE_PASS_URL_DECODE_RE = re.compile(r"\bunquote(?:_plus)?\s*\(")
_PATH_BOUNDARY_PAYLOAD_MARKERS = (
    "pathboundaryerror",
    "relative_to(",
    "commonpath(",
    "is_relative_to(",
    "symlink",
    "path traversal",
)


def _payload_has_single_pass_url_decode(text: str) -> bool:
    """Detect one-shot URL decoding in path-boundary validation.

    A single ``unquote`` turns a double-encoded traversal into a still-
    encoded path, so a subsequent canonical containment check sees an
    innocuous filename.  Repeated decoding in a loop (or two explicit nested
    decodes) is not flagged.  Callers must separately establish that the
    payload belongs to path-boundary code before treating this as a defect.
    """

    if not text:
        return False
    calls = list(_SINGLE_PASS_URL_DECODE_RE.finditer(text))
    if len(calls) != 1:
        return False
    call_line_start = text.rfind("\n", 0, calls[0].start()) + 1
    call_line = text[call_line_start : text.find("\n", calls[0].end())]
    call_indent = len(call_line) - len(call_line.lstrip(" \t"))
    prefix_lines = text[:call_line_start].splitlines()
    for line in reversed(prefix_lines):
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" \t"))
        if indent >= call_indent:
            continue
        stripped = line.strip()
        if re.match(r"(?:while\b|for\b).*:\s*(?:#.*)?$", stripped):
            return False
        # The nearest enclosing block is not a loop; outer blocks cannot
        # make the call repeat without the call being nested under them.
        break
    return True


def _payload_looks_like_path_boundary(text: str) -> bool:
    lowered = str(text or "").lower()
    return "unquote" in lowered and any(
        marker in lowered for marker in _PATH_BOUNDARY_PAYLOAD_MARKERS
    )


_DEDICATED_VERIFY_TOOLS: frozenset[str] = frozenset(
    {
        "run_tests",
        "run_checks",
        "verify",
        "lint_check",
        "format_code",
    }
)
_VERIFY_TOOLS: frozenset[str] = frozenset(
    {
        "exec_shell",
        "shell_command",
        "bash",
        *_DEDICATED_VERIFY_TOOLS,
    }
)

# Verification markers grouped by language. The "all" bucket is the
# legacy flat list — kept for the language-agnostic
# ``_has_code_verification`` helper. The per-language buckets power
# the §19 language-mismatch guard: writing TS but only running pytest
# does NOT count as verifying the TS edit.
_LANG_VERIFY_MARKERS: dict[str, tuple[str, ...]] = {
    "python": (
        "pytest",
        "unittest",
        "ruff",
        "mypy",
        "py_compile",
        "python -m compileall",
        "pyright",
        "flake8",
        "black --check",
    ),
    "typescript": (
        "tsc",
        "npm run typecheck",
        "pnpm typecheck",
        "yarn typecheck",
        "npm run lint",
        "pnpm lint",
        "yarn lint",
        "npm test",
        "pnpm test",
        "yarn test",
        "eslint",
        "vitest",
        "playwright",
        "jest",
    ),
    "rust": ("cargo check", "cargo build", "cargo test", "cargo clippy"),
    "go": ("go build", "go test", "go vet", "golangci-lint"),
}

_VERIFY_MARKERS_ALL: tuple[str, ...] = tuple(
    marker for markers in _LANG_VERIFY_MARKERS.values() for marker in markers
)


# File-extension → language bucket. Kept conservative: only languages
# we have a verifier story for. Unknown extensions return ``None`` so
# the guard treats them as "we don't know — don't nag".
_EXT_TO_LANG: dict[str, str] = {
    ".py": "python",
    ".pyi": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "typescript",
    ".jsx": "typescript",
    ".mjs": "typescript",
    ".cjs": "typescript",
    ".rs": "rust",
    ".go": "go",
}


def _path_language(path: str | None) -> str | None:
    """Map a file path to a verification-language bucket, or ``None``.

    Returning ``None`` for unknown extensions is intentional: callers
    must treat "unknown language" as "skip the language-specific
    check", not as "verification missing". We'd rather miss a real
    miss than spam a noisy nudge for every Markdown / YAML edit.
    """
    if not path:
        return None
    lowered = path.lower()
    for ext, lang in _EXT_TO_LANG.items():
        if lowered.endswith(ext):
            return lang
    return None


def _step_command_text(step: ReActStep) -> str:
    """Concatenate Action + arg `command` lowercased — for marker scans."""
    parsed = _parse_action(step.action)
    if parsed is None:
        return (step.action or "").lower()
    _name, args = parsed
    command = str(args.get("command") or args.get("cmd") or "")
    return f"{step.action or ''} {command}".lower()


_NODE_VERIFY_SCRIPT_RE = re.compile(
    r"^\s*node(?:\s+--?[a-z0-9_-]+)*\s+"
    r"(?!-e(?:\s|$))"
    r"[^\n]*?(?:test|spec|verify|verification|check)[^\n]*$",
    re.IGNORECASE,
)
_NODE_INLINE_FAILURE_BRANCH_RE = re.compile(
    r"^\s*node\s+-e(?:\s|$)[\s\S]*?"
    r"process\.exit\s*\(\s*(?:1\b|[^)]*\b(?:fail|failed|error|errors)\b[^)]*)\)",
    re.IGNORECASE,
)


def _node_command_is_verification(command: str) -> bool:
    """Recognize executable Node verification without trusting fake green text.

    Static fixtures often have no package manifest, so agents reasonably run
    ``node verify.js`` or an inline race harness.  A script name must carry a
    verification marker; inline code must contain a genuine non-zero failure
    branch.  Merely printing ``tests passed`` and exiting zero is deliberately
    excluded.
    """

    return bool(
        _NODE_VERIFY_SCRIPT_RE.search(command)
        or _NODE_INLINE_FAILURE_BRANCH_RE.search(command)
    )


def _step_is_verify(step: ReActStep, *, markers: tuple[str, ...]) -> bool:
    actions = step.actions or ([step.action] if step.action else [])
    for action in actions:
        parsed = _parse_action(action)
        if parsed is None:
            continue
        name, args = parsed
        if name in _DEDICATED_VERIFY_TOOLS:
            return True
        if name not in _VERIFY_TOOLS:
            continue
        command = str(args.get("command") or args.get("cmd") or "")
        if "tsc" in markers and _node_command_is_verification(command):
            return True
        haystack = f"{action} {command}".lower()
        if any(marker in haystack for marker in markers):
            return True
    return False


def _has_code_verification(steps: list[ReActStep]) -> bool:
    return any(_step_is_verify(step, markers=_VERIFY_MARKERS_ALL) for step in steps)


def _has_language_specific_verification(
    steps: list[ReActStep],
    *,
    language: str,
) -> bool:
    """True if any step ran a verifier whose markers belong to ``language``.

    Strict variant of ``_has_code_verification`` — used by the §19
    language-mismatch guard. ``language`` must be a key in
    ``_LANG_VERIFY_MARKERS``; unknown languages return False so callers
    can skip the check.
    """
    markers = _LANG_VERIFY_MARKERS.get(language)
    if not markers:
        return False
    return any(_step_is_verify(step, markers=markers) for step in steps)


# ──────────────────────────────────────────────────────────────────
# §20 — new-public-symbol detection (for the test-coverage guard)
# ──────────────────────────────────────────────────────────────────
# Conservative scan: only flag NEW top-level ``def name(`` and
# ``class Name`` introductions in non-test .py edits. We accept missing
# some real cases (private methods, nested defs) in exchange for near-
# zero false positives on refactors / docstring tweaks / import shuffles.

# Top-level public def/class — must be flush-left, name must not start
# with ``_``. ``async def`` covered. ``def __init__`` etc. start with
# underscore so they're already skipped.
_PUBLIC_SYMBOL_INTRO_RE = re.compile(
    r"(?:^|\n)(?:async\s+)?(?:def|class)\s+(?P<name>[A-Za-z][A-Za-z0-9_]*)",
)


def _is_test_path(path: str | None) -> bool:
    """Whether a path looks like a test file or test directory entry.

    ``tests/`` anywhere in the path counts (project-relative or absolute
    on either separator), as does a basename matching ``test_*.py`` or
    ``*_test.py``. Conftest is treated as a test file too.
    """
    if not path:
        return False
    norm = path.replace("\\", "/").lower()
    if "/tests/" in norm or norm.startswith("tests/") or norm == "tests":
        return True
    base = norm.rsplit("/", 1)[-1]
    if base == "conftest.py":
        return True
    if base.startswith("test_") and base.endswith(".py"):
        return True
    return base.endswith("_test.py")


def _extract_write_payload(action: str | None) -> str:
    """Return the textual payload that was written/inserted by an action.

    Concatenates ``content``, ``new_string``, and the ``new_string`` field
    of every entry in ``edits`` (multi_edit_file shape). Old/source text is
    explicitly excluded — we only care about what's NEW.
    """
    parsed = _parse_action(action or "")
    if parsed is None:
        return ""
    _name, args = parsed
    chunks: list[str] = []
    for key in ("content", "new_string", "new_str"):
        value = args.get(key)
        if isinstance(value, str):
            chunks.append(value)
    edits = args.get("edits")
    if isinstance(edits, list):
        for edit in edits:
            if not isinstance(edit, dict):
                continue
            for key in ("new_string", "new_str", "content"):
                value = edit.get(key)
                if isinstance(value, str):
                    chunks.append(value)
    return "\n".join(chunks)


def _step_introduces_python_public_symbol(step: ReActStep) -> bool:
    """Whether this write step adds a NEW top-level public def/class.

    Only fires for .py files that aren't test files. Detects by scanning
    the new-content payload for ``def NAME(`` / ``class NAME`` at column
    0 where NAME does not start with ``_``. Refactors that move existing
    code without adding new defs are NOT flagged because the matched
    line was already present (the guard layer dedups across the whole
    trajectory below).
    """
    path = _extract_step_path(step)
    if not path or not path.lower().endswith((".py", ".pyi")):
        return False
    if _is_test_path(path):
        return False
    payload = _extract_write_payload(step.action)
    if not payload:
        return False
    for match in _PUBLIC_SYMBOL_INTRO_RE.finditer(payload):
        if not match.group("name").startswith("_"):
            return True
    return False


def _has_test_write(steps: list[ReActStep]) -> bool:
    """Any write step targeting a test path (tests/ dir or test_*.py)."""
    for step in steps:
        if not _is_code_write_step(step):
            continue
        path = _extract_step_path(step)
        if path is not None and _is_test_path(path):
            return True
    return False


# ──────────────────────────────────────────────────────────────────
# §21 — public-signature change detection
# ──────────────────────────────────────────────────────────────────
# Catch the failure mode where the model edits a public ``def NAME(...)``
# parameter list (or return annotation) and ships without running a
# typechecker. We don't try to AST-diff the whole file — we just look
# at edit_file old/new pairs and check whether the old line "def F(...)"
# became a different "def F(...)" in the new payload.
#
# Conservative bias: only triggers on edit_file / multi_edit_file
# actions where BOTH old_string and new_string contain a top-level
# public def with the same name, and the parameter list differs. Whole-
# file rewrites via write_text_file are out of scope (we'd need the
# previous content to compare).

_PUBLIC_DEF_LINE_RE = re.compile(
    r"(?:^|\n)\s*(?:async\s+)?def\s+(?P<name>[A-Za-z][A-Za-z0-9_]*)\s*"
    r"\((?P<params>[^)]*)\)\s*(?:->\s*(?P<ret>[^:\n]+?))?\s*:",
)


def _extract_public_signatures(text: str) -> dict[str, tuple[str, str]]:
    """Map ``name -> (params, return_annotation)`` for top-level public defs.

    Names starting with ``_`` are excluded — those are private and a
    signature change there is internal refactoring, not an API break.
    """
    sigs: dict[str, tuple[str, str]] = {}
    if not text:
        return sigs
    for match in _PUBLIC_DEF_LINE_RE.finditer(text):
        name = match.group("name")
        if name.startswith("_"):
            continue
        params = (match.group("params") or "").strip()
        ret = (match.group("ret") or "").strip()
        # Last write wins — duplicate names within one payload chunk
        # shouldn't happen in valid Python, but be defensive.
        sigs[name] = (params, ret)
    return sigs


def _step_changed_public_signature(step: ReActStep) -> bool:
    """Whether this edit changes the parameter list / return annotation
    of a top-level public def (same name in old AND new, different sig).

    Returns False for write_text_file (no old payload to compare),
    non-Python paths, and test-path edits.
    """
    parsed = _parse_action(step.action)
    if parsed is None:
        return False
    name, args = parsed
    if name not in {"edit_file", "multi_edit_file", "edit_code", "str_replace"}:
        return False
    path = _extract_step_path(step)
    if not path or not path.lower().endswith((".py", ".pyi")):
        return False
    if _is_test_path(path):
        return False
    pairs: list[tuple[str, str]] = []
    if isinstance(args.get("old_string"), str) and isinstance(args.get("new_string"), str):
        pairs.append((args["old_string"], args["new_string"]))
    edits = args.get("edits")
    if isinstance(edits, list):
        for edit in edits:
            if not isinstance(edit, dict):
                continue
            old = edit.get("old_string") or edit.get("old_str")
            new = edit.get("new_string") or edit.get("new_str")
            if isinstance(old, str) and isinstance(new, str):
                pairs.append((old, new))
    for old, new in pairs:
        old_sigs = _extract_public_signatures(old)
        new_sigs = _extract_public_signatures(new)
        common = set(old_sigs) & set(new_sigs)
        for symbol in common:
            if old_sigs[symbol] != new_sigs[symbol]:
                return True
    return False


# ──────────────────────────────────────────────────────────────────
# §22 — wire-schema change detection
# ──────────────────────────────────────────────────────────────────
# octopus has no DB migrations, but it DOES have wire-shape schemas
# that external SDKs depend on (anthropic_compat, openai_gateway,
# protocol/items.py). A change there without a paired contract test
# can silently break SDK clients. We look at write actions whose path
# matches one of the wire-schema patterns; the guard then enforces
# that the trajectory ALSO touched a wire-shape contract test.

_WIRE_SCHEMA_PATH_PATTERNS: tuple[str, ...] = (
    "/runtime/protocol/items.py",
    "/runtime/sensing/siphon/anthropic_compat/",
    "/runtime/sensing/siphon/openai_gateway/",
    "/runtime/protocol/",
)

# Tests that count as "wire-shape contract test edits" for §22.
_WIRE_CONTRACT_TEST_MARKERS: tuple[str, ...] = (
    "anthropic_compat",
    "anthropic_gateway",
    "openai_gateway",
    "openai_sse",
    "openai_compat",
    "wire_shape",
    "wire_contract",
    "protocol_items",
)


def _is_wire_schema_path(path: str | None) -> bool:
    if not path:
        return False
    norm = "/" + path.replace("\\", "/").lstrip("/").lower()
    return any(pattern in norm for pattern in _WIRE_SCHEMA_PATH_PATTERNS)


def _is_wire_contract_test_path(path: str | None) -> bool:
    if not path or not _is_test_path(path):
        return False
    norm = path.replace("\\", "/").lower()
    return any(marker in norm for marker in _WIRE_CONTRACT_TEST_MARKERS)


def _step_edits_wire_schema(step: ReActStep) -> bool:
    path = _extract_step_path(step)
    return _is_wire_schema_path(path) if path else False


def _has_wire_contract_test_write(steps: list[ReActStep]) -> bool:
    for step in steps:
        if not _is_code_write_step(step):
            continue
        path = _extract_step_path(step)
        if path is not None and _is_wire_contract_test_path(path):
            return True
    return False


# ──────────────────────────────────────────────────────────────────
# §23 — third-party import without dependency declaration
# ──────────────────────────────────────────────────────────────────
# Look at write payloads for ``import X`` / ``from X import ...`` lines
# whose top-level package isn't stdlib AND isn't a first-party
# (``runtime`` / ``tests``) package AND wasn't already declared in
# pyproject.toml in the SAME trajectory.
#
# We use sys.stdlib_module_names (Python 3.10+) as the stdlib oracle.
# First-party packages are pinned: anything else must show up in a
# write to pyproject.toml within the same trajectory.

_FIRST_PARTY_TOP_LEVEL: frozenset[str] = frozenset(
    {
        "runtime",
        "tests",
        "frontend",
        "tools",
        "scripts",
    }
)

_IMPORT_LINE_RE = re.compile(
    r"(?:^|\n)\s*(?:from\s+(?P<from>[A-Za-z_][A-Za-z0-9_.]*)\s+import|"
    r"import\s+(?P<imp>[A-Za-z_][A-Za-z0-9_.]*))",
)


def _top_level_module(name: str) -> str:
    return name.split(".", 1)[0]


def _is_third_party_module(top: str) -> bool:
    if not top:
        return False
    if top in _FIRST_PARTY_TOP_LEVEL:
        return False
    if top in _sys.stdlib_module_names:
        return False
    # ``__future__`` lives in stdlib_module_names in 3.11+; defensive
    # double-check for older minors.
    return not top.startswith("__")


def _new_third_party_imports_in_payload(text: str) -> set[str]:
    out: set[str] = set()
    if not text:
        return out
    for match in _IMPORT_LINE_RE.finditer(text):
        raw = match.group("from") or match.group("imp") or ""
        top = _top_level_module(raw)
        if _is_third_party_module(top):
            out.add(top)
    return out


def _step_introduces_third_party_imports(step: ReActStep) -> set[str]:
    """Set of NEW third-party top-level packages this step appears to
    import. ``new_string`` minus ``old_string`` ensures we only flag
    additions, not pre-existing imports being moved around."""
    path = _extract_step_path(step)
    if not path or not path.lower().endswith((".py", ".pyi")):
        return set()
    if _is_test_path(path):
        return set()
    new_text, old_text = _extract_step_payloads(step)
    new_imports = _new_third_party_imports_in_payload(new_text)
    old_imports = _new_third_party_imports_in_payload(old_text)
    return new_imports - old_imports


def _step_writes_dep_manifest(step: ReActStep) -> bool:
    path = _extract_step_path(step)
    if not path:
        return False
    norm = path.replace("\\", "/").lower()
    base = norm.rsplit("/", 1)[-1]
    return base in {
        "pyproject.toml",
        "requirements.txt",
        "setup.py",
        "setup.cfg",
        "poetry.lock",
        "uv.lock",
    }


# ──────────────────────────────────────────────────────────────────
# §24 — false-verification claim detection
# ──────────────────────────────────────────────────────────────────
# Catch the failure mode where the model writes "all tests pass" /
# "已通过测试" in its Final Answer but the trajectory contains no
# successful verifier observation. This is the textual counterpart
# to the §18/§19 pattern — those guard the trajectory shape; this
# guards the claim itself.

_VERIFY_CLAIM_RE = re.compile(
    r"(?:"
    # English
    r"\ball\s+tests?\s+pass(?:ed|ing)?\b|"
    r"\btests?\s+pass(?:ed|ing)?\b|"
    r"\bverified\b|"
    r"\btypechecks?\s+pass(?:ed|ing)?\b|"
    r"\blint(?:ing)?\s+pass(?:ed|ing)?\b|"
    r"\bbuild\s+(?:passes|passed|succeed(?:ed|s)?)\b|"
    r"\b\d+\s+pass(?:ed|ing)?\b|"
    # Chinese
    r"全部测试通过|测试[已都全]?通过|已通过测试|"
    r"已[运通]?(?:跑|过)?(?:完|过)?(?:测试|test)|"
    r"(?:测试|test|lint|typecheck|类型检查|构建|build)[已全都]*(?:通过|成功|无误)|"
    r"无错误"
    r")",
    re.IGNORECASE,
)


def _final_answer_claims_verification(final_answer: str) -> bool:
    if not final_answer:
        return False
    return bool(_VERIFY_CLAIM_RE.search(final_answer))


# A verifier observation showing FAILING output must never be mistaken for
# a passing one. Conservative by construction: only strong, unambiguous
# failure signals a green run never emits — non-zero failure/error counts,
# uppercase runner tokens (pytest ``FAILED``, go ``FAIL``), compiler/lint
# error lines. "0 failed", "13 passed", "Found 0 errors", "All checks
# passed" deliberately do NOT match. Infra errors (ModuleNotFoundError,
# command-not-found) are handled separately by the callers below.
_RED_TOKEN_RE = re.compile(r"\bFAILED\b|\bFAIL\b")  # case-sensitive on purpose
_RED_PHRASE_RE = re.compile(
    r"\b[1-9]\d*\s+failed\b|"
    r"\b[1-9]\d*\s+error(?:s)?\b|"
    r"\bfound\s+[1-9]\d*\s+error|"
    r"\berror\s+ts\d+|"
    r"\bnpm\s+err!|"
    r"\bassertion\s*error\b|"
    r"\b(?:build|compilation|type-?check|typecheck|lint|tests?)\s+failed\b|"
    r"\btimeout after\b|\btimed[_ -]?out\b|\btool failed\b|"
    r'"success"\s*:\s*false|'
    r"\bexit\s+code\s+[1-9]|"
    r"\breturned\s+non-?zero|"
    r"测试[^。\n]{0,4}失败|构建失败|编译[^。\n]{0,4}失败|"
    r"类型检查[^。\n]{0,6}(?:失败|错误)|校验[^。\n]{0,4}失败",
    re.IGNORECASE,
)


def _verification_observation_is_red(observation: str) -> bool:
    """True when a verifier observation shows failing output (failing
    tests / type / lint / build), as opposed to an infra error like
    ModuleNotFoundError which callers handle separately. Strong-signal
    only — a passing run must never match."""
    if not observation:
        return False
    return bool(_RED_TOKEN_RE.search(observation) or _RED_PHRASE_RE.search(observation))


def _has_successful_verification_observation(steps: list[ReActStep]) -> bool:
    """Whether any verification step produced a non-empty, non-error,
    non-*failing* observation. Stricter than ``_has_code_verification`` —
    that just checks the action was issued; this checks the action *ran
    and did not report failures*.
    """
    for step in steps:
        if not _step_is_verify(step, markers=_VERIFY_MARKERS_ALL):
            continue
        observation = (step.observation or "").strip()
        if not observation or observation == "N/A":
            continue
        lowered = observation.lower()
        if (
            "未执行观察" in observation
            or "not executed" in lowered
            or "tool-availability guard" in lowered
            or "工具失败" in observation
            or "工具执行异常" in observation
            or "command not found" in lowered
            or "no such file" in lowered
            or "modulenotfounderror" in lowered
            or "traceback (most recent call last)" in lowered
            or _verification_observation_is_red(observation)
        ):
            continue
        return True
    return False


def _latest_verification_observation_is_red(steps: list[ReActStep]) -> bool:
    """Whether the MOST RECENT verifier observation in the trajectory is
    red (failing tests / type / lint / build). Only the latest matters: a
    run that went red then green (re-run after a fix) must not be flagged.
    Returns False when no verifier observation exists."""
    for step in reversed(steps):
        if not _step_is_verify(step, markers=_VERIFY_MARKERS_ALL):
            continue
        observation = (step.observation or "").strip()
        if not observation or observation == "N/A":
            continue
        return _verification_observation_is_red(observation)
    return False


# ──────────────────────────────────────────────────────────────────
# §28 — comment-out-as-fix detection
# ──────────────────────────────────────────────────────────────────
# Catch the failure mode where the model "fixes" a problem by deleting
# or commenting out the problematic call/test/assertion rather than
# diagnosing it. Heuristic: in an edit_file pair, the new_string is
# made up purely of blank lines and comments, OR the new_string is a
# strict subset that drops a previously-present executable construct
# (assert, raise, function call) and replaces it with a comment.
#
# Conservative: only flags when old_string had executable Python code
# AND new_string has none. Refactors that genuinely delete dead code
# and replace it with a leading docstring/comment will trip this — we
# accept that small false-positive in exchange for catching the real
# anti-pattern.

_PYTHON_EXECUTABLE_LINE_RE = re.compile(
    r"^\s*(?!#)(?!\"\"\")(?!''')[A-Za-z_\(\[\{\@]",
    re.MULTILINE,
)
_PYTHON_KEY_EXECUTABLE_RE = re.compile(
    r"\b(?:assert|raise|return\s|yield|"
    r"def\s|class\s|if\s|for\s|while\s|try:|except|with\s|"
    r"await\s|async\s)",
)
_PYTHON_LINE_COMMENT_RE = re.compile(r"#[^\n]*")


def _strip_comments_for_executable_check(text: str) -> str:
    """Remove # line comments so the executable-keyword scan doesn't
    false-positive on commented-out code like ``# was: raise X``.

    Only strips line comments, not docstrings — docstrings are caught
    by the line-level regex's lookbehind for ``\"\"\"`` / ``'''``.
    """
    return _PYTHON_LINE_COMMENT_RE.sub("", text or "")


def _payload_has_executable_python(text: str) -> bool:
    """Whether the text payload contains at least one executable Python
    line (not comment-only, not pure docstring/blank)."""
    if not text:
        return False
    stripped = _strip_comments_for_executable_check(text)
    if _PYTHON_KEY_EXECUTABLE_RE.search(stripped):
        return True
    return bool(_PYTHON_EXECUTABLE_LINE_RE.search(stripped))


def _step_replaced_code_with_comment(step: ReActStep) -> bool:
    """Edit step that replaces executable Python with comment/blank only.

    Returns True when:
      * action is edit_file / multi_edit_file / str_replace etc.
      * path is .py and not a test path
      * old_string contains executable Python
      * new_string contains NO executable Python
    """
    parsed = _parse_action(step.action)
    if parsed is None:
        return False
    name, args = parsed
    if name not in {"edit_file", "multi_edit_file", "edit_code", "str_replace"}:
        return False
    path = _extract_step_path(step)
    if not path or not path.lower().endswith((".py", ".pyi")):
        return False
    if _is_test_path(path):
        return False
    pairs: list[tuple[str, str]] = []
    if isinstance(args.get("old_string"), str) and isinstance(args.get("new_string"), str):
        pairs.append((args["old_string"], args["new_string"]))
    edits = args.get("edits")
    if isinstance(edits, list):
        for edit in edits:
            if not isinstance(edit, dict):
                continue
            old = edit.get("old_string") or edit.get("old_str")
            new = edit.get("new_string") or edit.get("new_str")
            if isinstance(old, str) and isinstance(new, str):
                pairs.append((old, new))
    for old, new in pairs:
        if _payload_has_executable_python(old) and not _payload_has_executable_python(new):
            return True
    return False


# ──────────────────────────────────────────────────────────────────
# §30 — broad-except suppression detection
# ──────────────────────────────────────────────────────────────────
# Catch the failure mode where the model "fixes" an exception by
# wrapping it in ``try: ... except Exception: pass`` (or ``except:
# pass``) without doing anything with the error. This is one of the
# most common forms of papering over a bug.
#
# Heuristic: new_string introduces a bare ``except:`` or
# ``except Exception:`` (or ``except BaseException:``) block whose body
# is one of: ``pass``, ``...``, a comment-only line, or a single
# ``return None``. We require old_string to NOT contain that same
# pattern, so adding new suppression is flagged but moving an
# already-existing one isn't.

_BROAD_EXCEPT_HEAD_RE = re.compile(
    r"(?:^|\n)(?P<indent>[ \t]*)except\s*"
    r"(?:\(\s*(?:Exception|BaseException)\s*\)|"
    r"Exception|BaseException|)"
    r"\s*(?:as\s+\w+\s*)?:[ \t]*\n",
)

_SUPPRESSION_BODY_RE = re.compile(
    r"^[ \t]+(?:pass|\.\.\.|return\s+None|return)\s*(?:#.*)?$",
)


def _payload_has_broad_except_suppression(text: str) -> bool:
    """Detect ``except [Exception|BaseException|]: <suppression-body>``."""
    if not text:
        return False
    for match in _BROAD_EXCEPT_HEAD_RE.finditer(text):
        # Find the FIRST non-empty line after the except header line.
        rest = text[match.end() :]
        first_line = ""
        for line in rest.splitlines():
            if line.strip():
                first_line = line
                break
        if not first_line:
            continue
        if _SUPPRESSION_BODY_RE.match(first_line):
            return True
        if first_line.lstrip().startswith("#"):
            return True
    return False


def _step_introduces_broad_except_suppression(step: ReActStep) -> bool:
    """Whether this write step adds a NEW broad-except suppression.

    Skips test paths and non-Python paths. Compares new_string and
    write payloads against old_string so existing suppression isn't
    flagged repeatedly when code is moved around.
    """
    path = _extract_step_path(step)
    if not path or not path.lower().endswith((".py", ".pyi")):
        return False
    if _is_test_path(path):
        return False
    new_text, old_text = _extract_step_payloads(step)
    return _payload_has_broad_except_suppression(
        new_text
    ) and not _payload_has_broad_except_suppression(old_text)


# ──────────────────────────────────────────────────────────────────
# §32 — frontend file outside tsconfig.json `include` detection
# ──────────────────────────────────────────────────────────────────
# tsconfig.json's `include` is a hand-maintained list of 22 files in
# this repo. Editing a .ts/.tsx file that ISN'T in that list means the
# typechecker silently won't see the change — a real failure mode the
# memory references at reference_verify_commands.md. Same applies if
# the file matches `exclude`.
#
# Strategy: parse tsconfig.json once per call, normalise paths, and
# match the edited path against include/exclude. We DON'T cache the
# parsed result — the file might change mid-trajectory, and the cost
# of re-reading is trivial.

_TSCONFIG_PATH_CANDIDATES: tuple[str, ...] = (
    "frontend/tsconfig.json",
    "tsconfig.json",
)


def _strip_jsonc_comments(text: str) -> str:
    """Cheap JSONC → JSON converter. Drops // line comments and
    /* block */ comments. Naive: doesn't understand strings, so a
    URL inside a string with ``//`` will be mangled. tsconfig.json
    rarely embeds URLs, and the consequence of a mangled parse is
    "guard returns None" — non-fatal.
    """
    if not text:
        return text
    # Block comments first.
    text = re.sub(r"/\*[\s\S]*?\*/", "", text)
    # Line comments — match leading whitespace + // up to newline.
    return re.sub(r"(^|\s)//[^\n]*", r"\1", text)


def _load_tsconfig(repo_root: str | None = None) -> dict[str, Any] | None:
    root = repo_root or _os.getcwd()
    for candidate in _TSCONFIG_PATH_CANDIDATES:
        path = _os.path.join(root, candidate)
        try:
            with open(path, encoding="utf-8") as fh:
                raw = fh.read()
        except OSError:
            continue
        try:
            return json.loads(_strip_jsonc_comments(raw))
        except json.JSONDecodeError:
            return None
    return None


def _normalize_frontend_path(path: str) -> str:
    """Return path relative to ``frontend/`` if it lives there,
    otherwise the path unchanged. Always uses forward slashes.
    """
    norm = path.replace("\\", "/").lstrip("./")
    if norm.startswith("frontend/"):
        norm = norm[len("frontend/") :]
    return norm


def _matches_tsconfig_pattern(rel_path: str, pattern: str) -> bool:
    """Approximate tsc's pattern semantics. Supports:
      * exact match
      * ``dir/`` prefix-match (treats trailing path-segment as dir)
      * ``*`` and ``**`` glob — anchored to the start of ``rel_path``
    Ignores extension-rewriting nuances (tsc is more lenient); we
    bias toward false-negative (saying "matched" when in doubt).
    """
    rel_path = rel_path.replace("\\", "/")
    pattern = pattern.replace("\\", "/")
    if rel_path == pattern:
        return True
    # Bare directory → covers everything beneath it.
    if (
        not pattern.endswith("/")
        and "." not in pattern.rsplit("/", 1)[-1]
        and rel_path.startswith(pattern + "/")
    ):
        return True
    if pattern.endswith("/") and rel_path.startswith(pattern):
        return True
    # Glob: convert tsc-style globs to a regex.
    if "*" in pattern:
        regex = re.escape(pattern)
        regex = regex.replace(r"\*\*/", r"(?:.*/)?")
        regex = regex.replace(r"\*\*", r".*")
        regex = regex.replace(r"\*", r"[^/]*")
        return bool(re.fullmatch(regex, rel_path))
    return False


def _is_frontend_path_outside_tsconfig(
    path: str,
    *,
    repo_root: str | None = None,
) -> bool:
    """Whether a TypeScript edit lands outside the tsc include set.

    Returns False (silent) for non-frontend paths, non-TS files, paths
    that match include, paths inside exclude, or when tsconfig.json
    can't be located/parsed (don't nag if oracle missing).
    """
    if not path:
        return False
    norm = path.replace("\\", "/").lower()
    if not norm.endswith((".ts", ".tsx", ".js", ".jsx", ".cjs", ".mjs")):
        return False
    if "/frontend/" not in "/" + norm.lstrip("/") and not norm.startswith("frontend/"):
        return False
    config = _load_tsconfig(repo_root)
    if not config:
        return False
    rel = _normalize_frontend_path(path)
    excludes = config.get("exclude") or []
    if any(_matches_tsconfig_pattern(rel, str(pattern)) for pattern in excludes):
        return False  # Excluded on purpose — not the guard's business.
    includes = config.get("include") or []
    if not includes:
        return False
    return not any(_matches_tsconfig_pattern(rel, str(pattern)) for pattern in includes)


def _step_edits_frontend_outside_tsconfig(
    step: ReActStep,
    *,
    repo_root: str | None = None,
) -> bool:
    path = _extract_step_path(step)
    if not path:
        return False
    return _is_frontend_path_outside_tsconfig(path, repo_root=repo_root)


# ──────────────────────────────────────────────────────────────────
# §33 — oversized single-edit detection
# ──────────────────────────────────────────────────────────────────
# A single ``write_text_file`` / ``edit_file`` payload that rewrites
# more than N lines in one shot is a high-blast-radius change. The
# model often accumulates errors at this scale because the LLM has
# to keep too much context coherent. Threshold tuned empirically for
# this repo (median real edit is < 30 lines).

_OVERSIZED_EDIT_LINE_THRESHOLD = 200


def _count_payload_lines(text: str) -> int:
    if not text:
        return 0
    return text.count("\n") + (0 if text.endswith("\n") else 1)


def _step_payload_line_count(step: ReActStep) -> int:
    """Total NEW-content lines across ``content``/``new_string``/``edits``.

    For a write_text_file we use the full content. For edit/multi-edit
    we sum new_string sizes — old_string is irrelevant because we care
    about what's being inserted.
    """
    new_text, _old_text = _extract_step_payloads(step)
    return _count_payload_lines(new_text)


def _step_is_oversized_edit(
    step: ReActStep,
    *,
    threshold: int = _OVERSIZED_EDIT_LINE_THRESHOLD,
) -> bool:
    """Whether this single edit step writes more than ``threshold`` lines.

    Skips test paths (test fixture files can be legitimately huge) and
    non-Python/TS-style code paths (config files, fixtures, JSON).
    """
    path = _extract_step_path(step)
    if not path:
        return False
    if _is_test_path(path):
        return False
    norm = path.lower()
    if not norm.endswith((".py", ".pyi", ".ts", ".tsx", ".js", ".jsx")):
        return False
    return _step_payload_line_count(step) > threshold


# ──────────────────────────────────────────────────────────────────
# §34 — secret-in-payload detection
# ──────────────────────────────────────────────────────────────────
# Detect well-known secret prefixes embedded in write payloads. We
# flag at the parsing layer; the guard layer surfaces it. This is a
# conservative regex set — false positives are tolerable because
# leaking a real key is much worse than nagging on a false hit.
#
# Patterns:
#   * ``sk-`` followed by 20+ chars (OpenAI / Anthropic-style)
#   * ``ghp_`` / ``ghs_`` / ``gho_`` / ``ghu_`` — GitHub PAT prefixes
#   * ``AKIA`` followed by 16 alnum chars — AWS access key
#   * ``xox[abps]-`` — Slack tokens
#   * ``-----BEGIN (RSA |EC |OPENSSH |DSA |PRIVATE)?(PRIVATE )?KEY-----``

_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("OpenAI/Anthropic-style key", re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}\b")),
    ("GitHub PAT", re.compile(r"\bgh[psou]_[A-Za-z0-9]{20,}\b")),
    ("AWS access key", re.compile(r"\bAKIA[A-Z0-9]{16}\b")),
    ("Slack token", re.compile(r"\bxox[abps]-[A-Za-z0-9-]{10,}\b")),
    ("Private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    # Hex API tokens of length 40+ assigned to obvious key-like names.
    (
        "Inline assigned credential",
        re.compile(
            r"(?:api[_-]?key|secret[_-]?key|access[_-]?token|password)"
            r"['\"]?\s*[:=]\s*['\"][A-Za-z0-9_\-]{20,}['\"]",
            re.IGNORECASE,
        ),
    ),
)


def _detect_secrets_in_payload(text: str) -> list[str]:
    """Return labels of any secret patterns matched in ``text``."""
    if not text:
        return []
    hits: list[str] = []
    for label, pattern in _SECRET_PATTERNS:
        if pattern.search(text):
            hits.append(label)
    return hits


def _step_introduces_secret(step: ReActStep) -> list[str]:
    """List of secret-pattern labels matched in this write step's NEW
    content. Old content is excluded so existing committed-and-rotated
    leaks don't keep tripping the guard. Empty list = nothing matched.
    """
    new_text, old_text = _extract_step_payloads(step)
    if not new_text and not old_text:
        return []
    new_hits = set(_detect_secrets_in_payload(new_text))
    old_hits = set(_detect_secrets_in_payload(old_text))
    return sorted(new_hits - old_hits)


# ──────────────────────────────────────────────────────────────────
# §37 — destructive-call detection
# ──────────────────────────────────────────────────────────────────
# Catch the failure mode where the model adds a destructive filesystem
# or process call in production code without any safeguard:
#   * shutil.rmtree
#   * os.remove / os.unlink / Path.unlink
#   * os.removedirs
#   * subprocess.run / call / Popen with ``rm -rf`` / ``del /F`` etc.
#
# We only flag NEW additions (new_string vs old_string diff) on
# non-test Python paths. Test files are exempt because tests legitimately
# create and tear down fixtures.

_DESTRUCTIVE_CALL_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("shutil.rmtree", re.compile(r"\bshutil\s*\.\s*rmtree\s*\(")),
    ("os.remove / os.unlink", re.compile(r"\bos\s*\.\s*(?:remove|unlink|removedirs)\s*\(")),
    ("Path.unlink / Path.rmdir", re.compile(r"\.(?:unlink|rmdir)\s*\(")),
    (
        "shell rm -rf",
        re.compile(r"(?:^|[\s\"'])rm\s+-[a-zA-Z]*r[a-zA-Z]*f", re.IGNORECASE),
    ),
    (
        "shell del /F",
        re.compile(r"(?:^|[\s\"'])del\s+/[fFsSqQ]", re.IGNORECASE),
    ),
)


def _detect_destructive_calls_in_payload(text: str) -> list[str]:
    if not text:
        return []
    hits: list[str] = []
    for label, pattern in _DESTRUCTIVE_CALL_PATTERNS:
        if pattern.search(text):
            hits.append(label)
    return hits


def _step_introduces_destructive_call(step: ReActStep) -> list[str]:
    """List of destructive-call labels added by this write step.

    Diffs new payload vs old payload so existing destructive calls
    being moved aren't repeatedly flagged. Skips test paths and
    non-Python files (shell scripts, .sh, etc. are out of scope —
    too many legitimate uses).
    """
    path = _extract_step_path(step)
    if not path or not path.lower().endswith((".py", ".pyi")):
        return []
    if _is_test_path(path):
        return []
    new_text, old_text = _extract_step_payloads(step)
    new_hits = set(_detect_destructive_calls_in_payload(new_text))
    old_hits = set(_detect_destructive_calls_in_payload(old_text))
    return sorted(new_hits - old_hits)


# ──────────────────────────────────────────────────────────────────
# §38 — time.sleep in production-path detection
# ──────────────────────────────────────────────────────────────────
# Adding ``time.sleep(N)`` to non-test runtime code is almost always
# a "wait for race condition to resolve" anti-pattern. Legitimate use
# cases (rate-limiter, retry-with-backoff) typically use a more
# specific construct (asyncio.sleep, tenacity, explicit retry helper).
# We flag the bare ``time.sleep`` and ``asyncio.sleep`` additions and
# let the model justify on a case-by-case basis.

_SLEEP_CALL_RE = re.compile(
    r"(?:^|[^A-Za-z_.])(?:time\s*\.\s*sleep|asyncio\s*\.\s*sleep)\s*\(",
)


def _payload_has_sleep_call(text: str) -> bool:
    if not text:
        return False
    return bool(_SLEEP_CALL_RE.search(text))


def _step_introduces_sleep(step: ReActStep) -> bool:
    """Whether this write step adds a NEW time.sleep / asyncio.sleep
    in non-test Python production code.

    Conservative: skip retry/backoff helpers (tenacity, etc.) implicitly
    by only catching the literal ``time.sleep`` / ``asyncio.sleep``
    forms.
    """
    path = _extract_step_path(step)
    if not path or not path.lower().endswith((".py", ".pyi")):
        return False
    if _is_test_path(path):
        return False
    new_text, old_text = _extract_step_payloads(step)
    return _payload_has_sleep_call(new_text) and not _payload_has_sleep_call(old_text)


# ──────────────────────────────────────────────────────────────────
# §40 — full-file rewrite detection
# ──────────────────────────────────────────────────────────────────
# ``write_text_file`` to a path that already exists and has substantial
# content is a high-risk move: the model could subtly drop imports /
# helpers / docstrings while "rewriting". We require either:
#   * the path is new (file doesn't exist on disk yet), or
#   * the same trajectory used edit_file / multi_edit_file on the SAME
#     file (proving the model knows the existing content).
# Otherwise, prefer edit_file with surgical changes.

_FULL_REWRITE_THRESHOLD = 100  # lines


def _step_is_full_file_rewrite_attempt(
    step: ReActStep,
    *,
    repo_root: str | None = None,
) -> tuple[bool, str | None, int]:
    """Return ``(is_rewrite, path, existing_line_count)``.

    ``is_rewrite`` is True when:
      * action is write_text_file (or alias) — full payload write
      * path resolves to an existing file > _FULL_REWRITE_THRESHOLD lines
      * path is non-test Python/TS code

    Caller is expected to additionally check whether the same trajectory
    contains a surgical edit on the same path before firing the guard.
    """
    parsed = _parse_action(step.action)
    if parsed is None:
        return (False, None, 0)
    name, _args = parsed
    if name not in {"write_text_file", "write_file", "create_file"}:
        return (False, None, 0)
    path = _extract_step_path(step)
    if not path:
        return (False, None, 0)
    if _is_test_path(path):
        return (False, path, 0)
    norm = path.lower()
    if not norm.endswith((".py", ".pyi", ".ts", ".tsx", ".js", ".jsx")):
        return (False, path, 0)
    abs_path = path
    if repo_root is not None:
        abs_path = _os.path.join(repo_root, path)
    try:
        with open(abs_path, encoding="utf-8") as fh:
            existing = fh.read()
    except OSError:
        # File doesn't exist (or can't read) → new file, no rewrite risk.
        return (False, path, 0)
    line_count = existing.count("\n") + (0 if existing.endswith("\n") else 1)
    return (line_count > _FULL_REWRITE_THRESHOLD, path, line_count)


def _step_is_surgical_edit_on(step: ReActStep, *, target_path: str) -> bool:
    """Whether a step is a surgical edit_file/multi_edit_file on the
    given target path. Used to whitelist a full-rewrite when the model
    has demonstrably read/edited the file surgically first."""
    parsed = _parse_action(step.action)
    if parsed is None:
        return False
    name, _args = parsed
    if name not in {"edit_file", "multi_edit_file", "edit_code", "str_replace"}:
        return False
    path = _extract_step_path(step)
    return path == target_path


# ──────────────────────────────────────────────────────────────────
# §42 — weak-test-assertion detection
# ──────────────────────────────────────────────────────────────────
# Catch the failure mode where the model satisfies the §20 test-coverage
# guard by writing a test that doesn't actually test anything:
#   * ``assert True`` / ``assert 1`` / ``assert x is not None``
#     (where x is the function under test, returning anything)
#   * test body is just ``pass``
#   * test body is just a single ``assert <one_var>`` with no comparison
#
# Only fires for files that are themselves test files AND were ADDED
# (not modified) in this trajectory — we don't second-guess pre-existing
# weak tests, and we don't try to grade quality, only catch obvious
# nothing-burgers.

_TEST_FUNC_RE = re.compile(
    r"(?:^|\n)def\s+(?P<name>test_[A-Za-z0-9_]+)\s*\([^)]*\)\s*(?:->\s*[^:\n]+)?\s*:"
    r"(?P<body>(?:\n[ \t]+[^\n]*)+)",
)

_WEAK_BODY_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("body is only `pass`", re.compile(r"^\s*pass\s*$")),
    ("body is only `...`", re.compile(r"^\s*\.\.\.\s*$")),
    ("assert True / assert 1", re.compile(r"^\s*assert\s+(?:True|1)\s*(?:#.*)?$")),
    (
        "assert <var> is not None (no comparison)",
        re.compile(r"^\s*assert\s+[A-Za-z_][A-Za-z0-9_.]*\s+is\s+not\s+None\s*(?:#.*)?$"),
    ),
    (
        "assert <var> (truthiness only)",
        re.compile(r"^\s*assert\s+[A-Za-z_][A-Za-z0-9_.]*\s*(?:#.*)?$"),
    ),
)


def _classify_test_body(body: str) -> str | None:
    """Return a label if ``body`` looks like a no-op test, else None.

    ``body`` is the indented block following a ``def test_x():`` header.
    We strip blank/docstring lines and check whether ALL remaining lines
    match a single weak pattern. Multi-line bodies with at least one
    non-trivial assertion are accepted.
    """
    if not body:
        return None
    # Strip leading docstring (single or triple).
    stripped_lines: list[str] = []
    in_docstring = False
    docstring_quote: str | None = None
    for raw in body.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        if in_docstring:
            if docstring_quote and docstring_quote in line:
                in_docstring = False
            continue
        if line.lstrip().startswith(('"""', "'''")):
            opener = '"""' if '"""' in line.lstrip()[:3] else "'''"
            after = line.lstrip()[3:]
            if opener in after:
                # Single-line docstring.
                continue
            in_docstring = True
            docstring_quote = opener
            continue
        if line.lstrip().startswith("#"):
            continue
        stripped_lines.append(line)
    if not stripped_lines:
        return "body is empty"
    if len(stripped_lines) > 1:
        return None  # Multi-line bodies likely have real logic.
    only_line = stripped_lines[0]
    for label, pattern in _WEAK_BODY_PATTERNS:
        if pattern.match(only_line):
            return label
    return None


def _detect_weak_tests_in_payload(text: str) -> list[tuple[str, str]]:
    """Return ``[(test_name, weakness_label)]`` for every weak test_*
    function defined in ``text``."""
    if not text:
        return []
    out: list[tuple[str, str]] = []
    for match in _TEST_FUNC_RE.finditer(text):
        name = match.group("name")
        body = match.group("body") or ""
        label = _classify_test_body(body)
        if label is not None:
            out.append((name, label))
    return out


def _step_introduces_weak_test(step: ReActStep) -> list[tuple[str, str]]:
    """List of ``(test_name, weakness)`` added by this write step.

    Diffs new payload vs old payload so existing weak tests aren't
    repeatedly flagged. Only fires for test paths.
    """
    path = _extract_step_path(step)
    if not path or not _is_test_path(path):
        return []
    if not path.lower().endswith((".py", ".pyi")):
        return []
    new_text, old_text = _extract_step_payloads(step)
    new_weak = set(_detect_weak_tests_in_payload(new_text))
    old_weak = set(_detect_weak_tests_in_payload(old_text))
    return sorted(new_weak - old_weak)


# ──────────────────────────────────────────────────────────────────
# §44 — print() in production-path detection
# ──────────────────────────────────────────────────────────────────
# octopus-agent uses ``logging`` everywhere (79 modules, 68 _logger
# calls; zero existing prints in runtime/core or runtime/safety).
# Adding a bare ``print(...)`` to non-test runtime code is a debug
# leftover. We only flag NEW prints — existing ones (e.g. CLI entry
# points that intentionally use stdout) being moved aren't flagged.
#
# Conservative: ``sys.stdout.write`` and ``rich.print`` aren't caught
# here. They're rarer and have legitimate UX uses.

_PRINT_CALL_RE = re.compile(r"(?:^|[^A-Za-z_.])print\s*\(")

# Files where print() is legitimate — CLI scripts, repl helpers, and
# explicit stdout-emitting entry points. Anything in scripts/ or
# tools/ is exempt because those are user-facing programs.
_PRINT_EXEMPT_PATH_PATTERNS: tuple[str, ...] = (
    "/scripts/",
    "/tools/",
    "/cli/",
    "/repl/",
    "/runtime/cli.py",
    "/runtime/__main__.py",
)


def _payload_has_print_call(text: str) -> bool:
    if not text:
        return False
    return bool(_PRINT_CALL_RE.search(text))


def _path_is_print_exempt(path: str) -> bool:
    norm = "/" + path.replace("\\", "/").lstrip("/").lower()
    return any(pattern in norm for pattern in _PRINT_EXEMPT_PATH_PATTERNS)


def _step_introduces_print(step: ReActStep) -> bool:
    """Whether this write step adds a NEW ``print(...)`` call to a
    non-test, non-CLI Python file."""
    path = _extract_step_path(step)
    if not path or not path.lower().endswith((".py", ".pyi")):
        return False
    if _is_test_path(path):
        return False
    if _path_is_print_exempt(path):
        return False
    new_text, old_text = _extract_step_payloads(step)
    return _payload_has_print_call(new_text) and not _payload_has_print_call(old_text)


# ──────────────────────────────────────────────────────────────────
# §45 — hardcoded personal/machine path detection
# ──────────────────────────────────────────────────────────────────
# Catch the failure mode where the agent hardcodes:
#   * ``C:\Users\<name>\...`` (Windows user dir)
#   * ``/Users/<name>/...`` (macOS user dir)
#   * ``/home/<name>/...`` (Linux user dir, name != ``runner``/``user``)
#   * ``/tmp/<specific>`` baked into runtime code (not configurable)
#
# We exempt obvious non-secret references (``/tmp/`` at module-level
# in scripts/) and accept ``getenv`` / ``os.path.expanduser`` rewrites
# silently (the diff sees them as "new" but they're correct).

_HARDCODED_PATH_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "Windows user dir",
        re.compile(
            r"[\"']?[A-Za-z]:(?:\\\\|\\|/)+Users(?:\\\\|\\|/)+"
            r"(?!Public(?:\\\\|\\|/))[A-Za-z0-9_.\-]+(?:\\\\|\\|/)+",
        ),
    ),
    (
        "macOS user dir",
        re.compile(r"[\"']/Users/(?!Shared/)[A-Za-z0-9_.\-]+/"),
    ),
    (
        "Linux user home",
        re.compile(r"[\"']/home/(?!runner/|user/|root/|ubuntu/)[A-Za-z0-9_.\-]+/"),
    ),
)


def _detect_hardcoded_paths_in_payload(text: str) -> list[str]:
    if not text:
        return []
    hits: list[str] = []
    for label, pattern in _HARDCODED_PATH_PATTERNS:
        if pattern.search(text):
            hits.append(label)
    return hits


def _step_introduces_hardcoded_path(step: ReActStep) -> list[str]:
    """Labels of any new hardcoded personal/machine paths introduced.

    Skips test paths (test fixtures legitimately reference local dirs)
    and non-text-content code files. Diffs new vs old payload.
    """
    path = _extract_step_path(step)
    if not path:
        return []
    if _is_test_path(path):
        return []
    norm = path.lower()
    if not norm.endswith(
        (".py", ".pyi", ".ts", ".tsx", ".js", ".jsx", ".yaml", ".yml", ".toml", ".json", ".env")
    ):
        return []
    new_text, old_text = _extract_step_payloads(step)
    new_hits = set(_detect_hardcoded_paths_in_payload(new_text))
    old_hits = set(_detect_hardcoded_paths_in_payload(old_text))
    return sorted(new_hits - old_hits)


# ──────────────────────────────────────────────────────────────────
# §47 — mock-only test detection
# ──────────────────────────────────────────────────────────────────
# Catch the failure mode where §20 + §42 are both satisfied because
# the new test exists and isn't ``assert True`` — but the assertion
# is purely ``mock.called`` / ``mock.call_count`` with no arg
# verification. A test that proves "the function was called" without
# checking WHAT it was called with proves nothing useful.
#
# Conservative: we only fire when EVERY new test in a file's payload
# uses mock-only assertions and NONE of them have ``assert_called_with``
# / ``call_args`` / ``mock_calls`` introspection. If the file mixes
# proper mock usage with one or two truthiness checks, we let it pass.

_MOCK_ONLY_ASSERTION_RE = re.compile(
    r"^\s*assert\s+[A-Za-z_][A-Za-z0-9_.]*"
    r"\.(?:called|call_count\s*(?:==|>=|>|<=|<|!=)\s*\d+)\s*$",
)
_MOCK_PROPER_INTROSPECTION_RE = re.compile(
    r"\.(?:assert_called_with|assert_called_once_with|assert_any_call|"
    r"assert_has_calls|call_args|call_args_list|mock_calls)\b",
)


def _classify_mock_only_test_body(body: str) -> bool:
    """True when the body's only assertions are mock truthiness checks."""
    if not body:
        return False
    has_mock_only = False
    for raw in body.splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith(('"""', "'''")):
            continue
        if _MOCK_PROPER_INTROSPECTION_RE.search(stripped):
            return False  # Has proper introspection — not mock-only.
        if _MOCK_ONLY_ASSERTION_RE.match(line):
            has_mock_only = True
            continue
        if stripped.startswith("assert "):
            # Some other assertion — could be real.
            return False
    return has_mock_only


def _detect_mock_only_tests_in_payload(text: str) -> list[str]:
    """Return list of test_* function names whose body only asserts
    mock truthiness without checking call arguments."""
    if not text:
        return []
    out: list[str] = []
    for match in _TEST_FUNC_RE.finditer(text):
        body = match.group("body") or ""
        if _classify_mock_only_test_body(body):
            out.append(match.group("name"))
    return out


def _step_introduces_mock_only_test(step: ReActStep) -> list[str]:
    """List of new test functions that are mock-truthiness-only."""
    path = _extract_step_path(step)
    if not path or not _is_test_path(path):
        return []
    if not path.lower().endswith((".py", ".pyi")):
        return []
    new_text, old_text = _extract_step_payloads(step)
    new_hits = set(_detect_mock_only_tests_in_payload(new_text))
    old_hits = set(_detect_mock_only_tests_in_payload(old_text))
    return sorted(new_hits - old_hits)


# ──────────────────────────────────────────────────────────────────
# §48 — pytest.skip without explicit reason detection
# ──────────────────────────────────────────────────────────────────
# Catch the failure mode where the model "fixes" a failing test by
# slapping ``@pytest.mark.skip`` or ``pytest.skip()`` on it. A skip
# with a real reason ("requires GPU", "slow integration test") is
# fine. A skip with no reason or a generic placeholder ("TODO",
# "skip", "fixme") is hiding a bug.

_PYTEST_SKIP_HEAD_RE = re.compile(
    r"@pytest\.mark\.skip\s*(?:\(\s*(?P<args>[^)]*)\))?|"
    r"\bpytest\.skip\s*\(\s*(?P<call>[^)]*)\)",
)
_PLACEHOLDER_REASONS: tuple[str, ...] = (
    "todo",
    "tbd",
    "fixme",
    "skip",
    "broken",
    "fix later",
    "wip",
    "temp",
    "temporary",
    "disabled",
)


def _is_meaningful_skip_reason(args_text: str) -> bool:
    """Whether the skip args contain a string reason longer than a
    placeholder. ``args_text`` is the literal contents between parens.
    Empty args / just whitespace / placeholder string returns False.
    """
    if not args_text or not args_text.strip():
        return False
    # Look for a quoted string. If none, no reason was given.
    string_match = re.search(r'(["\'])([^"\']*)\1', args_text)
    if not string_match:
        # Could be a name=value form like ``reason="..."`` → also matches.
        return False
    reason = string_match.group(2).strip().lower()
    if len(reason) < 8:
        return False
    return not any(reason.startswith(p) or reason == p for p in _PLACEHOLDER_REASONS)


def _payload_has_undocumented_skip(text: str) -> bool:
    if not text:
        return False
    for match in _PYTEST_SKIP_HEAD_RE.finditer(text):
        args_text = match.group("args") or match.group("call") or ""
        if not _is_meaningful_skip_reason(args_text):
            return True
    return False


def _step_introduces_undocumented_skip(step: ReActStep) -> bool:
    """Whether this write step adds a NEW pytest skip without a
    meaningful reason. Only fires for test paths.
    """
    path = _extract_step_path(step)
    if not path or not _is_test_path(path):
        return False
    if not path.lower().endswith((".py", ".pyi")):
        return False
    new_text, old_text = _extract_step_payloads(step)
    return _payload_has_undocumented_skip(new_text) and not _payload_has_undocumented_skip(old_text)


# ──────────────────────────────────────────────────────────────────
# §49 — deleted-test detection
# ──────────────────────────────────────────────────────────────────
# Catch the failure mode where the model "fixes" a failing test by
# deleting the entire test function. We detect:
#   * an edit_file step on a test path where ``old_string`` contains
#     a ``def test_NAME`` and ``new_string`` does NOT contain
#     ``def test_NAME`` (and isn't a rename of the same body).
#   * write_text_file overwriting a test path where the new content
#     drops test functions that existed in the old (caught by the
#     same payload diff via _extract_step_payloads).

_TEST_DEF_NAME_RE = re.compile(r"\bdef\s+(test_[A-Za-z0-9_]+)\s*\(")


def _test_function_names(text: str) -> set[str]:
    if not text:
        return set()
    return set(_TEST_DEF_NAME_RE.findall(text))


def _step_deleted_test_functions(step: ReActStep) -> list[str]:
    """List of ``test_NAME`` functions removed by this write step.

    Only fires for test paths. Uses old_string vs new_string set
    difference: a name in old but not in new → removed.
    """
    path = _extract_step_path(step)
    if not path or not _is_test_path(path):
        return []
    if not path.lower().endswith((".py", ".pyi")):
        return []
    new_text, old_text = _extract_step_payloads(step)
    if not old_text:
        return []  # No prior payload to compare — could be brand-new file.
    new_names = _test_function_names(new_text)
    old_names = _test_function_names(old_text)
    return sorted(old_names - new_names)


# ──────────────────────────────────────────────────────────────────
# §52 — generic test name detection
# ──────────────────────────────────────────────────────────────────
# Catch the failure mode where a test passes §20/§42/§47/§48/§49 but
# the test name is so generic it tells the next reader nothing about
# what the test guards. ``test_basic`` / ``test_works`` / ``test_x``
# / ``test_1`` etc. are placeholder names. A meaningful test name
# describes the BEHAVIOR under test (``test_handles_empty_input``,
# ``test_retries_on_timeout``).

_GENERIC_TEST_STEMS: frozenset[str] = frozenset(
    {
        "basic",
        "simple",
        "works",
        "ok",
        "thing",
        "stuff",
        "function",
        "method",
        "case",
        "example",
        "default",
        "something",
        "anything",
        "test",
        "main",
        "run",
        "execution",
        # Single-letter / numeric placeholders.
        "a",
        "b",
        "c",
        "x",
        "y",
        "z",
        "1",
        "2",
        "3",
        "01",
        "02",
        "first",
        "second",
        "third",
        # Obvious placeholders.
        "todo",
        "tbd",
        "fixme",
        "wip",
        "tmp",
    }
)


def _is_generic_test_name(name: str) -> bool:
    """Whether ``test_NAME`` has a placeholder stem."""
    if not name.startswith("test_"):
        return False
    stem = name[len("test_") :].lower().strip("_")
    if not stem:
        return True  # Just ``test_`` itself.
    return stem in _GENERIC_TEST_STEMS


def _detect_generic_test_names_in_payload(text: str) -> list[str]:
    if not text:
        return []
    return [name for name in _test_function_names(text) if _is_generic_test_name(name)]


def _step_introduces_generic_test_name(step: ReActStep) -> list[str]:
    """List of new test functions with placeholder names."""
    path = _extract_step_path(step)
    if not path or not _is_test_path(path):
        return []
    if not path.lower().endswith((".py", ".pyi")):
        return []
    new_text, old_text = _extract_step_payloads(step)
    new_hits = set(_detect_generic_test_names_in_payload(new_text))
    old_hits = set(_detect_generic_test_names_in_payload(old_text))
    return sorted(new_hits - old_hits)


# ──────────────────────────────────────────────────────────────────
# §54 — no-assertion test detection
# ──────────────────────────────────────────────────────────────────
# Catch the failure mode where the test body has substantive code
# (so it dodges §42's "body is only `pass`/`assert True`" check) but
# contains zero actual assertion. A test that just calls the code
# under test without checking results passes if it doesn't raise —
# which is almost never what the developer meant.
#
# We accept any of: ``assert``, ``assert_called_*``, ``mock.call_args``,
# ``pytest.raises``, ``pytest.warns``, ``assertRaises`` (unittest-style),
# ``self.assertX(...)``.

_ASSERTION_MARKERS_RE = re.compile(
    r"\b(?:"
    r"assert\b|"
    r"assert_called_(?:with|once_with|once|any_call)|"
    r"assert_has_calls|assert_not_called|"
    r"call_args(?:_list)?|mock_calls|"
    r"pytest\.raises|pytest\.warns|"
    r"self\.assert[A-Z][A-Za-z]*"
    r")",
)


def _test_body_has_assertion(body: str) -> bool:
    if not body:
        return False
    return bool(_ASSERTION_MARKERS_RE.search(body))


def _detect_no_assertion_tests_in_payload(text: str) -> list[str]:
    """Return list of test_* names whose body has substantive code
    (more than 1 non-blank, non-docstring line) but no assertion.

    The "more than 1 line" cutoff distinguishes this from §42 which
    catches single-line ``pass`` / ``assert True`` bodies.
    """
    if not text:
        return []
    out: list[str] = []
    for match in _TEST_FUNC_RE.finditer(text):
        name = match.group("name")
        body = match.group("body") or ""
        # Strip docstrings/comments/blanks for the line count.
        substantive_lines = 0
        in_docstring = False
        docstring_quote: str | None = None
        for raw in body.splitlines():
            stripped = raw.strip()
            if not stripped:
                continue
            if in_docstring:
                if docstring_quote and docstring_quote in raw:
                    in_docstring = False
                continue
            if stripped.startswith(('"""', "'''")):
                opener = '"""' if stripped.startswith('"""') else "'''"
                if opener in stripped[3:]:
                    continue
                in_docstring = True
                docstring_quote = opener
                continue
            if stripped.startswith("#"):
                continue
            substantive_lines += 1
        if substantive_lines <= 1:
            continue  # §42's territory.
        if not _test_body_has_assertion(body):
            out.append(name)
    return out


def _step_introduces_no_assertion_test(step: ReActStep) -> list[str]:
    path = _extract_step_path(step)
    if not path or not _is_test_path(path):
        return []
    if not path.lower().endswith((".py", ".pyi")):
        return []
    new_text, old_text = _extract_step_payloads(step)
    new_hits = set(_detect_no_assertion_tests_in_payload(new_text))
    old_hits = set(_detect_no_assertion_tests_in_payload(old_text))
    return sorted(new_hits - old_hits)


# ──────────────────────────────────────────────────────────────────
# §57 — async without await detection
# ──────────────────────────────────────────────────────────────────
# Catch the failure mode where a function is defined with ``async def``
# but its body doesn't await anything, doesn't yield, and doesn't use
# async-with / async-for. Such a function returns a coroutine that
# the caller probably doesn't await — meaning the body never runs.
# This is one of the most common Python concurrency bugs.
#
# Skip rules:
#   * test paths (test fixtures legitimately have empty async stubs)
#   * non-Python files
#   * abstract methods and protocols (decorated with @abstractmethod
#     or whose body is just ``...``) — those are intentionally empty.

_ASYNC_DEF_BLOCK_RE = re.compile(
    r"(?:^|\n)(?P<indent>[ \t]*)async\s+def\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*"
    r"\([^)]*\)\s*(?:->\s*[^:\n]+)?\s*:"
    r"(?P<body>(?:\n(?P=indent)[ \t]+[^\n]*|\n\s*$)*)",
)
_AWAIT_OR_YIELD_RE = re.compile(
    r"\b(?:await\b|yield\b)|\basync\s+(?:for|with)\b",
)
_ABSTRACT_DECORATOR_RE = re.compile(
    r"@(?:abc\.)?abstractmethod\b|@(?:typing\.)?overload\b",
)


def _async_body_uses_await(body: str) -> bool:
    """True iff the body contains await / yield / async-for / async-with.

    Bare ``...`` / ``pass`` bodies and abstract stubs return False —
    callers should still skip those via the surrounding heuristic
    (the §57 detector itself ignores ``...`` / ``pass``-only bodies).
    """
    if not body:
        return False
    return bool(_AWAIT_OR_YIELD_RE.search(body))


def _is_abstract_or_stub_body(body: str) -> bool:
    """Whether the body is a bare ``...`` / ``pass`` / docstring-only stub."""
    stripped_lines: list[str] = []
    in_docstring = False
    docstring_quote: str | None = None
    for raw in (body or "").splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        if in_docstring:
            if docstring_quote and docstring_quote in raw:
                in_docstring = False
            continue
        if stripped.startswith(('"""', "'''")):
            opener = '"""' if stripped.startswith('"""') else "'''"
            if opener in stripped[3:]:
                continue
            in_docstring = True
            docstring_quote = opener
            continue
        if stripped.startswith("#"):
            continue
        stripped_lines.append(stripped)
    if not stripped_lines:
        return True
    return all(
        line in {"pass", "...", "raise NotImplementedError", "raise NotImplementedError()"}
        for line in stripped_lines
    )


def _detect_async_without_await_in_payload(text: str) -> list[str]:
    """Return list of async function names whose body lacks await/yield."""
    if not text:
        return []
    out: list[str] = []
    for match in _ASYNC_DEF_BLOCK_RE.finditer(text):
        name = match.group("name")
        body = match.group("body") or ""
        if _is_abstract_or_stub_body(body):
            continue
        # Look upwards for an @abstractmethod decorator on the
        # immediately preceding lines (within 3 lines).
        head = text[max(0, match.start() - 200) : match.start()]
        recent_decorators = head.rsplit("\n", 4)[-3:]
        if any(_ABSTRACT_DECORATOR_RE.search(line) for line in recent_decorators):
            continue
        if not _async_body_uses_await(body):
            out.append(name)
    return out


def _step_introduces_async_without_await(step: ReActStep) -> list[str]:
    """List of new async functions with non-trivial bodies that never
    await/yield. Only fires for non-test Python paths."""
    path = _extract_step_path(step)
    if not path or not path.lower().endswith((".py", ".pyi")):
        return []
    if _is_test_path(path):
        return []
    new_text, old_text = _extract_step_payloads(step)
    new_hits = set(_detect_async_without_await_in_payload(new_text))
    old_hits = set(_detect_async_without_await_in_payload(old_text))
    return sorted(new_hits - old_hits)


# ──────────────────────────────────────────────────────────────────
# §59 — exception-swallow-via-log detection
# ──────────────────────────────────────────────────────────────────
# Catch the failure mode where the model "fixes" an exception by
# logging it and then either returning or continuing — silently
# discarding the failure. This is the LESS obvious sibling of §30:
# §30 catches ``except: pass``; §59 catches ``except: log.error(...)``
# without raising. To the next reader the log call looks like proper
# error handling — but the call STILL swallows the error.
#
# Heuristic: after an ``except`` header (any type), the body matches
# ``log<something>(...)`` (warning/error/exception/info) AND nothing
# in the body re-raises (``raise``, ``raise X``, ``return``-with-error,
# or ``raise from``). We don't try to be smart about "logged then
# raised" — those use ``raise`` and we accept them.

_EXCEPT_HEAD_ANY_RE = re.compile(
    r"(?:^|\n)(?P<indent>[ \t]*)except\b[^\n]*:[ \t]*\n",
)
_LOG_CALL_RE = re.compile(
    r"\b(?:log(?:ger)?|_logger|logging)\s*\.\s*"
    r"(?:debug|info|warn|warning|error|exception|critical|fatal)\s*\(",
)
_RERAISE_RE = re.compile(r"\braise\b")


def _payload_has_log_swallow(text: str) -> bool:
    """Detect ``except SomeError: log.error(...)`` without a re-raise."""
    if not text:
        return False
    for match in _EXCEPT_HEAD_ANY_RE.finditer(text):
        indent = match.group("indent")
        body_indent_marker = indent + " "  # body must be more indented
        # Read body lines until we hit a line at the same indent or less.
        rest = text[match.end() :]
        body_lines: list[str] = []
        for raw in rest.splitlines():
            stripped = raw.rstrip()
            if not stripped.strip():
                body_lines.append(raw)
                continue
            if not raw.startswith(body_indent_marker):
                break
            body_lines.append(raw)
        body = "\n".join(body_lines)
        if not _LOG_CALL_RE.search(body):
            continue
        if _RERAISE_RE.search(body):
            continue
        return True
    return False


def _step_introduces_log_swallow(step: ReActStep) -> bool:
    """Whether this write step adds a NEW log-and-swallow pattern."""
    path = _extract_step_path(step)
    if not path or not path.lower().endswith((".py", ".pyi")):
        return False
    if _is_test_path(path):
        return False
    new_text, old_text = _extract_step_payloads(step)
    return _payload_has_log_swallow(new_text) and not _payload_has_log_swallow(old_text)


# ──────────────────────────────────────────────────────────────────
# §61 — long-function detection
# ──────────────────────────────────────────────────────────────────
# Catch the failure mode where the model writes a single function
# longer than _LONG_FUNCTION_THRESHOLD lines. Long functions are
# harder to test, harder to read, and tend to bundle multiple
# responsibilities. We don't flag refactors that move existing long
# code — only NEW long bodies introduced by this trajectory.
#
# We're conservative: count only the function's own body lines (not
# nested defs), exclude blank lines and comments, and only fire when
# the new payload contains a fresh def whose body exceeds the
# threshold AND that exact name doesn't appear in the old payload.

_LONG_FUNCTION_THRESHOLD = 150

_FUNCTION_BLOCK_RE = re.compile(
    r"(?:^|\n)(?P<indent>[ \t]*)(?:async\s+)?def\s+"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*\([^)]*\)\s*"
    r"(?:->\s*[^:\n]+)?\s*:"
    r"(?P<body>(?:\n(?P=indent)[ \t]+[^\n]*|\n\s*$)*)",
)


def _count_function_body_lines(body: str) -> int:
    """Substantive (non-blank, non-comment, non-docstring) body lines."""
    if not body:
        return 0
    count = 0
    in_docstring = False
    docstring_quote: str | None = None
    for raw in body.splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        if in_docstring:
            if docstring_quote and docstring_quote in raw:
                in_docstring = False
            continue
        if stripped.startswith(('"""', "'''")):
            opener = '"""' if stripped.startswith('"""') else "'''"
            after = stripped[3:]
            if opener in after:
                continue
            in_docstring = True
            docstring_quote = opener
            continue
        if stripped.startswith("#"):
            continue
        count += 1
    return count


def _detect_long_functions_in_payload(text: str) -> list[tuple[str, int]]:
    """Return ``[(name, body_line_count)]`` for functions whose body
    exceeds ``_LONG_FUNCTION_THRESHOLD`` lines."""
    if not text:
        return []
    out: list[tuple[str, int]] = []
    for match in _FUNCTION_BLOCK_RE.finditer(text):
        body = match.group("body") or ""
        lines = _count_function_body_lines(body)
        if lines > _LONG_FUNCTION_THRESHOLD:
            out.append((match.group("name"), lines))
    return out


def _step_introduces_long_function(step: ReActStep) -> list[tuple[str, int]]:
    """List of ``(name, line_count)`` for new long functions added.

    Skips test paths (long parametrized fixtures) and non-Python files.
    Diffs new vs old payload by function NAME — moving an existing
    long function around isn't flagged.
    """
    path = _extract_step_path(step)
    if not path or not path.lower().endswith((".py", ".pyi")):
        return []
    if _is_test_path(path):
        return []
    new_text, old_text = _extract_step_payloads(step)
    new_long = _detect_long_functions_in_payload(new_text)
    old_long_names = {name for name, _lines in _detect_long_functions_in_payload(old_text)}
    return [(name, lines) for name, lines in new_long if name not in old_long_names]


# ──────────────────────────────────────────────────────────────────
# §63-§70 — Security + quality detectors (EXTRACTED 2026-06-06)
# ──────────────────────────────────────────────────────────────────
# The following detectors have been extracted to react_security_detectors.py
# to reduce this file's size. Re-exported here for backward compatibility.

from .react_security_detectors import (  # noqa: E402, F401 — re-exported for backward compatibility
    _detect_dynamic_exec_in_payload,
    _detect_magic_numbers_in_payload,
    _detect_repeated_literals_in_payload,
    _detect_shell_injection_in_payload,
    _detect_unsafe_deser_in_payload,
    _payload_has_network_in_loop,
    _step_introduces_dynamic_exec,
    _step_introduces_magic_number,
    _step_introduces_network_in_loop,
    _step_introduces_repeated_literal,
    _step_introduces_shell_injection,
    _step_introduces_unsafe_deser,
)
