"""Activate only the reviewed phase team, after an owner decision."""

from runtime.memory.cowork.group import MemberEvent
from runtime.projectos.governance import phase_authorized, phase_fingerprint, reported_cost
from runtime.protocol import ServerMethod


async def adjust_budget(runtime, turn, log, emitter, *, store, project, value, owner_id, tenant_id):
    import math
    from uuid import uuid4

    async def emit(text):
        await runtime._emit_agent_message(turn, log, emitter, text)

    try:
        cap = None if value == "off" else float(value)
        if cap is not None and (not math.isfinite(cap) or cap < 0):
            raise ValueError("invalid cap")
    except (ValueError, TypeError):
        await emit("请使用 /project budget 20 设置美元上限，或 /project budget off 申请关闭上限。")
        return
    if project is None:
        await emit("请先完成立项，再调整项目预算。")
        return
    phases = store.milestones_for(project.id)
    before = [phase_fingerprint(ms) for ms in phases]
    preview = f"项目：{project.name}\n新 AI 子任务费用上限：{str(cap) + ' USD' if cap is not None else '关闭限制'}\n已上报费用：${reported_cost(store, project.id):.4f}\n该上限约束后续子任务启动；在途请求、规划与验收模型费用、外部工具费用不在此硬性控制范围。"
    from runtime.projectos.governance import budget_status

    if any(budget_status(store, project.id, ms).get("reason") == "usage_missing" for ms in phases):
        preview += "\n存在未回报费用；提高额度不会解除费用缺失暂停。关闭限制将允许在无法确认全部费用时继续，需明确批准。"
    try:
        result = await emitter.request_approval(
            ServerMethod.REQ_COMMAND_APPROVAL,
            {
                "threadId": turn.thread_id,
                "turnId": turn.id,
                "itemId": uuid4().hex,
                "tool": "project_budget",
                "argsPreview": preview,
                "detail": "仅调整预算策略，不启动执行或付款。",
                "timeoutMs": 120000,
            },
            timeout=120.0,
        )
    except Exception:
        return
    if (result or {}).get("action") != "accept" or emitter.is_turn_interrupted(turn.id):
        await emit("预算未调整。")
        return
    if owner_id:
        from runtime.sensing.gateway.thread_access import ThreadAccessResolver

        access = ThreadAccessResolver(
            thread_store=runtime._thread_store,
            group_store=runtime._cowork_group_store,
            collaboration_store=runtime._collaboration_store,
        ).resolve(turn.thread_id, owner_id, tenant_id)
        if not access.can_manage:
            raise PermissionError("budget owner changed")
    current = store.project_for_thread(turn.thread_id)
    fresh = store.milestones_for(project.id)
    if (
        current is None
        or current.id != project.id
        or before != [phase_fingerprint(ms) for ms in fresh]
    ):
        await emit("项目方案已变化，请重新审批预算。")
        return
    for ms in fresh:
        ms.spec["ai_budget_usd"] = cap
        store.save_milestone(project.id, ms)
    store.append_event(
        project.id, kind="project.budget_changed", payload={"cap_usd": cap, "actor": owner_id}
    )
    await emit("预算策略已更新，未启动执行。发送 /project run 重新确认本阶段后继续。")


async def authorize_phase(runtime, turn, log, emitter, *, store, project, owner_id, tenant_id):
    async def emit(text):
        await runtime._emit_agent_message(turn, log, emitter, text)

    phases = store.milestones_for(project.id)
    ms = next((m for m in phases if m.id == project.current_ms), None)
    if ms is None or ms.status == "done":
        ms = next(
            (
                m
                for m in phases
                if m.status != "done"
                and all(other.status == "done" for other in phases if other.id in m.dependencies)
            ),
            None,
        )
    if ms is None or phase_authorized(store, project.id, ms):
        return True
    ids = ms.spec.get("phase_agents", [])
    registry = runtime._agent_registry
    if not ids or registry is None or any(not registry.has(id) for id in ids):
        await emit("本阶段的候选成员不可用，请先修订人员方案；未开始执行。")
        return False
    fingerprint = phase_fingerprint(ms)
    names = "、".join(registry.get(id).display_name for id in ids)
    cap = ms.spec.get("ai_budget_usd")
    preview = f"阶段：{ms.name}\n参与 AI：{names}\n任务：{ms.goal}\n已上报子任务费用：${reported_cost(store, project.id):.4f}\nAI 预算上限：{str(cap) + ' USD' if cap is not None else '未设置'}\n仅授权本阶段。验收后下一阶段另行确认；不授权付款或真人聘用。"
    if ms.success_criteria:
        preview += "\n验收标准：\n" + "\n".join(f"- {item}" for item in ms.success_criteria)
    if ms.due_at:
        preview += f"\n截止日期：{ms.due_at}"
    if ms.spec.get("approved_brief"):
        preview += "\n立项范围与约束：\n" + str(ms.spec["approved_brief"])
    await emit(preview)
    try:
        result = await emitter.request_approval(
            ServerMethod.REQ_COMMAND_APPROVAL,
            {
                "threadId": project.execution_thread_id or turn.thread_id,
                "turnId": turn.id,
                "itemId": fingerprint,
                "tool": "project_phase",
                "argsPreview": preview,
                "detail": "添加本阶段缺少的 AI 成员，并允许执行本阶段任务。",
                "timeoutMs": 120000,
            },
            timeout=120.0,
        )
    except Exception:
        return False
    if (result or {}).get("action") != "accept" or emitter.is_turn_interrupted(turn.id):
        await emit("本阶段未获批准，未添加成员或执行任务。")
        return False
    if owner_id:
        from runtime.sensing.gateway.thread_access import ThreadAccessResolver

        access = ThreadAccessResolver(
            thread_store=runtime._thread_store,
            group_store=runtime._cowork_group_store,
            collaboration_store=runtime._collaboration_store,
        ).resolve(turn.thread_id, owner_id, tenant_id)
        if not access.can_manage:
            raise PermissionError("phase owner changed")
    current = store.project_for_thread(turn.thread_id)
    fresh = store.get_milestone(ms.id)
    if (
        current is None
        or current.id != project.id
        or fresh is None
        or phase_fingerprint(fresh) != fingerprint
    ):
        await emit("阶段方案已变化，请重新审批。")
        return False
    if any(not registry.has(id) for id in ids):
        return False
    present = {
        m.id
        for m in runtime._cowork_group_store.state(turn.thread_id).roster
        if m.kind == "agent" and m.role == "participant" and not m.muted
    }
    for id in ids:
        if id not in present:
            runtime._cowork_group_store.append(
                turn.thread_id,
                MemberEvent(action="invite", actor=owner_id or "project-os", target_id=id),
            )
    store.append_event(
        project.id,
        kind="project.phase_authorized",
        payload={
            "milestone_id": ms.id,
            "fingerprint": fingerprint,
            "agents": ids,
            "actor": owner_id,
        },
    )
    return True
