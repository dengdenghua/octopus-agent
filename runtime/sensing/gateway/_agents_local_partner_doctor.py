"""Doctor-style readiness summary for LocalPartner.

Extracted from ``agents_local_partner.py`` (god-file reduction). Aggregates the
per-partner cards into a compact "what on this machine is usable right now?"
report for the operator.
"""

from __future__ import annotations

from typing import Any

from .agents_models import LocalPartnerWire

_DOCTOR_STATUS_LABELS = {
    "registered": "已连接",
    "ready": "可自动派工",
    "model_unconfigured": "模型未配置",
    "launcher_only": "仅发现启动器",
    "headless_unsupported": "暂不支持 headless",
    "missing": "未安装",
    "detected": "已检测到",
    "unsafe_executable": "路径不安全",
}


def _doctor_next_action(status: str) -> str:
    if status in {"registered", "ready"}:
        return "可直接派工；建议健康检查后再跑重要任务。"
    if status == "model_unconfigured":
        return "打开原生 CLI 登录/选模型，并确认 CLI 账号或企业授权可用。"
    if status == "launcher_only":
        return "安装官方 headless CLI；桌面/IDE 启动器只能手动使用。"
    if status == "headless_unsupported":
        return "回原生 CLI 使用，或等待厂商稳定 prompt-to-stdout 参数。"
    if status == "unsafe_executable":
        return "移除不安全 PATH，改用官方安装路径。"
    if status == "missing":
        return "安装对应官方 CLI，并确认命令进入 PATH。"
    return "打开原生 CLI 复查登录、模型、权限和网络状态。"


def doctor_summary(partners: list[LocalPartnerWire]) -> dict[str, Any]:
    """Aggregate local partner readiness into a doctor-style report.

    The per-partner cards stay detailed; this summary answers the operator's
    first question: "what on this machine is actually usable right now?"
    """
    total = len(partners)
    detected = sum(1 for partner in partners if partner.detected)
    ready = sum(1 for partner in partners if partner.ready)
    registered = sum(1 for partner in partners if partner.registered)
    groups_by_status: dict[str, dict[str, Any]] = {}
    for partner in partners:
        status = str(
            partner.effective_status or partner.readiness_status or partner.status or "missing"
        )
        group = groups_by_status.setdefault(
            status,
            {
                "status": status,
                "label": _DOCTOR_STATUS_LABELS.get(status, status),
                "count": 0,
                "partner_ids": [],
                "next_action": _doctor_next_action(status),
            },
        )
        group["count"] += 1
        group["partner_ids"].append(partner.id)

    groups = sorted(
        groups_by_status.values(),
        key=lambda group: (
            0 if group["status"] in {"registered", "ready"} else 1,
            str(group["label"]),
        ),
    )
    needs_attention = total - sum(
        int(group["count"]) for group in groups if group["status"] in {"registered", "ready"}
    )
    next_actions: list[str] = []
    seen: set[str] = set()
    for group in groups:
        if group["status"] in {"registered", "ready"}:
            continue
        action = str(group["next_action"])
        if action and action not in seen:
            next_actions.append(action)
            seen.add(action)
    if not next_actions and ready:
        next_actions.append("全部可用伙伴建议先跑健康检查，再执行重要派工。")
    elif not next_actions:
        next_actions.append("先安装至少一个官方 CLI，并完成原生登录/授权。")

    return {
        "summary": f"{ready}/{total} 个本地 CLI 伙伴可自动派工，{needs_attention} 个需要处理。",
        "total": total,
        "detected": detected,
        "ready": ready,
        "registered": registered,
        "needs_attention": needs_attention,
        "groups": groups,
        "next_actions": next_actions[:4],
    }


__all__ = ["doctor_summary"]
