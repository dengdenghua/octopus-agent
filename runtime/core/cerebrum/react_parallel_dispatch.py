"""Concurrent multi-action dispatcher for the ReAct loop (口子 2).

Moved from ``react_loop.py``: ``_dispatch_parallel_actions`` executes a
multi-action block — threaded when safe, force-serial when any action
is a write tool / unregistered / risky-or-untrusted — while emitting the
same ``tool_start`` / ``tool_end`` event pairs the single-action path
yields, and fencing untrusted tool output against prompt injection.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Generator
from typing import Any

from runtime.core.cerebrum.react_execution import (
    _beak_step_effective_success,
    _execute_action_via_beak,
    _tool_event_extras_from_beak_step,
)
from runtime.core.cerebrum.react_parsing import _parse_action, _summarize_observation
from runtime.execution.tool_engine import (
    normalize_tool_lifecycle_event,
    tool_lifecycle_event_to_react_event,
)
from runtime.platform.models import ParsedIntent
from runtime.safety.validation.prompt_injection import (
    is_untrusted_tool,
    mark_injection_taint,
    scan_for_injection,
    wrap_untrusted_observation,
)

_logger = logging.getLogger(__name__)

# Tools that mutate the workspace. When a multi-action block contains
# any of these we force serial dispatch — concurrent file writes can
# clobber each other and the auto-diagnostics path expects a single
# resolved_name.
_WRITE_TOOLS: frozenset[str] = frozenset(
    {
        "write_text_file",
        "edit_file",
        "multi_edit_file",
        "edit_text_file",
        "edit_code",
        "str_replace",
        "write_file",
        "create_file",
    }
)

# Default cap on parallel actions. Beyond this we still execute every
# call but slice them into pool-sized batches; protects against a
# model hallucinating 30 read_files at once.
_MAX_PARALLEL_ACTIONS = 4


def _dispatch_parallel_actions(
    actions: list[str],
    *,
    stack: Any,
    executor: Any,
    iteration: int,
    react_task_id: Any,
    agent: Any,
    intent: ParsedIntent,
) -> Generator[Any, None, tuple[str, list[dict[str, object]]]]:
    """Concurrent multi-action dispatcher (口子 2).

    Generator helper invoked via ``yield from`` from the main loop.
    Yields the same ``tool_start`` / ``tool_end`` events the legacy
    single-action path emits, one pair per action, with unique
    ``call_id`` per call. Returns ``(merged_observation, results)``
    via StopIteration.value.

    Force-serial fallbacks (executes via the same path but sequenced
    rather than threaded):
      * Any action targets a known write tool.
      * Any action's parsed name is unregistered (so we surface a
        "tool not found" observation immediately rather than after
        partial work has run).
    """
    import concurrent.futures as _cf

    # ReAct multi-actions use a ThreadPoolExecutor for independent reads.
    # ContextVars do not cross that boundary, so capture the concrete Session
    # now and rebind it inside every worker. Without this, list_cwd may resolve
    # against the selected workspace while adjacent read_file calls resolve
    # against the server repository, producing the deceptive "listed but not
    # found" failure seen in production behavioral runs.
    from runtime.platform.process.session import current_session

    parent_session = current_session()
    if parent_session is not None:
        parent_session.metadata.setdefault("_read_file_paths_this_turn", [])

    parsed_pairs: list[tuple[str, dict[str, Any]] | None] = [_parse_action(a) for a in actions]
    from runtime.safety.approval.approval_gate import assess_approval_risk

    resolved_names: list[str | None] = []
    has_unregistered = False
    has_write_tool = False
    # Risky/untrusted tools must run serially (inline, in this thread) so
    # the injection-taint contextvar the executor reads/writes is visible —
    # the parallel thread-pool path doesn't propagate it. Running them
    # inline also lets an untrusted tool's taint apply to a later risky tool
    # in the same batch via the executor's chokepoint block.
    has_risky_or_untrusted = False
    # Per-action flag: does this tool's OUTPUT taint the turn (untrusted
    # source)? Used to order the serial batch so untrusted tools run before
    # risky ones (see below).
    untrusted_flags: list[bool] = []
    # Per-action capability-disabled info: when a tool is recognized by the
    # catalog but its group is excluded by ``enable_web_skills=False``, we
    # populate this dict so (a) the model gets an actionable observation
    # explaining *why* the tool is unavailable and (b) the ``tool_end``
    # event carries the info for the UI to render a one-click enable prompt.
    disabled_infos: list[dict[str, str] | None] = []
    try:
        from runtime.execution.all_skills import is_known_but_disabled_tool
    except ImportError:  # pragma: no cover — defensive
        is_known_but_disabled_tool = lambda _n: (False, None)  # noqa: E731
    for p in parsed_pairs:
        if p is None:
            resolved_names.append(None)
            untrusted_flags.append(False)
            disabled_infos.append(None)
            has_unregistered = True
            continue
        name = p[0]
        registry = getattr(executor, "registry", None)
        if registry is None or not registry.has(name):
            resolved_names.append(None)
            untrusted_flags.append(False)
            has_unregistered = True
            # Distinguish "known but config-disabled" from "completely unknown"
            # so the model and UI get actionable context instead of a generic
            # "unregistered" message that invites 7 retries.
            _hit, _group = is_known_but_disabled_tool(name)
            disabled_infos.append(
                {"group": _group, "config_flag": "enable_web_skills"}
                if _hit and _group
                else None
            )
        else:
            resolved_names.append(name)
            disabled_infos.append(None)
            try:
                _aff = registry.get(name).affinity
            except (KeyError, AttributeError):
                _aff = None
            _is_untrusted = is_untrusted_tool(name, _aff)
            untrusted_flags.append(_is_untrusted)
            if name in _WRITE_TOOLS:
                has_write_tool = True
            if assess_approval_risk(name).level in {"medium", "high", "critical"} or _is_untrusted:
                has_risky_or_untrusted = True

    # Pre-allocate per-action call_ids so tool_start/tool_end can be
    # paired even if work runs out-of-order.
    call_ids = [uuid.uuid4().hex[:12] for _ in actions]
    started_at = [time.monotonic() for _ in actions]

    # Emit tool_start for every action up-front so the UI shows them
    # in parallel even if we end up running serially below.
    for idx in range(len(actions)):
        name = resolved_names[idx] or (parsed_pairs[idx][0] if parsed_pairs[idx] else "unknown")
        _input_preview = parsed_pairs[idx][1] if parsed_pairs[idx] else None
        yield tool_lifecycle_event_to_react_event(
            normalize_tool_lifecycle_event(
                "tool_start",
                {
                    "tool_name": name,
                    "tool_call_id": call_ids[idx],
                    "iteration": iteration,
                    "input_preview": _input_preview,
                    "parallel_batch_size": len(actions),
                },
                origin="react_compat",
            )
        )

    serial = has_write_tool or has_unregistered or has_risky_or_untrusted

    def _run_one(idx: int) -> tuple[str | None, Any]:
        # Skip dispatch for unregistered tools — the single-action
        # path's "(tool not registered)" message is reproduced here
        # so the model gets a uniform observation. When the tool is
        # recognized as config-disabled (e.g. web_search under
        # enable_web_skills=False), augment the message with the reason
        # and the remediation path so the model stops retrying and can
        # inform the user.
        if resolved_names[idx] is None:
            _di = disabled_infos[idx]
            if _di is not None:
                _tool_name = parsed_pairs[idx][0] if parsed_pairs[idx] else "unknown"
                return (
                    f"(工具未注册) {_tool_name} 所属组 '{_di['group']}' 被配置关闭"
                    f"({_di['config_flag']}=false)。如需启用:在 config.local.yaml "
                    f"设置 {_di['config_flag']}: true 并重启后端,或调用 "
                    f"POST /api/capabilities/enable 临时启用。当前请改用其他工具"
                    f"或告知用户该能力不可用。",
                    None,
                )
            return (
                f"(工具未注册或无法解析) action: {actions[idx][:200]}",
                None,
            )
        if parent_session is None:
            return _execute_action_via_beak(
                stack,
                actions[idx],
                react_task_id=react_task_id,
                react_step_counter=iteration,
                agent=agent,
                intent=intent,
            )
        from runtime.platform.process.session import _current_session

        session_token = _current_session.set(parent_session)
        try:
            return _execute_action_via_beak(
                stack,
                actions[idx],
                react_task_id=react_task_id,
                react_step_counter=iteration,
                agent=agent,
                intent=intent,
            )
        finally:
            _current_session.reset(session_token)

    observations: list[str | None] = [None] * len(actions)
    beak_steps: list[Any] = [None] * len(actions)
    if serial or len(actions) <= 1:
        # Run untrusted-output tools FIRST. The serial path exists so an
        # untrusted tool's injection taint reaches a later risky tool's
        # executor chokepoint — but in DECLARATION order the model can place a
        # risky tool (exec_shell) BEFORE the untrusted one (web_fetch), so the
        # risky tool runs while taint is still "none". Reorder execution so
        # taint is set first. Results stay indexed by original position, so the
        # tool_end emit order + merged observation below are unchanged. (Stable
        # sort preserves declared order within each group.)
        exec_order = sorted(
            range(len(actions)),
            key=lambda j: 0 if (j < len(untrusted_flags) and untrusted_flags[j]) else 1,
        )
        for idx in exec_order:
            obs, bk = _run_one(idx)
            observations[idx] = obs
            beak_steps[idx] = bk
    else:
        max_workers = min(len(actions), _MAX_PARALLEL_ACTIONS)
        with _cf.ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {pool.submit(_run_one, idx): idx for idx in range(len(actions))}
            for fut in _cf.as_completed(futures):
                idx = futures[fut]
                try:
                    obs, bk = fut.result()
                except Exception as exc:  # noqa: BLE001 — surface any worker exception as a tool error observation
                    obs, bk = (
                        f"(工具执行异常) {type(exc).__name__}: {exc}",
                        None,
                    )
                observations[idx] = obs
                beak_steps[idx] = bk

    # Emit tool_end events in declared (action) order so the UI
    # transcript matches the model's intent.
    results: list[dict[str, object]] = []
    merged_lines: list[str] = []
    n = len(actions)
    for idx in range(n):
        obs = observations[idx]
        bk = beak_steps[idx]
        name = resolved_names[idx] or (parsed_pairs[idx][0] if parsed_pairs[idx] else "unknown")
        _ok = not (
            obs is not None
            and isinstance(obs, str)
            and obs.startswith(("(工具失败)", "(工具执行异常)", "(工具未注册"))
        )
        if bk is not None:
            _ok = _beak_step_effective_success(bk)
        _duration_ms = int((time.monotonic() - started_at[idx]) * 1000)
        # Indirect prompt-injection defense: a tool whose output is
        # external (web/browser/MCP) is attacker-influenceable. Fence its
        # observation as DATA-not-instructions before it re-enters the
        # model's context, and flag known injection markers. The UI
        # preview keeps the raw text; only the model-facing copy is
        # wrapped. Failed-tool observations are error strings, not
        # untrusted content, so they're left alone.
        model_obs = obs
        if _ok and isinstance(obs, str) and obs:
            _reg = getattr(executor, "registry", None)
            _affinity: list[str] | None = None
            if _reg is not None and resolved_names[idx] and _reg.has(name):
                try:
                    _affinity = _reg.get(name).affinity
                except (KeyError, AttributeError):
                    _affinity = None
            if is_untrusted_tool(name, _affinity):
                _scan = scan_for_injection(obs)
                model_obs = wrap_untrusted_observation(
                    obs,
                    source=name,
                    scan=_scan,
                )
                if _scan.flagged:
                    # Taint the turn so a later high-risk tool is forced
                    # through human approval (read at the approval gate).
                    mark_injection_taint(_scan.severity)
                    _logger.warning(
                        "prompt-injection markers in %s output (severity=%s, signals=%s)",
                        name,
                        _scan.severity,
                        ",".join(_scan.labels),
                    )
        _end_payload = {
            "tool_name": name,
            "tool_call_id": call_ids[idx],
            "iteration": iteration,
            "status": "success" if _ok else "error",
            "output_preview": (
                _summarize_observation(obs) if isinstance(obs, str) and obs else obs
            ),
            "duration_ms": _duration_ms,
            "parallel_batch_size": n,
            **_tool_event_extras_from_beak_step(bk, name),
        }
        # Attach capability-disabled metadata so the UI can render a
        # one-click "enable web_search" prompt instead of a bare error.
        # Routed through ``extras`` by ``normalize_tool_lifecycle_event``.
        if disabled_infos[idx] is not None:
            _end_payload["capability_disabled"] = disabled_infos[idx]
        yield tool_lifecycle_event_to_react_event(
            normalize_tool_lifecycle_event(
                "tool_end",
                _end_payload,
                origin="react_compat",
            )
        )
        results.append(
            {
                "tool_name": name,
                "ok": _ok,
                "observation": model_obs or "",
                "duration_ms": _duration_ms,
                "call_id": call_ids[idx],
            }
        )
        # Per-call header keeps the model from confusing which
        # observation belongs to which action.
        merged_lines.append(f"[{idx + 1}/{n} {name}]\n{model_obs or '(no output)'}")

    merged_obs = "\n\n".join(merged_lines)
    return merged_obs, results
