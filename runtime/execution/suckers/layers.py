
from __future__ import annotations

from runtime.platform.models import SkillId

# ═══════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════
#
#
# ═══════════════════════════════════════════════════════════


ATOMIC_SKILL_NAMES: frozenset[str] = frozenset({
    "list_cwd",
    "read_file",
    "file_stats",
    "count_words",
    "hash_text",
    # file discovery/search · read-only project inspection helpers.
    "glob_files",
    "grep_text",
    "tree",
    "read_file_range",
    # memory · per-agent state writes · scoped to the agent's own core dir
    "remember",
    "recall",
    "note_user",
    "diary_write",
    "update_soul",
    "list_soul_history",
    "revert_soul",
    "recall_scores",
    "analyze_soul_impact",
    "auto_regression_check",  # atomic: reverts SOUL only w/ ≥5 samples drop
    "list_learned_skills",  # read-only enumeration · safe atomic
    # code intelligence · read-only AST queries · safe atomic
    "code_analyze",
    "code_search",
    "code_find_symbol",
    "code_dependency_graph",
    "get_available_voices",
    "get_data_source_desc",
    # knowledge graph · on-demand read-only query
    "kg_query",
    # mode · protocol-level transition out of plan mode · every agent
    # needs it or plan mode becomes a trap (no way to exit).
    "exit_plan_mode",
    # agent-meta · task plan surfacing to the user (▢/⏳/☑ panel).
    # Must be atomic so every agent implicitly exposes it · leaving
    # this out kills the "live progress checklist" UX on any agent
    # that didn't explicitly declare it in ``allowed_skills``.
    "todo_read",
    "todo_write",
    "search_skills",
    "query_skill",
    "search_capabilities",
    "query_capability",
    "use_capability",
    # interactive ask-user-question · structured multiple-choice
    # decision card. Atomic so every agent can prompt the user
    # without explicit allowlisting.
    "ask_user_question",
    # blackboard · turn-scoped shared state for parallel sub-agents.
    # In-process dict, no I/O · trivially atomic. Always-on so every
    # agent (lead OR sub-agent) can use bb_read/bb_write to exchange
    # findings within the same turn.
    "bb_read",
    "bb_write",
    "bb_keys",
    # NOTE: ``call_agent`` used to live here. That was wrong:
    # subagents are isolated Agent/Task dispatches, not per-step
    # atomic skills. Team-chat delegates via ``[ROUTE TO: <id>]``;
    # programmatic callers use runtime.execution.subagents.
})


def is_atomic(skill_name: str | SkillId) -> bool:
    return str(skill_name) in ATOMIC_SKILL_NAMES


def as_skill_ids() -> list[SkillId]:
    return [SkillId(n) for n in sorted(ATOMIC_SKILL_NAMES)]
