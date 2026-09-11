"""runtime.memory · 记忆系统（Memory System）

子包速查:
  journal         → append-only 事件日志 (JSONL) + progress 跟踪
  hemolymph       → ContextComposer —— 收集技能 + 规则 + 记忆到 prompt
  knowledge_graph → 三元组提取 + Cypher 查询
  threads         → 线程级记忆
  cowork          → 跨进程协调

  learning/       → 从 trajectory 学习（experience_ledger / review_queue /
                    promotion_applier / soul_holdout / turn_scoring /
                    deep_evolution）
  skills_lib/     → 技能库管理（skill_library / skill_curator / meta_skill /
                    ambient_suggestions / ambient_suggestions_scheduler）
  runtime_state/  → 运行时缓存与会话态（hot_cache / blackboard / hub /
                    scope_paths / file_transactions / process_timeline）
  users/          → 用户存储与画像（user_store / user_preferences /
                    profile / mention_history）
  diagnostics/    → 诊断与追溯（trace_store / error_classifier /
                    wiki_compiler）
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .diagnostics import (  # noqa: F401
        error_classifier,
        trace_store,
        wiki_compiler,
    )

    # Backward-compat shims: legacy code does ``from runtime.memory import X``
    # where X is the submodule name. After the Phase B reorg the modules live
    # inside subpackages, so re-export them at the parent level.
    from .learning import (  # noqa: F401
        deep_evolution,
        experience_ledger,
        promotion_applier,
        review_queue,
        soul_holdout,
        turn_scoring,
    )
    from .runtime_state import (  # noqa: F401
        blackboard,
        file_transactions,
        hot_cache,
        hub,
        process_timeline,
        scope_paths,
    )
    from .skills_lib import (  # noqa: F401
        ambient_suggestions,
        ambient_suggestions_scheduler,
        meta_skill,
        skill_curator,
        skill_library,
    )
    from .users import (  # noqa: F401
        mention_history,
        profile,
        user_preferences,
        user_store,
    )

_MODULES = {
    "error_classifier": "diagnostics.error_classifier",
    "trace_store": "diagnostics.trace_store",
    "wiki_compiler": "diagnostics.wiki_compiler",
    "deep_evolution": "learning.deep_evolution",
    "experience_ledger": "learning.experience_ledger",
    "promotion_applier": "learning.promotion_applier",
    "review_queue": "learning.review_queue",
    "soul_holdout": "learning.soul_holdout",
    "turn_scoring": "learning.turn_scoring",
    "blackboard": "runtime_state.blackboard",
    "file_transactions": "runtime_state.file_transactions",
    "hot_cache": "runtime_state.hot_cache",
    "hub": "runtime_state.hub",
    "process_timeline": "runtime_state.process_timeline",
    "scope_paths": "runtime_state.scope_paths",
    "ambient_suggestions": "skills_lib.ambient_suggestions",
    "ambient_suggestions_scheduler": "skills_lib.ambient_suggestions_scheduler",
    "meta_skill": "skills_lib.meta_skill",
    "skill_curator": "skills_lib.skill_curator",
    "skill_library": "skills_lib.skill_library",
    "mention_history": "users.mention_history",
    "profile": "users.profile",
    "user_preferences": "users.user_preferences",
    "user_store": "users.user_store",
    "diagnostics": "diagnostics",
    "learning": "learning",
    "runtime_state": "runtime_state",
    "skills_lib": "skills_lib",
    "users": "users",
}

__all__ = list(_MODULES)


def __getattr__(name: str) -> Any:
    module = _MODULES.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = import_module(f".{module}", __name__)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
