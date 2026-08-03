"""Skill-catalog formatting for the ReAct system prompt.

Extracted from ``react_context.py``. Pure formatting — no behaviour change.
"""

from __future__ import annotations

import logging
from collections.abc import Collection
from typing import Any

from runtime.core.cerebrum.capability_router import (
    activate_capabilities,
    order_skill_names,
)

_logger = logging.getLogger(__name__)


def _format_skill_catalog(
    registry: Any,
    *,
    max_skills: int = 100,
    user_context: dict | None = None,
    agent: Any = None,
    goal: str = "",
    include_names: Collection[str] | None = None,
) -> str:
    try:
        names = list(registry.all_names())
    except (AttributeError, TypeError, ValueError):  # noqa: BLE001
        return ""

    # Skills hidden from the single-agent ReAct catalog. They're
    # registered (so the bridge can dispatch when invoked) but kept
    # out of the prompt's skill listing so the model doesn't try
    # to use them when there's no swarm context.
    #
    # ``deep-research-swarm`` belongs to swarm mode only — it
    # dispatches into ``research_swarm_v1`` via TeamRunner, which
    # spawns sub-agents through ``ephemeral_runner``. That path
    # requires native ``tools`` support; offering it from a single-
    # agent loop tempts the model to call it from Agent / Inspiration
    # mode where the upstream model may not support function calling
    # and the call ends up doing nothing visible.
    # ``deep-research`` is the Agent-mode counterpart: it returns
    # the 7-phase instruction document the parent ReAct loop drives
    # via atomic web_search / fetch_url. Keep that one available.
    # ``call_agent`` is blocked by the ReAct executor because serial
    # single-subagent delegation is usually worse than the lead just doing
    # the work. Keep ``call_agent_parallel`` visible: it is the real
    # Kimi-style fan-out tool for independent lanes in Agent/Swarm mode.
    #
    # OVERRIDE: ``deep-research-swarm`` force-enabled in Agent mode per
    # user request. Risk: if the primary model lacks tool support
    # (Haiku, Inspiration, or certain DeepSeek variants), invocations
    # will fail with a cryptic error. The caller is responsible for
    # using a tool-capable model (Opus, Sonnet, Kimi, DeepSeek-R1).
    hidden_in_react: set[str] = {
        "exit_plan_mode",
        # "deep-research-swarm",  # force-enabled: user accepts tool-support risk
        "call_agent",
    }

    def _enabled(name: str) -> bool:
        try:
            return bool(registry.is_enabled(name))
        except (AttributeError, TypeError, ValueError):  # noqa: BLE001
            return True

    names = [n for n in names if n not in hidden_in_react and _enabled(n)]
    if include_names is not None:
        allowed_names = frozenset(include_names)
        names = [name for name in names if name in allowed_names]

    # A code regression preview runs in Octopus' isolated Playwright browser,
    # not the desktop Electron surface.  Hide incompatible live-browser tools
    # instead of relying on the model to recover after a guaranteed failure.
    from runtime.core.cerebrum.capability_router import filter_surface_compatible_skills

    names = filter_surface_compatible_skills(names, user_context=user_context)

    if agent is not None:
        allowed: set[str] | None
        try:
            allowed = set(agent.allowed_skill_union())
            agent_aff = {str(a).lower() for a in agent.affinity()}
        except (AttributeError, TypeError, ValueError):  # noqa: BLE001 - fail open to old behavior
            allowed = None
            agent_aff = set()

        if allowed is not None:
            allow_all = "*" in allowed
            try:
                from runtime.execution.all_skills import skill_kind as _classify
            except ImportError:
                _classify = lambda skill_id: "domain"  # noqa: E731

            def _visible(name: str) -> bool:
                if allow_all:
                    return True
                if name in allowed:
                    return True
                kind = _classify(name)
                if kind == "domain":
                    try:
                        skill = registry.get(name)
                        skill_aff = {
                            str(a).lower() for a in (getattr(skill, "affinity", None) or [])
                        }
                    except (AttributeError, TypeError, ValueError):  # noqa: BLE001
                        return True
                    if not skill_aff:
                        return False
                    if not agent_aff:
                        return True
                    return bool(skill_aff & agent_aff)
                return False

            names = [n for n in names if _visible(n)]

    if not names:
        return ""
    activation = activate_capabilities(
        goal,
        user_context=user_context,
        registry=registry,
    )
    # Capability-aware priority list. The unconditional groups (planning,
    # discovery, files, web, local execution) are always front-loaded so the
    # model keeps a stable core. Capability-conditional groups (git, browser,
    # delegation, high-level docs) are only front-loaded when the turn's
    # activation points at them — a plain "hello" or prose turn no longer pays
    # for 15 browser tools + 7 git tools it will never use. The model can still
    # discover any omitted tool via search_capabilities / query_skill, which
    # stay in the always-on group.
    _labels = set(activation.labels)
    _browser_cap = bool(_labels & {"browser-ui", "external-chrome", "code-ui-regression"})
    _uc_for_browser = user_context if isinstance(user_context, dict) else {}
    _browser_surface = str(
        _uc_for_browser.get("browser_surface") or ""
    ).strip().lower()
    _browser_cap = _browser_cap or _browser_surface in {"browser", "chrome"}
    _git_cap = bool(_labels & {"code", "files"})
    _delegation_cap = bool(_labels & {"delegation", "swarm"})
    _research_cap = bool(_labels & {"research"})

    priority = [
        # Planning + tool discovery (always on — the model needs these to
        # discover anything, including tools omitted below).
        "todo_write",
        "search_capabilities",
        "query_capability",
        "use_capability",
        "search_skills",
        "query_skill",
        # Files + code inspection/editing (always on — universal primitives).
        "list_cwd",
        "read_file",
        "file_stats",
        "code_search",
        "code_find_symbol",
        "code_analyze",
        "write_text_file",
        "edit_file",
        "multi_edit_file",
        "append_text_file",
        "edit_text_file",
        # Web research + URL reading (always on).
        "web_search",
        "web_fetch",
        "fetch_url",
        # Local execution + background jobs (always on).
        "exec_shell",
        "ipython",
        "background_exec",
        "read_background_output",
        "kill_background_exec",
        # Git workflow — only for code/files turns.
        *(
            [
                "git_status",
                "git_diff",
                "git_log",
                "git_add",
                "git_commit",
                "git_branch",
            ]
            if _git_cap
            else []
        ),
        # Delegation + shared blackboard — only for swarm/delegation turns.
        *(
            [
                "call_agent_parallel",
                "bb_write",
                "bb_read",
                "bb_keys",
            ]
            if _delegation_cap
            else []
        ),
        # Browser/Desktop observation for UI work — only for browser turns.
        *(
            [
                "browser_navigate",
                "live_browser_state",
                "live_browser_current_url",
                "live_browser_navigate",
                "live_browser_extract",
                "live_browser_find",
                "live_browser_click",
                "live_browser_type",
                "live_browser_wait",
                "live_browser_scroll",
                "live_browser_screenshot",
                "browser_get",
                "browser_extract",
                "browser_screenshot",
                "browser_click",
                "browser_type",
                "browser_upload",
                "screen_capture",
                "screen_info",
            ]
            if _browser_cap
            else []
        ),
        # High-level document/research workflows — only for research turns.
        *(
            ["deep-research", "report-writing", "docx"]
            if _research_cap
            else []
        ),
    ]
    priority_set = set(priority)
    names = [n for n in priority if n in names] + [n for n in names if n not in priority_set]
    names = order_skill_names(
        names,
        activation=activation,
        registry=registry,
    )
    # TF-IDF relevance selection · when the catalog would overflow
    # ``max_skills``, keep the pinned priority tools and fill the
    # remaining slots with the skills most relevant to the goal
    # (TF-IDF over name+summary+description+affinity — zero deps,
    # deterministic). The priority/capability ordering above already
    # ranks the full list; this step only decides which non-priority
    # skills survive the truncation, so a 300-skill registry no longer
    # evicts goal-relevant skills behind 100 alphabetically-lucky ones.
    if goal and len(names) > max_skills:
        try:
            from runtime.execution.suckers.search import TfIdfSkillSearcher

            pinned = [n for n in names if n in priority_set]
            rest = [n for n in names if n not in priority_set]
            budget = max(0, max_skills - len(pinned))
            relevant = set(TfIdfSkillSearcher(registry).search(goal, k=budget))
            names = pinned + [n for n in rest if n in relevant]
        except Exception:  # noqa: BLE001 — selection is an optimization, never fatal
            pass
    lines: list[str] = ["可用工具 (skill):"]
    for name in names[:max_skills]:
        try:
            skill = registry.get(name)
            # Progressive disclosure (octopus optimisation lane C):
            # the catalog only lists name + ≤30字 short description.
            # The model can call ``query_skill(name)`` for the full
            # parameter schema + long description when it actually
            # needs to invoke the skill. This keeps the system prompt
            # small and stable so prompt cache stays warm.
            short = (getattr(skill, "summary", "") or "").strip() or (
                getattr(skill, "effective_summary", "") or ""
            ).strip()
            if not short:
                # Fall back to first sentence of description, capped
                # at 30 characters. Prefer to break at the first
                # punctuation so we don't dangle mid-word.
                full = (getattr(skill, "description", "") or "").strip()
                if full:
                    # Take everything up to the first sentence terminator
                    # / newline; if none, use first 30 chars.
                    cut = len(full)
                    for sep in ("。", ".", "\n", "·", ";", "；"):
                        idx = full.find(sep)
                        if 0 < idx < cut:
                            cut = idx
                    short = full[: min(cut, 30)].strip()
            if not short:
                short = "(无描述)"
        except (AttributeError, TypeError, KeyError, ValueError):  # noqa: BLE001
            short = "(无描述)"
        lines.append(f"  - {name}: {short}")
    if len(names) > max_skills:
        lines.append(f"  ... (还有 {len(names) - max_skills} 个,省略)")
    lines.append(
        "提示: 上面只列名+短描述; 调用前若需完整参数 schema 请用 "
        '`query_skill(name="<skill_name>")`。',
    )
    lines.append(
        "Capability-first: prefer `search_capabilities`, "
        "`query_capability`, and `use_capability` before low-level child skills.",
    )
    # When no capability lane is active (vague goal), surface a lightweight
    # capability map so the model still knows the lanes exist even if their
    # full tool sets were trimmed away. It stays discoverable via
    # search_capabilities — the index is only a name-level hint, not schemas.
    if not activation.active:
        try:
            from runtime.core.cerebrum.capability_router import capability_index

            _idx = capability_index()
            if _idx:
                lines.append("")
                lines.append("<capability-index>")
                lines.append("可用能力与代表工具(未激活具体路由, 供参考):")
                lines.append(_idx)
                lines.append("不确定用哪个工具时先用 search_capabilities 查询完整工具集。")
                lines.append("</capability-index>")
        except (ImportError, AttributeError):  # noqa: BLE001 — best-effort hint
            pass
    return "\n".join(lines)
