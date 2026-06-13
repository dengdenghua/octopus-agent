from __future__ import annotations

import json
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
_ADVERTISED_BUILTINS: frozenset[str] = frozenset({
    "architect",
    "debugger",
    "explorer",
    "researcher",
    "reviewer",
    "security-review",
})


# ── Cheap-model routing policy ────────────────────────────
# Roles whose work is "research-style" (web fetching, fact-checking,
# data extraction, code reading, surface review) auto-route to the
# cheap subagent model unless the spec explicitly opts out via
# ``"cheap": False``. The non-cheap roles — architect / synthesizer /
# designer / implementer — keep the parent's primary model since they
# carry the heavy reasoning load.
_NON_CHEAP_ROLES: frozenset[str] = frozenset({
    "architect",
    "synthesizer",
    "designer",
    "implementer",
})

_CHEAP_BY_DEFAULT_ROLES: frozenset[str] = frozenset({
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
})

_FULL_TOOL_MARKERS: frozenset[str] = frozenset({
    "*",
    "all",
    "full",
    "inherit_all",
    "全部",
})

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
    "research", "researcher", "explore", "explorer", "investigate",
    "study", "analyst", "analyzer", "fact_check", "fact-check",
    "scout", "probe", "screen", "screener", "audit", "auditor",
    "monitor", "watcher", "intel",
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
    if any(hint in lower for hint in _RESEARCH_NAME_HINTS):
        if "researcher" in allowed:
            return "researcher", requested
    # Code-shaped → debugger or explorer
    if any(hint in lower for hint in ("debug", "fix", "trace", "diagnose")):
        if "debugger" in allowed:
            return "debugger", requested
    if any(hint in lower for hint in ("review", "critic", "audit_code")):
        if "reviewer" in allowed:
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
        "timeout", "timed out", "connection", "rate limit",
        "rate-limit", "rate_limit", "too many requests",
        "temporarily", "503", "504",
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
    **_kw: Any,
) -> dict[str, Any]:
    """Spawn an isolated subagent turn — escalation when you need
    specialized expertise or parallel work.

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
    cur_count, within = _check_absolute_cap(turn_id)
    if not within:
        return {
            "agent_id": target_raw,
            "output": "",
            "success": False,
            "error": (
                f"delegation budget exhausted for this turn "
                f"(used {cur_count}/{_PER_TURN_ABSOLUTE_LIMIT}). "
                "Do the rest of this turn's work yourself · "
                "do NOT call_agent again."
            ),
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

    # First attempt
    subagent_context = _skill_context_from_spec({
        **_kw,
        "skills": skills,
        "tools": tools,
        "skill_pack": skill_pack,
        "skill_packs": skill_packs,
        "plugin": plugin,
        "plugins": plugins,
        "tool_allowlist": tool_allowlist,
    }, context)
    result = call_subagent(
        agent_id=target,
        prompt=final_prompt,
        context=subagent_context,
        timeout_s=timeout_s,
        session=session,
    )

    # Retry once on transient failure. Critical: retry does NOT bump
    # the budget counter — that happens in ``_record_delegation`` based
    # on the FINAL result (success vs. repeat-failure vs. first-failure).
    if _is_transient_error(result):
        retry_result = call_subagent(
            agent_id=target,
            prompt=final_prompt,
            context=subagent_context,
            timeout_s=timeout_s,
            session=session,
        )
        if retry_result.get("success"):
            retry_result.setdefault("retried", True)
            result = retry_result
        else:
            # Both attempts failed — surface that fact in the error
            result["retried"] = True
            existing_err = result.get("error") or ""
            result["error"] = (
                f"{existing_err} (retry also failed: "
                f"{retry_result.get('error') or 'unknown'})"
            )

    # Record against budget AFTER we know the outcome. Smart-budget:
    # first-time failures get a free pass; repeat failures + successes
    # both count.
    _record_delegation(
        turn_id, fingerprint, succeeded=bool(result.get("success")),
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
            raw.get("agent_id") or raw.get("agent_name")
            or raw.get("agent") or raw.get("role")
            or raw.get("name") or ""
        )
        prm = (
            raw.get("prompt") or raw.get("task")
            or raw.get("message") or raw.get("query")
            or raw.get("description") or raw.get("instruction") or ""
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
                f"no fallback subagent available for {aid_raw!r}. "
                f"Available: {sorted(allowed)}.",
            )
        # Cheap routing: explicit ``cheap`` in the spec wins; otherwise
        # the role-name policy decides. ``cheap=False`` disables the
        # auto-cheap behavior so heavy-reasoning roles dropped into the
        # default-cheap allowlist by mistake can still be pinned to the
        # primary model from the call site.
        cheap_flag = (
            bool(raw.get("cheap")) if "cheap" in raw
            else _role_defaults_to_cheap(str(aid_resolved))
        )
        cleaned.append({
            "spec_index": len(cleaned),
            "agent_id": aid_resolved,
            "agent_id_original": str(aid_raw),
            "bb_key": str(raw.get("bb_key") or raw.get("key") or "").strip(),
            "prompt": _wrap_prompt_with_role_label(str(prm), role_label),
            "task_preview": str(prm).replace("\n", " ").strip()[:240],
            "role_label": role_label,
            "cheap": cheap_flag,
            "context": _skill_context_from_spec(raw, context),
        })

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
            f"delegation budget exhausted for this turn "
            f"(used {cur_count}/{_PER_TURN_ABSOLUTE_LIMIT}). "
            "Do the rest yourself · do NOT call_agent again.",
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
        try:
            result = call_subagent(
                agent_id=spec["agent_id"],
                prompt=spec["prompt"],
                context=spec.get("context"),
                timeout_s=timeout_s,
                session=session,
                use_cheap_model=bool(spec.get("cheap")),
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
        # Retry once on transient failure. Per-spec retry, not per
        # parallel batch — one slow worker shouldn't block faster ones.
        if _is_transient_error(result):
            try:
                retry = call_subagent(
                    agent_id=spec["agent_id"],
                    prompt=spec["prompt"],
                    context=spec.get("context"),
                    timeout_s=timeout_s,
                    session=session,
                    use_cheap_model=bool(spec.get("cheap")),
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
                        f"{existing_err} (retry also failed: "
                        f"{retry.get('error') or 'unknown'})"
                    )
            except (ConnectionError, TimeoutError, TypeError, ValueError):
                result["retried"] = True
        # Record this spec's outcome against the smart-budget. Each
        # spec gets its own fingerprint so a failed spec doesn't
        # spend budget on a first try (LLM gets a chance to fix it),
        # but a repeat of the same {agent, prompt} does count.
        spec_fingerprint = _compute_fingerprint(spec["agent_id"], spec["prompt"])
        _record_delegation(
            turn_id, spec_fingerprint,
            succeeded=bool(result.get("success")), budget=orch_budget,
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
                    spec.get("bb_key")
                    or spec.get("role_label")
                    or spec.get("agent_id_original")
                )
                results.append({
                    "agent_id": (
                        spec.get("agent_id_original") or spec.get("agent_id") or "?"
                    ),
                    "spec_index": spec.get("spec_index"),
                    "task_label": task_label,
                    "bb_key": spec.get("bb_key"),
                    "task_preview": spec.get("task_preview"),
                    "output": "",
                    "success": False,
                    "error": f"{type(exc).__name__}: {exc}",
                    "error_type": type(exc).__name__,
                })
        for f in not_done:
            spec = future_specs.get(f, {})
            f.cancel()
            task_label = (
                spec.get("bb_key")
                or spec.get("role_label")
                or spec.get("agent_id_original")
            )
            results.append({
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
            })
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

    return _build_parallel_envelope(results, total=len(cleaned))


def _build_parallel_envelope(
    results: list[dict[str, Any]], *, total: int,
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
            failures.append({
                "role": "?",
                "agent_id": "?",
                "error": f"non-dict result: {r!r}",
                "error_type": "malformed",
            })
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
            "iteration_count": r.get("iteration_count")
            or r.get("rounds_completed"),
            "rounds_completed": r.get("rounds_completed")
            or r.get("iteration_count"),
            "duration_s": r.get("duration_s"),
            "files_touched": list(r.get("files_touched") or []),
            "retried": bool(r.get("retried") or r.get("retry_attempted")),
            "round_cap_exceeded": bool(r.get("round_cap_exceeded")),
            "partial": bool(r.get("partial")),
        }
        if r.get("success"):
            successes.append({
                **common,
                "output": output,
            })
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
            failures.append({
                key: value
                for key, value in failure.items()
                if value not in (None, "", [], False)
            })
            if output.strip():
                partial_outputs.append({
                    "agent_id": agent_id,
                    "spec_index": r.get("spec_index"),
                    "task_label": r.get("task_label"),
                    "error": error,
                    "error_type": _derive_error_type(r),
                    "output": output,
                })

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
        f"{success_count}/{total} sub-agents succeeded"
        if total
        else "0/0 sub-agents succeeded"
    )
    honesty_warning = ""
    if partial:
        failed_labels = [
            str(f.get("task_label") or f.get("agent_id") or f.get("role") or "?")
            for f in failures
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
    if choices:
        opts = " / ".join(choices)
        ballot = (
            f"Choose exactly one of: {opts}.\n"
            f"Line 1 MUST be `VERDICT: <one of {opts}>`.\n"
            "Line 2 MUST be `REASON: <one sentence, <=30 words>`."
        )
    else:
        ballot = (
            "Line 1 MUST be `VERDICT: <your short answer / label>`.\n"
            "Line 2 MUST be `REASON: <one sentence, <=30 words>`."
        )
    return (
        "You are ONE independent voter on a panel. Judge the question "
        "below on your own merits — do not assume other voters agree.\n\n"
        f"QUESTION:\n{question}\n\n{ballot}"
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
    votes: list[dict[str, Any]], choices: list[str] | None,
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
            "verdict": None, "confidence": 0.0, "unanimous": False,
            "tie": False, "tie_between": [], "tally": {},
            "voter_count": len(votes), "votes_cast": 0,
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
        return (
            f"[unanimous] all {tally['votes_cast']} voters agree: "
            f"{tally['verdict']}."
        )
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
        question or _kw.get("prompt") or _kw.get("task")
        or _kw.get("claim") or _kw.get("query") or "",
    ).strip()
    if not q:
        return {
            "ok": False, "error": "question is required", "verdict": None,
            "confidence": 0.0, "tally": {}, "votes": [], "voter_count": 0,
            "votes_cast": 0, "abstentions": 0,
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
    specs = [{"agent_id": voter, "prompt": ballot} for _ in range(n_int)]

    env = _call_agent_parallel(
        specs=specs, timeout_s=timeout_s, context=context, session=session,
    )

    votes: list[dict[str, Any]] = []
    for s in env.get("successes", []):
        verdict, reason = _extract_verdict(str(s.get("output") or ""), ballot_choices)
        votes.append({
            "verdict": verdict,
            "reason": reason,
            "agent_id": s.get("agent_id"),
            "codename": s.get("codename"),
            "abstained": not verdict,
        })

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
        "review/write/memory/shell, plugins?: plugin or package hints}. "
        "Use skill packs when the subtask needs tools beyond the role's "
        "default allowlist.\n"
        "\n"
        "Advertised specialist roles:\n"
        f"{role_table}"
    )
    registry.register(Skill(
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
                expect=SkillExpect(schema_keys=[
                    "agent_id", "output", "success", "error",
                ]),
                custom_predicate=lambda r: (
                    isinstance(r, dict)
                    and r.get("success") is False
                    and "agent_id is required" in (r.get("error") or "")
                ),
            ),
        ],
    ), replace=True)

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
        "line such as \"Subagent status: 3/5 succeeded; 2 failed\" and MUST "
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
    registry.register(Skill(
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
                expect=SkillExpect(schema_keys=[
                    "ok", "successes", "failures", "partial",
                    "total", "success_count", "notes",
                    "results", "count", "outputs", "error",
                ]),
                custom_predicate=lambda r: (
                    isinstance(r, dict)
                    and r.get("count") == 0
                    and r.get("ok") is False
                    and r.get("partial") is False
                    and r.get("successes") == []
                ),
            ),
        ],
    ), replace=True)

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
        "fixed ballot e.g. [\"yes\",\"no\"] (omit for a free-form verdict), "
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
    registry.register(Skill(
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
                expect=SkillExpect(schema_keys=[
                    "ok", "verdict", "tally", "votes", "note",
                ]),
                custom_predicate=lambda r: (
                    isinstance(r, dict)
                    and r.get("ok") is False
                    and "required" in (r.get("error") or "")
                ),
            ),
        ],
    ), replace=True)
    return 3


__all__ = ["register_delegation_skills"]
