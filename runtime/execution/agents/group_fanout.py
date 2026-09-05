"""Group fan-out — the WeChat "boss speaks, everyone chimes in" experience.

When a message lands in a team room and the user wants the whole group to react
(蜂群 / 冒泡), this fans the message out to each member agent IN PARALLEL. Each
member replies briefly in its own persona — a short "bubble", not a full task
run — and the replies come back per-member so the UI can stream each as its own
group-chat bubble.

Each unit is one of the room's in-process roster agents giving a conversational
reply through the same delegation boundary as an ordinary agent turn.

Honest scope: this is still *conversation*, not a full task graph.  It does,
however, now returns a deterministic arbitration summary so downstream team
surfaces can pick a primary response, classify failures, and decide the next
action without re-parsing bubbles.

Debate (蜂群多轮辩论): pass ``debate_rounds >= 2`` to run a second (or Nth)
round where every member sees the previous round's transcript and is invited to
@-rebut or support specific members — grafting the "成员互见 + @反驳" capability
that persistent team rooms have onto our one-shot fan-out.
"""

from __future__ import annotations

import concurrent.futures as _cf
import logging
import re
from collections.abc import Callable
from typing import Any

from runtime.execution.agents.collaboration_quality import (
    apply_semantic_review,
    assess_collaboration_quality,
    build_collaboration_delivery,
    build_semantic_review_prompt,
    parse_semantic_review,
)
from runtime.execution.agents.team_patterns import (
    is_team_presence_query,
    pattern_member_role,
    pattern_role_label,
)

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

# Hard bound on debate rounds so a hostile cue can't spin up unbounded LLM cost.
_MAX_DEBATE_ROUNDS = 3
_LOG = logging.getLogger(__name__)

_ERROR_OUTPUT_PREFIXES = (
    "[planner error]",
    "[runner error]",
    "[subagent error]",
)

_FUTURE_WORK_RE = re.compile(
    r"(?:稍后|一会儿|随后|晚点|查完|整理好|完成后|做好后|"
    r"我(?:先去|去查|来查|会去|马上去)).{0,80}"
    r"(?:发|回复|汇报|整理|研究|查|看|做|处理|分析|验证|测试|扒)",
    re.IGNORECASE,
)
_ANSWER_EVIDENCE_RE = re.compile(
    r"(?:结论|结果|发现|数据显示|根据|证据|风险(?:是|在于)|建议(?:是|采用)|"
    r"已(?:完成|验证|测试|查到|确认)|https?://)",
    re.IGNORECASE,
)
_QUESTION_ONLY_RE = re.compile(r"[?？]\s*$")
_INPUT_REQUEST_RE = re.compile(
    r"(?:请|麻烦|需要你|能否|可否).{0,24}(?:提供|补充|发|贴|说明|告诉)|"
    r"(?:把|先把).{0,24}(?:发来|贴出来|告诉我)",
    re.IGNORECASE,
)
_GENERIC_WILLINGNESS_RE = re.compile(
    r"(?:^|[，,。.!！\s])(?:没问题|可以(?:的)?|收到|我来|交给我|"
    r"我能帮|我可以帮|随时可以).{0,28}$",
    re.IGNORECASE,
)


def is_group_presence_query(message: str) -> bool:
    """Return whether a message only asks if the team is available."""

    return is_team_presence_query(message)


def format_group_presence_reply(members: list[dict[str, Any]]) -> str:
    """Build a truthful roster-status answer without spending model calls."""

    names = [
        str(
            member.get("display_name") or member.get("name") or member.get("agent_id") or ""
        ).strip()
        for member in members
        if isinstance(member, dict)
    ]
    names = [name for name in names if name]
    if not names:
        return "当前没有可响应的 AI 成员。"
    return f"{len(names)} 位 AI 成员均已就绪：{'、'.join(names)}。"


def _error_output(output: str) -> str | None:
    text = str(output or "").strip()
    lowered = text.lower()
    if any(lowered.startswith(prefix) for prefix in _ERROR_OUTPUT_PREFIXES):
        return text
    # A group-bubble lane cannot continue working after it returns. Treat a
    # promise to report later as non-delivery, otherwise the UI would mark a
    # future intention as a completed member result.
    if _FUTURE_WORK_RE.search(text) and not _ANSWER_EVIDENCE_RE.search(text):
        return "成员只承诺稍后处理，未在本轮交付结果"
    # Fan-out replies must be self-contained contributions. Questions and
    # requests for more input may be useful blockers, but are not answers and
    # must not enter arbitration as completed responses.
    if len(text) <= 160 and _QUESTION_ONLY_RE.search(text) and not _ANSWER_EVIDENCE_RE.search(text):
        return "成员只提出反问，未形成有效回应"
    if len(text) <= 200 and _INPUT_REQUEST_RE.search(text) and not _ANSWER_EVIDENCE_RE.search(text):
        return "成员要求补充输入，未形成有效回应"
    if len(text) <= 80 and _GENERIC_WILLINGNESS_RE.search(text):
        return "成员仅表达接收或意愿，未形成有效回应"
    return None


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
    quality = reply.get("quality")
    if isinstance(quality, dict):
        try:
            # Keep successful replies above empty successes while ranking them
            # with the explicit quality rubric rather than response length.
            return 100 + max(0, min(100, int(quality.get("score") or 0)))
        except (TypeError, ValueError):
            pass
    return 100 + min(20, max(1, len(text) // 40))


def _reply_status(reply: dict[str, Any]) -> str:
    if reply.get("cancelled"):
        return "cancelled"
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
            "round": int(reply.get("round") or 1),
            "pattern_role": reply.get("pattern_role"),
            "error": reply.get("error"),
            "validation": reply.get("validation"),
            "quality": reply.get("quality"),
        }
        if status == "cancelled":
            row["recommended_action"] = "none"
        elif status == "failed":
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
    cancelled = [row["agent_id"] for row in rows if row["status"] == "cancelled"]
    empty = [row["agent_id"] for row in rows if row["status"] == "empty"]

    if cancelled and not primary and not failed and not empty:
        next_action = "collaboration_cancelled"
    elif primary and failed:
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
        "cancelled_agent_ids": cancelled,
        "empty_agent_ids": empty,
        "rounds": max([int(r.get("round") or 1) for r in rows], default=1),
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


def _pattern_role_instruction(pattern_role: str | None) -> str:
    instructions = {
        "proposer": "提出一个具体、可验证的候选方案，不要只给态度。",
        "critic": "不要附和；优先寻找候选方案的漏洞、反例和失败条件。",
        "verifier": "依据事实、测试或验收标准检查结论，明确哪些仍未被证明。",
        "alternative": "尝试一条不同路径，并说明它相对已有方案的取舍。",
        "explorer": "独立给出你的专业判断，避免重复其他成员可能给出的常识。",
    }
    role = str(pattern_role or "").strip()
    if not role:
        return ""
    return f"本轮职责：{pattern_role_label(role)}。{instructions.get(role, '')}\n"


def build_fanout_prompt(
    message: str,
    speaker: str,
    roster: list[str],
    *,
    pattern_role: str | None = None,
) -> str:
    """The per-member instruction: answer the actual question in persona."""
    names = "、".join(roster) if roster else "(只有你)"
    return (
        f"你在一个团队群聊里,群成员有:{names}。\n"
        f"群里有人（{speaker or '老板'}）说:「{message}」\n\n"
        f"{_pattern_role_instruction(pattern_role)}"
        f"请用你自己的人设、第一人称,像在微信群里冒泡那样自然地接一句切题的话"
        f"(1-3 句即可):围绕这句话本身给出你的观点、信息或能直接帮上的具体动作。\n"
        f"硬性要求:\n"
        f"1) 必须切题——直接回应『{message}』这件事,不要跑题到你自己的日常话题或"
        f"泛泛地说'我能帮你'。\n"
        f"2) 不要反问、不要只表态不干活、不要复述别人的话。\n"
        f"3) 只能陈述本轮已经完成的判断或结果；禁止承诺'稍后再查/整理后发'。\n"
        f"4) 不要长篇大论,不要列大纲。"
    )


def build_debate_prompt(
    message: str,
    speaker: str,
    roster: list[str],
    transcript: list[dict[str, Any]],
    *,
    round_no: int = 2,
    mentioned: list[str] | None = None,
    pattern_role: str | None = None,
) -> str:
    """Round-2+ instruction: everyone sees the prior round and @-rebuts.

    ``transcript`` is ``[{agent_id, display_name, reply}]`` from the previous
    round. ``mentioned`` are display names the boss explicitly @-mentioned in
    the original message — those members are the debate's first targets.
    """
    names = "、".join(roster) if roster else "(只有你)"
    lines = []
    for t in transcript or []:
        who = str(t.get("display_name") or t.get("agent_id") or "?")
        reply = str(t.get("reply") or "").strip()
        if reply:
            lines.append(f"· {who}: {reply}")
    transcript_text = "\n".join(lines) if lines else "(上一轮没有有效发言)"
    mention_note = ""
    if mentioned:
        mention_note = (
            "老板在消息里专门 @ 了这些成员，请优先针对他们的观点展开："
            + "、".join(mentioned)
            + "。\n"
        )
    return (
        f"你在一个团队群聊里,群成员有:{names}。\n"
        f"{speaker or '用户'}刚才问:「{message}」\n\n"
        f"—— 第 {round_no} 轮 · 成员互见辩论 ——\n"
        f"这是大家上一轮的全部发言（现在所有人都看得到）：\n{transcript_text}\n\n"
        f"{mention_note}"
        f"{_pattern_role_instruction(pattern_role)}"
        f"请用你自己的人设、第一人称回应（1-3 句，必须围绕上面这条消息本身，"
        f"不要跑题到你的日常话题）：\n"
        f"1) 如果你不同意某位成员的看法，用「@对方名字」点名反驳，只驳观点、不人身攻击；\n"
        f"2) 如果你认同某人，可以点名支持并补一句你的角度；\n"
        f"3) 不要复述别人已经说过的话，不要长篇大论。"
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
    debate_rounds: int = 1,
    mentioned: list[str] | None = None,
    speaker: str = "用户",
    pattern: dict[str, Any] | None = None,
    max_quality_retries: int = 1,
    semantic_reviewer: Callable[..., dict[str, Any]] | None = None,
    semantic_reviewer_agent_id: str | None = None,
    on_reply: Callable[[dict[str, Any]], None] | None = None,
    result_committer: Callable[[dict[str, Any]], bool] | None = None,
    should_cancel: Callable[[], bool] | None = None,
    should_cancel_member: Callable[[str], bool] | None = None,
) -> dict[str, Any]:
    """Fan ``message`` out to each member in parallel; collect persona replies.

    ``members`` is ``[{name|agent_id, display_name?}]``. ``agent_caller`` is the
    one-shot subagent invoker — ``agent_caller(agent_id=..., prompt=...)`` →
    ``{output, success, error}`` (in production: ``delegation_skills._call_agent``).

    When ``debate_rounds >= 2`` the fan-out becomes a multi-round debate: each
    subsequent round feeds every member the previous round's full transcript and
    invites them to @-rebut or support specific members. Replies carry a
    ``round`` field (1-based) so the UI can group/annotate rounds.

    Returns ``{ok, replies:[{agent_id, display_name, reply, ok, error, round}],
    count, spoke, debate:{rounds, transcript, mentioned}, arbitration}``. Order
    follows the roster within each round. Never raises — one member's failure is
    isolated.
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

    pattern_payload = dict(pattern) if isinstance(pattern, dict) else {}
    pattern_id = str(pattern_payload.get("id") or "parallel_roundtable").strip()
    try:
        pattern_rounds = int(pattern_payload.get("debate_rounds") or 1)
    except (TypeError, ValueError):
        pattern_rounds = 1
    # Debate rounds are clamped so a hostile cue can't spin up unbounded cost.
    rounds = max(
        1,
        min(max(int(debate_rounds or 1), pattern_rounds), _MAX_DEBATE_ROUNDS),
    )
    quality_retries = max(0, min(int(max_quality_retries or 0), 2))

    def _cancelled() -> bool:
        if should_cancel is None:
            return False
        try:
            return bool(should_cancel())
        except Exception as exc:  # noqa: BLE001 - cancellation checks must fail open
            _LOG.warning("group fanout cancellation check failed: %s", exc)
            return False

    def _member_cancelled(agent_id: str) -> bool:
        if _cancelled():
            return True
        if should_cancel_member is None:
            return False
        try:
            return bool(should_cancel_member(agent_id))
        except Exception as exc:  # noqa: BLE001 - cancellation checks must fail open
            _LOG.warning("group member cancellation check failed: %s", exc)
            return False

    def _run_round(round_no: int, transcript: list[dict[str, Any]]) -> list[dict[str, Any]]:
        def _one(index: int, member: dict[str, Any]) -> dict[str, Any]:
            agent_id = str(member.get("name") or member.get("agent_id"))
            display = str(member.get("display_name") or agent_id)
            pattern_role = pattern_member_role(pattern_id, index)
            if round_no == 1:
                prompt = build_fanout_prompt(
                    msg,
                    speaker,
                    roster,
                    pattern_role=pattern_role,
                )
            else:
                prompt = build_debate_prompt(
                    msg,
                    speaker,
                    roster,
                    transcript,
                    round_no=round_no,
                    mentioned=mentioned,
                    pattern_role=pattern_role,
                )
            rec: dict[str, Any] = {
                "response_id": _response_id(
                    turn_id,
                    (round_no - 1) * len(clean) + index,
                    agent_id,
                ),
                "agent_id": agent_id,
                "display_name": display,
                "reply": "",
                "ok": False,
                "error": None,
                "round": round_no,
                "pattern_role": pattern_role,
                "validation": {
                    "status": "pending",
                    "reason": None,
                    "attempt_count": 0,
                    "attempts": [],
                },
            }

            def _mark_cancelled() -> dict[str, Any]:
                rec["cancelled"] = True
                rec["error"] = "collaboration cancelled"
                rec["validation"] = {
                    "status": "cancelled",
                    "reason": rec["error"],
                    "attempt_count": len(attempts),
                    "attempts": attempts,
                }
                return rec

            attempts: list[dict[str, Any]] = []
            try:
                attempt_prompt = prompt
                for attempt_index in range(quality_retries + 1):
                    retry_quality = False
                    for steering_restart in range(3):
                        if _member_cancelled(agent_id):
                            return _mark_cancelled()
                        res = agent_caller(
                            agent_id=agent_id,
                            prompt=attempt_prompt,
                            timeout_s=90,
                        )
                        # Cancellation wins over a simultaneously arriving result.
                        # This prevents a late provider response from reappearing
                        # after the user has stopped the collaboration.
                        if _member_cancelled(agent_id):
                            return _mark_cancelled()
                        output = str(res.get("output") or "").strip()
                        output_error = _error_output(output)
                        transport_ok = bool(res.get("success"))
                        rejection = str(res.get("error") or output_error or "").strip() or None
                        attempts.append(
                            {
                                "attempt": len(attempts) + 1,
                                "status": (
                                    "accepted"
                                    if transport_ok and output_error is None
                                    else "rejected"
                                ),
                                "reason": rejection,
                            }
                        )
                        if (
                            transport_ok
                            and output_error is not None
                            and attempt_index < quality_retries
                        ):
                            attempt_prompt = (
                                prompt
                                + "\n\n<quality-retry>上一版回复未通过验收："
                                + output_error
                                + "。请直接重写并在本轮给出与原问题相关的具体判断、依据或明确阻塞；"
                                + "不要解释返工过程。</quality-retry>"
                            )
                            retry_quality = True
                            break
                        rec["ok"] = transport_ok and output_error is None
                        rec["reply"] = output if rec["ok"] else ""
                        rec["error"] = rejection
                        rec["validation"] = {
                            "status": "accepted" if rec["ok"] else "rejected",
                            "reason": rec["error"],
                            "attempt_count": len(attempts),
                            "attempts": attempts,
                        }
                        for audit_key in (
                            "context_delivery",
                            "session_compaction",
                            "steering_count",
                            "steering_generation",
                            "steering_seq",
                        ):
                            if audit_key in res:
                                rec[audit_key] = res[audit_key]
                        committed = True
                        if result_committer is not None:
                            try:
                                committed = bool(result_committer(dict(rec)))
                            except Exception as exc:  # noqa: BLE001 - isolate callback faults
                                _LOG.warning(
                                    "group fanout result committer failed: %s",
                                    exc,
                                    exc_info=True,
                                )
                        if committed:
                            break
                        attempts[-1]["status"] = "superseded_by_steering"
                        attempts[-1]["reason"] = "newer member steering arrived"
                        if steering_restart == 2:
                            rec["ok"] = False
                            rec["reply"] = ""
                            rec["error"] = "member steering did not stabilize; retry the member"
                            rec["validation"] = {
                                "status": "rejected",
                                "reason": rec["error"],
                                "attempt_count": len(attempts),
                                "attempts": attempts,
                            }
                    if retry_quality:
                        continue
                    break
            except Exception as exc:  # noqa: BLE001 — one member's failure is isolated
                rec["error"] = f"{type(exc).__name__}: {exc}"
                rec["validation"] = {
                    "status": "rejected",
                    "reason": rec["error"],
                    "attempt_count": len(attempts) + 1,
                    "attempts": [
                        *attempts,
                        {
                            "attempt": len(attempts) + 1,
                            "status": "rejected",
                            "reason": rec["error"],
                        },
                    ],
                }
            return rec

        def _cancelled_reply(index: int, member: dict[str, Any]) -> dict[str, Any]:
            agent_id = str(member.get("name") or member.get("agent_id"))
            return {
                "response_id": _response_id(
                    turn_id,
                    (round_no - 1) * len(clean) + index,
                    agent_id,
                ),
                "agent_id": agent_id,
                "display_name": str(member.get("display_name") or agent_id),
                "reply": "",
                "ok": False,
                "cancelled": True,
                "error": "collaboration cancelled",
                "round": round_no,
                "pattern_role": pattern_member_role(pattern_id, index),
                "validation": {
                    "status": "cancelled",
                    "reason": "collaboration cancelled",
                    "attempt_count": 0,
                    "attempts": [],
                },
            }

        def _emit(reply: dict[str, Any]) -> None:
            if on_reply is None:
                return
            try:
                on_reply(dict(reply))
            except Exception as exc:  # noqa: BLE001 - observability must not fail work
                _LOG.warning("group fanout reply collector failed: %s", exc, exc_info=True)

        results: list[dict[str, Any]] = []
        if _cancelled():
            results = [_cancelled_reply(index, member) for index, member in enumerate(clean)]
            for reply in results:
                _emit(reply)
            return results

        pool = _cf.ThreadPoolExecutor(max_workers=workers, thread_name_prefix="group-fanout")
        futures = {
            pool.submit(_one, index, member): (index, member) for index, member in enumerate(clean)
        }
        pending = set(futures)
        stopped = False
        try:
            while pending:
                if _cancelled():
                    stopped = True
                    for future in pending:
                        future.cancel()
                    # Treat every not-yet-collected lane as cancelled even if
                    # its provider thread is still unwinding. Late values are
                    # deliberately ignored and never reach ``on_reply``.
                    cancelled_rows = [_cancelled_reply(*futures[future]) for future in pending]
                    results.extend(cancelled_rows)
                    for reply in cancelled_rows:
                        _emit(reply)
                    break
                done, pending = _cf.wait(
                    pending,
                    timeout=0.05,
                    return_when=_cf.FIRST_COMPLETED,
                )
                for future in done:
                    reply = future.result()
                    results.append(reply)
                    _emit(reply)
        finally:
            pool.shutdown(wait=not stopped, cancel_futures=stopped)

        order = {str(m.get("name") or m.get("agent_id")): i for i, m in enumerate(clean)}
        results.sort(key=lambda r: order.get(r["agent_id"], len(order)))
        return results

    all_replies: list[dict[str, Any]] = []
    transcript: list[dict[str, Any]] = []
    for round_no in range(1, rounds + 1):
        round_replies = _run_round(round_no, transcript)
        all_replies.extend(round_replies)
        if _cancelled():
            break
        # Feed the next round only the successful, non-empty replies.
        transcript = [
            {
                "agent_id": r["agent_id"],
                "display_name": r["display_name"],
                "reply": r["reply"],
            }
            for r in round_replies
            if r["ok"] and str(r.get("reply") or "").strip()
        ]
        if not transcript:
            break  # nobody spoke this round — no point debating into a void

    spoke = sum(1 for r in all_replies if r["ok"] and r["reply"].strip())
    attempt_count = sum(
        max(1, int((reply.get("validation") or {}).get("attempt_count") or 1))
        for reply in all_replies
    )
    quality_retry_count = max(0, attempt_count - len(all_replies))
    recovered_after_retry_count = sum(
        1
        for reply in all_replies
        if reply.get("ok") and int((reply.get("validation") or {}).get("attempt_count") or 1) > 1
    )
    quality = assess_collaboration_quality(msg, all_replies, pattern=pattern_payload)
    # Outcome order is identical to reply order, including repeated agent ids
    # across debate rounds, so zip preserves per-round quality identity.
    for reply, outcome in zip(all_replies, quality.get("outcomes") or [], strict=False):
        reply["quality"] = outcome if isinstance(outcome, dict) else None
    arbitration = arbitrate_group_fanout(all_replies, turn_id=turn_id)
    synthesis = synthesize_group_fanout(all_replies, arbitration)
    delivery = build_collaboration_delivery(all_replies, quality)
    if (
        semantic_reviewer is not None
        and not _cancelled()
        and bool(quality.get("evidence_required"))
    ):
        valid_response_ids = {
            str(item.get("response_id") or "")
            for item in delivery.get("contributions") or []
            if isinstance(item, dict) and str(item.get("response_id") or "")
        }
        try:
            review_result = semantic_reviewer(
                prompt=build_semantic_review_prompt(msg, delivery),
                timeout_s=120,
            )
            if not review_result.get("success"):
                raise RuntimeError(str(review_result.get("error") or "semantic reviewer failed"))
            semantic_review = parse_semantic_review(
                str(review_result.get("output") or ""),
                valid_response_ids=valid_response_ids,
                reviewer_agent_id=semantic_reviewer_agent_id,
            )
        except Exception as exc:  # noqa: BLE001 — fail closed, keep contributions visible
            semantic_review = {
                "schema": "octopus.collaboration_semantic_review.v1",
                "verdict": "review_failed",
                "confidence": 0.0,
                "accepted_response_ids": [],
                "issues": [
                    {
                        "code": "reviewer_error",
                        "message": f"{type(exc).__name__}: {exc}"[:1000],
                    }
                ],
                "summary": "语义验证执行失败",
                "reviewer_agent_id": semantic_reviewer_agent_id,
            }
        quality, delivery = apply_semantic_review(quality, delivery, semantic_review)
    debate = (
        {
            "rounds": max([int(r.get("round") or 1) for r in all_replies], default=1),
            "transcript": transcript,
            "mentioned": mentioned or [],
        }
        if rounds > 1
        else None
    )
    return {
        "ok": spoke > 0,
        "cancelled": _cancelled(),
        "replies": all_replies,
        "count": len(all_replies),
        "spoke": spoke,
        "attempt_count": attempt_count,
        "quality_retry_count": quality_retry_count,
        "recovered_after_retry_count": recovered_after_retry_count,
        "dropped": capacity["dropped_members"],
        "capacity": capacity,
        "arbitration": arbitration,
        "synthesis": synthesis,
        "quality": quality,
        "delivery": delivery,
        "debate": debate,
        "pattern": pattern_payload or None,
    }
