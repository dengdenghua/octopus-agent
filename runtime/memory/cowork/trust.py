"""成员信任分（闲鱼式）— cowork 群里"这个人/这个 AI 靠不靠谱"的可解释评分。

设计约束（与署名链/封签同一套价值观）：
- **纯计算、零 I/O**：输入折叠后的群状态 + 绑定项目的任务读模型 + 原始成员
  事件，输出每个成员的分数与完整构成。与 ``frontend/src/core/projects``
  的纯函数风格对齐，方便单测。
- **可解释**：分数由显式权重（下方常量）从可数事件算出，不接黑盒模型；
  每个分数都带 ``components``，UI 悬浮即可回答"这个分怎么来的"。
- **不可造假**：事件源（群成员时间线、任务审核链）带哈希链封签
  （``runtime/platform/integrity/chain.py``），分母抹不掉、改不动。
- **诚实边界**：没有交付记录就如实给 70 分"无记录"，绝不编造中立证据。

信号语义（正/负）：
- 按约完成（done）→ 正；failed/rejected → 负；
- 返工（attempts-1，reset/重派累计）→ 负；
- 人工签收（review_mode=operator/human_run，真人签过字的交付）→ 加分；
- 被真人接管（drive 事件把方向盘交给人类）→ 对该 AI 成员扣分——它的产出
  曾不被信任到需要人接手。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from runtime.memory.cowork.group import GroupState, Member, MemberEvent

# ── 评分权重（全部显式，改这里即改全站口径）──────────────────
BASE_NO_RECORD = 70.0  # 无任何记录时的中立分
COMPLETION_FLOOR = 40.0  # 全失败时的地板分
COMPLETION_SPAN = 55.0  # 完成率 → 分数的映射跨度 (floor .. floor+span)
HUMAN_SIGNED_BONUS = 2.0  # 每单人工签收
HUMAN_SIGNED_BONUS_CAP = 10.0
REWORK_PENALTY = 3.0  # 每次返工
REWORK_PENALTY_CAP = 15.0
TAKEOVER_PENALTY = 5.0  # 每次被真人接管
TAKEOVER_PENALTY_CAP = 20.0

_LABEL_RELIABLE = "可靠"
_LABEL_NORMAL = "正常"
_LABEL_WATCH = "观察"
_LABEL_RISKY = "高风险"
_LABEL_NO_RECORD = "无记录"


def _clamp_score(value: float) -> int:
    return max(0, min(100, round(value)))


def _label_for(score: int, sample_size: int, takeovers: int = 0) -> str:
    if sample_size == 0 and takeovers == 0:
        return _LABEL_NO_RECORD
    if score >= 85:
        return _LABEL_RELIABLE
    if score >= BASE_NO_RECORD:
        return _LABEL_NORMAL
    if score >= 50:
        return _LABEL_WATCH
    return _LABEL_RISKY


def takeover_counts(events: Sequence[MemberEvent]) -> dict[str, int]:
    """每个成员被真人接管过的次数（含已交还的历史）。

    只数 ``action="drive"`` 且方向盘交给人类的事件；AI 交还给 AI、真人自驱
    都不算——前者是恢复正常，后者从来不是被接管。
    """

    counts: dict[str, int] = {}
    for event in events:
        if event.action == "drive" and event.driver == "human" and event.target_id:
            counts[event.target_id] = counts.get(event.target_id, 0) + 1
    return counts


def _completed_by(task: dict[str, Any]) -> str:
    output = task.get("output")
    if isinstance(output, dict):
        return str(output.get("completed_by") or "").strip()
    return ""


def deliveries_for_member(
    member: Member, tasks: Sequence[dict[str, Any]]
) -> list[dict[str, Any]]:
    """归到该成员名下的交付记录。

    - ``agent`` / ``role`` 成员：按派单归属（assigned_agent 优先，退回
      assigned_role——与 project-os-tab 成员卡的 ownedTasks 口径一致）；
    - ``human`` 成员：只认真人节点执行且 ``output.completed_by`` 署名为本人
      的任务——签名链里谁签的字就是谁干的，不按头像猜。
    """

    if member.kind == "human":
        return [
            task
            for task in tasks
            if str(task.get("review_mode") or "") == "human_run"
            and _completed_by(task) == member.id
        ]
    matched: list[dict[str, Any]] = []
    for task in tasks:
        assigned_agent = str(task.get("assigned_agent") or "").strip()
        assigned_role = str(task.get("assigned_role") or "").strip()
        if assigned_agent:
            hit = assigned_agent == member.id
        else:
            hit = bool(assigned_role) and assigned_role == member.id
        if hit:
            matched.append(task)
    return matched


def member_trust(
    member: Member,
    tasks: Sequence[dict[str, Any]],
    takeovers: int = 0,
) -> dict[str, Any]:
    """一个成员的信任分与完整构成。``tasks`` 是全量任务读模型 dict 列表。"""

    mine = deliveries_for_member(member, tasks)
    completed = sum(1 for t in mine if t.get("status") == "done")
    failed = sum(1 for t in mine if t.get("status") in ("failed", "rejected"))
    rework = sum(max(0, int(t.get("attempts") or 0) - 1) for t in mine)
    human_signed = sum(
        1
        for t in mine
        if t.get("status") == "done"
        and str(t.get("review_mode") or "") in ("operator", "human_run")
    )
    sample_size = completed + failed

    if sample_size == 0 and takeovers == 0:
        score = _clamp_score(BASE_NO_RECORD)
    else:
        rate = completed / sample_size if sample_size else 0.5
        score = COMPLETION_FLOOR + COMPLETION_SPAN * rate
        score += min(HUMAN_SIGNED_BONUS_CAP, HUMAN_SIGNED_BONUS * human_signed)
        score -= min(REWORK_PENALTY_CAP, REWORK_PENALTY * rework)
        score -= min(TAKEOVER_PENALTY_CAP, TAKEOVER_PENALTY * takeovers)
        score = _clamp_score(score)

    return {
        "member_id": member.id,
        "kind": member.kind,
        "driver": member.driver,
        "accountable_owner": member.accountable_owner,
        "score": score,
        "label": _label_for(score, sample_size, takeovers),
        "sample_size": sample_size,
        "components": {
            "completed": completed,
            "failed": failed,
            "rework_count": rework,
            "human_signed": human_signed,
            "takeover_count": takeovers,
        },
    }


def trust_report(
    state: GroupState,
    tasks: Sequence[dict[str, Any]],
    events: Sequence[MemberEvent],
) -> dict[str, Any]:
    """整群信任分报告。``tasks`` 为绑定项目任务读模型（可空），
    ``events`` 为群成员时间线原始事件。"""

    takeovers = takeover_counts(events)
    scores = [
        member_trust(member, tasks, takeovers.get(member.id, 0))
        for member in state.roster
    ]
    scores.sort(key=lambda item: (-item["score"], item["member_id"]))
    return {
        "scores": scores,
        "weights": {
            "base_no_record": BASE_NO_RECORD,
            "completion_floor": COMPLETION_FLOOR,
            "completion_span": COMPLETION_SPAN,
            "human_signed_bonus": HUMAN_SIGNED_BONUS,
            "human_signed_bonus_cap": HUMAN_SIGNED_BONUS_CAP,
            "rework_penalty": REWORK_PENALTY,
            "rework_penalty_cap": REWORK_PENALTY_CAP,
            "takeover_penalty": TAKEOVER_PENALTY,
            "takeover_penalty_cap": TAKEOVER_PENALTY_CAP,
        },
        "basis": "sealed_events+review_chain",
    }
