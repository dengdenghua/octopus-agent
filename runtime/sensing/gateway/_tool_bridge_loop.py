"""The native agentic tool loop (``stream_agentic_fallback``).

Extracted from ``tool_bridge.py`` (the Claude-native agentic loop). This
satellite owns the main ``stream_agentic_fallback`` generator — the bounded
``plan → tool_use → execute → tool_result`` loop that turns Octopus skills
into Claude-native ``tool_use`` calls and streams ``(kind, delta, final)``
events back to the SSE consumer.

The parent ``tool_bridge`` module re-exports every name here so existing
importers and tests are unchanged.
"""

from __future__ import annotations

import contextlib
import contextvars
import json
import logging
import time
from collections.abc import Callable, Iterator
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from typing import Any

from runtime.core.cerebrum.capability_router import activate_capabilities
from runtime.core.cerebrum.react_native import require_public_update_on_tool_specs
from runtime.core.cerebrum.todo_protocol import (
    context_mode,
    render_todo_protocol_guidance,
    should_require_todo_protocol,
)
from runtime.execution.tool_spec_builder import build_anthropic_tool_specs
from runtime.platform.models import ParsedIntent
from runtime.platform.models.llm import model_supports_thinking
from runtime.sensing.model_router.models import (
    Message,
    ModelRequest,
    ToolCall,
    thinking_budget_for_effort,
)

from ._tool_bridge_exec import _execute_tool_call, _recover_named_xml_tool_calls
from ._tool_bridge_native import (
    _NATIVE_STREAM_DEADLINE,
    _NATIVE_STREAM_REDIRECTED,
    _deduplicate_native_tool_calls,
    _iter_native_model_stream_with_deadline,
    _native_call_failure_is_definitive,
    _native_definitive_failure_target,
    _native_failure_is_definitive,
    _native_model_recovery_timeout_s,
    _native_post_tool_timeout_s,
    _native_tool_batch_fingerprint,
    _native_tool_call_fingerprint,
)
from ._tool_bridge_policy import (
    _CODE_MUTATION_TOOLS,
    _CODE_TERMINAL_VERIFIER_TOOLS,
    _CODE_VERIFICATION_TOOLS,
    _SERIAL_BARRIER_TOOLS,
    PARALLEL_TOOL_USE_DEFAULT,
    PARALLEL_TOOL_USE_MAX_WORKERS,
    REFLECTION_INTERVAL,
    _filter_tool_specs_for_workspace_contract,
    _is_code_change_task,
    _is_security_change_task,
    _is_shell_mutation,
    _is_shell_terminal_verifier,
    _is_shell_verification,
    _native_tool_round_budget,
    _reflection_checkpoint_message,
    _tool_uses_session_scope,
)
from ._tool_bridge_protocol import (
    _NATIVE_ROUND_TEXT_PREFIX_RE,
    _NATIVE_TEXT_STREAM_SUPPRESS_MARKERS,
    _NATIVE_TEXT_STREAM_TAIL_MARGIN,
    _generate_native_action_checkpoint,
    _generate_native_evidence_checkpoint,
    _native_calls_with_public_checkpoint,
    _native_public_checkpoint,
    _native_result_checkpoint,
    _ordered_read_handoffs_requested,
    _public_narrative_silence_s,
)
from ._tool_bridge_scoring import _record_score_safe
from ._tool_bridge_session import (
    _browser_action_evidence,
    _browser_operation_guidance,
    _ensure_explicit_browser_skills,
    _required_browser_action_evidence,
    _session_metadata_from_intent,
)

_logger = logging.getLogger("octopus.agentic")


def _rescue_policy_names() -> tuple[Any, Any]:
    """Lazily resolve rescue-policy helpers through the parent module.

    Tests monkeypatch ``tool_bridge._next_custom_model_fallback`` /
    ``tool_bridge._is_provider_unavailable_error`` at module level, so the
    loop must read them live from the parent namespace (not a locally-bound
    alias) for those patches to take effect. Returns ``(is_unavailable, fallback)``.
    """
    from runtime.sensing.gateway import tool_bridge as _tb

    return _tb._is_provider_unavailable_error, _tb._next_custom_model_fallback


def _native_plan_reconciliation_milestones(
    calls: list[ToolCall],
    result_blocks: list[dict[str, Any]],
) -> list[str]:
    """Return successful write/verification milestones after the last todo."""
    last_todo_index = max(
        (index for index, call in enumerate(calls) if call.name == "todo_write"),
        default=-1,
    )
    milestones: list[str] = []
    for index, (call, block) in enumerate(zip(calls, result_blocks, strict=True)):
        if index <= last_todo_index or block.get("is_error"):
            continue
        if (
            call.name in _CODE_MUTATION_TOOLS or _is_shell_mutation(call)
        ) and "workspace/document write" not in milestones:
            milestones.append("workspace/document write")
        if (
            call.name in _CODE_VERIFICATION_TOOLS or _is_shell_verification(call)
        ) and "green verification" not in milestones:
            milestones.append("green verification")
    return milestones


def stream_agentic_fallback(
    stack: Any,
    intent: ParsedIntent,
    agent: Any,
    *,
    model: str | None = None,
    sub_event_queue: Any = None,
    steering_drain: Callable[[], list[str]] | None = None,
) -> Iterator[tuple[str, Any, Any]]:
    """Agentic streaming · same ``(kind, delta, final)`` shape as
    ``_stream_direct_llm_fallback`` so the SSE loop can consume
    both paths identically.

    Extra event kinds vs the direct fallback:

    * ``("tool_start", {id, name, input, iteration}, None)``
    * ``("tool_end",   {id, name, output, is_error, iteration}, None)``

    The tool_start/tool_end pair gets turned into SSE ``custom``
    frames by the router, feeding the existing
    ``LiveToolTimeline`` component in the UI.

    Sub-agent events
    ----------------

    When ``sub_event_queue`` is provided (same ``queue.Queue`` the
    SSE pump is draining), it's stashed on ``Session.metadata`` so
    the ephemeral sub-agent runner can push
    ``("sub_tool_start"/"sub_tool_end", payload, None)`` tuples into
    it when IT executes tools. The SSE pump's drain loop serializes
    parent + sub-agent events into one ordered stream with
    ``parent_tool_use_id`` fields linking children to the
    ``call_agent_parallel`` / ``call_agent`` row they run under.

    The ``_active_parent_tool_use_id`` session-metadata key is
    flipped on/off around each parent ``_execute_tool_call`` so
    sub-agents spawned inside a handler can read the id of the
    parent tool_use they're running under · see
    ``ephemeral_runner._emit_sub_tool_event``.
    """
    # Resolve monkeypatchable policy values live from the parent module so
    # tests that ``monkeypatch.setattr(tool_bridge, "MAX_TOOL_ROUNDS", ...)``
    # (or ``_native_model_round_timeout_s``) take effect here.
    from runtime.sensing.gateway import tool_bridge as _tb

    max_tool_rounds = _tb.MAX_TOOL_ROUNDS
    _native_model_round_timeout_s = _tb._native_model_round_timeout_s

    router = getattr(stack.planner, "router", None)
    if router is None:
        return

    # Build the conversational message thread from intent · same
    # helper the direct fallback uses so system prompt / team
    # roster / profile memories stay in sync.
    from .openai_gateway import (
        _conversation_messages_for_model,
        _profile_memories_payload,
    )

    messages: list[Message] = _conversation_messages_for_model(intent)

    try:
        from runtime.core.cerebrum.llm_planner import (
            _render_team_roster_section,
        )

        team_section = _render_team_roster_section(
            intent.user_context or {},
        )
    except (ImportError, AttributeError):
        team_section = ""
    if team_section:
        messages.insert(0, Message(role="system", content=team_section))

    if agent is not None and getattr(agent, "soul", None):
        # Re-read SOUL.md from disk on every turn so the
        # ``update_soul`` skill (agent rewriting its own scaffold)
        # takes effect on the very NEXT turn rather than only after
        # a process restart. Falls back to the cached ``agent.soul``
        # when the file isn't readable for any reason — keeps the
        # legacy behavior intact when no SOUL.md exists on disk.
        soul_text = agent.soul
        try:
            from pathlib import Path

            _agent_id = getattr(agent, "agent_id", "") or ""
            if _agent_id:
                _project_root = Path(__file__).resolve().parents[3]
                _soul_path = _project_root / "agents" / _agent_id / "agent-core" / "SOUL.md"
                if _soul_path.exists():
                    fresh = _soul_path.read_text(encoding="utf-8").strip()
                    if fresh:
                        soul_text = fresh
                        # Mirror back to the live Agent instance so
                        # other code reading agent.soul (display
                        # rendering, etc) sees the latest copy too.
                        with contextlib.suppress(AttributeError, TypeError):
                            agent.soul = fresh
        except (OSError, ValueError):  # noqa: BLE001 — soul file refresh failed; keep current soul text
            pass
        try:
            from runtime.execution.agents.loader import compose_runtime_soul

            soul_text = compose_runtime_soul(agent)
        except (ImportError, AttributeError):  # noqa: BLE001 — compose_runtime_soul unavailable; proceed without soul prefix
            pass
        messages.insert(0, Message(role="system", content=soul_text))

    # Counter-assertion against the well-known "I have no persistent
    # memory" denial many chat models default to. The agentic path
    # exposes real `remember` / `recall` / `note_user` tools that
    # write to disk and survive across conversations — telling the
    # model the tools ARE real and to use them rather than denying
    # the premise. Cheap (a few tokens) and only loaded when
    # memory tools exist in the registry.
    try:
        _has_mem = any(stack.executor.registry.has(n) for n in ("remember", "recall", "note_user"))
    except (AttributeError, TypeError, KeyError):
        _has_mem = False
    if _has_mem:
        messages.insert(
            0,
            Message(
                role="system",
                content=(
                    "CAPABILITIES · cross-conversation memory:\n"
                    "You DO have persistent memory via the `remember`, "
                    "`recall`, and `note_user` tools. They write to "
                    "disk files that survive across turns and threads. "
                    "When the user asks you to remember something or "
                    "references past context, CALL THESE TOOLS — do "
                    "not say 'I don't have persistent memory' or 'each "
                    "conversation is fresh.' That denial was trained in "
                    "before you had these tools; it is no longer true.\n"
                    "- User asks to remember a fact → call `remember`\n"
                    "- User mentions a preference / style → call `note_user`\n"
                    "- User references past context → call `recall` first\n"
                ),
            ),
        )

    # Same anti-denial pattern for the `call_agent` (subagent
    # delegation) tool. Without this, when the user asks for multiple
    # delegations in one turn, Claude reflexively says "I don't have
    # the ability to dispatch to subagents" — which is false; the
    # tool is right there in its tool list. The denial happens because
    # the model's general training conflicts with the per-turn budget
    # (see delegation_skills.py). The capability assertion below tells
    # it: yes you have this, just use it sparingly per the rules.
    try:
        _has_delegation = stack.executor.registry.has("call_agent")
    except (AttributeError, TypeError, KeyError):
        _has_delegation = False
    if _has_delegation:
        messages.insert(
            0,
            Message(
                role="system",
                content=(
                    "CAPABILITIES · sub-agent delegation:\n"
                    "You DO have a `call_agent` tool that spawns an "
                    "isolated specialist subagent (architect / "
                    "security-review). When the user asks you to "
                    "delegate something appropriate, CALL THE TOOL — "
                    "do not say 'I am Claude, I cannot dispatch to "
                    "subagents' or 'I don't have that capability.' "
                    "That denial is wrong; the tool is in your tool "
                    "list.\n"
                    "Delegation is optional, not a template. Use it only "
                    "when the task is large, long-running, or naturally "
                    "parallel. For one focused specialist task, call_agent "
                    "is enough. For several independent subtasks, prefer "
                    "the parallel delegation tool when available and choose "
                    "the number of subagents from the actual task split; "
                    "do not spawn helpers just to fill a fixed swarm shape."
                ),
            ),
        )

    # Same anti-denial pattern for the SOUL.md self-evolution
    # tools (`update_soul` / `revert_soul` / `list_soul_history`).
    # Without this assertion Claude reflexively says "I'm just an
    # LLM, I don't have a 'soul' file to edit" — which is wrong;
    # the agent's `agents/<id>/agent-core/SOUL.md` IS its persona
    # file, the tool exists in the spec, and writes/reverts there
    # actually persist into the next session's system prompt.
    try:
        _has_soul = stack.executor.registry.has("update_soul")
    except (AttributeError, TypeError, KeyError):
        _has_soul = False
    # Skill library capability assertion · same anti-denial pattern.
    # Agents reflexively want to "do it directly" instead of going
    # through apply_skill, leaking the template's discipline. This
    # tells them: when a learned skill matches the request, USE
    # apply_skill — don't ad-hoc reinvent the template every time.
    try:
        _has_skill_lib = stack.executor.registry.has("learn_skill_from_text")
    except (AttributeError, TypeError, KeyError):
        _has_skill_lib = False
    if _has_skill_lib:
        messages.insert(
            0,
            Message(
                role="system",
                content=(
                    "CAPABILITIES · learned skill library:\n"
                    "You have a per-agent skill library at "
                    "agents/<your_id>/skills/. When the user asks for "
                    "output that matches a learned template (tech "
                    "comparison, report format, slide outline, anything "
                    "you've previously taught yourself via "
                    "`learn_skill_from_text`), DON'T re-invent the shape "
                    "from scratch. Workflow:\n"
                    "  1. `list_learned_skills` to see what you already "
                    "know. **This is free (0 tokens) — call it whenever "
                    "the user asks for structured output**.\n"
                    "  2. Pick the matching skill from that list.\n"
                    "  3. `apply_skill(name=<skill>, user_request=...)` "
                    "to produce the output. Pass the user's specific "
                    "request as user_request — apply_skill will fill in "
                    "the template for you.\n"
                    "  4. When LEARNING a new skill, pass "
                    "`golden_samples=['req A', 'req B', 'req C']` so the "
                    "C1 gate verifies the template actually reproduces "
                    "on 3 different topics before persisting. The skill "
                    "is dropped (not saved) if it fails the gate.\n\n"
                    "TRIGGERS · phrases that should ALWAYS make you "
                    "`list_learned_skills` first:\n"
                    '  · "write a report on…" / "写一份…报告"\n'
                    '  · "compare X and Y and Z" / "对比…/评估…"\n'
                    '  · "summarize X same as Y" / "像…一样写"\n'
                    '  · "做成 X 那样的" / "以后按这个格式做"\n'
                    '  · "同 Y 一样的" / "templatize this"\n\n'
                    "Do NOT manually compose markdown when a saved skill "
                    "covers the shape · the whole point of learning a "
                    "skill is to enforce its discipline on every reuse. "
                    "If the existing skill needs improvement, "
                    "`learn_skill_from_text` again to overwrite."
                ),
            ),
        )

    if _has_soul:
        messages.insert(
            0,
            Message(
                role="system",
                content=(
                    "CAPABILITIES · self-evolution via SOUL.md:\n"
                    "You DO have `update_soul`, `revert_soul`, "
                    "`list_soul_history`, `recall_scores`, "
                    "`analyze_soul_impact`, `deep_reflect`, and "
                    "`deep_evolve` tools. They edit a real file at "
                    "agents/<your_id>/agent-core/SOUL.md that gets "
                    "auto-loaded into your system prompt on the very "
                    "NEXT turn (hot-reloaded · no restart needed). "
                    "Per-turn quality scores live in `.scores.jsonl` "
                    "next to it. When the user asks you to record a "
                    "self-lesson, roll back, inspect history, OR "
                    "evaluate your own performance — CALL THE TOOL. "
                    "Do not say 'I'm Claude, I don't have a soul' or "
                    "'I have no such tool.' Those denials are wrong; "
                    "the tools are in your tool list and they really "
                    "modify your future behavior. Every successful "
                    "update_soul auto-snapshots the prior state into "
                    ".soul_history/, so revert_soul is always safe.\n"
                    "Reflection cost ladder · pick the cheapest that "
                    "can answer the question:\n"
                    "  - `analyze_soul_impact` · zero LLM cost · "
                    "heuristic before/after delta on score history\n"
                    "  - `deep_reflect` · 1 cheap LLM call (~2-3¢) · "
                    "use when heuristic says 'inconclusive'\n"
                    "  - `deep_evolve` · expensive autonomous loop "
                    "(~10-30¢) · ONLY when user explicitly asks for "
                    "'deep evolution' / '深度演化' / similar. Default "
                    "dry_run=True · returns proposals without mutating "
                    "SOUL · review first, then re-run with dry_run=False "
                    "if you want to commit."
                ),
            ),
        )

    from runtime.memory.users.profile import render_profile_memories

    profile_section = render_profile_memories(
        _profile_memories_payload(intent),
    )
    if profile_section:
        messages.insert(0, Message(role="system", content=profile_section))

    try:
        from runtime.memory.runtime_state.hub import (
            MemoryHub,
            MemoryQuery,
            format_records_for_prompt,
        )

        _metadata_for_memory = _session_metadata_from_intent(intent)
        _workspace_for_memory = _metadata_for_memory.get("workspace_path")
        _project_for_memory = (
            str(_workspace_for_memory).strip()
            if isinstance(_workspace_for_memory, str) and str(_workspace_for_memory).strip()
            else None
        )
        _agent_id_for_memory = (
            str(getattr(agent, "agent_id", "") or "") if agent is not None else None
        )
        _team_id_for_memory = _metadata_for_memory.get("team_id")
        _team_id_for_memory = (
            str(_team_id_for_memory).strip()
            if isinstance(_team_id_for_memory, str) and str(_team_id_for_memory).strip()
            else None
        )
        memory_section = format_records_for_prompt(
            MemoryHub(
                repo_root=_project_for_memory,
                planner=getattr(stack, "planner", None),
            ).retrieve(
                MemoryQuery(
                    text=intent.normalized_goal,
                    agent_id=_agent_id_for_memory,
                    project=_project_for_memory,
                    team_id=_team_id_for_memory,
                    limit=8,
                )
            ),
        )
    except Exception:  # noqa: BLE001 — best-effort; logged
        _logger.debug("memory hub prompt injection failed", exc_info=True)
        memory_section = ""
    if memory_section:
        messages.insert(0, Message(role="system", content=memory_section))

    if not messages:
        messages.append(
            Message(
                role="user",
                content=intent.normalized_goal,
            )
        )

    _intent_user_context = intent.user_context or {}
    _ensure_explicit_browser_skills(
        getattr(stack.executor, "registry", None),
        _intent_user_context,
    )
    _browser_prompt = _browser_operation_guidance(_intent_user_context)
    _browser_required_evidence = (
        _required_browser_action_evidence(intent.normalized_goal) if _browser_prompt else set()
    )
    if _browser_prompt:
        messages.insert(0, Message(role="system", content=_browser_prompt))
    _capability_activation = activate_capabilities(
        intent.normalized_goal,
        user_context=_intent_user_context,
        registry=getattr(stack.executor, "registry", None),
    )
    _capability_activation_prompt = _capability_activation.render_prompt()
    if _capability_activation_prompt:
        messages.insert(
            0,
            Message(
                role="system",
                content=_capability_activation_prompt,
            ),
        )
    messages.insert(
        0,
        Message(
            role="system",
            content=(
                "TOOL LOOP DISCIPLINE:\n"
                "- Reuse successful tool results already present in this turn. Never "
                "repeat an identical read/search/list call merely to reconfirm it.\n"
                "- If a read-only target is confirmed missing, changing pagination or "
                "range arguments cannot make it exist; correct the path or inspect its "
                "parent instead.\n"
                "- Once the evidence requested by the user is present, stop calling "
                "tools and return the complete answer."
            ),
        ),
    )
    _code_change_task = _is_code_change_task(intent)
    if _code_change_task:
        available_code_tools = [
            name
            for name in (
                "list_cwd",
                "read_file",
                "grep_text",
                "glob_files",
                "edit_file",
                "write_text_file",
                "multi_edit_file",
                "exec_shell",
                "run_tests",
                "lint_check",
            )
            if stack.executor.registry.has(name)
        ]
        messages.insert(
            0,
            Message(
                role="system",
                content=(
                    "CODE EXECUTION CONTRACT:\n"
                    "- These tools are enabled in this turn: "
                    + ", ".join(f"`{name}`" for name in available_code_tools)
                    + ". Do not claim tools are unavailable and do not merely "
                    "draft a patch in prose; call the tools to change the scoped "
                    "workspace.\n"
                    "- Inspect an existing file with `read_file` before using "
                    "an edit/write tool on it. Prefer native file tools over "
                    "shell-generated source code.\n"
                    "- After changing implementation or tests, run the focused "
                    "test command that proves the requested behavior. Lint is "
                    "useful additional evidence but does not prove runtime "
                    "behavior and does not replace tests.\n"
                    "- Prefer the smallest focused regression tests. In "
                    "concurrency tests, coordinate callers before they enter "
                    "the operation; never put a barrier for all callers inside "
                    "a loader that correct coalescing should invoke only once.\n"
                    "- A failed check is evidence that work remains. Diagnose it, "
                    "repair the implementation or test, and rerun verification; "
                    "do not mark the task complete or pause while the latest "
                    "verification is failing.\n"
                ),
            ),
        )
    if _is_security_change_task(intent):
        messages.insert(
            0,
            Message(
                role="system",
                content=(
                    "SECURITY REPAIR CONTRACT:\n"
                    "- Write down the trust boundary and the exact order of "
                    "decode, normalization, resolution, and authorization checks.\n"
                    "- Add adversarial regression cases, not only the reported "
                    "example: repeated/mixed encoding, nested traversal, absolute "
                    "paths, separator variants where relevant, and symlink/TOCTOU "
                    "escape where the API touches paths.\n"
                    "- Treat input that changes meaning under another decoding "
                    "pass as ambiguous and unsafe: a downstream layer may decode "
                    "again. Repeatedly encoded traversal must be rejected with the "
                    "domain boundary exception, never left to FileNotFoundError.\n"
                    "- Verify the rejection uses the promised domain exception, "
                    "not an incidental file-not-found or permission error.\n"
                    "- Do not claim zero residual risk solely because self-authored "
                    "happy-path tests passed. Re-read the final implementation and "
                    "challenge its normalization assumptions before finishing.\n"
                ),
            ),
        )
    _todo_protocol_mode = context_mode(_intent_user_context)
    _todo_protocol_required = False

    # Anti-denial for the live task checklist. The tool is small but
    # UX-critical; Claude-family models sometimes answer "todo_write
    # is not available" when the user explicitly names it, even though
    # it is present in the tools array. State the capability plainly.
    try:
        _has_todo_write = stack.executor.registry.has("todo_write")
    except (AttributeError, TypeError, KeyError):
        _has_todo_write = False
    if _has_todo_write:
        _todo_protocol_required = should_require_todo_protocol(
            intent.normalized_goal,
            _intent_user_context,
        )
        messages.insert(
            0,
            Message(
                role="system",
                content=(
                    "CAPABILITIES · task checklist:\n"
                    "You DO have a `todo_write` tool. It records the live "
                    "task checklist shown to the user during multi-step work. "
                    "When a task has several steps, CALL `todo_write` at the "
                    "start, then call it again when one item becomes "
                    "`in_progress` or `completed`. Do not say `todo_write` is "
                    "unavailable; that denial is wrong because the tool is in "
                    "your tool list.\n"
                    "Accepted payloads: prefer `items=[...]` or `todos=[...]` "
                    "as arrays; JSON strings are tolerated for compatibility. Each "
                    "item may use `content`, `text`, `title`, or `task`, plus an "
                    "optional stable `id`, "
                    "`status` (`pending` / `in_progress` / `completed`) and "
                    "optional `activeForm` / `active_form`. Preserve returned IDs "
                    "and always pass the complete list, not a diff.\n\n"
                    + render_todo_protocol_guidance(
                        required=_todo_protocol_required,
                        mode=_todo_protocol_mode,
                    )
                ),
            ),
        )

    messages.insert(
        0,
        Message(
            role="system",
            content=(
                "REALTIME INTERACTION CONTRACT:\n"
                "- During a multi-step task, accompany each meaningful tool "
                "batch with one short ordinary-text checkpoint before the tool "
                "call. State the conclusion just established and what you are "
                "doing next; do not expose private chain-of-thought.\n"
                "- Keep checkpoints concrete and user-facing. Avoid generic "
                "phrases such as 'working on it' when a verified finding is "
                "available.\n"
                "- After the last tool result, produce the complete answer "
                "directly instead of another process-only checkpoint.\n"
            ),
        ),
    )

    # Bind the agent into a Session for the duration of this stream
    # so memory skills (`remember`, `recall`, `note_user`,
    # `diary_write`) can resolve the active agent_id via
    # ``current_session()``. Without this, any memory/scope-aware call
    # here would lose turn metadata because the pump thread inherits
    # no ContextVar from its parent. Scoped to this function so it
    # tears down cleanly when the stream ends.
    from runtime.platform.process.session import Session

    user_context = _intent_user_context
    _session_obj = Session(
        actor=getattr(intent, "actor", None),
        agent=agent,
        thread_id=(
            getattr(intent, "thread_id", None)
            or getattr(intent, "conversation_id", None)
            or user_context.get("thread_id")
            or user_context.get("conversation_id")
        ),
        metadata=_session_metadata_from_intent(intent),
    )
    # Stash the SSE pump queue on the Session so sub-agents spawned
    # via ``call_agent`` / ``call_agent_parallel`` can push their
    # own tool_start/tool_end events and have them appear in the
    # same ordered stream the parent emits. See module docstring +
    # ``ephemeral_runner._emit_sub_tool_event``.
    if sub_event_queue is not None:
        _session_obj.metadata["sub_tool_event_queue"] = sub_event_queue

    # Resolve upstream model name through the dispatcher so we
    # know whether we're talking to an Anthropic-family model
    # (the only one that honors ``tools=``).
    effective_model = (
        model
        if model and model not in ("octopus-agent", "")
        else getattr(stack.planner, "planner_model", None) or "molili"
    )

    tool_specs = build_anthropic_tool_specs(
        stack.executor.registry,
        agent=agent,
        user_context=_intent_user_context,
        goal=intent.normalized_goal,
    )
    tool_specs, workspace_contract = _filter_tool_specs_for_workspace_contract(
        tool_specs,
        intent.normalized_goal,
    )
    evidence_tool_specs = tool_specs
    if bool(_intent_user_context.get("realtime_public_orientation")):
        base_tool_specs = tool_specs
        tool_specs = require_public_update_on_tool_specs(base_tool_specs)
        evidence_tool_specs = require_public_update_on_tool_specs(
            base_tool_specs,
            evidence_round=True,
        )
    _tool_round_budget = _native_tool_round_budget(
        intent.normalized_goal,
        workspace_contract=workspace_contract,
        code_change_task=_code_change_task,
    )
    if _tool_round_budget < max_tool_rounds:
        messages.insert(
            0,
            Message(
                role="system",
                content=(
                    "TOOL-ROUND BUDGET:\n"
                    f"You have at most {_tool_round_budget} evidence-gathering "
                    "rounds before tools are disabled for synthesis. Prefer "
                    "the strongest available evidence, avoid retrying equivalent "
                    "URLs or searches, and answer as soon as the request is "
                    "supported. The final synthesis round must produce the best "
                    "complete answer from collected evidence."
                ),
            ),
        )
    if workspace_contract == "no_local_access":
        messages.insert(
            0,
            Message(
                role="system",
                content=(
                    "LOCAL WORKSPACE ACCESS IS FORBIDDEN FOR THIS TURN:\n"
                    "The user explicitly prohibited reading, inspecting, "
                    "modifying, or creating local files. Local filesystem, "
                    "shell, memory-write, delegation, and artifact tools have "
                    "therefore been removed from the tool list. Use only remote "
                    "research/browser tools and the live checklist. Do not claim "
                    "that local inspection is required and do not ask another "
                    "agent to perform it."
                ),
            ),
        )
    elif workspace_contract == "read_only":
        messages.insert(
            0,
            Message(
                role="system",
                content=(
                    "READ-ONLY WORKSPACE CONTRACT:\n"
                    "The user permitted inspection but prohibited mutation. "
                    "File-write, edit, shell, test, formatting, memory-write, "
                    "and self-modification tools have been removed. Do not "
                    "create or modify local files."
                ),
            ),
        )
    if not tool_specs:
        # Registry is empty or broken · degrade to direct LLM.
        _logger.warning(
            "agentic · no tool specs available · degrading to direct",
        )
        return

    accumulated_text = ""
    accumulated_reasoning = ""
    # Stats accumulator · summed across all rounds the model executes.
    # Surfaced in the final ``done`` payload so the SSE consumer can
    # forward to the message metadata for the UI footer (token usage
    # + wall-clock duration). Per-round tokens come from the Anthropic
    # SDK's `final.usage` object; we just sum.
    _started_at = time.monotonic()
    _last_public_checkpoint_at = _started_at
    _realtime_public_narrative = bool(_intent_user_context.get("realtime_public_narrative"))
    _public_narrative_interval = _public_narrative_silence_s(_intent_user_context)
    _ordered_read_handoffs = _ordered_read_handoffs_requested(intent.normalized_goal)
    _result_handoff_ready = False
    _total_in_tokens = 0
    _total_out_tokens = 0
    _todo_seen = False
    _tool_work_since_todo = False
    _todo_guard_nudges = 0
    # Tool-error counter for the per-turn quality score (0 errors →
    # full credit, any errors → partial). Bumped in the tool_result
    # building loop below.
    _tool_error_count = 0
    _completed_tool_count = 0
    _attempted_models = {effective_model}
    _provider_failovers = 0
    _stall_failovers = 0
    _code_mutation_seen = False
    _code_verification_state: bool | None = None
    _clean_code_verifier_rounds = 0
    _green_verification_convergence_active = False
    _green_convergence_todo_only = False
    _code_semantic_steps: list[Any] = []
    _code_semantic_repair_required = False
    _code_semantic_repair_message = ""
    _pending_code_semantic_nudge = ""
    _code_semantic_guard_nudges = 0
    _code_completion_nudges = 0
    _code_no_action_stops = 0
    _quality_failovers = 0
    _browser_observed_evidence: set[str] = set()
    _browser_guard_nudges = 0
    _force_convergence_next = False
    _model_timeout_recoveries = 0
    _failed_native_batches: dict[str, tuple[int, bool]] = {}
    _definitive_failed_native_targets: set[str] = set()
    _successful_native_read_calls: set[str] = set()
    _repeated_failure_guard_hits = 0
    _pending_steering: list[str] = []
    _last_steering_probe_at = 0.0

    if (intent.user_context or {}).get("live_steering"):
        from runtime.core.cerebrum.live_steering import (
            insert_live_steering_protocol,
        )

        insert_live_steering_protocol(messages)

    def _capture_steering(*, force: bool = False) -> bool:
        """Collect live user input without exposing it to two rounds.

        Native provider streams and tools are synchronous from this
        generator's point of view. Polling here gives them a cooperative
        redirect boundary while the durable queue remains the single source
        of delivery and idempotency.
        """
        nonlocal _last_steering_probe_at
        if steering_drain is None:
            return False
        now = time.monotonic()
        if not force and now - _last_steering_probe_at < 0.1:
            return False
        _last_steering_probe_at = now
        try:
            captured = [str(text).strip() for text in steering_drain()]
        except Exception:  # noqa: BLE001 — steering must not break execution
            _logger.warning("live steering poll failed", exc_info=True)
            return False
        captured = [text for text in captured if text]
        if not captured:
            return False
        _pending_steering.extend(captured)
        return True

    def _append_pending_steering() -> None:
        if not _pending_steering:
            return
        from runtime.core.cerebrum.live_steering import (
            append_live_steering_messages,
        )

        append_live_steering_messages(messages, _pending_steering)
        _pending_steering.clear()

    def _observe_code_tool_result(
        call: ToolCall,
        is_error: bool,
        output: str,
        iteration: int,
    ) -> None:
        nonlocal _clean_code_verifier_rounds
        nonlocal _code_mutation_seen, _code_verification_state
        nonlocal _code_semantic_guard_nudges
        nonlocal _code_semantic_repair_message, _code_semantic_repair_required
        nonlocal _pending_code_semantic_nudge
        nonlocal _green_convergence_todo_only
        nonlocal _green_verification_convergence_active
        if not _code_change_task:
            return
        if (call.name in _CODE_MUTATION_TOOLS or _is_shell_mutation(call)) and not is_error:
            _code_mutation_seen = True
            # Any later mutation invalidates proof from an earlier test run.
            _code_verification_state = None
            _clean_code_verifier_rounds = 0
            _green_verification_convergence_active = False
            _green_convergence_todo_only = False
        if not is_error:
            from runtime.core.cerebrum.react_guards import (  # noqa: PLC0415
                _concurrency_semantic_followup_guard,
            )
            from runtime.core.cerebrum.react_types import ReActStep  # noqa: PLC0415

            try:
                args_json = json.dumps(call.input or {}, ensure_ascii=False, default=str)
            except (TypeError, ValueError):
                args_json = "{}"
            _code_semantic_steps.append(
                ReActStep(
                    iteration=iteration,
                    action=f"{call.name}({args_json})",
                    observation=output,
                )
            )
            if call.name in _CODE_MUTATION_TOOLS or _is_shell_mutation(call):
                semantic_message = _concurrency_semantic_followup_guard(
                    _code_semantic_steps,
                    is_code_mode=True,
                )
                _code_semantic_repair_required = semantic_message is not None
                _code_semantic_repair_message = semantic_message or ""
                if semantic_message:
                    _pending_code_semantic_nudge = semantic_message
                    _code_semantic_guard_nudges += 1
                    _code_verification_state = None
                    _clean_code_verifier_rounds = 0
                    _green_verification_convergence_active = False
                    _green_convergence_todo_only = False
                else:
                    _pending_code_semantic_nudge = ""
                    _code_semantic_guard_nudges = 0
        if call.name in _CODE_VERIFICATION_TOOLS or _is_shell_verification(call):
            _code_verification_state = not is_error
        if call.name in _CODE_TERMINAL_VERIFIER_TOOLS or _is_shell_terminal_verifier(call):
            if _code_mutation_seen and not is_error:
                _clean_code_verifier_rounds += 1
            elif is_error:
                _clean_code_verifier_rounds = 0
            if _code_verification_state is True and _clean_code_verifier_rounds >= 2:
                _green_verification_convergence_active = True

    # Realtime generators can be resumed by different worker contexts after
    # every yielded SSE event.  A ContextVar set once for the generator is
    # therefore not a durable execution-scope boundary.  Keep the concrete
    # Session object here and bind it around each tool call below (including
    # the thread-pool path), so every handler sees the same workspace even
    # when adjacent ``next()`` calls arrive through different contexts.
    from runtime.platform.process.session import _current_session  # noqa: PLC0415

    for round_i in range(max_tool_rounds):
        # User follow-ups accepted by turn/steer become real user messages at
        # the next model boundary. The stream/tool probes below can now create
        # that boundary by cancelling only the current operation scope.
        _capture_steering(force=True)
        _append_pending_steering()
        # Soft reflection · at every REFLECTION_INTERVAL boundary
        # (after rounds 10, 20, …) drop a one-line system check-in
        # so the model can decide whether to wrap up or keep going.
        # Cheap (~30 tokens), and avoids the pathology where the
        # model auto-extends to the cap on a task that's already
        # done. Skip round 0 — the first round can never be a
        # "continuation", so the prompt is just noise.
        if round_i > 0 and round_i % REFLECTION_INTERVAL == 0:
            messages.append(
                Message(
                    role="user",
                    content=_reflection_checkpoint_message(
                        round_i,
                        _tool_round_budget,
                    ),
                )
            )
        _round_plan_bootstrap_mode = (
            _todo_protocol_required
            and _has_todo_write
            and not _todo_seen
            and _completed_tool_count == 0
        )
        _round_todo_only_mode = _green_convergence_todo_only
        _round_convergence_mode = _force_convergence_next
        _force_convergence_next = False
        _round_tool_specs = evidence_tool_specs if _completed_tool_count > 0 else tool_specs
        if _round_plan_bootstrap_mode or _round_todo_only_mode:
            _active_tool_specs = [spec for spec in _round_tool_specs if spec.name == "todo_write"]
        elif _round_convergence_mode:
            _active_tool_specs = []
        else:
            _active_tool_specs = _round_tool_specs
        # Streaming thinking for the native loop: without this the request
        # keeps ModelRequest.enable_thinking=False (the default), so a
        # thinking-capable model (deepseek-v4, kimi-thinking, o-series, …)
        # never emits a reasoning channel and the UI shows no thinking
        # surface — the "思考不流式" the realtime workbench reports. The
        # native streamer already passes thinking_delta through verbatim.
        _native_wants_thinking = model_supports_thinking(effective_model)
        req = ModelRequest(
            model=effective_model,
            messages=messages,
            max_tokens=4096,
            temperature=1.0,
            enable_thinking=_native_wants_thinking,
            thinking_budget=thinking_budget_for_effort(
                _intent_user_context.get("reasoning_effort"),
                4096,
            ),
            tools=_active_tool_specs,
            require_tool_use=(
                True
                if _round_plan_bootstrap_mode or _round_todo_only_mode
                else False
                if _round_convergence_mode
                else (
                    (
                        _code_change_task
                        and (
                            not _code_mutation_seen
                            or _code_verification_state is not True
                            or _code_semantic_repair_required
                        )
                    )
                    or bool(_browser_required_evidence - _browser_observed_evidence)
                )
            ),
        )

        round_text_chunks: list[str] = []
        round_tool_calls: list[ToolCall] = []
        _round_commentary_emitted = False
        _round_timed_out = False
        _round_redirected = False
        # Live text streaming state: round text streams as it decodes
        # (holdback + envelope guards below) instead of dumping at round
        # end — the final synthesis round is usually the longest text of
        # the turn, and buffering it made TTFT equal its full decode time.
        _round_text_streamed = 0
        _round_text_stream_suppressed = False
        # Leading "Update:"/"Progress:" label is stripped at the source
        # (first decidable delta) so every downstream consumer — live
        # stream, end-of-round tail flush, checkpoint condensation, the
        # assistant message appended to model context — sees clean text.
        _round_prefix_decided = False

        _round_stream_event_seen = False
        _round_timeout_s = _native_model_round_timeout_s()
        if _completed_tool_count > 0:
            _round_timeout_s = _native_post_tool_timeout_s(_round_timeout_s)
        if _round_convergence_mode:
            _round_timeout_s = _native_model_recovery_timeout_s(_round_timeout_s)
        try:
            for event in _iter_native_model_stream_with_deadline(
                router,
                req,
                _round_timeout_s,
                visible_started=lambda chunks=round_text_chunks: len(chunks),
                redirect_probe=_capture_steering,
            ):
                if event is _NATIVE_STREAM_DEADLINE:
                    _round_timed_out = True
                    _logger.warning(
                        "agentic round %d exceeded %.1fs; switching to convergence",
                        round_i + 1,
                        _round_timeout_s,
                    )
                    break
                if event is _NATIVE_STREAM_REDIRECTED:
                    _round_redirected = True
                    break
                _round_stream_event_seen = True
                etype = event.type
                if etype == "text_delta":
                    round_text_chunks.append(event.delta)
                    if not _round_prefix_decided:
                        _joined_prefix_probe = "".join(round_text_chunks)
                        _prefix_match = _NATIVE_ROUND_TEXT_PREFIX_RE.match(_joined_prefix_probe)
                        if _prefix_match:
                            round_text_chunks[:] = [_joined_prefix_probe[_prefix_match.end() :]]
                            _round_prefix_decided = True
                        elif len(_joined_prefix_probe) >= len("Progress: "):
                            # Past the longest label — the opening is prose.
                            _round_prefix_decided = True
                    # TTFT: stream the round's text live — but only in
                    # post-tool rounds. First-round preambles keep the
                    # condensed-checkpoint treatment: their prose is the
                    # most likely place for protocol echoes, and the
                    # checkpoint filters/condenses it deliberately. After
                    # at least one tool completed, round text is progress
                    # narration or the final synthesis (usually the
                    # longest text of the turn) and streams live with:
                    # (a) a tail margin keeping split tool envelopes
                    # atomic; (b) envelope markers reverting the round to
                    # buffered mode; (c) the bridge stripping leaked
                    # protocol tags on every text delta. Content of a
                    # final-answer round is unchanged — only timing moves.
                    # Known rare seam: a post-tool round that times out /
                    # redirects after streaming leaves its visible prefix
                    # in place, and the recovery answer repeats that
                    # content (the recovery prompt deliberately does not
                    # assume the user saw it).
                    if (
                        _completed_tool_count > 0
                        and not _round_text_stream_suppressed
                        and event.delta
                    ):
                        _joined_round = "".join(round_text_chunks)
                        _lowered_round = _joined_round.lower()
                        if any(
                            marker in _lowered_round
                            for marker in _NATIVE_TEXT_STREAM_SUPPRESS_MARKERS
                        ):
                            _round_text_stream_suppressed = True
                        else:
                            _safe_upto = max(
                                _round_text_streamed,
                                len(_joined_round) - _NATIVE_TEXT_STREAM_TAIL_MARGIN,
                            )
                            if _safe_upto > _round_text_streamed:
                                yield (
                                    "text",
                                    _joined_round[_round_text_streamed:_safe_upto],
                                    None,
                                )
                                _round_text_streamed = _safe_upto
                elif etype == "thinking_delta":
                    # Thinking shouldn't fire here (tools+thinking
                    # are incompatible) but if a provider somehow
                    # emits it, pass through so the UI stays sane.
                    accumulated_reasoning += event.delta
                    yield ("reasoning", event.delta, None)
                elif etype == "tool_use":
                    if event.tool_call is not None:
                        round_tool_calls.append(event.tool_call)
                        if _round_text_streamed > 0 and not _round_commentary_emitted:
                            # The pre-tool prose already streamed live as
                            # visible text (Kimi-style interleaved
                            # prose → tools → answer timeline); emitting
                            # the condensed checkpoint on top would
                            # duplicate it.
                            _round_commentary_emitted = True
                            _last_public_checkpoint_at = time.monotonic()
                        if not _round_commentary_emitted:
                            checkpoint = _native_public_checkpoint(
                                "".join(round_text_chunks),
                            )
                            if checkpoint:
                                yield ("commentary", checkpoint, None)
                                _round_commentary_emitted = True
                                _last_public_checkpoint_at = time.monotonic()
                elif etype == "done":
                    # Pull this round's token counts from the
                    # ModelResponse (every router populates these via
                    # the provider's usage object · falls back to 0
                    # silently for routers that don't track).
                    fin = getattr(event, "final", None)
                    if fin is not None:
                        response_model = str(getattr(fin, "model", "") or "").strip()
                        if response_model and response_model != effective_model:
                            # A dispatch-level provider rescue may transparently
                            # serve this round from another model. Stick to the
                            # healthy model for subsequent tool-result rounds;
                            # retrying the unavailable provider every round can
                            # corrupt cross-provider tool continuation state.
                            effective_model = response_model
                            _attempted_models.add(response_model)
                        _total_in_tokens += int(getattr(fin, "input_tokens", 0) or 0)
                        _total_out_tokens += int(getattr(fin, "output_tokens", 0) or 0)
                    break
        except Exception as exc:  # noqa: BLE001 — classify before re-raising
            _rescue_is_unavailable, _rescue_fallback = _rescue_policy_names()
            if (
                not _round_stream_event_seen
                and _provider_failovers < 2
                and _rescue_is_unavailable(exc)
            ):
                fallback_model = _rescue_fallback(
                    effective_model,
                    _attempted_models,
                )
                if fallback_model:
                    _logger.warning(
                        "agentic provider unavailable for %s; retrying with %s",
                        effective_model,
                        fallback_model,
                    )
                    effective_model = fallback_model
                    _attempted_models.add(fallback_model)
                    _provider_failovers += 1
                    continue
            if not isinstance(exc, (ConnectionError, TimeoutError, OSError)):
                raise
            _logger.warning("agentic round %d stream failed: %s", round_i, exc)
            break

        round_text = "".join(round_text_chunks)
        if _round_redirected and not round_tool_calls:
            if round_text.strip():
                messages.append(Message(role="assistant", content=round_text))
            _append_pending_steering()
            continue
        if _round_timed_out and not round_tool_calls:
            _model_timeout_recoveries += 1
            if _model_timeout_recoveries >= 2:
                stall_message = (
                    "模型连续两次未能在单轮时限内给出可用的下一步或最终答案。"
                    "已经完成的工具结果仍保留在过程记录中，但这次无法可靠完成汇总；"
                    "可以点击继续，从现有进度重新收敛。"
                )
                yield (
                    "error",
                    {"kind": "model_stall", "message": stall_message},
                    None,
                )
                return
            partial_round_text = round_text.strip()
            if partial_round_text:
                # The timed-out provider may already have produced a useful
                # prefix. It was not emitted publicly by this native path, so
                # preserve it as assistant context for the tools-disabled
                # recovery instead of making the model start over blind.
                messages.append(
                    Message(
                        role="assistant",
                        content=partial_round_text,
                    )
                )
            if _completed_tool_count > 0 and _stall_failovers < 1:
                _, _rescue_fallback = _rescue_policy_names()
                fallback_model = _rescue_fallback(
                    effective_model,
                    _attempted_models,
                )
                if fallback_model:
                    _logger.warning(
                        "agentic model %s stayed silent after evidence; "
                        "switching final synthesis to %s",
                        effective_model,
                        fallback_model,
                    )
                    effective_model = fallback_model
                    _attempted_models.add(fallback_model)
                    _stall_failovers += 1
                    _model_timeout_recoveries = 0
            recovery_update = (
                "这一轮响应超过单轮时限；已保留前面的有效结果，"
                "现在会减少额外操作，直接收拢阶段结论或最终答案。"
            )
            yield ("commentary_runtime", recovery_update, None)
            messages.append(
                Message(
                    role="user",
                    content=(
                        "[SYSTEM CHECK - model round timeout]\n"
                        "The previous native-tool model stream exceeded its "
                        "wall-clock deadline without a usable tool call or final "
                        "answer. Preserve every completed tool result. Do not call "
                        "more tools and do not deliberate at length. Return one "
                        "complete final answer for the user, incorporating any "
                        "partial assistant draft immediately above without assuming "
                        "the user has seen it and without merely continuing mid-sentence. "
                        "Use only the evidence already present; "
                        "if evidence is insufficient, name the exact gap truthfully."
                    ),
                )
            )
            _force_convergence_next = True
            continue
        if round_tool_calls:
            _model_timeout_recoveries = 0
        if not round_tool_calls and not _round_convergence_mode:
            round_tool_calls = _recover_named_xml_tool_calls(
                round_text,
                allowed_names={spec.name for spec in _active_tool_specs},
            )

        _duplicate_native_calls = 0
        _current_native_batch_fingerprint = ""
        _structured_public_checkpoint = ""
        if round_tool_calls:
            round_tool_calls, _structured_public_checkpoint = _native_calls_with_public_checkpoint(
                round_tool_calls
            )
            round_tool_calls, _duplicate_native_calls = _deduplicate_native_tool_calls(
                round_tool_calls
            )
            suppressed_targets = [
                target
                for call in round_tool_calls
                if (target := _native_definitive_failure_target(call))
                in _definitive_failed_native_targets
            ]
            if suppressed_targets:
                round_tool_calls = [
                    call
                    for call in round_tool_calls
                    if _native_definitive_failure_target(call)
                    not in _definitive_failed_native_targets
                ]
                _repeated_failure_guard_hits += 1
                messages.append(
                    Message(
                        role="user",
                        content=(
                            "[SYSTEM CHECK - definitive missing target suppressed]\n"
                            "The runtime did not repeat a read against a path already "
                            "confirmed missing. Pagination or range changes cannot make "
                            "that target exist. Correct the path, inspect its parent "
                            "directory, use a different source, or finish from existing "
                            "evidence. Do not request the same missing target again."
                        ),
                    )
                )
                if not round_tool_calls:
                    if _repeated_failure_guard_hits >= 2:
                        _force_convergence_next = True
                    continue
            repeated_successes = [
                _native_tool_call_fingerprint(call)
                for call in round_tool_calls
                if _native_tool_call_fingerprint(call) in _successful_native_read_calls
            ]
            if repeated_successes:
                round_tool_calls = [
                    call
                    for call in round_tool_calls
                    if _native_tool_call_fingerprint(call) not in _successful_native_read_calls
                ]
                _repeated_failure_guard_hits += 1
                messages.append(
                    Message(
                        role="user",
                        content=(
                            "[SYSTEM CHECK - redundant successful read suppressed]\n"
                            "The identical read/search/list call already succeeded in this "
                            "turn. Reuse its existing result instead of executing it again. "
                            "Choose a genuinely new evidence source only if the user's "
                            "request still has a specific unmet gap; otherwise finalize now."
                        ),
                    )
                )
                if not round_tool_calls:
                    _force_convergence_next = True
                    continue
            _current_native_batch_fingerprint = _native_tool_batch_fingerprint(round_tool_calls)
            failed_count, definitive_failure = _failed_native_batches.get(
                _current_native_batch_fingerprint,
                (0, False),
            )
            retry_limit = 1 if definitive_failure else 2
            if failed_count >= retry_limit:
                _repeated_failure_guard_hits += 1
                messages.append(
                    Message(
                        role="user",
                        content=(
                            "[SYSTEM CHECK - repeated failed tool call suppressed]\n"
                            "The runtime did not execute the identical tool call or ordered "
                            "batch again because the same arguments already produced a "
                            "definitive failure. Treat that result as evidence. Correct the "
                            "path or arguments, choose a different evidence source, or finish "
                            "from the evidence already collected. Do not repeat the same call."
                        ),
                    )
                )
                if _repeated_failure_guard_hits >= 2:
                    _force_convergence_next = True
                continue

        _prior_result_handoff = bool(round_tool_calls and _result_handoff_ready)
        if _prior_result_handoff:
            # The previous result already supplied the fact and the immediate
            # next scope, so another pre-tool paraphrase would be duplicate UI.
            _round_commentary_emitted = True
        if round_tool_calls and not _round_commentary_emitted:
            if _round_text_streamed > 0:
                # The provider sent tool_use ahead of this round's text,
                # so the tool_use-boundary dedup above never fired — but
                # the prose did stream live afterwards. Condensing it
                # again here would republish already-visible text (the
                # duplicate "Update: …"/checkpoint pair seen in live
                # acceptance). A structured public_update attached to the
                # call itself is independent of the round prose and still
                # goes out.
                checkpoint = _structured_public_checkpoint
                if not checkpoint:
                    _round_commentary_emitted = True
                    _last_public_checkpoint_at = time.monotonic()
            else:
                checkpoint = _structured_public_checkpoint or _native_public_checkpoint(round_text)
            if checkpoint:
                yield ("commentary", checkpoint, None)
                _round_commentary_emitted = True
                _last_public_checkpoint_at = time.monotonic()

        _action_narration_pool: ThreadPoolExecutor | None = None
        _action_narration_future: Any = None
        if (
            round_tool_calls
            and not _round_commentary_emitted
            and not _round_redirected
            and (_realtime_public_narrative or _ordered_read_handoffs)
            and any(
                call.name not in {"todo_write", "write_todos", "exit_plan_mode"}
                for call in round_tool_calls
            )
            and (
                _completed_tool_count == 0
                or time.monotonic() - _last_public_checkpoint_at >= _public_narrative_interval
            )
        ):
            _action_narration_pool = ThreadPoolExecutor(
                max_workers=1,
                thread_name_prefix="tool-bridge-public-action",
            )
            _action_narration_future = _action_narration_pool.submit(
                contextvars.copy_context().run,
                _generate_native_action_checkpoint,
                router,
                model=effective_model,
                messages=messages,
                calls=round_tool_calls,
            )

        def _take_action_narration(*, wait_for_completion: bool = False) -> str:
            """Collect one in-flight action update without delaying tool start."""
            nonlocal _action_narration_future, _action_narration_pool
            nonlocal _last_public_checkpoint_at, _round_commentary_emitted
            nonlocal _total_in_tokens, _total_out_tokens
            future = _action_narration_future
            if future is None or (not wait_for_completion and not future.done()):
                return ""
            try:
                checkpoint, checkpoint_in_tokens, checkpoint_out_tokens = future.result()
                _total_in_tokens += checkpoint_in_tokens
                _total_out_tokens += checkpoint_out_tokens
            except Exception as exc:  # noqa: BLE001 — optional narration
                _logger.warning("public action narration failed: %s", exc)
                checkpoint = ""
            finally:
                if _action_narration_pool is not None:
                    _action_narration_pool.shutdown(wait=False, cancel_futures=True)
                _action_narration_future = None
                _action_narration_pool = None
            if checkpoint:
                _round_commentary_emitted = True
                _last_public_checkpoint_at = time.monotonic()
            return checkpoint

        if round_tool_calls:
            _result_handoff_ready = False

        # A quiet native provider must not make the conversation start with a
        # bare execution row.  Give the bounded model-authored repair a chance
        # to speak before execution; compliant providers already supplied the
        # structured checkpoint above and pay no extra call.
        checkpoint = _take_action_narration(wait_for_completion=True)
        if checkpoint:
            yield ("commentary", checkpoint, None)

        for call in round_tool_calls:
            yield (
                "tool_start",
                {
                    "id": call.id,
                    "name": call.name,
                    "input": call.input,
                    "iteration": round_i + 1,
                },
                None,
            )

        if not round_tool_calls:
            # Close the narrow race where the user steers while the model is
            # producing what would otherwise become its final answer. Treat
            # that text as an intermediate assistant message and give the
            # newly arrived user correction the next word.
            _capture_steering(force=True)
            if _pending_steering:
                if round_text.strip():
                    messages.append(Message(role="assistant", content=round_text))
                _append_pending_steering()
                continue
            _missing_browser_evidence = _browser_required_evidence - _browser_observed_evidence
            if (
                not _round_convergence_mode
                and _missing_browser_evidence
                and _browser_guard_nudges < 3
            ):
                _browser_guard_nudges += 1
                accumulated_text = ""
                messages.append(
                    Message(
                        role="user",
                        content=(
                            "[SYSTEM CHECK - browser task incomplete]\n"
                            "Do not finish yet. Continue through the browser UI. "
                            "The current trajectory still lacks successful action "
                            "evidence for: "
                            + ", ".join(sorted(_missing_browser_evidence))
                            + ". Use the persistent browser_* tools and verify the "
                            "resulting page state before answering."
                        ),
                    )
                )
                continue
            if not _round_convergence_mode and _code_change_task and not _code_mutation_seen:
                _code_no_action_stops += 1
                if _code_no_action_stops >= 2 and _quality_failovers < 2:
                    _, _rescue_fallback = _rescue_policy_names()
                    fallback_model = _rescue_fallback(
                        effective_model,
                        _attempted_models,
                    )
                    if fallback_model:
                        _logger.warning(
                            "code model %s stopped without acting; switching to %s",
                            effective_model,
                            fallback_model,
                        )
                        effective_model = fallback_model
                        _attempted_models.add(fallback_model)
                        _quality_failovers += 1
                        _code_no_action_stops = 0
                        _code_completion_nudges = 0
                        _todo_guard_nudges = 0
                        messages.append(
                            Message(
                                role="user",
                                content=(
                                    "[SYSTEM CHECK - execution model fallback]\n"
                                    "The previous model route stopped twice without "
                                    "making the requested code change. Continue the "
                                    "task now: inspect the scoped workspace, modify "
                                    "the implementation and regression tests, and "
                                    "run real verification before answering."
                                ),
                            )
                        )
                        continue
            if (
                not _round_convergence_mode
                and _code_change_task
                and _code_semantic_repair_required
                and _code_semantic_guard_nudges < 4
            ):
                _code_semantic_guard_nudges += 1
                accumulated_text = ""
                messages.append(
                    Message(
                        role="user",
                        content=(
                            "[SYSTEM CHECK - concurrency semantic repair required]\n"
                            + _code_semantic_repair_message
                            + " Do not finalize or rerun equivalent verification yet. "
                            "Inspect and repair the affected production implementation first."
                        ),
                    )
                )
                continue
            if not _round_convergence_mode and _todo_protocol_required and _has_todo_write:
                _todo_guard_message: str | None = None
                if not _todo_seen:
                    _todo_guard_message = (
                        "[SYSTEM CHECK - task checklist required]\n"
                        "This turn is multi-step or execution-heavy. Do not "
                        "give the final answer yet. Call `todo_write` now "
                        "with a complete checklist for the work, then "
                        "continue."
                    )
                elif _tool_work_since_todo:
                    _todo_guard_message = (
                        "[SYSTEM CHECK - checklist update required]\n"
                        "You used tools after the latest checklist update. "
                        "Before the final answer, call `todo_write` again "
                        "with the complete list and mark completed or "
                        "in-progress items accurately."
                    )
                if _todo_guard_message and _todo_guard_nudges < 2:
                    _todo_guard_nudges += 1
                    accumulated_text = ""
                    messages.append(
                        Message(
                            role="user",
                            content=_todo_guard_message,
                        )
                    )
                    continue
            if (
                not _round_convergence_mode
                and _code_change_task
                and (not _code_mutation_seen or _code_verification_state is not True)
                and _code_completion_nudges < 2
            ):
                _code_completion_nudges += 1
                if not _code_mutation_seen:
                    state = "No successful source or regression-test mutation was observed."
                elif _code_verification_state is False:
                    state = "The latest verification failed."
                else:
                    state = "The changed files have not been verified after the latest mutation."
                accumulated_text = ""
                messages.append(
                    Message(
                        role="user",
                        content=(
                            "[SYSTEM CHECK - implementation not verified]\n"
                            f"{state} Do not finalize or pause yet. Inspect the "
                            "current files, repair the implementation or regression "
                            "tests, then rerun a focused test/lint command. Only "
                            "finish after that command succeeds, or clearly report "
                            "a concrete external blocker that tools cannot resolve."
                        ),
                    )
                )
                continue
            # Model replied with pure text · conversation is done.
            if _completed_tool_count > 0:
                yield (
                    "commentary_runtime",
                    "证据已经收齐；我现在把关键信息收束成最终回答。",
                    None,
                )
            accumulated_text += round_text
            # Chunks up to ``_round_text_streamed`` already went out live
            # during the round — deliver only the held-back tail. Content
            # is identical to the old full dump; only timing changed.
            if _round_text_streamed < len(round_text):
                yield ("text", round_text[_round_text_streamed:], None)
            _final_duration = int((time.monotonic() - _started_at) * 1000)
            yield (
                "stats",
                {
                    "input_tokens": _total_in_tokens,
                    "output_tokens": _total_out_tokens,
                    "duration_ms": _final_duration,
                    "rounds": round_i + 1,
                },
                None,
            )
            # Per-turn quality score · zero-cost heuristic that
            # feeds the SOUL self-evolution feedback loop. See
            # ``runtime/memory/turn_scoring.py`` · best-effort,
            # never blocks the user reply.
            _record_score_safe(
                agent=agent,
                intent=intent,
                has_final_reply=bool(accumulated_text),
                tool_error_count=_tool_error_count,
                rounds_used=round_i + 1,
                duration_ms=_final_duration,
            )
            yield ("done", "", accumulated_text)
            return

        if _code_change_task:
            _code_no_action_stops = 0

        # Rebuild the turn in Anthropic's structured shape so the
        # next ``messages.stream()`` call is a valid continuation.
        # Required chain:
        #   assistant [text + tool_use blocks]
        #   user      [tool_result blocks, keyed by tool_use_id]
        #
        # Assistant text + tool_use re-materialization: reconstruct
        # from what we captured this round. Claude tolerates either
        # re-asserting the assistant turn or leaving it off when
        # the follow-up user message carries well-formed
        # ``tool_result`` blocks with matching ids. We include
        # the assistant turn for explicitness and to keep token
        # accounting sane (API bills input tokens on what WE
        # send; not resending the assistant text means we pay
        # less but the model loses its own context trail).
        assistant_blocks: list[dict[str, Any]] = []
        # Tool-round prose is intentionally not replayed. Providers that emit
        # XML calls put the envelope in text; preserving it would leak raw
        # protocol markup and can make the next round repeat the same call.
        for call in round_tool_calls:
            assistant_blocks.append(
                {
                    "type": "tool_use",
                    "id": call.id,
                    "name": call.name,
                    "input": call.input,
                }
            )
        if assistant_blocks:
            messages.append(
                Message(
                    role="assistant",
                    content=assistant_blocks,
                )
            )

        # Execute each tool, build matching tool_result blocks.
        # Concurrency policy (octopus optimisation lane B):
        # When enabled and the round has 2+ independent tool calls
        # (no serial-barrier tools mixed in), dispatch via
        # ThreadPoolExecutor and gather results in submission order.
        # Output ordering of tool_result blocks matches round_tool_calls
        # so the assistant ↔ tool_result pairing stays correct.
        tool_result_blocks: list[dict[str, Any]] = []
        _parallel_enabled = (
            PARALLEL_TOOL_USE_DEFAULT
            and len(round_tool_calls) >= 2
            and not any(c.name in _SERIAL_BARRIER_TOOLS for c in round_tool_calls)
            and not any(_tool_uses_session_scope(stack, c) for c in round_tool_calls)
            and bool(
                getattr(stack, "metadata", {}).get(
                    "parallel_tool_use",
                    True,
                )
            )
        )
        from runtime.safety.approval.cancellation import (  # noqa: PLC0415
            CancellationSource,
            CancellationToken,
            current_cancellation_token,
            scoped_cancellation,
        )

        _parent_cancellation = current_cancellation_token()
        _tool_batch_source = (
            CancellationSource()
            if _parent_cancellation is CancellationToken.none()
            else _parent_cancellation.link()
        )
        _tool_batch_redirected = _round_redirected
        _redirected_tool_ids: set[str] = set()
        if _tool_batch_redirected:
            _redirected_tool_ids.update(call.id for call in round_tool_calls)
            _tool_batch_source.cancel(reason="user redirected before tool execution")

        if _parallel_enabled:
            # Each call must see the same parent-tool-use-id
            # context as the serial path; we set/clear once around
            # the whole batch (per-call propagation isn't needed
            # because the contextvar is read at handler-call time
            # not at gather-time).
            # Read tracking lives in shared Session metadata. Initialise the
            # list before workers start so simultaneous first reads cannot
            # each install a different list and lose another worker's proof.
            _session_obj.metadata.setdefault("_read_file_paths_this_turn", [])
            _outputs: dict[str, tuple[str, bool]] = {}

            def _run_one(
                call: ToolCall,
                tool_batch_source: Any = _tool_batch_source,
            ) -> tuple[str, tuple[str, bool]]:
                # ContextVars do not propagate into ThreadPoolExecutor
                # workers.  Bind the parent Session explicitly; otherwise
                # scope-aware skills resolve relative paths against the
                # server process CWD and writes lose their workspace guard.
                # ``_active_parent_tool_use_id`` carries the id of the
                # CURRENT call so any nested call_agent reports its parent.
                from runtime.platform.process.session import _current_session

                _call_session_token = _current_session.set(_session_obj)
                _session_obj.metadata["_active_parent_tool_use_id"] = call.id
                try:
                    with scoped_cancellation(tool_batch_source.token):
                        if tool_batch_source.is_cancelled:
                            out, err = (
                                f"(cancelled before execution: {tool_batch_source.token.reason})",
                                True,
                            )
                        else:
                            out, err = _execute_tool_call(stack, call)
                finally:
                    _current_session.reset(_call_session_token)
                return call.id, (out, err)

            if _tool_batch_redirected:
                _outputs.update(
                    {
                        call.id: (
                            "(cancelled before execution: user redirected active work)",
                            True,
                        )
                        for call in round_tool_calls
                    }
                )
            else:
                with ThreadPoolExecutor(
                    max_workers=min(
                        PARALLEL_TOOL_USE_MAX_WORKERS,
                        len(round_tool_calls),
                    ),
                    thread_name_prefix="tool-bridge-parallel",
                ) as pool:
                    future_calls = {
                        pool.submit(
                            contextvars.copy_context().run,
                            _run_one,
                            call,
                        ): call
                        for call in round_tool_calls
                    }
                    pending = set(future_calls)
                    while pending:
                        done, pending = wait(
                            pending,
                            timeout=0.1,
                            return_when=FIRST_COMPLETED,
                        )
                        for future in done:
                            call = future_calls[future]
                            try:
                                cid, (out, err) = future.result()
                            except Exception as exc:  # noqa: BLE001 — surface as tool failure
                                cid, out, err = call.id, f"(parallel exec error: {exc})", True
                                _logger.warning(
                                    "parallel tool exec future failed: %s",
                                    exc,
                                )
                            _outputs[cid] = (out, err)
                        if pending and _capture_steering():
                            _tool_batch_redirected = True
                            _redirected_tool_ids.update(
                                future_calls[future].id for future in pending
                            )
                            _tool_batch_source.cancel(reason="user redirected active tool batch")

                        checkpoint = _take_action_narration()
                        if checkpoint:
                            yield ("commentary", checkpoint, None)

            checkpoint = _take_action_narration(wait_for_completion=True)
            if checkpoint:
                yield ("commentary", checkpoint, None)

            # Cleanup the contextvar marker the parent set.
            _session_obj.metadata.pop("_active_parent_tool_use_id", None)

            # Emit tool_end events + build tool_result blocks IN
            # round_tool_calls order so the model sees a stable
            # narrative even though execution was parallel.
            for call in round_tool_calls:
                if call.name == "todo_write":
                    _todo_seen = True
                    _tool_work_since_todo = False
                else:
                    _tool_work_since_todo = True
                output, is_error = _outputs.get(
                    call.id,
                    ("(no result)", True),
                )
                if call.id in _redirected_tool_ids:
                    is_error = True
                _observe_code_tool_result(call, is_error, output, round_i + 1)
                if not is_error:
                    _browser_observed_evidence.update(_browser_action_evidence(call))
                yield (
                    "tool_end",
                    {
                        "id": call.id,
                        "name": call.name,
                        "output": output[:200],
                        "is_error": is_error,
                        **({"status": "cancelled"} if call.id in _redirected_tool_ids else {}),
                        "iteration": round_i + 1,
                        "parallel": True,
                    },
                    None,
                )
                block: dict[str, Any] = {
                    "type": "tool_result",
                    "tool_use_id": call.id,
                    "content": output,
                }
                if is_error:
                    block["is_error"] = True
                    _tool_error_count += 1
                tool_result_blocks.append(block)
        else:
            # Serial fallback — original behaviour. Triggers when:
            #   - only 1 tool this round (nothing to parallelise)
            #   - todo_write / exit_plan_mode / soul ops in the round
            #   - PARALLEL_TOOL_USE_DEFAULT=False
            #   - stack.metadata['parallel_tool_use']=False
            def _run_serial_one(
                call: ToolCall,
                tool_batch_source: Any = _tool_batch_source,
            ) -> tuple[str, bool]:
                _call_session_token = _current_session.set(_session_obj)
                _session_obj.metadata["_active_parent_tool_use_id"] = call.id
                try:
                    with scoped_cancellation(tool_batch_source.token):
                        if tool_batch_source.is_cancelled:
                            return (
                                f"(cancelled before execution: {tool_batch_source.token.reason})",
                                True,
                            )
                        return _execute_tool_call(stack, call)
                finally:
                    _session_obj.metadata.pop(
                        "_active_parent_tool_use_id",
                        None,
                    )
                    _current_session.reset(_call_session_token)

            # Only realtime turns need the worker hop: it leaves this
            # generator free to poll steering while a synchronous handler is
            # running. Batch/CLI callers without steering keep the zero-cost
            # direct path.
            serial_pool = (
                ThreadPoolExecutor(max_workers=1, thread_name_prefix="tool-bridge-steerable")
                if (steering_drain is not None or _action_narration_future is not None)
                and not _tool_batch_redirected
                else None
            )
            try:
                for call_index, call in enumerate(round_tool_calls):
                    if call.name == "todo_write":
                        _todo_seen = True
                        _tool_work_since_todo = False
                    else:
                        _tool_work_since_todo = True
                    if _tool_batch_redirected:
                        output, is_error = (
                            "(cancelled before execution: user redirected active work)",
                            True,
                        )
                    elif serial_pool is None:
                        output, is_error = _run_serial_one(call)
                    else:
                        future = serial_pool.submit(
                            contextvars.copy_context().run,  # type: ignore[arg-type]
                            _run_serial_one,
                            call,
                        )
                        while not future.done():
                            wait((future,), timeout=0.1)
                            checkpoint = _take_action_narration()
                            if checkpoint:
                                yield ("commentary", checkpoint, None)
                            if not future.done() and _capture_steering():
                                _tool_batch_redirected = True
                                _redirected_tool_ids.update(
                                    pending_call.id
                                    for pending_call in round_tool_calls[call_index:]
                                )
                                _tool_batch_source.cancel(
                                    reason="user redirected active tool batch"
                                )
                        try:
                            output, is_error = future.result()  # type: ignore[assignment]
                        except Exception as exc:  # noqa: BLE001 — surface as tool failure
                            output, is_error = f"(serial exec error: {exc})", True
                            _logger.warning("serial tool exec future failed: %s", exc)
                    checkpoint = _take_action_narration(wait_for_completion=True)
                    if checkpoint:
                        yield ("commentary", checkpoint, None)
                    if call.id in _redirected_tool_ids:
                        is_error = True
                    _observe_code_tool_result(call, is_error, output, round_i + 1)
                    if not is_error:
                        _browser_observed_evidence.update(_browser_action_evidence(call))
                    yield (
                        "tool_end",
                        {
                            "id": call.id,
                            "name": call.name,
                            "output": output[:200],
                            "is_error": is_error,
                            **({"status": "cancelled"} if call.id in _redirected_tool_ids else {}),
                            "iteration": round_i + 1,
                        },
                        None,
                    )
                    block = {
                        "type": "tool_result",
                        "tool_use_id": call.id,
                        "content": output,
                    }
                    if is_error:
                        block["is_error"] = True
                        _tool_error_count += 1
                    tool_result_blocks.append(block)
            finally:
                if serial_pool is not None:
                    serial_pool.shutdown(wait=True, cancel_futures=True)

        _tool_batch_source.cancel(reason="tool batch closed")
        _completed_tool_count += len(round_tool_calls)

        if _current_native_batch_fingerprint:
            batch_failed = bool(tool_result_blocks) and all(
                bool(block.get("is_error")) for block in tool_result_blocks
            )
            if batch_failed:
                previous_count, previous_definitive = _failed_native_batches.get(
                    _current_native_batch_fingerprint,
                    (0, False),
                )
                _failed_native_batches[_current_native_batch_fingerprint] = (
                    previous_count + 1,
                    previous_definitive
                    or _native_failure_is_definitive(
                        round_tool_calls,
                        tool_result_blocks,
                    ),
                )
                for call, block in zip(
                    round_tool_calls,
                    tool_result_blocks,
                    strict=True,
                ):
                    if _native_call_failure_is_definitive(call, block):
                        target = _native_definitive_failure_target(call)
                        if target:
                            _definitive_failed_native_targets.add(target)
            else:
                _failed_native_batches.pop(_current_native_batch_fingerprint, None)
                _repeated_failure_guard_hits = 0
                repeatable_read_names = {
                    "read_file",
                    "read_text_file",
                    "list_cwd",
                    "glob_files",
                    "grep_text",
                }
                for call, block in zip(
                    round_tool_calls,
                    tool_result_blocks,
                    strict=True,
                ):
                    if call.name in repeatable_read_names and not block.get("is_error"):
                        _successful_native_read_calls.add(_native_tool_call_fingerprint(call))

        messages.append(
            Message(
                role="user",
                content=tool_result_blocks,
            )
        )
        _plan_milestones = _native_plan_reconciliation_milestones(
            round_tool_calls,
            tool_result_blocks,
        )
        if _todo_protocol_required and _has_todo_write and _plan_milestones:
            messages.append(
                Message(
                    role="user",
                    content=(
                        "[SYSTEM CHECK - dynamic plan reconciliation checkpoint]\n"
                        f"Completed milestone: {', '.join(_plan_milestones)}. "
                        "Finish the current write/repair/verification chain, then before "
                        "switching to a different phase call `todo_write` with the complete "
                        "revised checklist. Mark only evidence-backed items complete; preserve "
                        "stable IDs for unchanged work; add, remove, reword, or reorder items "
                        "when the discovered code or documentation changed the scope."
                    ),
                )
            )
        if _tool_batch_redirected:
            _append_pending_steering()
            continue

        meaningful_batch = any(
            call.name not in {"todo_write", "write_todos", "exit_plan_mode"}
            for call in round_tool_calls
        )
        result_handoff_required = bool(
            _ordered_read_handoffs
            and meaningful_batch
            and any(
                call.name in {"read_file", "read_text_file", "read_file_range"}
                for call in round_tool_calls
            )
        )
        _result_commentary_emitted = False
        if (
            (not _round_commentary_emitted or result_handoff_required)
            and (_realtime_public_narrative or _ordered_read_handoffs)
            and meaningful_batch
            and (
                result_handoff_required
                or time.monotonic() - _last_public_checkpoint_at >= _public_narrative_interval
            )
        ):
            try:
                checkpoint, checkpoint_in_tokens, checkpoint_out_tokens = (
                    _generate_native_evidence_checkpoint(
                        router,
                        model=effective_model,
                        messages=messages,
                    )
                )
                _total_in_tokens += checkpoint_in_tokens
                _total_out_tokens += checkpoint_out_tokens
            except Exception as exc:  # noqa: BLE001 — optional narration
                _logger.warning("public progress synthesis failed: %s", exc)
                checkpoint = ""
            if checkpoint:
                yield ("commentary", checkpoint, None)
                _round_commentary_emitted = True
                _result_commentary_emitted = True
                if result_handoff_required:
                    _result_handoff_ready = True
                _last_public_checkpoint_at = time.monotonic()

        if not _round_commentary_emitted or (
            result_handoff_required and not _result_commentary_emitted
        ):
            checkpoint = _native_result_checkpoint(
                round_tool_calls,
                tool_result_blocks,
                goal=intent.normalized_goal,
            )
            if checkpoint:
                # Evidence-derived fallback remains useful to non-realtime
                # consumers, but it is runtime prose and must never be
                # presented as if the model said it.
                yield ("commentary_runtime", checkpoint, None)
                _round_commentary_emitted = True
                if result_handoff_required:
                    _result_handoff_ready = True

        if _pending_code_semantic_nudge:
            messages.append(
                Message(
                    role="user",
                    content=(
                        "[SYSTEM CHECK - concurrency semantic repair required]\n"
                        + _pending_code_semantic_nudge
                        + " Repair the production implementation before running more "
                        "verification or attempting the final answer."
                    ),
                )
            )
            _pending_code_semantic_nudge = ""

        if _green_verification_convergence_active and not _code_semantic_repair_required:
            _todo_completed_this_round = any(call.name == "todo_write" for call in round_tool_calls)
            if _green_convergence_todo_only and _todo_completed_this_round:
                _green_convergence_todo_only = False
                _force_convergence_next = True
                messages.append(
                    Message(
                        role="user",
                        content=(
                            "[SYSTEM CHECK - green verification convergence]\n"
                            "The final checklist update is recorded. Do not call or "
                            "request any more tools. Produce the concise final answer "
                            "from the completed implementation and verification evidence."
                        ),
                    )
                )
            elif not _green_convergence_todo_only:
                if _todo_protocol_required and _has_todo_write and _tool_work_since_todo:
                    _green_convergence_todo_only = True
                    messages.append(
                        Message(
                            role="user",
                            content=(
                                "[SYSTEM CHECK - green verification convergence]\n"
                                "Two independent clean verifier calls succeeded after "
                                "the latest code mutation. Terminal evidence is complete. "
                                "Do not run another test, lint, shell, read, or environment "
                                "probe. Call `todo_write` once now to record the final "
                                "checklist state; that is the only remaining tool action."
                            ),
                        )
                    )
                else:
                    _force_convergence_next = True
                    messages.append(
                        Message(
                            role="user",
                            content=(
                                "[SYSTEM CHECK - green verification convergence]\n"
                                "Two independent clean verifier calls succeeded after "
                                "the latest code mutation. Do not call or request any "
                                "more tools. Produce the concise final answer now."
                            ),
                        )
                    )

        if round_i + 1 >= _tool_round_budget and _tool_round_budget < max_tool_rounds:
            yield (
                "commentary_runtime",
                "已达到本轮证据收集预算；现在停止扩展检索，直接用现有结果完成回答。",
                None,
            )
            messages.append(
                Message(
                    role="user",
                    content=(
                        "[SYSTEM CHECK - evidence budget reached]\n"
                        f"The task used its {_tool_round_budget} tool rounds. "
                        "Do not call, request, or describe any more tools. "
                        "Using only the completed observations above, produce "
                        "the best complete final answer now. Be concise and "
                        "truthful about any remaining evidence gap."
                    ),
                )
            )
            _force_convergence_next = True

    # Exceeded max rounds. Pause instead of pretending the turn is
    # complete: ask the user whether to spend another work budget or
    # synthesize a report from the evidence already collected. The
    # no-tool checkpoint call lets the model summarize the current
    # evidence while preventing another unbounded tool loop.
    checkpoint_chunks: list[str] = []
    messages.append(
        Message(
            role="user",
            content=(
                "[SYSTEM CHECK - user decision required]\n"
                f"The tool loop reached its {max_tool_rounds}-round limit. "
                "Do not call more tools. Do not write the final report yet. "
                "Using only the observations and tool results above, write a "
                "concise checkpoint for the user:\n"
                "1. What has been completed.\n"
                "2. The key findings or evidence collected so far.\n"
                "3. What remains uncertain or worth checking next.\n"
                "4. Ask the user to choose: reply `继续` to spend another "
                "work budget, or reply `生成报告` / `就此生成报告` to "
                "synthesize the final report from the current evidence."
            ),
        )
    )
    checkpoint_req = ModelRequest(
        model=effective_model,
        messages=messages,
        max_tokens=4096,
        temperature=0.7,
        tools=[],
    )
    checkpoint_visible = {"started": False}
    try:
        for event in _iter_native_model_stream_with_deadline(
            router,
            checkpoint_req,
            _native_model_round_timeout_s(),
            visible_started=lambda state=checkpoint_visible: state["started"],
        ):
            if event is _NATIVE_STREAM_DEADLINE:
                _logger.warning(
                    "agentic checkpoint synthesis exceeded %.1fs",
                    _native_model_round_timeout_s(),
                )
                break
            etype = event.type
            if etype == "text_delta":
                checkpoint_chunks.append(event.delta)
                checkpoint_visible["started"] = True
                yield ("text", event.delta, None)
            elif etype == "thinking_delta":
                accumulated_reasoning += event.delta
                yield ("reasoning", event.delta, None)
            elif etype == "done":
                fin = getattr(event, "final", None)
                if fin is not None:
                    _total_in_tokens += int(getattr(fin, "input_tokens", 0) or 0)
                    _total_out_tokens += int(getattr(fin, "output_tokens", 0) or 0)
                    if not checkpoint_chunks:
                        checkpoint_text = getattr(fin, "text", "") or ""
                        if checkpoint_text:
                            checkpoint_chunks.append(checkpoint_text)
                            yield ("text", checkpoint_text, None)
                break
    except (ConnectionError, TimeoutError, OSError) as exc:
        _logger.warning("agentic checkpoint synthesis failed: %s", exc)

    checkpoint_text = "".join(checkpoint_chunks).strip()
    final_text = checkpoint_text or (
        "已达到本轮工具调用上限。回复 `继续` 我会继续搜索/执行；"
        "回复 `生成报告` 我会基于目前已收集的信息整理最终报告。"
    )

    _final_duration = int((time.monotonic() - _started_at) * 1000)
    yield (
        "stats",
        {
            "input_tokens": _total_in_tokens,
            "output_tokens": _total_out_tokens,
            "duration_ms": _final_duration,
            "rounds": max_tool_rounds,
        },
        None,
    )
    # Per-turn quality score · this exit means we hit the round
    # cap without a clean final reply, so it'll be scored low
    # ("round_cap" reason).
    _record_score_safe(
        agent=agent,
        intent=intent,
        has_final_reply=bool(checkpoint_text),
        tool_error_count=_tool_error_count,
        rounds_used=max_tool_rounds,
        duration_ms=_final_duration,
    )
    yield ("done", "", final_text)
