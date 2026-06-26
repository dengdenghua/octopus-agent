from __future__ import annotations

import contextlib
import json
import re
from collections import OrderedDict
from typing import Any

from .delegation_budget import (
    _PER_TURN_ABSOLUTE_LIMIT,
)
from .delegation_budget import (
    check_absolute_cap as _check_absolute_cap,
)
from .delegation_budget import (
    compute_fingerprint as _compute_fingerprint,
)
from .delegation_budget import (
    current_orchestration_budget as _current_orchestration_budget,
)
from .delegation_budget import (
    orchestration_budget_scope as _orchestration_budget_scope,
)
from .delegation_budget import (
    record_delegation as _record_delegation,
)
from .registry import Skill, SkillRegistry
from .testing import SkillExpect, SkillTestCase

# ── Role visibility policy ────────────────────────────────
# ``arbiter`` is internal (used by team-vote dispatcher).
# ``researcher`` / ``debugger`` / ``explorer`` / ``reviewer`` exist in
# BUILTIN_ROLES but are deliberately NOT advertised so the lead agent
# does that work itself. They remain CALLABLE if the model knows
# their name — that's a deliberate escape hatch, not a contradiction.
_INTERNAL_AGENTS: frozenset[str] = frozenset({"arbiter"})
_ADVERTISED_BUILTINS: frozenset[str] = frozenset(
    {
        "architect",
        "debugger",
        "explorer",
        "researcher",
        "reviewer",
        "security-review",
    }
)


# ── Cheap-model routing policy ────────────────────────────
# Roles whose work is "research-style" (web fetching, fact-checking,
# data extraction, code reading, surface review) auto-route to the
# cheap subagent model unless the spec explicitly opts out via
# ``"cheap": False``. The non-cheap roles — architect / synthesizer /
# designer / implementer — keep the parent's primary model since they
# carry the heavy reasoning load.
_NON_CHEAP_ROLES: frozenset[str] = frozenset(
    {
        "architect",
        "synthesizer",
        "designer",
        "implementer",
    }
)

_CHEAP_BY_DEFAULT_ROLES: frozenset[str] = frozenset(
    {
        "researcher",
        "fact_checker",
        "fact-checker",
        "security",
        "security-review",
        "performance",
        "style",
        "reproducer",
        "hypothesizer",
        "verifier",
        "debugger",
        "explorer",
        "reviewer",
    }
)

_FULL_TOOL_MARKERS: frozenset[str] = frozenset(
    {
        "*",
        "all",
        "full",
        "inherit_all",
        "全部",
    }
)

_DYNAMIC_SKILL_PACKS: dict[str, tuple[str, ...]] = {
    "research": (
        "web_search",
        "fetch_url",
        "bb_write",
        "bb_read",
        "bb_keys",
        "todo_write",
    ),
    "web": (
        "web_search",
        "fetch_url",
        "browser_get",
        "browser_extract",
        "browser_state",
        "browser_find",
    ),
    "browser": (
        "browser_get",
        "browser_extract",
        "browser_navigate",
        "browser_click",
        "browser_type",
        "browser_scroll",
        "browser_wait",
        "browser_screenshot",
        "browser_find",
        "browser_state",
        "live_browser_current_url",
        "live_browser_state",
        "live_browser_extract",
        "live_browser_find",
        "live_browser_click",
        "live_browser_type",
        "live_browser_scroll",
        "live_browser_wait",
        "live_browser_screenshot",
    ),
    "files": (
        "list_cwd",
        "tree",
        "glob_files",
        "grep_text",
        "read_file",
        "read_file_range",
        "file_stats",
    ),
    "filesystem": (
        "list_cwd",
        "tree",
        "glob_files",
        "grep_text",
        "read_file",
        "read_file_range",
        "file_stats",
    ),
    "code": (
        "list_cwd",
        "tree",
        "glob_files",
        "grep_text",
        "read_file",
        "read_file_range",
        "code_search",
        "exec_shell",
        "edit_file",
        "multi_edit_file",
        "write_text_file",
        "propose_patch",
        "bb_read",
        "bb_write",
        "bb_keys",
        "todo_read",
        "todo_write",
    ),
    "review": (
        "list_cwd",
        "glob_files",
        "grep_text",
        "read_file",
        "read_file_range",
        "file_stats",
        "bb_read",
        "bb_write",
    ),
    "write": (
        "read_file",
        "edit_file",
        "multi_edit_file",
        "write_text_file",
        "propose_patch",
        "exec_shell",
    ),
    "memory": (
        "bb_read",
        "bb_write",
        "bb_keys",
        "todo_read",
        "todo_write",
        "query_skill",
    ),
    "shell": ("exec_shell",),
}


def _role_defaults_to_cheap(role: str) -> bool:
    """Return True when the named role should auto-route to the cheap
    subagent model. Heavy-reasoning roles (architect/synthesizer/...)
    return False; the explicit research/review allowlist returns True;
    anything else falls back to False so unknown user-defined agents
    keep using the primary model unless the caller asks otherwise."""
    if not role:
        return False
    if role in _NON_CHEAP_ROLES:
        return False
    return role in _CHEAP_BY_DEFAULT_ROLES


def _route_context_risk_level(context: dict[str, Any] | None) -> str:
    ctx = context or {}
    for key in (
        "task_risk_level",
        "risk_level",
        "approval_risk_level",
        "quality_risk_level",
    ):
        value = ctx.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "low"


def _parallel_route_decision(
    agent_id: str,
    context: dict[str, Any] | None,
) -> dict[str, Any]:
    ctx = context or {}
    try:
        from runtime.safety.evolution.subagent_routing import (
            decide_subagent_route,
        )

        decision = decide_subagent_route(
            role=agent_id,
            risk_level=_route_context_risk_level(ctx),
            review_queue_path=ctx.get("review_queue_path"),
            subagent_policy_path=ctx.get("subagent_policy_path"),
            enabled=bool(ctx.get("enable_subagent_fitness_routing", True)),
        )
        return decision.to_dict()
    except Exception:  # noqa: BLE001
        return {
            "schema": "octopus.subagent_route_decision.v1",
            "role": agent_id,
            "action": "allow",
            "reason": "subagent fitness routing unavailable",
            "risk_level": _route_context_risk_level(ctx),
            "verdict": "unknown",
            "score": None,
            "confidence": 0.0,
            "evidence_item_ids": [],
        }


def _dedupe_names(names: list[str]) -> list[str]:
    return list(OrderedDict((name, None) for name in names if name).keys())


def _coerce_name_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return []
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = None
        if parsed is not None and parsed is not value:
            return _coerce_name_list(parsed)
        for sep in ("，", "、", ";", "\n", "\t"):
            raw = raw.replace(sep, ",")
        return [part.strip() for part in raw.split(",") if part.strip()]
    if isinstance(value, dict):
        out: list[str] = []
        for key in (
            "tools",
            "skills",
            "skill_pack",
            "skill_packs",
            "plugins",
            "items",
        ):
            out.extend(_coerce_name_list(value.get(key)))
        return out
    if isinstance(value, (list, tuple, set)):
        out: list[str] = []
        for item in value:
            out.extend(_coerce_name_list(item))
        return out
    return [str(value).strip()] if str(value).strip() else []


def _skill_context_from_spec(
    raw: dict[str, Any],
    base_context: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Build dynamic tool grants for a spawned subagent.

    The lead can pass concrete tool names through ``skills`` / ``tools``
    or higher-level bundles through ``skill_pack(s)`` / ``plugins``.
    Actual tool exposure is still intersected with the live registry by
    ``ephemeral_runner``.
    """
    context: dict[str, Any] = {}
    if isinstance(base_context, dict):
        context.update(base_context)
    embedded = raw.get("context")
    if isinstance(embedded, dict):
        context.update(embedded)

    direct = _coerce_name_list(raw.get("skills"))
    direct.extend(_coerce_name_list(raw.get("tools")))
    direct.extend(_coerce_name_list(raw.get("tool_allowlist")))
    direct.extend(_coerce_name_list(raw.get("skill_allowlist")))
    direct.extend(_coerce_name_list(raw.get("extra_skills")))
    direct.extend(_coerce_name_list(raw.get("extra_tools")))

    pack_names = _coerce_name_list(raw.get("skill_pack"))
    pack_names.extend(_coerce_name_list(raw.get("skill_packs")))
    pack_names.extend(_coerce_name_list(raw.get("pack")))
    pack_names.extend(_coerce_name_list(raw.get("packs")))

    plugin_names = _coerce_name_list(raw.get("plugin"))
    plugin_names.extend(_coerce_name_list(raw.get("plugins")))

    requested = [name.strip() for name in [*direct, *pack_names, *plugin_names]]
    if any(name.lower() in _FULL_TOOL_MARKERS for name in requested):
        context["tool_allowlist_mode"] = "all"

    expanded: list[str] = []
    for name in pack_names:
        expanded.extend(_DYNAMIC_SKILL_PACKS.get(name.strip().lower(), ()))
    for name in plugin_names:
        expanded.extend(_DYNAMIC_SKILL_PACKS.get(name.strip().lower(), ()))

    existing = _coerce_name_list(context.get("extra_tool_allowlist"))
    grants = _dedupe_names([*existing, *expanded, *direct])
    if grants:
        context["extra_tool_allowlist"] = grants
    if pack_names:
        context["skill_pack_names"] = _dedupe_names(pack_names)
    if plugin_names:
        context["plugin_grants"] = _dedupe_names(plugin_names)
    if direct:
        context["direct_skill_grants"] = _dedupe_names(direct)

    return context or None


# ── Per-turn delegation budget (smart-budget, 2026-06) ──
#
# Budget is tracked per Session.turn_id. The legacy hard cap of 1
# successful delegation per turn (kept as a backstop) blocked the LLM
# from iterating on failed specs. The new smart-budget system
# distinguishes failure classes:
#
#   * First-time structural failure (bad prompt, unknown agent) does
#     NOT count against budget → gives the LLM a chance to fix and retry.
#     The failure is fingerprinted (agent_id + normalized prompt hash)
#     so repeated identical attempts DO count.
#
#   * Transient failure (timeout / connection) auto-retries ONCE inside
#     ``_call_agent`` (see ``_is_transient_error``). If both attempts
#     fail, the call is treated as a structural failure for budget
#     purposes — the next attempt with a different prompt gets a free
#     pass, but the same prompt repeated counts.
#
#   * Repeat failure (same agent + same normalized prompt) counts fully,
#     preventing infinite loops where the model keeps delegating the
#     same broken spec without learning.
#
# Implementation lives in ``delegation_budget.py`` — imported above as
# ``_check_absolute_cap`` / ``_record_delegation`` / ``_compute_fingerprint``.

# Default per-subagent wall-clock timeout. Bumped from 300s in 2026-06
# after operator feedback: research-style subagents commonly need 10-15
# rounds × ~60s/round, hitting the old 300s budget after only 5 rounds.
# 900s gives ~15 rounds headroom for parallel fan-outs without letting
# a stuck subagent hang the whole pipeline indefinitely.
_DEFAULT_SUBAGENT_TIMEOUT_S: int = 900

# Number of times a transient subagent failure (timeout / connection
# error) is retried before being reported as final. Set to 1 because
# retrying a structural failure (unknown role, malformed prompt) just
# wastes more tokens — only timeout-class errors get a second chance.
_MAX_RETRY_ON_TRANSIENT: int = 1


def _bump_and_check(turn_id: str | None) -> tuple[int, bool]:
    """Legacy compat shim — see ``delegation_budget.bump_and_check``."""
    cur, within = _check_absolute_cap(turn_id)
    return (cur + 1, within)


def _delegation_budget_exhausted_message(
    used: int,
    *,
    budget: Any = None,
    action: str = "Do the rest of this turn's work yourself · do NOT call_agent again.",
) -> str:
    if budget is not None:
        limit = getattr(budget, "max_spawns", _PER_TURN_ABSOLUTE_LIMIT)
        return f"orchestration spawn budget exhausted for this turn (used {used}/{limit}). {action}"
    return (
        "delegation budget exhausted for this turn "
        f"(used {used}/{_PER_TURN_ABSOLUTE_LIMIT}). {action}"
    )


# ── Catalog rendering ─────────────────────────────────────


def _format_role_catalog() -> str:
    """Render the advertised specialist list.

    Delegation is still constrained by the prompt policy and per-turn
    budget; the catalog itself should be honest about the roles that can
    actually be called so swarm mode can split research/write/review work
    without guessing hidden role names.
    """
    rows: list[tuple[str, str]] = []
    try:
        from .ephemeral_agents import BUILTIN_ROLES

        for name in sorted(_ADVERTISED_BUILTINS):
            role = BUILTIN_ROLES.get(name)
            if role is None:
                continue
            desc = (role.description or "").strip().split("\n", 1)[0]
            if len(desc) > 160:
                desc = desc[:157] + "..."
            rows.append((name, desc))
    except Exception:  # noqa: BLE001
        pass
    if not rows:
        return "  (no advertised subagents)"
    return "\n".join(f"  - {name}: {desc}" for name, desc in rows)


def _allowed_agent_ids() -> set[str]:
    """Names of every subagent this skill is allowed to spawn — INCLUDES
    the un-advertised builtins (researcher / debugger / explorer /
    reviewer) as escape hatches, plus any user-defined ``.claude/agents/``
    entries. We just don't advertise them."""
    out: set[str] = set()
    try:
        from .ephemeral_agents import BUILTIN_ROLES

        out.update(set(BUILTIN_ROLES.keys()) - _INTERNAL_AGENTS)
    except Exception:  # noqa: BLE001
        pass
    try:
        from runtime.execution.subagents import get_subagent_registry

        reg = get_subagent_registry()
        if reg is not None:
            out.update(set(reg.all_names()) - _INTERNAL_AGENTS)
    except Exception:  # noqa: BLE001
        pass
    return out


# ── Custom role-name resolution ──────────────────────────
# Operators frequently want to name a delegation target after the
# task ("sleep_researcher_eight" / "kyc_screener_alpha") rather than
# pick one of the 6 advertised generic builtins. Forcing them to map
# to "researcher" loses the task-shape signal in logs/UI and breaks
# parallel runs that need distinct labels.
#
# Strategy: any unknown agent_id falls back to a generic builtin
# (default ``researcher`` for research-shaped names, ``general`` for
# everything else) AND injects the original name as a role label
# into the subagent prompt — the LLM still understands the task
# framing, the bridge logs preserve the custom name in metadata,
# and the parent gets exactly the structured failures it requested.

# Names that look research-y route to the cheap researcher builtin.
_RESEARCH_NAME_HINTS: tuple[str, ...] = (
    "research",
    "researcher",
    "explore",
    "explorer",
    "investigate",
    "study",
    "analyst",
    "analyzer",
    "fact_check",
    "fact-check",
    "scout",
    "probe",
    "screen",
    "screener",
    "audit",
    "auditor",
    "monitor",
    "watcher",
    "intel",
)


def _resolve_custom_agent_id(
    requested: str,
    allowed: set[str],
) -> tuple[str, str | None]:
    """Resolve a possibly-custom ``requested`` name to a runnable
    builtin agent_id. Returns ``(actual_id, role_label)`` where
    ``role_label`` is the original name when fallback was used (None
    when the requested name was already a real agent).

    The role_label is later injected into the subagent prompt so the
    LLM still sees the task-shaped framing the operator intended.
    """
    if requested in allowed:
        return requested, None
    lower = requested.lower()
    # Research-shaped → researcher (cheap model, broad search tools)
    if any(hint in lower for hint in _RESEARCH_NAME_HINTS) and "researcher" in allowed:
        return "researcher", requested
    # Code-shaped → debugger or explorer
    if (
        any(hint in lower for hint in ("debug", "fix", "trace", "diagnose"))
        and "debugger" in allowed
    ):
        return "debugger", requested
    if any(hint in lower for hint in ("review", "critic", "audit_code")) and "reviewer" in allowed:
        return "reviewer", requested
    # Unknown shape → general/explorer fallback
    for fallback in ("explorer", "researcher", "general"):
        if fallback in allowed:
            return fallback, requested
    # No builtins at all — return as-is, caller will reject
    return requested, None


def _wrap_prompt_with_role_label(
    prompt: str,
    role_label: str | None,
) -> str:
    """When a custom name was substituted, prepend a role-framing
    header so the LLM still acts in-character. Otherwise pass through.
    """
    if not role_label:
        return prompt
    header = (
        f"# Role: {role_label}\n\n"
        f"You are acting as **{role_label}** for this task. The framework "
        f"resolved this custom role to a generic builtin, but you should "
        f"still adopt the focus implied by the name "
        f"({role_label!r}) when prioritizing what to investigate "
        f"and how to structure your output.\n\n"
        f"---\n\n"
    )
    return header + prompt


# ── Handler ───────────────────────────────────────────────


def _resolve_session_and_turn() -> tuple[Any, str | None]:
    """Pull the active Session + turn_id from the ContextVar."""
    try:
        from runtime.platform.process.session import current_session

        sess = current_session()
        return sess, (getattr(sess, "turn_id", None) if sess else None)
    except Exception:  # noqa: BLE001
        return None, None


def _is_transient_error(result: dict[str, Any]) -> bool:
    """Heuristic: should we retry this failure once?

    Retry on timeout / connection / rate-limit class errors. Don't
    retry on structural failures (unknown role, malformed prompt,
    budget exhausted) — those won't get better next time.
    """
    if result.get("success"):
        return False
    err_type = (result.get("error_type") or "").lower()
    if err_type in {"timeout", "connectionerror", "ratelimiterror"}:
        return True
    err_msg = (result.get("error") or "").lower()
    transient_markers = (
        "timeout",
        "timed out",
        "connection",
        "rate limit",
        "rate-limit",
        "rate_limit",
        "too many requests",
        "temporarily",
        "503",
        "504",
    )
    return any(marker in err_msg for marker in transient_markers)


def _call_agent(
    agent_id: str = "",
    prompt: str = "",
    *,
    role: str = "",
    task: str = "",
    name: str = "",
    message: str = "",
    query: str = "",
    context: dict[str, Any] | None = None,
    skills: Any = None,
    tools: Any = None,
    skill_pack: Any = None,
    skill_packs: Any = None,
    plugin: Any = None,
    plugins: Any = None,
    tool_allowlist: Any = None,
    timeout_s: int = _DEFAULT_SUBAGENT_TIMEOUT_S,
    session: Any = None,
    output_schema: Any = None,
    **_kw: Any,
) -> dict[str, Any]:
    """Spawn an isolated subagent turn — escalation when you need
    specialized expertise or parallel work.

    Pass ``output_schema`` (a JSON Schema object) to get a structured,
    validated result: the subagent is asked for JSON matching the schema and
    re-asked once on a mismatch; on success the parsed object is returned under
    ``parsed`` with ``schema_ok=True`` (the raw ``output`` is always kept too).

    Returns ``{agent_id, output, success, error}``. On budget exhaustion
    returns ``success=False`` with a message that instructs the model to
    do the work itself.

    Custom agent_ids (not in the builtin allowlist) are accepted and
    resolved to a generic builtin (researcher / explorer / general)
    based on name shape. The original custom name is preserved as a
    role label injected into the subagent prompt — see
    ``_resolve_custom_agent_id``.

    Budget rules (2026-06 smart-budget):
      - Absolute cap: 5 calls per turn (hard limit)
      - Success counts against budget
      - First-time failure is FREE (you can fix the spec and retry)
      - Repeat failure (same agent + same prompt) counts (prevents loops)
      - Transient failures (timeout / connection) auto-retry once

    TL;DR: if a delegation fails because your prompt was unclear or the
    agent_id was wrong, you get a free second chance to fix it. But if
    you keep delegating the same broken spec, that counts against budget.
    """
    from runtime.execution.subagents import call_subagent

    target_raw = agent_id or role or name
    if not target_raw:
        return {
            "agent_id": "",
            "output": "",
            "success": False,
            "error": "agent_id is required",
        }

    allowed = _allowed_agent_ids()
    target, role_label = _resolve_custom_agent_id(str(target_raw), allowed)
    if target not in allowed:
        return {
            "agent_id": target_raw,
            "output": "",
            "success": False,
            "error": (
                f"unknown subagent {target_raw!r} and no fallback builtin "
                f"available. Available: {sorted(allowed)}. "
                "If you really need delegation, pick one of these; "
                "otherwise just do the work yourself."
            ),
        }

    # Per-turn budget · resolves Session via ContextVar (set by the
    # agentic / react path before the tool loop). When no Session is
    # active (raw unit test, etc.) enforcement is OFF.
    #
    # Smart-budget rules (see ``_record_delegation`` for full docs):
    #   - Pre-check: absolute cap (default 5/turn)
    #   - Post-call: success counts; first-time failure is FREE;
    #     repeat failure (same agent + same prompt) counts.
    sess, turn_id = _resolve_session_and_turn()
    if session is None:
        session = sess
    orch_budget = _current_orchestration_budget()
    cur_count, within = _check_absolute_cap(turn_id, budget=orch_budget)
    if not within:
        return {
            "agent_id": target_raw,
            "output": "",
            "success": False,
            "error": _delegation_budget_exhausted_message(
                cur_count,
                budget=orch_budget,
            ),
            "error_type": "budget_exhausted",
        }

    # Inject the custom role label into the prompt so the LLM still
    # adopts the intended task framing even though the underlying
    # builtin is generic.
    final_prompt = _wrap_prompt_with_role_label(
        prompt or task or message or query,
        role_label,
    )

    # Compute fingerprint up-front so we can attribute the result
    # correctly regardless of which retry branch we end up in.
    fingerprint = _compute_fingerprint(target, final_prompt)

    # Optional structured output: the model (or an internal caller) may ask the
    # subagent for a JSON value matching a schema. Accept a dict, or a JSON
    # string some models stringify; anything else is ignored (no enforcement)
    # rather than crashing the delegation.
    schema_arg: dict[str, Any] | None = None
    if isinstance(output_schema, dict):
        schema_arg = output_schema
    elif isinstance(output_schema, str) and output_schema.strip():
        try:
            _loaded = json.loads(output_schema)
        except (json.JSONDecodeError, ValueError):
            _loaded = None
        if isinstance(_loaded, dict):
            schema_arg = _loaded

    # First attempt
    subagent_context = _skill_context_from_spec(
        {
            **_kw,
            "skills": skills,
            "tools": tools,
            "skill_pack": skill_pack,
            "skill_packs": skill_packs,
            "plugin": plugin,
            "plugins": plugins,
            "tool_allowlist": tool_allowlist,
        },
        context,
    )
    if orch_budget is not None and not orch_budget.try_charge():
        return {
            "agent_id": target_raw,
            "output": "",
            "success": False,
            "error": _delegation_budget_exhausted_message(
                orch_budget.used,
                budget=orch_budget,
            ),
            "error_type": "budget_exhausted",
        }
    result = call_subagent(
        agent_id=target,
        prompt=final_prompt,
        context=subagent_context,
        timeout_s=timeout_s,
        session=session,
        output_schema=schema_arg,
    )

    # Retry once on transient failure. Critical: retry does NOT bump
    # the budget counter — that happens in ``_record_delegation`` based
    # on the FINAL result (success vs. repeat-failure vs. first-failure).
    if _is_transient_error(result):
        if orch_budget is not None and not orch_budget.try_charge():
            result["retry_skipped"] = True
            existing_err = result.get("error") or ""
            result["error"] = (
                f"{existing_err} (retry skipped: "
                f"{_delegation_budget_exhausted_message(orch_budget.used, budget=orch_budget, action='Retry skipped.')})"
            )
        else:
            retry_result = call_subagent(
                agent_id=target,
                prompt=final_prompt,
                context=subagent_context,
                timeout_s=timeout_s,
                session=session,
                output_schema=schema_arg,
            )
            if retry_result.get("success"):
                retry_result.setdefault("retried", True)
                result = retry_result
            else:
                # Both attempts failed — surface that fact in the error
                result["retried"] = True
                existing_err = result.get("error") or ""
                result["error"] = (
                    f"{existing_err} (retry also failed: {retry_result.get('error') or 'unknown'})"
                )

    # Record against budget AFTER we know the outcome. Smart-budget:
    # first-time failures get a free pass; repeat failures + successes
    # both count.
    if orch_budget is None:
        _record_delegation(
            turn_id,
            fingerprint,
            succeeded=bool(result.get("success")),
        )

    # Preserve the operator's original custom name in the response so
    # logs / UI show what they asked for, not the resolved builtin.
    if role_label:
        result["agent_id"] = target_raw
        result["resolved_to"] = target
        result["custom_role"] = role_label
    return result


def _derive_error_type(result: dict[str, Any]) -> str:
    """Best-effort classification of a sub-agent failure.

    Prefers an explicit ``error_type`` key from the bridge, then the
    ``status`` field (e.g. ``timeout``), then the leading exception
    class name from the ``error`` string. Falls back to ``unknown``.
    """
    et = result.get("error_type")
    if isinstance(et, str) and et:
        return et
    if result.get("status") == "timeout":
        return "timeout"
    err = str(result.get("error") or "")
    head = err.split(":", 1)[0].strip()
    if head == "TimeoutError" or "timed out" in err.lower():
        return "timeout"
    if head in ("ConnectionError", "OSError", "TransportError"):
        return "transport"
    if head:
        return head.lower()
    return "unknown"


def _empty_parallel_result(error: str) -> dict[str, Any]:
    """Validation / budget failure shape · keep legacy + new keys."""
    return {
        # legacy keys for backward compat
        "results": [],
        "count": 0,
        "outputs": [],
        "error": error,
        # new keys
        "ok": False,
        "successes": [],
        "failures": [],
        "partial": False,
        "total": 0,
        "success_count": 0,
        "notes": [],
    }


def _coerce_parallel_specs(specs: Any) -> list[dict[str, Any]] | None:
    """Accept the common LLM shape where ``specs`` arrives as JSON text."""
    if isinstance(specs, list):
        return specs
    if isinstance(specs, dict):
        nested = specs.get("specs") or specs.get("agents") or specs.get("items")
        if isinstance(nested, list):
            return nested
        return None
    if not isinstance(specs, str):
        return None
    raw = specs.strip()
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict):
        nested = parsed.get("specs") or parsed.get("agents") or parsed.get("items")
        if isinstance(nested, list):
            return nested
    return None


def _coerce_timeout_s(timeout_s: Any) -> int:
    if isinstance(timeout_s, bool):
        return _DEFAULT_SUBAGENT_TIMEOUT_S
    try:
        value = int(float(timeout_s))
    except (TypeError, ValueError):
        return _DEFAULT_SUBAGENT_TIMEOUT_S
    return value if value > 0 else _DEFAULT_SUBAGENT_TIMEOUT_S


def _call_agent_parallel(
    specs: list[dict[str, Any]] | str | None = None,
    *,
    timeout_s: int | str = _DEFAULT_SUBAGENT_TIMEOUT_S,
    context: dict[str, Any] | None = None,
    session: Any = None,
    **_kw: Any,
) -> dict[str, Any]:
    """Spawn N sub-agents concurrently and gather their results.

    Args:
        specs: list of ``{"agent_id": "<role>", "prompt": "<brief>"}``
            dicts. Each spec triggers one sub-agent run in its own
            worker thread; all share the parent's blackboard
            (``bb_read`` / ``bb_write``) via the parent's ``turn_id``.
        timeout_s: per-sub-agent timeout (default 900s, applies to
            EACH sub-agent independently — total wall clock is
            ``max(per-agent durations)``, not the sum). Bumped from
            300s in 2026-06 after research workloads hit the 5-round
            ceiling. Failed subagents auto-retry ONCE on transient
            (timeout / connection / rate-limit) errors.

    Returns:
        ``{"ok": bool, "successes": [...], "failures": [...],
        "partial": bool, "total": int, "success_count": int,
        "notes": list[str], "outputs": [<success output strings>],
        "results": [...], "count": int}``

        ``ok=False`` only when ZERO sub-agents succeeded. ``partial=True``
        when at least one succeeded AND at least one failed — in that
        case ``notes`` carries a ``[partial-degradation]`` line so the
        main agent can decide whether to synthesise from the available
        outputs or escalate.

        Legacy ``results`` / ``count`` / ``outputs`` keys are preserved
        for callers written against the original shape.

    Budget rules (2026-06 smart-budget):
      - Absolute cap: 5 delegations per turn (hard limit)
      - Each spec counts independently against the budget:
          * Success counts
          * First-time spec failure is FREE (you can adjust and retry
            that one spec without burning the whole batch's budget)
          * Repeat failure on the same {agent, prompt} counts
      - Transient failures auto-retry once per spec
      - Parallel batches can iterate: if 1/3 specs fails, you can
        retry just that one spec for free in your next call

    TL;DR: failure is a learning opportunity, not a punishment. The
    framework only penalizes you for wasting calls on the EXACT SAME
    broken spec twice.
    """
    specs = _coerce_parallel_specs(specs)
    timeout_s = _coerce_timeout_s(timeout_s)
    if not specs or not isinstance(specs, list):
        return _empty_parallel_result(
            "specs is required (list of {agent_id, prompt})",
        )

    # Validate every spec up front so a bad input doesn't waste an
    # LLM round-trip.
    cleaned: list[dict[str, Any]] = []
    allowed = _allowed_agent_ids()
    for raw in specs:
        if not isinstance(raw, dict):
            continue
        aid_raw = (
            raw.get("agent_id")
            or raw.get("agent_name")
            or raw.get("agent")
            or raw.get("role")
            or raw.get("name")
            or ""
        )
        prm = (
            raw.get("prompt")
            or raw.get("task")
            or raw.get("message")
            or raw.get("query")
            or raw.get("description")
            or raw.get("instruction")
            or ""
        )
        if not aid_raw and prm:
            aid_raw = "researcher"
        if not aid_raw or not prm:
            continue
        # Custom names are resolved to a generic builtin via the
        # fallback chain (see _resolve_custom_agent_id). Only fail
        # when there are NO builtins at all (which would mean the
        # registry is broken).
        aid_resolved, role_label = _resolve_custom_agent_id(str(aid_raw), allowed)
        if aid_resolved not in allowed:
            return _empty_parallel_result(
                f"no fallback subagent available for {aid_raw!r}. Available: {sorted(allowed)}.",
            )
        # Cheap routing: explicit ``cheap`` in the spec wins; otherwise
        # the role-name policy decides. ``cheap=False`` disables the
        # auto-cheap behavior so heavy-reasoning roles dropped into the
        # default-cheap allowlist by mistake can still be pinned to the
        # primary model from the call site.
        cheap_flag = (
            bool(raw.get("cheap")) if "cheap" in raw else _role_defaults_to_cheap(str(aid_resolved))
        )
        cleaned.append(
            {
                "spec_index": len(cleaned),
                "agent_id": aid_resolved,
                "agent_id_original": str(aid_raw),
                "bb_key": str(raw.get("bb_key") or raw.get("key") or "").strip(),
                "prompt": _wrap_prompt_with_role_label(str(prm), role_label),
                "task_preview": str(prm).replace("\n", " ").strip()[:240],
                "role_label": role_label,
                "cheap": cheap_flag,
                "context": _skill_context_from_spec(raw, context),
                # Optional JSON Schema: when a spec carries one, the sub-agent's
                # reply is validated (and re-asked once on mismatch) by
                # call_subagent, and the parsed object rides back in the envelope.
                "output_schema": raw.get("output_schema"),
            }
        )

    if not cleaned:
        return _empty_parallel_result(
            "no valid {agent_id, prompt} entries in specs",
        )

    # Budget · pre-check absolute cap. Smart-budget rules apply
    # per-spec inside the worker thread (see _record_delegation calls
    # in _run_one), so the parallel call as a whole can succeed even
    # when one spec fails (and that single failure won't count).
    parent_sess, turn_id = _resolve_session_and_turn()
    if session is None:
        session = parent_sess
    # Captured on THIS (calling) thread so the pool workers can charge it via
    # closure — the ContextVar itself doesn't propagate into the pool.
    orch_budget = _current_orchestration_budget()
    cur_count, within = _check_absolute_cap(turn_id, budget=orch_budget)
    if not within:
        return _empty_parallel_result(
            _delegation_budget_exhausted_message(
                cur_count,
                budget=orch_budget,
                action="Do the rest yourself · do NOT call_agent again.",
            ),
        )

    # Concurrent fan-out · one worker thread per spec. Each worker
    # binds the parent's Session into its own ContextVar so
    # blackboard / memory skills inside the sub-agent see the same
    # turn_id and can exchange data via bb_read/bb_write.
    import concurrent.futures as _cf

    from runtime.execution.subagents import call_subagent

    def _run_one(spec: dict[str, Any]) -> dict[str, Any]:
        # Bind parent session in this worker thread · ContextVars
        # don't propagate across threads automatically.
        if session is not None:
            try:
                from runtime.platform.process.session import _current_session

                _current_session.set(session)
            except Exception:  # noqa: BLE001
                pass
        original_id = spec.get("agent_id_original") or spec["agent_id"]
        role_label = spec.get("role_label")
        task_label = spec.get("bb_key") or role_label or original_id
        route_decision = _parallel_route_decision(
            str(spec["agent_id"]),
            spec.get("context"),
        )
        if route_decision.get("action") == "block":
            return {
                "agent_id": original_id,
                "resolved_to": spec.get("agent_id"),
                "custom_role": role_label,
                "output": "",
                "success": False,
                "status": "blocked",
                "error": str(route_decision.get("reason") or "subagent blocked by routing policy"),
                "error_type": "subagent_route_blocked",
                "spec_index": spec.get("spec_index"),
                "task_label": task_label,
                "bb_key": spec.get("bb_key"),
                "task_preview": spec.get("task_preview"),
                "subagent_route_decision": route_decision,
            }
        call_context = dict(spec.get("context") or {})
        call_context["subagent_route_decision"] = route_decision
        if orch_budget is not None and not orch_budget.try_charge():
            return {
                "agent_id": original_id,
                "resolved_to": spec.get("agent_id"),
                "custom_role": role_label,
                "output": "",
                "success": False,
                "status": "budget_exhausted",
                "error": _delegation_budget_exhausted_message(
                    orch_budget.used,
                    budget=orch_budget,
                    action="This lane was not spawned.",
                ),
                "error_type": "budget_exhausted",
                "spec_index": spec.get("spec_index"),
                "task_label": task_label,
                "bb_key": spec.get("bb_key"),
                "task_preview": spec.get("task_preview"),
                "subagent_route_decision": route_decision,
            }
        try:
            result = call_subagent(
                agent_id=spec["agent_id"],
                prompt=spec["prompt"],
                context=call_context,
                timeout_s=timeout_s,
                session=session,
                use_cheap_model=bool(spec.get("cheap")),
                output_schema=spec.get("output_schema"),
            )
        except (ConnectionError, TimeoutError, TypeError, ValueError) as exc:  # noqa: BLE001
            result = {
                "agent_id": spec["agent_id"],
                "output": "",
                "success": False,
                "error": f"{type(exc).__name__}: {exc}",
                "error_type": type(exc).__name__,
            }
        result["spec_index"] = spec.get("spec_index")
        result["task_label"] = task_label
        result["bb_key"] = spec.get("bb_key")
        result["task_preview"] = spec.get("task_preview")
        result["subagent_route_decision"] = route_decision
        # Retry once on transient failure. Per-spec retry, not per
        # parallel batch — one slow worker shouldn't block faster ones.
        if _is_transient_error(result):
            if orch_budget is not None and not orch_budget.try_charge():
                result["retry_skipped"] = True
                existing_err = result.get("error") or ""
                result["error"] = (
                    f"{existing_err} (retry skipped: "
                    f"{_delegation_budget_exhausted_message(orch_budget.used, budget=orch_budget, action='Retry skipped.')})"
                )
            else:
                try:
                    retry = call_subagent(
                        agent_id=spec["agent_id"],
                        prompt=spec["prompt"],
                        context=call_context,
                        timeout_s=timeout_s,
                        session=session,
                        use_cheap_model=bool(spec.get("cheap")),
                        output_schema=spec.get("output_schema"),
                    )
                    if retry.get("success"):
                        retry["retried"] = True
                        result = retry
                        result["spec_index"] = spec.get("spec_index")
                        result["task_label"] = task_label
                        result["bb_key"] = spec.get("bb_key")
                        result["task_preview"] = spec.get("task_preview")
                    else:
                        result["retried"] = True
                        existing_err = result.get("error") or ""
                        result["error"] = (
                            f"{existing_err} (retry also failed: {retry.get('error') or 'unknown'})"
                        )
                except (ConnectionError, TimeoutError, TypeError, ValueError):
                    result["retried"] = True
        # Record this spec's outcome against the smart-budget. Each
        # spec gets its own fingerprint so a failed spec doesn't
        # spend budget on a first try (LLM gets a chance to fix it),
        # but a repeat of the same {agent, prompt} does count.
        if orch_budget is None:
            spec_fingerprint = _compute_fingerprint(spec["agent_id"], spec["prompt"])
            _record_delegation(
                turn_id,
                spec_fingerprint,
                succeeded=bool(result.get("success")),
            )
        # Preserve operator's original agent_id in response
        if role_label:
            result["agent_id"] = original_id
            result["resolved_to"] = spec["agent_id"]
            result["custom_role"] = role_label
        return result

    results: list[dict[str, Any]] = []
    # Bound concurrency · 8 workers covers most real fan-outs; more
    # would just thrash on LLM API rate limits anyway.
    max_workers = min(len(cleaned), 8)
    pool = _cf.ThreadPoolExecutor(
        max_workers=max_workers,
        thread_name_prefix="subagent-parallel",
    )
    try:
        future_specs = {pool.submit(_run_one, s): s for s in cleaned}
        # ``timeout_s`` here is a batch-level guard. Finished workers
        # still return normally; stragglers become per-agent failures
        # instead of blowing away the whole parallel envelope.
        done, not_done = _cf.wait(
            future_specs.keys(),
            timeout=timeout_s + 30,
            return_when=_cf.ALL_COMPLETED,
        )
        for f in done:
            try:
                results.append(f.result(timeout=1))
            except (ConnectionError, TimeoutError, TypeError, ValueError) as exc:  # noqa: BLE001
                spec = future_specs.get(f, {})
                task_label = (
                    spec.get("bb_key") or spec.get("role_label") or spec.get("agent_id_original")
                )
                results.append(
                    {
                        "agent_id": (spec.get("agent_id_original") or spec.get("agent_id") or "?"),
                        "spec_index": spec.get("spec_index"),
                        "task_label": task_label,
                        "bb_key": spec.get("bb_key"),
                        "task_preview": spec.get("task_preview"),
                        "output": "",
                        "success": False,
                        "error": f"{type(exc).__name__}: {exc}",
                        "error_type": type(exc).__name__,
                    }
                )
        for f in not_done:
            spec = future_specs.get(f, {})
            f.cancel()
            task_label = (
                spec.get("bb_key") or spec.get("role_label") or spec.get("agent_id_original")
            )
            results.append(
                {
                    "agent_id": spec.get("agent_id_original") or spec.get("agent_id") or "?",
                    "spec_index": spec.get("spec_index"),
                    "task_label": task_label,
                    "bb_key": spec.get("bb_key"),
                    "task_preview": spec.get("task_preview"),
                    "resolved_to": spec.get("agent_id"),
                    "custom_role": spec.get("role_label"),
                    "output": "",
                    "success": False,
                    "status": "timeout",
                    "error": f"subagent timed out after {timeout_s}s",
                    "error_type": "timeout",
                }
            )
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

    return _build_parallel_envelope(results, total=len(cleaned))


def _build_parallel_envelope(
    results: list[dict[str, Any]],
    *,
    total: int,
) -> dict[str, Any]:
    """Split raw per-spec results into successes/failures and build
    the graceful-degradation envelope. Pure function · easy to unit
    test in isolation."""
    successes: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    outputs: list[str] = []
    partial_outputs: list[dict[str, Any]] = []

    for r in results:
        if not isinstance(r, dict):
            failures.append(
                {
                    "role": "?",
                    "agent_id": "?",
                    "error": f"non-dict result: {r!r}",
                    "error_type": "malformed",
                }
            )
            continue
        agent_id = str(r.get("agent_id") or "")
        output = str(r.get("output") or "")
        common = {
            "role": str(r.get("role") or r.get("custom_role") or agent_id),
            "agent_id": agent_id,
            "spec_index": r.get("spec_index"),
            "task_label": r.get("task_label"),
            "bb_key": r.get("bb_key"),
            "task_preview": r.get("task_preview"),
            "codename": r.get("codename"),
            "avatar": r.get("avatar"),
            "resolved_to": r.get("resolved_to"),
            "custom_role": r.get("custom_role"),
            "iteration_count": r.get("iteration_count") or r.get("rounds_completed"),
            "rounds_completed": r.get("rounds_completed") or r.get("iteration_count"),
            "duration_s": r.get("duration_s"),
            "files_touched": list(r.get("files_touched") or []),
            "retried": bool(r.get("retried") or r.get("retry_attempted")),
            "round_cap_exceeded": bool(r.get("round_cap_exceeded")),
            "partial": bool(r.get("partial")),
            "subagent_route_decision": r.get("subagent_route_decision"),
        }
        if r.get("success"):
            success_entry = {**common, "output": output}
            # Carry schema-validated output through the envelope when present
            # (a spec passed ``output_schema``); absent for plain free-text
            # specs, so non-schema callers see no shape change.
            if "parsed" in r:
                success_entry["parsed"] = r.get("parsed")
            if "schema_ok" in r:
                success_entry["schema_ok"] = r.get("schema_ok")
            successes.append(success_entry)
            if output.strip():
                outputs.append(output)
        else:
            error = str(r.get("error") or "")
            failure = {
                **common,
                "error": error,
                "error_type": _derive_error_type(r),
                "output": output,
                "partial_output": output,
                "status": r.get("status"),
            }
            failures.append(
                {key: value for key, value in failure.items() if value not in (None, "", [], False)}
            )
            if output.strip():
                partial_outputs.append(
                    {
                        "agent_id": agent_id,
                        "spec_index": r.get("spec_index"),
                        "task_label": r.get("task_label"),
                        "error": error,
                        "error_type": _derive_error_type(r),
                        "output": output,
                    }
                )

    success_count = len(successes)
    failure_count = len(failures)
    partial = success_count > 0 and failure_count > 0
    ok = success_count > 0

    notes: list[str] = []
    if partial:
        # Stable de-duplicated reason list, ordered by first appearance.
        seen: set[str] = set()
        reasons: list[str] = []
        for f in failures:
            et = f.get("error_type") or "unknown"
            if et not in seen:
                seen.add(et)
                reasons.append(et)
        notes.append(
            f"[partial-degradation] {success_count}/{total} sub-agents "
            f"completed; {failure_count} failed "
            f"(reasons: {', '.join(reasons)}). Synthesise from the "
            "available outputs unless they're insufficient — in that "
            "case escalate to the user."
        )

    status_summary = (
        f"{success_count}/{total} sub-agents succeeded" if total else "0/0 sub-agents succeeded"
    )
    honesty_warning = ""
    if partial:
        failed_labels = [
            str(f.get("task_label") or f.get("agent_id") or f.get("role") or "?") for f in failures
        ]
        honesty_warning = (
            "PARTIAL RUN: do not claim all sub-agents completed. "
            f"State that {status_summary}; failed lanes: "
            f"{', '.join(failed_labels)}."
        )
    elif failure_count > 0:
        honesty_warning = (
            "FAILED RUN: no sub-agent completed successfully. Do not present "
            "a complete multi-agent result unless you independently filled "
            "the gaps and disclose that fallback."
        )

    return {
        # new graceful-degradation envelope
        "ok": ok,
        "status_summary": status_summary,
        "honesty_warning": honesty_warning,
        "successes": successes,
        "failures": failures,
        "partial": partial,
        "total": total,
        "success_count": success_count,
        "notes": notes,
        "partial_outputs": partial_outputs,
        # legacy keys preserved
        "results": results,
        "count": len(results),
        "succeeded": success_count,
        "failed": failure_count,
        "outputs": outputs,
    }


# ── consensus / vote gate ────────────────────────────────────────
# A verification gate: spawn N INDEPENDENT voters on the SAME question,
# parse each one's VERDICT line, and tally a majority. This is the
# "adversarial verify / judge panel" pattern — confirm or refute a claim
# with independent voters instead of trusting one agent. The aggregation
# (``_extract_verdict`` / ``_tally_votes``) is a pure function · unit
# tested in isolation; the spawn reuses ``_call_agent_parallel`` so the
# concurrency cap, injection taint, budget, retry and timeout are all the
# same already-tested machinery.

_VOTE_MIN = 2
_VOTE_MAX = 5  # aligns with the per-turn delegation cap


def _coerce_vote_choices(choices: Any) -> list[str] | None:
    """Normalise a ballot into distinct labels, or None for a free verdict."""
    if choices is None:
        return None
    if isinstance(choices, str):
        parts = [c.strip() for c in choices.replace("|", ",").split(",")]
    elif isinstance(choices, (list, tuple)):
        parts = [str(c).strip() for c in choices]
    else:
        return None
    out: list[str] = []
    seen: set[str] = set()
    for p in parts:
        if p and p.lower() not in seen:
            seen.add(p.lower())
            out.append(p)
    return out or None


def _build_ballot_prompt(question: str, choices: list[str] | None) -> str:
    # The exact JSON shape ({verdict, reason}) is enforced by the schema
    # instruction call_subagent appends — here we only state the semantics so
    # the two don't contradict ("Line 1 MUST be ..." vs "output ONLY JSON").
    if choices:
        opts = " / ".join(choices)
        decide = f"Your `verdict` MUST be exactly one of: {opts}."
    else:
        decide = "Your `verdict` is a short answer / label."
    return (
        "You are ONE independent voter on a panel. Judge the question "
        "below on your own merits — do not assume other voters agree.\n\n"
        f"QUESTION:\n{question}\n\n"
        f"{decide}\n"
        "Also give a one-sentence `reason` (<=30 words)."
    )


def _normalize_verdict(raw: str, choices: list[str] | None) -> str:
    # Whitespace-only strip is enough: the substring match below tolerates
    # markdown / trailing punctuation noise ("**yes**", "yes.") on its own.
    v = (raw or "").strip()
    if not v:
        return ""
    if not choices:
        return v[:48]
    vl = v.lower()
    for c in choices:  # exact (casefold)
        if vl == c.lower():
            return c
    for c in choices:  # verdict line may be a sentence containing the choice
        cl = c.lower()
        if vl.startswith(cl) or cl in vl:
            return c
    return ""  # could not map to a ballot choice → abstention


def _extract_verdict(output: str, choices: list[str] | None) -> tuple[str, str]:
    """Parse (verdict, reason) from a voter's free text. verdict is ""
    when unparseable (counted as an abstention)."""
    text = (output or "").strip()
    verdict_raw = ""
    reason = ""
    for line in text.splitlines():
        s = line.strip().lstrip("-*# ").strip()
        low = s.lower()
        if not verdict_raw and low.startswith("verdict"):
            verdict_raw = s.split(":", 1)[-1].strip() if ":" in s else s[7:].strip()
        elif not reason and low.startswith("reason"):
            reason = s.split(":", 1)[-1].strip() if ":" in s else s[6:].strip()
    if not verdict_raw:
        for line in text.splitlines():
            if line.strip():
                verdict_raw = line.strip()
                break
    verdict = _normalize_verdict(verdict_raw, choices)
    if not reason:
        reason = " ".join(text.split())[:200]
    return verdict, reason


def _tally_votes(
    votes: list[dict[str, Any]],
    choices: list[str] | None,
) -> dict[str, Any]:
    """Pure majority aggregation over parsed votes."""
    abstentions = sum(1 for v in votes if not v.get("verdict"))
    tally: dict[str, int] = {}
    for v in votes:
        key = v.get("verdict")
        if key:
            tally[key] = tally.get(key, 0) + 1
    votes_cast = sum(tally.values())
    if votes_cast == 0:
        return {
            "verdict": None,
            "confidence": 0.0,
            "unanimous": False,
            "tie": False,
            "tie_between": [],
            "tally": {},
            "voter_count": len(votes),
            "votes_cast": 0,
            "abstentions": abstentions,
        }
    top = max(tally.values())
    winners = sorted(k for k, c in tally.items() if c == top)
    tie = len(winners) > 1
    return {
        "verdict": None if tie else winners[0],
        "confidence": round(top / votes_cast, 3),
        "unanimous": len(tally) == 1 and abstentions == 0,
        "tie": tie,
        "tie_between": winners if tie else [],
        "tally": dict(sorted(tally.items(), key=lambda kv: (-kv[1], kv[0]))),
        "voter_count": len(votes),
        "votes_cast": votes_cast,
        "abstentions": abstentions,
    }


def _vote_note(tally: dict[str, Any]) -> str:
    if tally["votes_cast"] == 0:
        return (
            "[no-verdict] no voter produced a parseable VERDICT; treat as "
            "inconclusive and decide yourself."
        )
    if tally["tie"]:
        return (
            f"[no-consensus] split {tally['tally']} between "
            f"{', '.join(tally['tie_between'])} — no majority. Do NOT claim a "
            "decision; break the tie yourself or escalate."
        )
    if tally["unanimous"]:
        return f"[unanimous] all {tally['votes_cast']} voters agree: {tally['verdict']}."
    return (
        f"[majority] {tally['verdict']} at {tally['confidence']:.0%} "
        f"({tally['tally']}); minority dissent present — weigh it before acting."
    )


def _call_agent_vote(
    question: str = "",
    *,
    n: int | str = 3,
    agent_id: str = "reviewer",
    choices: Any = None,
    timeout_s: int | str = _DEFAULT_SUBAGENT_TIMEOUT_S,
    context: dict[str, Any] | None = None,
    session: Any = None,
    **_kw: Any,
) -> dict[str, Any]:
    """Verification gate: spawn N independent voters on the SAME question,
    parse each VERDICT, return a majority decision + confidence + dissent.

    Use it to CONFIRM or REFUTE a claim with independent judgment rather
    than trusting a single agent (e.g. "is this bug real?", "does this
    patch fix it?", "which design is safer: A or B?").
    """
    q = str(
        question
        or _kw.get("prompt")
        or _kw.get("task")
        or _kw.get("claim")
        or _kw.get("query")
        or "",
    ).strip()
    if not q:
        return {
            "ok": False,
            "error": "question is required",
            "verdict": None,
            "confidence": 0.0,
            "tally": {},
            "votes": [],
            "voter_count": 0,
            "votes_cast": 0,
            "abstentions": 0,
            "note": "[no-verdict] nothing to vote on",
        }
    try:
        n_int = int(n)
    except (TypeError, ValueError):
        n_int = 3
    n_int = max(_VOTE_MIN, min(_VOTE_MAX, n_int))
    ballot_choices = _coerce_vote_choices(choices)
    voter = str(agent_id or "reviewer").strip() or "reviewer"
    ballot = _build_ballot_prompt(q, ballot_choices)
    # Ask each voter for a JSON object; call_subagent validates it and re-asks
    # once on a mismatch. ``verdict`` is left a free string (not an enum) so
    # _normalize_verdict keeps its lenient casefold/substring mapping to the
    # ballot — avoids rejecting a valid "Keep" against choice "keep".
    vote_schema = {
        "type": "object",
        "properties": {
            "verdict": {"type": "string"},
            "reason": {"type": "string"},
        },
        "required": ["verdict"],
    }
    specs = [
        {"agent_id": voter, "prompt": ballot, "output_schema": vote_schema} for _ in range(n_int)
    ]

    env = _call_agent_parallel(
        specs=specs,
        timeout_s=timeout_s,
        context=context,
        session=session,
    )

    votes: list[dict[str, Any]] = []
    for s in env.get("successes", []):
        parsed = s.get("parsed")
        if isinstance(parsed, dict) and "verdict" in parsed:
            # Schema-validated reply — trust the structured fields.
            verdict = _normalize_verdict(str(parsed.get("verdict") or ""), ballot_choices)
            reason = str(parsed.get("reason") or "").strip()[:200]
            if not reason:
                reason = " ".join(str(s.get("output") or "").split())[:200]
        else:
            # No parsed object (schema failed after retry, or none requested):
            # fall back to the legacy free-text parse so a malformed reply is
            # no worse than before rather than a hard abstention.
            verdict, reason = _extract_verdict(str(s.get("output") or ""), ballot_choices)
        votes.append(
            {
                "verdict": verdict,
                "reason": reason,
                "agent_id": s.get("agent_id"),
                "codename": s.get("codename"),
                "abstained": not verdict,
            }
        )

    tally = _tally_votes(votes, ballot_choices)
    return {
        "ok": bool(env.get("ok")) and tally["votes_cast"] > 0,
        "question": q[:240],
        "choices": ballot_choices,
        **tally,
        "votes": votes,
        "note": _vote_note(tally),
        "subagent_status": env.get("status_summary"),
        "honesty_warning": env.get("honesty_warning") or "",
    }


# ── deterministic orchestration (find -> dedup -> loop, optional verify) ──
# The model declares a goal; the recipe runs a DETERMINISTIC multi-round
# discovery loop in code (fan-out -> split -> dedup vs seen -> loop until dry),
# optionally gating each finding through call_agent_vote. The whole run is
# bounded by an ``orchestration_budget_scope`` so loops are possible (the flat
# 5/turn cap would otherwise refuse the 2nd round). The outer call still costs
# one against the per-turn cap so orchestrations can't be spammed.

_ORCH_MAX_SPAWNS_CEILING = 48
# Higher ceiling for the OPT-IN budget-driven path only (a trusted token budget
# set by the bus/operator). Lets a deep verify+synth run use its full natural
# spawn count (~n*rounds*voters) instead of being throttled at 48. The default
# (no budget) path keeps the conservative 48 cap untouched.
_ORCH_MAX_SPAWNS_BUDGET_CEILING = 256
_ORCH_VERIFY_VOTERS = 3
_ORCH_MAX_FINDINGS_PER_WORKER = 50
_ORCH_MAX_FINDINGS_TOTAL = 200


def _resolve_max_spawns(
    max_spawns: int | str | None,
    *,
    n: int,
    rounds: int,
    verify: bool,
    synthesize: bool,
    token_budget: int | float | None = None,
) -> int:
    """Resolve an orchestration's total spawn budget.

    Precedence:
      1. explicit ``max_spawns`` (clamped to the conservative 48 ceiling);
      2. opt-in ``token_budget`` (TRUSTED only) → scale to budget up to the
         higher ``_ORCH_MAX_SPAWNS_BUDGET_CEILING``;
      3. default → ``n*rounds`` estimate, hard-capped at 48 (unchanged).

    Pure function so the budget policy is unit-testable without spawning agents.
    """
    if max_spawns is not None:
        try:
            explicit = int(max_spawns)
        except (TypeError, ValueError):
            explicit = n * rounds
        return max(n, min(_ORCH_MAX_SPAWNS_CEILING, explicit))
    if token_budget is not None:
        from runtime.execution.suckers.delegation_budget import (
            max_spawns_for_token_budget,
        )

        return max(
            n,
            max_spawns_for_token_budget(token_budget, ceiling=_ORCH_MAX_SPAWNS_BUDGET_CEILING),
        )
    verify_cost = n * rounds * _ORCH_VERIFY_VOTERS if verify else 0
    synth_cost = 1 if synthesize else 0
    planned = n * rounds + verify_cost + synth_cost
    return min(_ORCH_MAX_SPAWNS_CEILING, max(n, planned))


_NULL_FINDING_TOKENS = frozenset(
    {
        "none",
        "n/a",
        "na",
        "nothing",
        "no new findings",
        "no findings",
        "(none)",
    }
)
# A LEADING list marker only: a bullet, or an enumerator like "1." / "2)" /
# "(3)" / "4、" followed by a space. Deliberately NOT a bare digit run, so a
# finding whose content starts with a number ("3 retries observed") is kept
# intact rather than mangled.
_LIST_MARKER = re.compile(r"^\s*(?:[-*•·]|\(?\d{1,3}[.)）、])\s+")
# Markdown noise a real model emits around a list (observed live): horizontal
# rules (--- *** ===), ATX headings (## Foo), and lines that are entirely one
# bold/emphasis span used as a section label (**Critical issues**). A finding
# that merely CONTAINS bold ("**Always** validate") is kept — only whole-line
# emphasis is dropped.
_NOISE_LINE = re.compile(
    r"^(?:[-*=_~#]{3,}|#{1,6}\s.*|\*\*[^*]+\*\*|__[^_]+__|\*[^*]+\*)$",
)


def _split_findings(
    output: str,
    *,
    max_items: int = _ORCH_MAX_FINDINGS_PER_WORKER,
) -> list[str]:
    """One finding per line; strip a leading list marker, drop null markers and
    markdown noise (rules / headings / section labels), and cap how many lines a
    single worker can contribute (runaway guard)."""
    out: list[str] = []
    for line in (output or "").splitlines():
        s = _LIST_MARKER.sub("", line.strip()).strip()
        if not s or s.lower() in _NULL_FINDING_TOKENS or _NOISE_LINE.match(s):
            continue
        out.append(s)
        if len(out) >= max_items:
            break
    return out


def _norm_finding(s: str) -> str:
    return " ".join((s or "").lower().split())


def _dedupe_findings(items: list[str], seen_norms: set[str]) -> list[str]:
    """Return the items whose normalised form hasn't been seen; updates seen."""
    fresh: list[str] = []
    for it in items:
        key = _norm_finding(it)
        if key and key not in seen_norms:
            seen_norms.add(key)
            fresh.append(it)
    return fresh


# Finders return a JSON array of atomic findings; call_subagent validates it
# (and re-asks once on mismatch). Structured output replaces the brittle
# one-finding-per-line text parsing — the array survives multi-line findings,
# prose wrappers and markdown that _split_findings would mangle or drop.
_FINDER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "findings": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["findings"],
}


def _findings_from_success(s: dict[str, Any]) -> list[str]:
    """Extract one worker's findings, preferring the schema-validated array and
    falling back to legacy one-per-line parsing when no parsed object is present
    (schema disabled, or it failed after the retry). The per-worker cap and
    null-marker filter apply on both paths."""
    parsed = s.get("parsed")
    if isinstance(parsed, dict) and isinstance(parsed.get("findings"), list):
        out: list[str] = []
        for raw in parsed["findings"]:
            txt = str(raw).strip()
            if not txt or txt.lower() in _NULL_FINDING_TOKENS:
                continue
            out.append(txt)
            if len(out) >= _ORCH_MAX_FINDINGS_PER_WORKER:
                break
        return out
    return _split_findings(str(s.get("output") or ""))


def _finder_prompt(goal: str, seen: list[str]) -> str:
    base = (
        "You are one worker in a parallel discovery pass.\n\n"
        f"GOAL:\n{goal}\n\n"
        "Report your findings as JSON: a `findings` array where each element is "
        "ONE atomic finding (a short string). No preamble or commentary — just "
        'the findings. If you have nothing, return {"findings": []}.'
    )
    if seen:
        shown = "\n".join(f"- {s}" for s in seen[:40])
        base += (
            "\n\nAlready found — do NOT repeat these; include only genuinely "
            "NEW ones (or an empty array if you have nothing new):\n"
            f"{shown}"
        )
    return base


def _synthesis_prompt(goal: str, findings: list[str]) -> str:
    """Prompt for the single synthesizer that closes an orchestration: turn the
    confirmed findings into one coherent answer. The closing step my own
    fan-out harness always has — without it ``run_orchestration`` hands back a
    bag of findings and makes the caller synthesize."""
    numbered = "\n".join(f"{i + 1}. {f}" for i, f in enumerate(findings))
    return (
        "You are the synthesizer at the end of a parallel discovery + "
        "verification pass. Combine the CONFIRMED FINDINGS below into ONE "
        "coherent, non-redundant answer to the GOAL. Merge overlaps, order by "
        "importance, and add nothing that is not supported by a finding.\n\n"
        f"GOAL:\n{goal}\n\n"
        f"CONFIRMED FINDINGS:\n{numbered}\n\n"
        "Return the synthesized answer as plain text — no preamble."
    )


def _coerce_roles(agent_id: Any) -> list[str]:
    """Normalise ``agent_id`` into a worker-role roster (deduped, order kept).
    A LIST gives heterogeneous lenses (e.g. researcher + explorer + critic)
    that are rotated across the per-round workers — diverse lenses surface more
    than N copies of one role (the multi-modal-sweep principle)."""
    raw = agent_id if isinstance(agent_id, (list, tuple)) else [agent_id]
    roles: list[str] = []
    for entry in raw:
        if entry is None:
            continue
        role = str(entry).strip()
        if role and role not in roles:
            roles.append(role)
    return roles or ["researcher"]


def _run_orchestration(
    goal: str = "",
    *,
    agent_id: str | list[str] = "researcher",
    n: int | str = 3,
    rounds: int | str = 2,
    patience: int | str = 1,
    verify: bool = False,
    synthesize: bool = False,
    choices: Any = None,
    max_spawns: int | str | None = None,
    timeout_s: int | str = _DEFAULT_SUBAGENT_TIMEOUT_S,
    context: dict[str, Any] | None = None,
    session: Any = None,
    **_kw: Any,
) -> dict[str, Any]:
    """Run a deterministic discovery loop: fan out ``n`` workers per round,
    split + dedupe their findings, loop up to ``rounds`` (stopping early after
    ``patience`` dry rounds), optionally vote-verify each finding, and
    optionally synthesize the confirmed findings into one coherent answer. The
    whole run is bounded by a spawn budget so it can't run away.
    """
    goal = str(goal or _kw.get("prompt") or _kw.get("task") or _kw.get("query") or "").strip()
    if not goal:
        return {
            "ok": False,
            "error": "goal is required",
            "collected": [],
            "confirmed": [],
            "count": 0,
        }

    def _clamp(value: Any, lo: int, hi: int, default: int) -> int:
        try:
            return max(lo, min(hi, int(value)))
        except (TypeError, ValueError):
            return default

    n = _clamp(n, 1, 6, 3)
    rounds = _clamp(rounds, 1, 5, 2)
    patience = _clamp(patience, 0, 3, 1)
    # LLM callers pass booleans as strings ("true"/"false") just as often as
    # real bools; normalise so ``synthesize="false"`` doesn't read truthy.
    synthesize = str(synthesize).strip().lower() not in (
        "",
        "0",
        "false",
        "no",
        "off",
        "none",
    )
    # Opt-in budget-driven depth, from TRUSTED sources only — never the model's
    # call args (or a model could raise its own cap):
    #   1. per-turn: ``session.metadata["orchestration_token_budget"]`` (set by
    #      the bus / audit.ultracode path);
    #   2. deployment-wide: the ``OCTOPUS_ORCH_TOKEN_BUDGET`` operator env.
    # Per-turn wins; absent both, the conservative n*rounds / 48 default holds.
    _orch_token_budget: Any = None
    try:
        _sess_meta = getattr(session, "metadata", None)
        if isinstance(_sess_meta, dict):
            _orch_token_budget = _sess_meta.get("orchestration_token_budget")
    except (AttributeError, TypeError):
        _orch_token_budget = None
    if _orch_token_budget is None:
        from runtime.execution.suckers.delegation_budget import (
            operator_orchestration_token_budget,
        )

        _orch_token_budget = operator_orchestration_token_budget()
    max_spawns = _resolve_max_spawns(
        max_spawns,
        n=n,
        rounds=rounds,
        verify=verify,
        synthesize=synthesize,
        token_budget=_orch_token_budget,
    )
    roles = _coerce_roles(agent_id)

    # Outer gate: an orchestration costs ONE against the per-turn cap so the
    # model can't spawn unboundedly by launching many orchestrations.
    parent_sess, turn_id = _resolve_session_and_turn()
    if session is None:
        session = parent_sess
    _, within = _check_absolute_cap(turn_id)
    if not within:
        return {
            "ok": False,
            "error": (
                "delegation budget exhausted for this turn — do the rest "
                "yourself, don't launch another orchestration."
            ),
            "collected": [],
            "confirmed": [],
            "count": 0,
        }
    fingerprint = _compute_fingerprint("run_orchestration", goal)
    _record_delegation(turn_id, fingerprint, succeeded=True)

    ballot = _coerce_vote_choices(choices) or ["keep", "drop"]
    seen_norms: set[str] = set()
    collected: list[str] = []
    per_round: list[int] = []
    dry = 0
    stopped = "rounds"

    # Blackboard coordination: publish the evolving findings to the turn's
    # shared blackboard so sibling agents — and a later orchestration on the
    # same goal — build on them instead of re-discovering. Stigmergic
    # coordination the harness ENFORCES (the orchestrator reads/publishes),
    # not something the model must remember to do. No turn / no board (unit
    # tests) → a no-op; best-effort throughout, never breaks the run.
    from runtime.memory.runtime_state.blackboard import get_blackboard

    board = get_blackboard(turn_id)
    bb_key = f"orchestration.findings.{fingerprint}"
    inherited = 0
    if board is not None:
        try:
            prior = board.read(bb_key, None)
            if isinstance(prior, list) and prior:
                seed = [str(x) for x in prior if str(x).strip()]
                seed = seed[:_ORCH_MAX_FINDINGS_TOTAL]
                _dedupe_findings(seed, seen_norms)  # seed the dedup set
                collected.extend(seed)
                inherited = len(seed)
        except Exception:  # noqa: BLE001 — sharing must never break the run
            pass

    def _publish(findings: list[str]) -> None:
        if board is None:
            return
        # Sharing must never break the run.
        with contextlib.suppress(Exception):
            board.write(bb_key, list(findings), writer="run_orchestration")

    with _orchestration_budget_scope(int(max_spawns)) as budget:
        for _ in range(int(rounds)):
            if not budget.has_room():
                stopped = "budget"
                break
            env = _call_agent_parallel(
                specs=[
                    {
                        "agent_id": roles[i % len(roles)],
                        "prompt": _finder_prompt(goal, collected),
                        "output_schema": _FINDER_SCHEMA,
                    }
                    for i in range(n)
                ],
                timeout_s=timeout_s,
                context=context,
                session=session,
            )
            items: list[str] = []
            for s in env.get("successes", []):
                items.extend(_findings_from_success(s))
            fresh = _dedupe_findings(items, seen_norms)
            per_round.append(len(fresh))
            if not fresh:
                dry += 1
                if dry > patience:
                    stopped = "dry"
                    break
                continue
            dry = 0
            collected.extend(fresh)
            _publish(collected)  # share this round's progress on the blackboard
            if len(collected) >= _ORCH_MAX_FINDINGS_TOTAL:
                del collected[_ORCH_MAX_FINDINGS_TOTAL:]
                stopped = "cap"
                break

        confirmed = list(collected)
        synthesis = ""
        verified = False
        unverified = 0
        if verify and collected:
            verified = True
            voters = _ORCH_VERIFY_VOTERS
            # Deterministic budget split: verify as many findings as the
            # remaining spawn budget affords (each vote spends ``voters``); the
            # rest are kept but flagged unverified. WHICH findings get verified
            # is deterministic (the first ``affordable``); only the verdicts
            # vary with the model — as verification inherently must.
            affordable = max(0, budget.remaining() // voters)
            to_verify = collected[:affordable]
            unverified = len(collected) - len(to_verify)

            def _verdict_for(finding: str) -> str | None:
                try:
                    vote = _call_agent_vote(
                        question=f"Is this finding correct and worth keeping?\n\n{finding}",
                        n=voters,
                        choices=ballot,
                        timeout_s=timeout_s,
                        context=context,
                        session=session,
                    )
                    return vote.get("verdict")
                except Exception:  # noqa: BLE001 — a failed vote keeps the finding
                    return None

            verdicts: list[str | None] = [None] * len(to_verify)
            if to_verify:
                import concurrent.futures as _cf
                import contextvars as _ctxvars

                pool_workers = max(1, min(4, len(to_verify)))
                with _cf.ThreadPoolExecutor(
                    max_workers=pool_workers,
                    thread_name_prefix="orch-verify",
                ) as pool:
                    # copy_context per task so each pool thread sees the ambient
                    # orchestration budget (a ContextVar doesn't auto-propagate
                    # into pool workers); the votes then charge the same envelope.
                    futures = {
                        pool.submit(_ctxvars.copy_context().run, _verdict_for, f): idx
                        for idx, f in enumerate(to_verify)
                    }
                    for fut in _cf.as_completed(futures):
                        verdicts[futures[fut]] = fut.result()

            # Drop only on an explicit majority "drop"; ties/no-verdict keep.
            kept = [f for f, v in zip(to_verify, verdicts, strict=True) if v != ballot[-1]]
            confirmed = kept + collected[len(to_verify) :]

        # Closing synthesis: one spawn folds the confirmed findings into a
        # single coherent answer (the stage that makes the harness return a
        # usable result, not a bag of findings). Budget-gated like everything
        # else; a failed/empty synthesis leaves ``confirmed`` untouched.
        if synthesize and confirmed and budget.has_room():
            synth_env = _call_agent_parallel(
                specs=[
                    {
                        "agent_id": roles[0],
                        "prompt": _synthesis_prompt(goal, confirmed),
                    }
                ],
                timeout_s=timeout_s,
                context=context,
                session=session,
            )
            synth_succ = synth_env.get("successes", [])
            if synth_succ:
                synthesis = str(synth_succ[0].get("output") or "").strip()
        # Publish the verified set so the shared pool reflects confirmed (not
        # just collected) findings for the rest of the turn.
        _publish(confirmed)
        budget_used = budget.used

    return {
        "ok": True,
        "goal": goal[:240],
        "collected": collected,
        "confirmed": confirmed,
        "count": len(confirmed),
        "rounds_run": len(per_round),
        "fresh_per_round": per_round,
        "verified": verified,
        "unverified": unverified,
        "synthesis": synthesis,
        "shared": board is not None,
        "inherited": inherited,
        "stopped_reason": stopped,
        "budget_used": budget_used,
        "max_spawns": int(max_spawns),
    }


# ── verdict-gated repair loop (produce -> judge -> rewrite -> re-judge) ──
_REPAIR_MAX_REPAIRS_CEILING = 4
_REPAIR_DEFAULT_JUDGE_N = 3


def _run_verdict_repair(
    task: str = "",
    *,
    agent_id: str = "general",
    judge_n: int | str = _REPAIR_DEFAULT_JUDGE_N,
    max_repairs: int | str = 2,
    choices: Any = None,
    timeout_s: int | str = _DEFAULT_SUBAGENT_TIMEOUT_S,
    context: dict[str, Any] | None = None,
    session: Any = None,
    **kw: Any,
) -> dict[str, Any]:
    """Produce → judge → (on FAIL) rewrite-with-critique → re-judge, bounded.

    The verdict-gated repair loop octopus lacked: a worker attempts the task, an
    independent ``call_agent_vote`` judges it, and a rejection drives a corrected
    re-attempt that is *fed the critique* — Orca's PLAN→CRITIQUE→REWRITE closed
    loop, built on octopus's own sub-agent + vote primitives. The control flow
    (loop, stop-on-pass, bound) is deterministic code in
    :func:`runtime.execution.suckers.verdict_repair.run_verdict_repair`.
    """
    from runtime.execution.suckers.verdict_repair import Verdict, run_verdict_repair

    task = str(task or kw.get("goal") or kw.get("prompt") or kw.get("query") or "").strip()
    if not task:
        return {
            "ok": False,
            "error": "task is required",
            "passed": False,
            "output": "",
            "attempts": 0,
            "rounds": [],
        }

    def _clamp(value: Any, lo: int, hi: int, default: int) -> int:
        try:
            return max(lo, min(hi, int(value)))
        except (TypeError, ValueError):
            return default

    n_judge = _clamp(judge_n, _VOTE_MIN, _VOTE_MAX, _REPAIR_DEFAULT_JUDGE_N)
    repairs = _clamp(max_repairs, 0, _REPAIR_MAX_REPAIRS_CEILING, 2)
    # First ballot choice = "accept"; default to a plain pass/fail gate.
    ballot = _coerce_vote_choices(choices) or ["pass", "fail"]
    pass_choice = ballot[0]

    def _produce(attempt: int, critique: str) -> str:
        if attempt == 0 or not critique:
            prompt = task
        else:
            prompt = (
                f"{task}\n\n"
                "An independent reviewer REJECTED your previous attempt for these "
                f"reasons:\n{critique}\n\n"
                "Produce a corrected result that fixes every cited problem. "
                "Return only the result."
            )
        env = _call_agent_parallel(
            specs=[{"agent_id": str(agent_id or "general"), "prompt": prompt}],
            timeout_s=timeout_s,
            context=context,
            session=session,
        )
        successes = env.get("successes") or []
        return str(successes[0].get("output") or "").strip() if successes else ""

    def _judge(output: str) -> Verdict:
        if not output:
            return Verdict(passed=False, label="fail", critique="the attempt produced no output")
        question = (
            "Does the RESULT fully and correctly accomplish the TASK? Answer "
            "'fail' if anything is missing, wrong, or unverified.\n\n"
            f"TASK:\n{task}\n\nRESULT:\n{output}"
        )
        vote = _call_agent_vote(
            question=question,
            n=n_judge,
            choices=ballot,
            timeout_s=timeout_s,
            context=context,
            session=session,
        )
        label = str(vote.get("verdict") or "")
        passed = bool(label) and label == pass_choice
        critique = ""
        if not passed:
            reasons = [
                str(v.get("reason") or "").strip()
                for v in vote.get("votes", [])
                if str(v.get("verdict") or "") != pass_choice and v.get("reason")
            ]
            critique = " ; ".join(r for r in reasons if r)[:600] or (
                "rejected by the reviewers without a specific reason"
            )
        return Verdict(
            passed=passed,
            label=label or "fail",
            critique=critique,
            confidence=float(vote.get("confidence") or 0.0),
        )

    # Bound the whole loop in a spawn budget so the per-turn delegation cap
    # doesn't refuse the repair re-runs (same mechanism the orchestration loop
    # uses): (1 + repairs) producers, each followed by n_judge voters.
    planned = (1 + repairs) * (1 + n_judge)
    max_spawns = _clamp(planned, 1 + n_judge, _ORCH_MAX_SPAWNS_CEILING, planned)
    with _orchestration_budget_scope(int(max_spawns)):
        result = run_verdict_repair(produce=_produce, judge=_judge, max_repairs=repairs)

    final = result.final_verdict
    return {
        "ok": True,
        "task": task[:240],
        "passed": result.passed,
        "repaired": result.repaired,
        "output": result.output,
        "attempts": result.attempts,
        "verdict": final.label if final else "",
        "confidence": final.confidence if final else 0.0,
        "rounds": [
            {
                "attempt": r.attempt,
                "passed": r.verdict.passed,
                "verdict": r.verdict.label,
                "critique": r.verdict.critique,
            }
            for r in result.rounds
        ],
        "max_spawns": int(max_spawns),
    }


# ── tournament: N isolated candidates -> judge -> pick the best ─────────
_TOURNAMENT_MAX_CANDIDATES = 5


def _run_tournament(
    goal: str = "",
    *,
    n: int | str = 3,
    agent_id: str = "worktree_writer",
    judge_n: int | str = 3,
    repo_root: str | None = None,
    timeout_s: int | str = _DEFAULT_SUBAGENT_TIMEOUT_S,
    max_workers: int | str = 4,
    context: dict[str, Any] | None = None,
    session: Any = None,
    **kw: Any,
) -> dict[str, Any]:
    """Run the SAME goal as N isolated git-worktree candidates, then judge-pick
    the best diff — the missing half on top of octopus's existing worktree
    isolation. Reuses ``run_worktree_loop`` (each candidate edits in its own
    worktree, no collisions) + ``call_agent_vote`` (an independent panel picks
    the winner); the selection logic is deterministic in
    ``subagents.tournament.select_winner``. Never auto-applies — the winner's
    diff is returned for review (reconciling parallel edits is a human call).
    """
    import os

    from runtime.execution.subagents.tournament import Candidate, select_winner
    from runtime.execution.subagents.worktree_loop import (
        is_git_repo,
        run_worktree_loop,
        subagent_worktree_worker,
    )

    goal = str(goal or kw.get("task") or kw.get("prompt") or "").strip()
    if not goal:
        return {
            "ok": False,
            "error": "goal is required",
            "winner": None,
            "candidates": [],
            "decided_by": "none",
        }

    def _clamp(value: Any, lo: int, hi: int, default: int) -> int:
        try:
            return max(lo, min(hi, int(value)))
        except (TypeError, ValueError):
            return default

    root = str(repo_root or os.getcwd())
    if not is_git_repo(root):
        return {
            "ok": False,
            "error": f"not a git repo: {root}",
            "winner": None,
            "candidates": [],
            "decided_by": "none",
        }

    n_cand = _clamp(n, 2, _TOURNAMENT_MAX_CANDIDATES, 3)
    n_judge = _clamp(judge_n, _VOTE_MIN, _VOTE_MAX, 3)

    worker = subagent_worktree_worker(agent_id=str(agent_id or "worktree_writer"))
    loop = run_worktree_loop(
        root,
        [goal] * n_cand,
        worker,
        max_workers=_clamp(max_workers, 1, n_cand, n_cand),
    )
    results = loop.get("results") or []
    candidates = [
        Candidate(
            id=f"candidate_{r.get('index', i) + 1}",
            output=str(r.get("diff") or ""),
            ok=bool(r.get("ok")),
            meta={
                "files": r.get("files") or [],
                "branch": r.get("branch"),
                "error": r.get("error"),
            },
        )
        for i, r in enumerate(results)
    ]

    def _judge(viable: list[Candidate]) -> str | None:
        blocks: list[str] = []
        for c in viable:
            files = ", ".join(str(f) for f in (c.meta.get("files") or [])) or "(no files)"
            diff = (c.output or "")[:2000]
            blocks.append(f"### {c.id} — files: {files}\n{diff}")
        question = (
            "Each candidate independently attempted the SAME goal in isolation. "
            "Which ONE best and most correctly accomplishes it? Weigh "
            "correctness, completeness, and simplicity.\n\n"
            f"GOAL:\n{goal}\n\n" + "\n\n".join(blocks)
        )
        vote = _call_agent_vote(
            question=question,
            n=n_judge,
            choices=[c.id for c in viable],
            timeout_s=timeout_s,
            context=context,
            session=session,
        )
        return str(vote.get("verdict") or "") or None

    # The judge's voters go through the delegation path → bound them in a spawn
    # budget so the per-turn cap doesn't refuse them. The worktree candidates run
    # under their own concurrency cap, before the judge.
    with _orchestration_budget_scope(n_judge + 1):
        result = select_winner(candidates, _judge)

    winner = result.winner
    return {
        "ok": winner is not None,
        "goal": goal[:240],
        "decided_by": result.decided_by,
        "candidate_count": len(candidates),
        "viable_count": result.viable_count,
        "winner": (
            {
                "id": winner.id,
                "files": list(winner.meta.get("files") or []),
                "branch": winner.meta.get("branch"),
                "diff": winner.output,
            }
            if winner
            else None
        ),
        "candidates": [
            {
                "id": c.id,
                "ok": c.ok,
                "viable": c.viable,
                "files": list(c.meta.get("files") or []),
                "error": c.meta.get("error"),
            }
            for c in candidates
        ],
        "note": "diffs are NOT auto-applied — review the winner and apply it yourself",
    }


# ── cli_team: a team of EXTERNAL CLI agents (Claude/Codex) ──────────────
def _run_cli_team(
    goal: str = "",
    *,
    members: Any = None,
    judge: bool = True,
    judge_n: int | str = 3,
    repo_root: str | None = None,
    context: dict[str, Any] | None = None,
    session: Any = None,
    **kw: Any,
) -> dict[str, Any]:
    """Run a team of the user's OWN external coding-agent CLIs (Claude Code /
    Codex) in parallel — each in its own isolated git worktree, briefed from and
    harvesting to the shared blackboard — then judge-pick the best diff. Detects
    installed CLIs automatically; never auto-merges (returns the winning diff for
    review). The Conductor/orca pattern on octopus's pieces."""
    import os

    from runtime.execution.agents.cli_team import detect_installed_partners, run_cli_team
    from runtime.execution.subagents.tournament import Candidate, select_winner

    goal = str(goal or kw.get("task") or kw.get("prompt") or "").strip()
    if not goal:
        return {"ok": False, "error": "goal is required", "members": [], "winner": None}

    mems = members if isinstance(members, list) and members else detect_installed_partners()
    if not mems:
        return {
            "ok": False,
            "error": "no installed coding-agent CLI detected (install Claude Code or Codex)",
            "members": [],
            "winner": None,
        }

    root = str(repo_root or os.getcwd())
    turn_id = None
    if isinstance(context, dict):
        turn_id = context.get("turn_id") or context.get("thread_id")
    turn_id = turn_id or os.environ.get("OCTOPUS_TURN_ID")

    result = run_cli_team(goal, mems, repo_root=root, turn_id=turn_id)
    members_out = result.get("members") or []

    def _judge_int(value: Any, default: int) -> int:
        try:
            return max(_VOTE_MIN, min(_VOTE_MAX, int(value)))
        except (TypeError, ValueError):
            return default

    winner: dict[str, Any] | None = None
    viable = [m for m in members_out if m.get("ok") and str(m.get("diff") or "").strip()]
    if str(judge).strip().lower() not in ("false", "0", "no", "off") and len(viable) > 1:
        n_judge = _judge_int(judge_n, 3)
        cands = [
            Candidate(
                id=str(m["agent_id"]),
                output=str(m.get("diff") or ""),
                ok=bool(m.get("ok")),
                meta={"files": m.get("files") or []},
            )
            for m in members_out
        ]

        def _judge(viable_cands: list[Candidate]) -> str | None:
            blocks = [f"### {c.id}\n{(c.output or '')[:2000]}" for c in viable_cands]
            question = (
                "Several CLI agents each attempted the SAME goal in isolation. Which "
                "diff best and most correctly accomplishes it? Weigh correctness, "
                f"completeness, simplicity.\n\nGOAL:\n{goal}\n\n" + "\n\n".join(blocks)
            )
            vote = _call_agent_vote(
                question=question,
                n=n_judge,
                choices=[c.id for c in viable_cands],
                context=context,
                session=session,
            )
            return str(vote.get("verdict") or "") or None

        with _orchestration_budget_scope(n_judge + 1):
            sel = select_winner(cands, _judge)
        if sel.winner is not None:
            winner = {
                "agent_id": sel.winner.id,
                "files": list(sel.winner.meta.get("files") or []),
                "diff": sel.winner.output,
                "decided_by": sel.decided_by,
            }

    return {
        "ok": bool(result.get("ok")),
        "goal": goal[:240],
        "count": result.get("count", 0),
        "succeeded": result.get("succeeded", 0),
        "members": [
            {
                "agent_id": m.get("agent_id"),
                "partner_id": m.get("partner_id"),
                "ok": m.get("ok"),
                "files": m.get("files") or [],
                "error": m.get("error"),
            }
            for m in members_out
        ],
        "winner": winner,
        "note": "diffs are NOT merged — review (or apply the winner's diff) yourself",
    }


_PIPELINE_MAX_ITEMS = 16
_PIPELINE_MAX_STAGES = 4


def _run_pipeline(
    items: list[Any] | str | None = None,
    *,
    stages: list[dict[str, Any]] | None = None,
    default_agent_id: str = "researcher",
    timeout_s: int | str = _DEFAULT_SUBAGENT_TIMEOUT_S,
    context: dict[str, Any] | None = None,
    session: Any = None,
    **_kw: Any,
) -> dict[str, Any]:
    """Process each item through ordered stages independently and concurrently.

    Unlike ``call_agent_parallel`` (which fans out identical agents on
    independent specs), ``run_pipeline`` chains stages for EACH item:
    item-A runs stage1 → stage2 → stage3 while item-B is still in stage1.
    Wall-clock = max(slowest single-item chain), not sum-of-slowest-per-stage.

    Each stage prompt template may use:
        {item}   — the original item value
        {prev}   — the previous stage's output (empty for stage 0)
        {stage0_output}, {stage1_output}, ... — any prior stage's output

    Stage failure halts that item's chain; remaining stages are skipped.
    """
    import concurrent.futures as _cf
    import contextvars as _ctxvars

    from runtime.execution.subagents import call_subagent

    # ── coerce items ─────────────────────────────────────────────────
    if isinstance(items, str):
        try:
            import json as _json

            _parsed = _json.loads(items)
            items = _parsed if isinstance(_parsed, list) else [items]
        except Exception:  # noqa: BLE001
            items = [items]

    if not items or not isinstance(items, list):
        return {
            "ok": False,
            "error": "items is required (list of strings or dicts)",
            "results": [],
            "success_count": 0,
            "failure_count": 0,
            "total": 0,
            "stages_run": 0,
        }

    # ── coerce stages ────────────────────────────────────────────────
    if not stages or not isinstance(stages, list):
        return {
            "ok": False,
            "error": "stages is required (list of {prompt_template, agent_id?})",
            "results": [],
            "success_count": 0,
            "failure_count": 0,
            "total": len(items),
            "stages_run": 0,
        }

    items = list(items[:_PIPELINE_MAX_ITEMS])
    stages = list(stages[:_PIPELINE_MAX_STAGES])
    timeout_s = _coerce_timeout_s(timeout_s)
    default_role = str(default_agent_id or "researcher").strip() or "researcher"

    # ── delegation budget ─────────────────────────────────────────────
    parent_sess, turn_id = _resolve_session_and_turn()
    if session is None:
        session = parent_sess
    _, within = _check_absolute_cap(turn_id)
    if not within:
        return {
            "ok": False,
            "error": (
                "delegation budget exhausted for this turn — do the rest "
                "yourself, don't launch another pipeline."
            ),
            "results": [],
            "success_count": 0,
            "failure_count": 0,
            "total": len(items),
            "stages_run": 0,
        }
    _record_delegation(
        turn_id,
        _compute_fingerprint("run_pipeline", str(items[:3])),
        succeeded=True,
    )

    max_spawns = len(items) * len(stages)

    # ── per-item chain worker ────────────────────────────────────────
    def _run_item_chain(item: Any) -> dict[str, Any]:
        item_str = item if isinstance(item, str) else str(item)
        stage_outputs: list[dict[str, Any]] = []
        prev = ""
        chain_ok = True

        for s_idx, stage_spec in enumerate(stages):
            if not chain_ok:
                # Previous stage failed — skip remaining stages for this item
                stage_outputs.append(
                    {
                        "stage": s_idx,
                        "agent_id": str(stage_spec.get("agent_id") or default_role),
                        "output": "",
                        "ok": False,
                        "skipped": True,
                    }
                )
                continue

            tmpl = str(stage_spec.get("prompt_template") or stage_spec.get("prompt") or "").strip()
            if not tmpl:
                stage_outputs.append(
                    {
                        "stage": s_idx,
                        "agent_id": str(stage_spec.get("agent_id") or default_role),
                        "output": "",
                        "ok": False,
                        "error": "prompt_template is required for this stage",
                    }
                )
                chain_ok = False
                continue

            # Build substitution context from prior stage outputs
            sub_ctx: dict[str, str] = {"item": item_str, "prev": prev}
            for i, prior in enumerate(stage_outputs):
                sub_ctx[f"stage{i}_output"] = str(prior.get("output") or "")
            try:
                prompt = tmpl.format_map(sub_ctx)
            except (KeyError, ValueError):
                prompt = tmpl  # unknown placeholder — use template raw

            role = str(stage_spec.get("agent_id") or default_role).strip() or default_role
            stage_budget = _current_orchestration_budget()
            if stage_budget is not None and not stage_budget.try_charge():
                stage_outputs.append(
                    {
                        "stage": s_idx,
                        "agent_id": role,
                        "output": "",
                        "ok": False,
                        "error": _delegation_budget_exhausted_message(
                            stage_budget.used,
                            budget=stage_budget,
                            action="This pipeline stage was not spawned.",
                        ),
                        "error_type": "budget_exhausted",
                    }
                )
                chain_ok = False
                continue

            try:
                result = call_subagent(
                    agent_id=role,
                    prompt=prompt,
                    context=context,
                    timeout_s=timeout_s,
                    session=session,
                )
            except Exception as exc:  # noqa: BLE001
                result = {
                    "success": False,
                    "output": "",
                    "error": f"{type(exc).__name__}: {exc}",
                }

            ok = bool(result.get("success"))
            out = str(result.get("output") or "")
            entry: dict[str, Any] = {
                "stage": s_idx,
                "agent_id": role,
                "output": out,
                "ok": ok,
            }
            if not ok:
                entry["error"] = result.get("error") or "subagent failed"
            stage_outputs.append(entry)

            if ok:
                prev = out
            else:
                chain_ok = False

        return {
            "item": item_str,
            "stages": stage_outputs,
            "final_output": prev,
            "ok": chain_ok,
        }

    # ── concurrent fan-out of item chains ───────────────────────────
    item_results: list[dict[str, Any]] = []
    max_workers = min(len(items), 8)

    with (
        _orchestration_budget_scope(max_spawns),
        _cf.ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="pipeline",
        ) as pool,
    ):
        # copy_context so each worker thread inherits the orchestration
        # budget ContextVar from the calling thread.
        futures = {
            pool.submit(_ctxvars.copy_context().run, _run_item_chain, it): it for it in items
        }
        done, not_done = _cf.wait(
            futures.keys(),
            timeout=timeout_s * len(stages) + 30,
            return_when=_cf.ALL_COMPLETED,
        )
        for f in done:
            try:
                item_results.append(f.result(timeout=1))
            except Exception as exc:  # noqa: BLE001
                it = futures.get(f, "")
                item_results.append(
                    {
                        "item": str(it),
                        "stages": [],
                        "final_output": "",
                        "ok": False,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
        for f in not_done:
            f.cancel()
            it = futures.get(f, "")
            item_results.append(
                {
                    "item": str(it),
                    "stages": [],
                    "final_output": "",
                    "ok": False,
                    "error": "timeout",
                }
            )

    # Restore original insertion order
    _order = {(it if isinstance(it, str) else str(it)): i for i, it in enumerate(items)}
    item_results.sort(key=lambda r: _order.get(r["item"], 9999))

    success_count = sum(1 for r in item_results if r["ok"])
    return {
        "ok": success_count > 0,
        "results": item_results,
        "success_count": success_count,
        "failure_count": len(item_results) - success_count,
        "total": len(items),
        "stages_run": len(stages),
    }


def register_delegation_skills(registry: SkillRegistry) -> int:
    """Register `call_agent` for sub-agent delegation. Returns count.

    The description is generated each time so a re-register reflects
    the current advertised role catalog. App boot sequence:
    ``register_all`` first (registers with builtin advertisements),
    then ``set_subagent_registry`` + ``register_delegation_skills``
    again (to refresh, though user defs aren't advertised here ·
    they remain callable).
    """
    role_table = _format_role_catalog()
    description = (
        "Spawn an isolated specialist subagent for one focused "
        "subtask. The subagent runs in its own context window with "
        "its own tools, runs ONE turn, returns a single summary "
        "string back to you. This tool exists and works · the "
        "guidance below is about WHEN to use it, not whether you "
        "have it.\n"
        "\n"
        "Frequency: this is an EXCEPTION tool in normal chat/code turns, "
        "not a default reflex. In explicit `swarm` mode it may be used as "
        "part of a dynamic orchestration plan when the task is large enough. "
        "Most tasks lead handles itself. Hard cap is 1 call per "
        "turn — if you need delegation again on the same turn, the "
        "second call returns an error · do that work yourself.\n"
        "\n"
        "Use it when ALL three are true:\n"
        "  1. The subtask falls inside an advertised specialist "
        "role.\n"
        "  2. The lead's general competence is genuinely "
        "insufficient — you've thought about it for at least one "
        "turn first.\n"
        "  3. You haven't already used `call_agent` this turn.\n"
        "\n"
        "Skip delegation (do it yourself with normal tools) for:\n"
        "  - Anything you can finish in ≤ 2 more turns.\n"
        "  - Code work touching ≤ 3 files (read / edit / debug).\n"
        "  - Web research / fact lookup → use `web_search`.\n"
        "  - 'I don't know how to start' reflex → just start.\n"
        "  - Asking the user a clarifying question → reply directly.\n"
        "\n"
        "When the user asks for MULTIPLE delegations in one turn: "
        "pick the single most-specialist task and delegate that, "
        "then handle the rest yourself in the same turn. Tell the "
        "user what you split. Don't refuse the whole request — "
        "delegate one, do the others.\n"
        "\n"
        "Args: {agent_id: string (one of the names below), "
        "prompt: string (focused brief, written like a user message), "
        "skills?/tools?: list of concrete skill names, "
        "skill_pack(s)?: one or more of research/web/browser/files/code/"
        "review/write/memory/shell, plugins?: plugin or package hints, "
        "output_schema?: a JSON Schema object — pass it when you need the "
        "subagent's answer as a validated JSON object you can parse "
        "(returned under `parsed`), e.g. "
        '{"type":"object","properties":{"verdict":{"type":"string"}},'
        '"required":["verdict"]}}. '
        "Use skill packs when the subtask needs tools beyond the role's "
        "default allowlist.\n"
        "\n"
        "Advertised specialist roles:\n"
        f"{role_table}"
    )
    registry.register(
        Skill(
            name="call_agent",
            description=description,
            affinity=["delegation", "subagent", "task", "last-resort"],
            cost_profile="high",  # spawns a separate LLM turn
            trusted_source="skill://public/call_agent",
            handler=_call_agent,
            tests=[
                SkillTestCase(
                    name="missing_agent_id_returns_error",
                    tier="golden",
                    args={"agent_id": "", "prompt": "hi"},
                    expect=SkillExpect(
                        schema_keys=[
                            "agent_id",
                            "output",
                            "success",
                            "error",
                        ]
                    ),
                    custom_predicate=lambda r: (
                        isinstance(r, dict)
                        and r.get("success") is False
                        and "agent_id is required" in (r.get("error") or "")
                    ),
                ),
            ],
        ),
        replace=True,
    )

    # ── parallel variant ─────────────────────────────────────
    parallel_description = (
        "Spawn N sub-agents CONCURRENTLY (Kimi-style swarm) for tasks "
        "that decompose cleanly into independent sub-tasks each "
        "needing a specialist. All siblings + lead share a turn-scoped "
        "blackboard (bb_read / bb_write / bb_keys) so they can exchange "
        "partial findings.\n"
        "\n"
        "Availability: this is a real parallel delegation tool in ordinary "
        "Agent/ReAct mode as well as explicit swarm mode. In Agent mode, use "
        "it when multiple independent lanes would materially improve speed "
        "or quality; the lead remains responsible for synthesis and final "
        "delivery.\n"
        "\n"
        "Use it when:\n"
        "  - The task is genuinely parallel (research lanes, file areas, "
        "vendor comparisons, review lanes), AND\n"
        "  - Each sub-task fits an advertised specialist role, AND\n"
        "  - The lead can integrate the returned summaries into a final "
        "deliverable in the same turn.\n"
        "\n"
        "Skip if:\n"
        "  - Sub-tasks are sequential (each depends on previous output) — "
        "use serial reasoning instead.\n"
        "  - You'd just be parallelizing trivial work — overhead > gain.\n"
        "  - A single web_search/read_file pass is enough.\n"
        "\n"
        "Swarm workflow hint: update todo_write first, assign independent "
        "roles dynamically, ask workers to bb_write compact findings under "
        "clear keys, then bb_keys/bb_read, synthesize, verify/cross-check, "
        "and produce the final answer or file deliverable. Do NOT stop after "
        "the parallel call with only raw worker logs.\n"
        "\n"
        "Honesty contract: if the returned envelope has ``partial=True`` or "
        "``failed > 0``, your final answer MUST include a brief run-status "
        'line such as "Subagent status: 3/5 succeeded; 2 failed" and MUST '
        "not say that all lanes completed. Name the failed lanes from "
        "``failures[].task_label`` / ``failures[].agent_id`` and either "
        "disclose the gap or explicitly describe how you filled it yourself.\n"
        "\n"
        "Budget (2026-06 smart-budget): Each spec counts independently. "
        "First-time failures are FREE (you can fix and retry). Repeat "
        "failures (same agent + same prompt) count. Absolute cap: 5 "
        "delegations/turn. Wall-clock = max(per-agent time), not sum.\n"
        "\n"
        "Args: {specs: list[{agent_id: string, prompt: string, "
        "skills?/tools?: list of concrete skill names, "
        "skill_pack(s)?: research/web/browser/files/code/review/write/"
        "memory/shell, plugins?: plugin/package hints}], "
        "timeout_s?: int (per-agent, default 900)}.\n"
        "\n"
        "Returns: {ok, successes:[{role, agent_id, output, files_touched}], "
        "failures:[{role, agent_id, error, error_type}], partial, total, "
        "success_count, notes:[...], plus legacy keys "
        "(results, count, succeeded, failed, outputs)}. ``ok=False`` only "
        "when zero workers succeed — partial failures still return ok=True "
        "with the surviving outputs and a [partial-degradation] note in "
        "``notes`` so you can synthesise from what came back.\n"
        "\n"
        "Available specialist roles (same as call_agent):\n"
        f"{role_table}"
    )
    registry.register(
        Skill(
            name="call_agent_parallel",
            description=parallel_description,
            affinity=["delegation", "subagent", "parallel", "swarm"],
            cost_profile="high",  # spawns N separate LLM turns
            trusted_source="skill://public/call_agent_parallel",
            handler=_call_agent_parallel,
            tests=[
                SkillTestCase(
                    name="empty_specs_returns_error",
                    tier="golden",
                    args={"specs": []},
                    expect=SkillExpect(
                        schema_keys=[
                            "ok",
                            "successes",
                            "failures",
                            "partial",
                            "total",
                            "success_count",
                            "notes",
                            "results",
                            "count",
                            "outputs",
                            "error",
                        ]
                    ),
                    custom_predicate=lambda r: (
                        isinstance(r, dict)
                        and r.get("count") == 0
                        and r.get("ok") is False
                        and r.get("partial") is False
                        and r.get("successes") == []
                    ),
                ),
            ],
        ),
        replace=True,
    )

    # ── consensus / vote gate ────────────────────────────────
    vote_description = (
        "Verification gate — spawn N INDEPENDENT voters on the SAME "
        "question and tally a MAJORITY verdict (with confidence + dissent). "
        "This is the adversarial-verify / judge-panel pattern: confirm or "
        "refute a claim with independent judgment instead of trusting one "
        "agent.\n"
        "\n"
        "Use it for decisions that matter: 'is this bug real?', 'does this "
        "patch actually fix it?', 'is this answer correct?', 'which option is "
        "safer: A or B?'. A natural pairing is call_agent_parallel (gather "
        "candidate answers) → call_agent_vote (adjudicate them).\n"
        "\n"
        "Each voter runs in its own context and must emit `VERDICT: <choice>` "
        "then `REASON: <one line>`. Unparseable replies count as abstentions; "
        "a split returns verdict=null with tie=true (no decision — you break "
        "it or escalate).\n"
        "\n"
        "Args: {question: string (the claim / question to judge), n?: int "
        "2-5 voters (default 3 · odd avoids ties), choices?: list[string] a "
        'fixed ballot e.g. ["yes","no"] (omit for a free-form verdict), '
        "agent_id?: voter role (default reviewer), timeout_s?: int}.\n"
        "\n"
        "Returns: {ok, verdict (null on tie / no-verdict), confidence (0-1), "
        "unanimous, tie, tie_between, tally:{choice:count}, "
        "votes:[{verdict, reason, codename, abstained}], votes_cast, "
        "abstentions, note, honesty_warning}.\n"
        "\n"
        "Budget: each voter is one delegation against the 5/turn cap, so a "
        "3-voter vote uses 3. Reserve it for decisions worth the spend."
    )
    registry.register(
        Skill(
            name="call_agent_vote",
            description=vote_description,
            affinity=["delegation", "verify", "vote", "consensus", "judge"],
            cost_profile="high",  # spawns N separate LLM turns
            trusted_source="skill://public/call_agent_vote",
            handler=_call_agent_vote,
            tests=[
                SkillTestCase(
                    name="missing_question_returns_error",
                    tier="golden",
                    args={"question": ""},
                    expect=SkillExpect(
                        schema_keys=[
                            "ok",
                            "verdict",
                            "tally",
                            "votes",
                            "note",
                        ]
                    ),
                    custom_predicate=lambda r: (
                        isinstance(r, dict)
                        and r.get("ok") is False
                        and "required" in (r.get("error") or "")
                    ),
                ),
            ],
        ),
        replace=True,
    )

    # ── deterministic orchestration loop ─────────────────────
    orchestrate_description = (
        "Run a DETERMINISTIC multi-round discovery loop end-to-end in one "
        "call: fan out N workers per round, split their findings (one per "
        "line), de-duplicate against everything seen so far, and loop until "
        "no new findings arrive (or the round budget runs out) — optionally "
        "vote-verifying each finding. The control flow (looping, dedup, "
        "stop-when-dry) is code, not the model, so nothing is skipped.\n"
        "\n"
        "Use it for EXHAUSTIVE discovery where one pass isn't enough: 'find "
        "all the edge cases', 'enumerate every place X happens', 'gather "
        "everything known about Y'. This is the loop the flat per-turn cap "
        "normally forbids — it runs inside a bounded spawn budget instead.\n"
        "\n"
        "Args: {goal: string (what to discover), n?: int 1-6 workers/round "
        "(default 3), rounds?: int 1-5 (default 2), patience?: int 0-3 dry "
        "rounds tolerated before stopping (default 1), verify?: bool "
        "(default false — vote-verify each finding), synthesize?: bool "
        "(default false — fold the confirmed findings into ONE coherent "
        "answer via a final synthesizer; returned in `synthesis`), choices?: "
        "[keep,drop]-style ballot for verify, max_spawns?: int total spawn "
        "budget (auto-sized, capped at 48), agent_id?: worker role, or a LIST "
        "of roles rotated across workers for diverse lenses, e.g. "
        "[researcher, explorer, critic] (default researcher)}.\n"
        "\n"
        "Returns: {ok, goal, collected:[...], confirmed:[...] (== collected "
        "unless verify), count, rounds_run, fresh_per_round:[...], verified, "
        "unverified, synthesis (str, '' unless synthesize), shared (bool — "
        "findings published to the turn blackboard), inherited (int — findings "
        "seeded from siblings' blackboard entries), stopped_reason "
        "(rounds|dry|budget), budget_used, max_spawns}.\n"
        "\n"
        "Coordination: findings are auto-shared on the turn's blackboard, so a "
        "sibling agent or a later orchestration on the same goal builds on "
        "them instead of re-discovering — enforced by the harness, no manual "
        "bb_write needed.\n"
        "\n"
        "Budget: one orchestration costs ONE against the 5/turn delegation "
        "cap; its internal fan-outs/votes draw from the bounded spawn budget, "
        "not the turn cap. Reserve it for genuinely multi-round work."
    )
    registry.register(
        Skill(
            name="run_orchestration",
            description=orchestrate_description,
            affinity=["delegation", "orchestration", "swarm", "discovery", "loop"],
            cost_profile="high",  # spawns many LLM turns under a budget
            trusted_source="skill://public/run_orchestration",
            handler=_run_orchestration,
            tests=[
                SkillTestCase(
                    name="missing_goal_returns_error",
                    tier="golden",
                    args={"goal": ""},
                    expect=SkillExpect(
                        schema_keys=[
                            "ok",
                            "collected",
                            "confirmed",
                            "count",
                        ]
                    ),
                    custom_predicate=lambda r: (
                        isinstance(r, dict)
                        and r.get("ok") is False
                        and "required" in (r.get("error") or "")
                    ),
                ),
            ],
        ),
        replace=True,
    )

    # ── verdict-gated repair loop ─────────────────────────────────
    verdict_repair_description = (
        "Run a task through a CLOSED quality loop in one call: a worker "
        "produces a result, an independent panel VOTES pass/fail on it, and a "
        "rejection drives a corrected re-attempt that is FED the reviewers' "
        "critique — produce → judge → rewrite → re-judge, bounded. The loop "
        "(stop-on-pass, bound, feeding the critique forward) is deterministic "
        "code, not the model, so a FAIL actually triggers a fix instead of just "
        "shipping.\n"
        "\n"
        "Use it when correctness matters more than speed and a single attempt "
        "isn't trustworthy: 'write this function AND make sure it's right', "
        "'draft the migration and have it reviewed until it passes', 'answer "
        "this, but verify before returning'.\n"
        "\n"
        "Args: {task: string (what to accomplish), agent_id?: worker role "
        "(default general), judge_n?: int 2-5 voters on the gate (default 3), "
        "max_repairs?: int 0-4 corrective re-attempts (default 2), choices?: "
        "[accept,reject]-style ballot where the FIRST label means accept "
        "(default [pass,fail])}.\n"
        "\n"
        "Returns: {ok, task, passed (bool — did it clear the gate), repaired "
        "(bool — only reached pass AFTER a repair), output (the accepted/best "
        "result), attempts, verdict, confidence, rounds:[{attempt, passed, "
        "verdict, critique}], max_spawns}.\n"
        "\n"
        "Budget: one call costs ONE against the 5/turn delegation cap; its "
        "internal produce/judge fan-outs draw from a bounded spawn budget."
    )
    registry.register(
        Skill(
            name="verdict_repair",
            description=verdict_repair_description,
            affinity=["delegation", "verify", "repair", "critique", "quality", "judge"],
            cost_profile="high",  # spawns producers + voters across rounds
            trusted_source="skill://public/verdict_repair",
            handler=_run_verdict_repair,
            tests=[
                SkillTestCase(
                    name="missing_task_returns_error",
                    tier="golden",
                    args={"task": ""},
                    expect=SkillExpect(
                        schema_keys=[
                            "ok",
                            "passed",
                            "output",
                            "attempts",
                            "rounds",
                        ]
                    ),
                    custom_predicate=lambda r: (
                        isinstance(r, dict)
                        and r.get("ok") is False
                        and "required" in (r.get("error") or "")
                    ),
                ),
            ],
        ),
        replace=True,
    )

    # ── tournament: best-of-N over isolated worktree candidates ───
    tournament_description = (
        "Attempt the SAME goal N independent times, each in its OWN isolated "
        "git worktree (no collisions), then have an independent panel VOTE on "
        "which result is best — best-of-N with a judge. Builds on octopus's "
        "worktree isolation (the candidates) plus call_agent_vote (the judge); "
        "selection is deterministic code. NEVER auto-applies: the winning diff "
        "is returned for you to review and apply (reconciling parallel edits is "
        "a human call).\n"
        "\n"
        "Use it when one attempt is unreliable and the solution space is wide, "
        "so divergent tries help: 'implement X — try a few approaches and keep "
        "the best', 'refactor this several ways and pick the cleanest'. Costly "
        "(N full coding sub-agents + voters) — reserve it for genuinely "
        "high-value or ambiguous work.\n"
        "\n"
        "Args: {goal: string (what each candidate should accomplish), n?: int "
        "2-5 candidates (default 3), agent_id?: worker role (default "
        "worktree_writer), judge_n?: int 2-5 voters (default 3), repo_root?: "
        "path (default cwd — must be a git repo)}.\n"
        "\n"
        "Returns: {ok, goal, decided_by (judge|only_candidate|judge_abstained|"
        "none), candidate_count, viable_count, winner:{id, files, branch, "
        "diff}, candidates:[{id, ok, viable, files, error}], note}. Apply the "
        "winner's diff yourself — nothing is merged automatically."
    )
    registry.register(
        Skill(
            name="tournament",
            description=tournament_description,
            affinity=["delegation", "worktree", "tournament", "best_of", "judge", "candidates"],
            cost_profile="high",  # N coding sub-agents in worktrees + voters
            trusted_source="skill://public/tournament",
            handler=_run_tournament,
            tests=[
                SkillTestCase(
                    name="missing_goal_returns_error",
                    tier="golden",
                    args={"goal": ""},
                    expect=SkillExpect(
                        schema_keys=[
                            "ok",
                            "winner",
                            "candidates",
                            "decided_by",
                        ]
                    ),
                    custom_predicate=lambda r: (
                        isinstance(r, dict)
                        and r.get("ok") is False
                        and "required" in (r.get("error") or "")
                    ),
                ),
            ],
        ),
        replace=True,
    )

    # ── cli_team: a team of the user's external coding CLIs ───────
    cli_team_description = (
        "Run a TEAM of the user's OWN external coding-agent CLIs (Claude Code / "
        "Codex, auto-detected on this machine) on one goal — each in its own "
        "isolated git worktree (no collisions), each briefed from + harvesting to "
        "the shared blackboard (team stigmergy), then judge-pick the best diff. "
        "Uses the user's own logins/subscriptions; NEVER auto-merges (returns the "
        "winning diff for review). This is best-of-N across DIFFERENT real coding "
        "agents, not octopus sub-agents.\n"
        "\n"
        "Use it when you want several top coding agents to each take a crack at a "
        "task and keep the best ('have Claude and Codex both implement this, pick "
        "the better one'). Costly + needs those CLIs installed.\n"
        "\n"
        "Args: {goal: string, members?: [{agent_id, partner_id, command}] (default "
        "auto-detect installed claude-code/codex-cli), judge?: bool (default true "
        "— vote a winner), judge_n?: int 2-5 voters, repo_root?: path (default "
        "cwd, must be a git repo)}.\n"
        "\n"
        "Returns: {ok, goal, count, succeeded, members:[{agent_id, partner_id, ok, "
        "files, error}], winner:{agent_id, files, diff, decided_by}, note}. Apply "
        "the winner's diff yourself."
    )
    registry.register(
        Skill(
            name="cli_team",
            description=cli_team_description,
            affinity=["delegation", "cli", "external_agent", "worktree", "team", "best_of"],
            cost_profile="high",  # N external coding agents in worktrees + voters
            trusted_source="skill://public/cli_team",
            handler=_run_cli_team,
            tests=[
                SkillTestCase(
                    name="missing_goal_returns_error",
                    tier="golden",
                    args={"goal": ""},
                    expect=SkillExpect(schema_keys=["ok", "members", "winner"]),
                    custom_predicate=lambda r: (
                        isinstance(r, dict)
                        and r.get("ok") is False
                        and "required" in (r.get("error") or "")
                    ),
                ),
            ],
        ),
        replace=True,
    )

    # ── pipeline (item-chain, no inter-stage barrier) ─────────────
    pipeline_description = (
        "Process a list of items through ORDERED STAGES without waiting for "
        "all items to complete each stage before advancing — item A can be in "
        "stage 3 while item B is still in stage 1.\n"
        "\n"
        "Use it when:\n"
        "  - You have N independent items (files, URLs, tasks) that each need "
        "the SAME sequence of specialist passes (find → review → fix, or "
        "extract → classify → summarise).\n"
        "  - Stages are sequential PER ITEM (each stage needs the previous "
        "output for that item), but items themselves are independent.\n"
        "  - You want true pipeline throughput: wall-clock = max(slowest item "
        "chain), not sum of slowest-per-stage.\n"
        "\n"
        "Stage prompt templates use:\n"
        "  {item}   — the original item value\n"
        "  {prev}   — previous stage's output for this item (empty for stage 0)\n"
        "  {stage0_output}, {stage1_output}, ... — any earlier stage's output\n"
        "\n"
        "A failed stage halts that item's chain; remaining stages for that item "
        "are skipped. Other items continue.\n"
        "\n"
        "Args: {items: list[str|dict] (up to 16), "
        "stages: list[{prompt_template: str, agent_id?: str}] (up to 4 stages), "
        "default_agent_id?: str (used when stage omits agent_id, default researcher), "
        "timeout_s?: int (per-subagent, default 900)}.\n"
        "\n"
        "Returns: {ok, results:[{item, stages:[{stage, agent_id, output, ok}], "
        "final_output, ok}], success_count, failure_count, total, stages_run}.\n"
        "\n"
        "Budget: one pipeline costs ONE against the 5/turn delegation cap; "
        "item × stage spawn budget is managed internally."
    )
    registry.register(
        Skill(
            name="run_pipeline",
            description=pipeline_description,
            affinity=["delegation", "pipeline", "stages", "multi-step", "batch"],
            cost_profile="high",
            trusted_source="skill://public/run_pipeline",
            handler=_run_pipeline,
            tests=[
                SkillTestCase(
                    name="empty_items_returns_error",
                    tier="golden",
                    args={"items": [], "stages": [{"prompt_template": "review {item}"}]},
                    expect=SkillExpect(
                        schema_keys=[
                            "ok",
                            "results",
                            "success_count",
                            "failure_count",
                            "total",
                        ]
                    ),
                    custom_predicate=lambda r: (
                        isinstance(r, dict)
                        and r.get("ok") is False
                        and "required" in (r.get("error") or "")
                    ),
                ),
                SkillTestCase(
                    name="empty_stages_returns_error",
                    tier="golden",
                    args={"items": ["foo"], "stages": []},
                    expect=SkillExpect(
                        schema_keys=[
                            "ok",
                            "results",
                            "success_count",
                            "failure_count",
                            "total",
                        ]
                    ),
                    custom_predicate=lambda r: (
                        isinstance(r, dict)
                        and r.get("ok") is False
                        and "required" in (r.get("error") or "")
                    ),
                ),
            ],
        ),
        replace=True,
    )
    # 8 delegation/orchestration skills registered above (call_agent,
    # call_agent_parallel, call_agent_vote, run_orchestration,
    # verdict_repair, tournament, cli_team, run_pipeline). Bump when adding
    # another — the count had drifted to a stale 5.
    return 8


__all__ = ["register_delegation_skills"]
