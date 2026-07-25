"""Group fan-out — the WeChat "boss speaks, everyone chimes in" experience.

When a message lands in a team room and the user wants the whole group to react
(蜂群 / 冒泡), this fans the message out to each member agent IN PARALLEL. Each
member replies briefly in its own persona — a short "bubble", not a full task
run — and the replies come back per-member so the UI can stream each as its own
group-chat bubble.

This is the native-agent sibling of ``cli_team.run_cli_team`` (which fans out to
external coding CLIs): same parallel-and-collect shape, but each unit is one of
the room's in-process roster agents giving a conversational reply.

Honest scope: this is still *conversation*, not a full task graph.  It does,
however, now returns a deterministic arbitration summary so downstream team
surfaces can pick a primary response, classify failures, and decide the next
action without re-parsing bubbles.
"""

from __future__ import annotations

import concurrent.futures as _cf
from collections.abc import Callable
from typing import Any

# Keep the group from getting spammy / expensive: a real group chat has a few
# people chime in, not 20. Also bounds the parallel LLM fan-out cost.
_MAX_FANOUT = 6
_MAX_SCALE_FANOUT = 512
_ARBITRATION_SCHEMA = "octopus.group_fanout_arbitration.v1"
_SYNTHESIS_SCHEMA = "octopus.group_fanout_synthesis.v1"
_CAPACITY_SCHEMA = "octopus.group_fanout_capacity.v1"

# Capacity tier thresholds for _capacity_tier().  These are descriptive
# buckets, not scaling limits — they drive the capacity verdict reported
# back to the UI so team surfaces can reason about fan-out size.
_KIMI_SCALE_MEMBERS = 300
_LARGE_TIER_MEMBERS = 64
_TEAM_TIER_MEMBERS = 16
_ROOM_TIER_MEMBERS = 2


def _response_id(turn_id: str | None, index: int, agent_id: str) -> str:
    prefix = str(turn_id or "fanout").strip() or "fanout"
    safe_agent = (
        "".join(ch if ch.isalnum() or ch in ("-", "_", ".") else "-" for ch in agent_id).strip("-")
        or "agent"
    )
    return f"{prefix}:resp:{index}:{safe_agent}"


def _score_reply(reply: dict[str, Any]) -> int:
    if not reply.get("ok"):
        return 0
    text = str(reply.get("reply") or "").strip()
    if not text:
        return 40
    # Keep this intentionally boring and deterministic.  The score is a
    # readiness signal, not a quality judgment: successful non-empty replies
    # beat empty successes, and slightly fuller replies win stable ties.
    return 100 + min(20, max(1, len(text) // 40))


def _reply_status(reply: dict[str, Any]) -> str:
    if not reply.get("ok"):
        return "failed"
    if str(reply.get("reply") or "").strip():
        return "answered"
    return "empty"


def _capacity_tier(dispatched_members: int, requested_members: int) -> str:
    if requested_members >= _KIMI_SCALE_MEMBERS:
        return "kimi_scale"
    if dispatched_members >= _LARGE_TIER_MEMBERS:
        return "large"
    if dispatched_members >= _TEAM_TIER_MEMBERS:
        return "team_scale"
    if dispatched_members >= _ROOM_TIER_MEMBERS:
        return "room_scale"
    return "single"


def arbitrate_group_fanout(
    replies: list[dict[str, Any]],
    *,
    turn_id: str | None = None,
) -> dict[str, Any]:
    """Build a machine-readable arbitration summary for fan-out replies.

    The fan-out path remains lightweight and persona-oriented, but group/team
    callers still need a reliable answer to "who gave the usable response?" and
    "what should the runtime do next?".  This helper is deterministic and does
    not ask another model to judge the model outputs.
    """
    rows: list[dict[str, Any]] = []
    for index, reply in enumerate(replies):
        agent_id = str(reply.get("agent_id") or "")
        status = _reply_status(reply)
        score = _score_reply(reply)
        row = {
            "response_id": str(reply.get("response_id") or _response_id(turn_id, index, agent_id)),
            "roster_index": index,
            "agent_id": agent_id,
            "display_name": str(reply.get("display_name") or agent_id),
            "status": status,
            "ok": bool(reply.get("ok")),
            "score": score,
            "reply_chars": len(str(reply.get("reply") or "").strip()),
            "error": reply.get("error"),
        }
        if status == "failed":
            row["recommended_action"] = "retry_member"
        elif status == "empty":
            row["recommended_action"] = "ask_member_to_expand"
        else:
            row["recommended_action"] = "use_response"
        rows.append(row)

    ranked = sorted(
        rows,
        key=lambda row: (
            int(row["score"]),
            -int(row["roster_index"]),
        ),
        reverse=True,
    )
    for rank, row in enumerate(ranked, start=1):
        row["rank"] = rank

    primary = next((row for row in ranked if row["status"] == "answered"), None)
    answered = [row["agent_id"] for row in rows if row["status"] == "answered"]
    failed = [row["agent_id"] for row in rows if row["status"] == "failed"]
    empty = [row["agent_id"] for row in rows if row["status"] == "empty"]

    if primary and failed:
        next_action = "use_primary_and_retry_failed_members"
    elif primary:
        next_action = "use_primary_response"
    elif empty and not failed:
        next_action = "ask_members_to_expand"
    elif failed:
        next_action = "retry_or_fallback_to_single_agent"
    else:
        next_action = "fallback_to_single_agent"

    return {
        "schema": _ARBITRATION_SCHEMA,
        "turn_id": turn_id,
        "primary_response_id": primary["response_id"] if primary else None,
        "primary_agent_id": primary["agent_id"] if primary else None,
        "recommended_next_action": next_action,
        "answered_agent_ids": answered,
        "failed_agent_ids": failed,
        "empty_agent_ids": empty,
        "ranking": ranked,
        "outcomes": rows,
    }


def synthesize_group_fanout(
    replies: list[dict[str, Any]],
    arbitration: dict[str, Any],
) -> dict[str, Any]:
    """Produce a structured, replayable synthesis for the fanout result.

    This is intentionally deterministic: the runtime already paid for the
    member replies, so the coordinator can expose a useful delivery envelope
    without another model call. UI/replay/benchmarks can then tell whether the
    swarm produced a primary answer, supporting signals, and retry targets.
    """
    rows = [reply for reply in replies if isinstance(reply, dict)]
    by_agent = {
        str(reply.get("agent_id") or ""): str(reply.get("reply") or "").strip() for reply in rows
    }
    primary_agent_id = str(arbitration.get("primary_agent_id") or "").strip()
    answered = [
        str(agent_id) for agent_id in arbitration.get("answered_agent_ids") or [] if str(agent_id)
    ]
    failed = [
        str(agent_id) for agent_id in arbitration.get("failed_agent_ids") or [] if str(agent_id)
    ]
    empty = [
        str(agent_id) for agent_id in arbitration.get("empty_agent_ids") or [] if str(agent_id)
    ]
    retry_agent_ids = [*failed, *empty]
    supporting_agent_ids = [agent_id for agent_id in answered if agent_id != primary_agent_id]
    primary_reply = by_agent.get(primary_agent_id, "") if primary_agent_id else ""
    return {
        "schema": _SYNTHESIS_SCHEMA,
        "primary_agent_id": primary_agent_id or None,
        "primary_reply": primary_reply[:2000],
        "supporting_agent_ids": supporting_agent_ids,
        "retry_agent_ids": retry_agent_ids,
        "answered_count": len(answered),
        "total_count": len(rows),
        "recommended_next_action": arbitration.get("recommended_next_action"),
        "ready": bool(primary_agent_id and primary_reply),
    }


def build_fanout_prompt(message: str, speaker: str, roster: list[str]) -> str:
    """The per-member instruction: react in persona, short, group-chat style."""
    names = "、".join(roster) if roster else "(只有你)"
    return (
        f"你在一个团队群聊里,群成员有:{names}。\n"
        f"刚才群里有人说:「{message}」\n\n"
        f"请用你自己的人设、第一人称,像在微信群里冒泡那样自然地接一句话"
        f"(1-3 句即可):说说这事你能帮上什么、或你的角度。不要复述别人的话,"
        f"不要长篇大论,不要列大纲——就是随口接一句。"
    )


def run_group_fanout(
    message: str,
    members: list[dict[str, Any]],
    *,
    agent_caller: Callable[..., dict[str, Any]],
    max_members: int = _MAX_FANOUT,
    max_concurrency: int | None = None,
    scale_mode: str = "safe",
    turn_id: str | None = None,
) -> dict[str, Any]:
    """Fan ``message`` out to each member in parallel; collect persona replies.

    ``members`` is ``[{name|agent_id, display_name?}]``. ``agent_caller`` is the
    one-shot subagent invoker — ``agent_caller(agent_id=..., prompt=...)`` →
    ``{output, success, error}`` (in production: ``delegation_skills._call_agent``).

    Returns ``{ok, replies:[{agent_id, display_name, reply, ok, error}], count,
    spoke, arbitration}``. Order follows the roster. Never raises — one
    member's failure is isolated.
    """
    msg = (message or "").strip()
    if not msg:
        return {"ok": False, "error": "message is required", "replies": [], "count": 0, "spoke": 0}
    eligible = [
        m for m in (members or []) if isinstance(m, dict) and (m.get("name") or m.get("agent_id"))
    ]
    requested_members = len(eligible)
    scale = str(scale_mode or "safe").strip().lower()
    if scale not in {"safe", "full"}:
        scale = "safe"
    max_cap = _MAX_SCALE_FANOUT if scale == "full" else max(1, int(max_members or _MAX_FANOUT))
    max_members = max(1, min(int(max_members or _MAX_FANOUT), max_cap))
    clean = eligible[:max_members]
    if not clean:
        return {"ok": False, "error": "no members", "replies": [], "count": 0, "spoke": 0}

    roster = [str(m.get("display_name") or m.get("name") or m.get("agent_id")) for m in clean]
    concurrency_limit = (
        max_members if max_concurrency is None else max(1, int(max_concurrency or 1))
    )
    workers = max(1, min(len(clean), concurrency_limit))
    capacity = {
        "schema": _CAPACITY_SCHEMA,
        "requested_members": requested_members,
        "dispatched_members": len(clean),
        "dropped_members": max(0, requested_members - len(clean)),
        "max_members": max_members,
        "max_concurrency": concurrency_limit,
        "concurrency": workers,
        "scale_mode": scale,
        "capacity_tier": _capacity_tier(len(clean), requested_members),
    }

    def _one(member: dict[str, Any]) -> dict[str, Any]:
        agent_id = str(member.get("name") or member.get("agent_id"))
        display = str(member.get("display_name") or agent_id)
        rec: dict[str, Any] = {
            "agent_id": agent_id,
            "display_name": display,
            "reply": "",
            "ok": False,
            "error": None,
        }
        try:
            res = agent_caller(
                agent_id=agent_id,
                prompt=build_fanout_prompt(msg, display, roster),
                timeout_s=90,
            )
            rec["ok"] = bool(res.get("success"))
            rec["reply"] = str(res.get("output") or "")
            rec["error"] = res.get("error")
        except Exception as exc:  # noqa: BLE001 — one member's failure is isolated
            rec["error"] = f"{type(exc).__name__}: {exc}"
        return rec

    results: list[dict[str, Any]] = []
    with _cf.ThreadPoolExecutor(max_workers=workers, thread_name_prefix="group-fanout") as pool:
        futures = [pool.submit(_one, m) for m in clean]
        for fut in _cf.as_completed(futures):
            results.append(fut.result())

    order = {str(m.get("name") or m.get("agent_id")): i for i, m in enumerate(clean)}
    results.sort(key=lambda r: order.get(r["agent_id"], len(order)))
    for index, reply in enumerate(results):
        reply.setdefault(
            "response_id",
            _response_id(turn_id, index, str(reply.get("agent_id") or "")),
        )
    spoke = sum(1 for r in results if r["ok"] and r["reply"].strip())
    arbitration = arbitrate_group_fanout(results, turn_id=turn_id)
    synthesis = synthesize_group_fanout(results, arbitration)
    return {
        "ok": spoke > 0,
        "replies": results,
        "count": len(results),
        "spoke": spoke,
        "dropped": capacity["dropped_members"],
        "capacity": capacity,
        "arbitration": arbitration,
        "synthesis": synthesis,
    }
