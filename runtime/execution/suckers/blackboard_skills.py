"""
blackboard_skills · expose the turn-scoped shared dict as 3 skills.

Sister to ``memory_skills`` but different scope:
- ``remember`` / ``recall`` are CROSS-TURN per-agent memory (disk
  files in ``agents/<id>/agent-core/MEMORY.md``).
- ``bb_read`` / ``bb_write`` / ``bb_keys`` are WITHIN-TURN shared
  memory between lead + concurrent sub-agents (in-process dict).

The blackboard is the substrate that makes ``call_agent_parallel``
useful — without it, parallel sub-agents are mini silos. With it,
sub-agent A can drop a partial finding under key ``"competitor_a"``
and sub-agent B (running concurrently or right after) can see it
via ``bb_read("competitor_a")``.

All three skills resolve the active turn via ``current_session()``.
When invoked outside a Session (raw unit test), they return a clear
"no turn scope" error rather than silently dropping data.
"""
from __future__ import annotations

from typing import Any

from .registry import Skill, SkillRegistry
from .testing import SkillExpect, SkillTestCase


def _resolve_turn_id() -> str | None:
    try:
        from runtime.platform.process.session import current_session
        sess = current_session()
        return getattr(sess, "turn_id", None) if sess else None
    except Exception:  # noqa: BLE001
        return None


def _bb_write(
    key: str = "",
    value: Any = None,
    **_kw: Any,
) -> dict[str, Any]:
    """Write a value to the shared blackboard for this turn."""
    if not key:
        return {"ok": False, "error": "key is required"}
    turn_id = _resolve_turn_id()
    if not turn_id:
        return {
            "ok": False,
            "error": "no Session/turn active · blackboard is turn-scoped",
        }
    from runtime.memory.runtime_state.blackboard import get_blackboard
    bb = get_blackboard(turn_id)
    if bb is None:
        return {"ok": False, "error": "blackboard unavailable"}
    writer = _resolve_writer_id()
    bb.write(key, value, writer=writer)
    audit = bb.audit()
    return {
        "ok": True,
        "key": key,
        "stored_at_turn": turn_id[:8],
        "writer": writer,
        "overwrite_count": audit.get("overwrite_count", 0),
        "contested": key in set(audit.get("contested_keys", [])),
    }


def _bb_read(key: str = "", **_kw: Any) -> dict[str, Any]:
    """Read a value from the shared blackboard for this turn."""
    if not key:
        return {"ok": False, "error": "key is required"}
    turn_id = _resolve_turn_id()
    if not turn_id:
        return {
            "ok": False,
            "error": "no Session/turn active · blackboard is turn-scoped",
        }
    from runtime.memory.runtime_state.blackboard import get_blackboard
    bb = get_blackboard(turn_id)
    if bb is None:
        return {"ok": False, "found": False, "error": "blackboard unavailable"}
    val = bb.read(key, default=None)
    if val is None:
        return {"ok": True, "found": False, "key": key, "value": None}
    return {"ok": True, "found": True, "key": key, "value": val}


def _bb_keys(**_kw: Any) -> dict[str, Any]:
    """List all keys currently on the blackboard."""
    turn_id = _resolve_turn_id()
    if not turn_id:
        return {
            "ok": False, "keys": [], "count": 0,
            "error": "no Session/turn active · blackboard is turn-scoped",
        }
    from runtime.memory.runtime_state.blackboard import get_blackboard
    bb = get_blackboard(turn_id)
    if bb is None:
        return {
            "ok": False, "keys": [], "count": 0,
            "error": "blackboard unavailable",
        }
    keys = bb.keys()
    return {"ok": True, "keys": keys, "count": len(keys), "audit": bb.audit()}


def _resolve_writer_id() -> str | None:
    try:
        from runtime.platform.process.session import current_session
        sess = current_session()
        if sess is None:
            return None
        return (
            getattr(sess, "agent_id", None)
            or getattr(sess, "actor", None)
            or getattr(sess, "thread_id", None)
        )
    except Exception:  # noqa: BLE001
        return None


def register_blackboard_skills(registry: SkillRegistry) -> int:
    """Register bb_read / bb_write / bb_keys. Returns count."""
    registry.register(Skill(
        name="bb_write",
        description=(
            "Write a value to the shared blackboard. The blackboard is "
            "an in-memory key/value store scoped to the current turn — "
            "lead agent + all concurrent sub-agents share it. Use it to "
            "pass findings between parallel workers (e.g. "
            "`bb_write(key='competitor_a', value={...})`). "
            "Args: {key: string, value: any JSON-serializable}. "
            "DON'T use for things that should persist across turns — "
            "use `remember` for that."
        ),
        affinity=["blackboard", "shared_state", "multi_agent"],
        cost_profile="low",
        trusted_source="skill://public/bb_write",
        handler=_bb_write,
        tests=[
            SkillTestCase(
                name="empty_key_returns_error",
                tier="golden",
                args={"key": "", "value": "x"},
                expect=SkillExpect(schema_keys=["ok", "error"]),
                custom_predicate=lambda r: (
                    isinstance(r, dict) and r.get("ok") is False
                ),
            ),
        ],
    ))

    registry.register(Skill(
        name="bb_read",
        description=(
            "Read a value from the shared blackboard. Returns "
            "{ok, found, key, value}. `found=False` means no entry "
            "exists for that key yet. Use this to check what other "
            "concurrent sub-agents (or the lead) have written. "
            "Args: {key: string}."
        ),
        affinity=["blackboard", "shared_state", "multi_agent"],
        cost_profile="low",
        trusted_source="skill://public/bb_read",
        handler=_bb_read,
        tests=[
            SkillTestCase(
                name="empty_key_returns_error",
                tier="golden",
                args={"key": ""},
                expect=SkillExpect(schema_keys=["ok", "error"]),
                custom_predicate=lambda r: (
                    isinstance(r, dict) and r.get("ok") is False
                ),
            ),
        ],
    ))

    registry.register(Skill(
        name="bb_keys",
        description=(
            "List all keys currently on the shared blackboard. Useful "
            "when you don't know what your concurrent siblings have "
            "written yet — call `bb_keys()` first, then `bb_read(k)` "
            "on the interesting ones. Returns {ok, keys, count}."
        ),
        affinity=["blackboard", "shared_state", "multi_agent"],
        cost_profile="low",
        trusted_source="skill://public/bb_keys",
        handler=_bb_keys,
        tests=[
            SkillTestCase(
                name="returns_keys_list",
                tier="golden",
                args={},
                expect=SkillExpect(schema_keys=["ok", "keys", "count"]),
            ),
        ],
    ))
    return 3


__all__ = ["register_blackboard_skills"]
