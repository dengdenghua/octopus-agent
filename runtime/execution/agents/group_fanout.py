"""Group fan-out — the WeChat "boss speaks, everyone chimes in" experience.

When a message lands in a team room and the user wants the whole group to react
(蜂群 / 冒泡), this fans the message out to each member agent IN PARALLEL. Each
member replies briefly in its own persona — a short "bubble", not a full task
run — and the replies come back per-member so the UI can stream each as its own
group-chat bubble.

This is the native-agent sibling of ``cli_team.run_cli_team`` (which fans out to
external coding CLIs): same parallel-and-collect shape, but each unit is one of
the room's in-process roster agents giving a conversational reply.

Honest scope: this is *conversation*, not orchestration — every member answers
independently, there is no leader, no shared task graph, no merge. Tracked work
still goes through tasks / cluster mode.
"""

from __future__ import annotations

import concurrent.futures as _cf
from collections.abc import Callable
from typing import Any

# Keep the group from getting spammy / expensive: a real group chat has a few
# people chime in, not 20. Also bounds the parallel LLM fan-out cost.
_MAX_FANOUT = 6


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
    turn_id: str | None = None,
) -> dict[str, Any]:
    """Fan ``message`` out to each member in parallel; collect persona replies.

    ``members`` is ``[{name|agent_id, display_name?}]``. ``agent_caller`` is the
    one-shot subagent invoker — ``agent_caller(agent_id=..., prompt=...)`` →
    ``{output, success, error}`` (in production: ``delegation_skills._call_agent``).

    Returns ``{ok, replies:[{agent_id, display_name, reply, ok, error}], count,
    spoke}``. Order follows the roster. Never raises — one member's failure is
    isolated.
    """
    msg = (message or "").strip()
    if not msg:
        return {"ok": False, "error": "message is required", "replies": [], "count": 0, "spoke": 0}
    clean = [
        m
        for m in (members or [])
        if isinstance(m, dict) and (m.get("name") or m.get("agent_id"))
    ][:max_members]
    if not clean:
        return {"ok": False, "error": "no members", "replies": [], "count": 0, "spoke": 0}

    roster = [
        str(m.get("display_name") or m.get("name") or m.get("agent_id")) for m in clean
    ]

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
    workers = max(1, min(len(clean), max_members))
    with _cf.ThreadPoolExecutor(max_workers=workers, thread_name_prefix="group-fanout") as pool:
        futures = [pool.submit(_one, m) for m in clean]
        for fut in _cf.as_completed(futures):
            results.append(fut.result())

    order = {
        str(m.get("name") or m.get("agent_id")): i for i, m in enumerate(clean)
    }
    results.sort(key=lambda r: order.get(r["agent_id"], len(order)))
    spoke = sum(1 for r in results if r["ok"] and r["reply"].strip())
    return {
        "ok": spoke > 0,
        "replies": results,
        "count": len(results),
        "spoke": spoke,
        "dropped": max(0, len([m for m in (members or []) if isinstance(m, dict)]) - len(clean)),
    }
