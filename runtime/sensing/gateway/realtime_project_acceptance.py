"""Review actual deliverables before advancing an owner-gated milestone."""

from runtime.projectos.acceptance import delivery_fingerprint, has_delivery_content
from runtime.protocol import ServerMethod


async def accept_delivery(
    runtime, turn, log, emitter, *, project_store, thread_id, milestone_id, owner_id, tenant_id
):
    async def emit(text):
        await runtime._emit_agent_message(turn, log, emitter, text)

    project = project_store.project_for_thread(thread_id)
    if project is None:
        await emit("当前对话尚未建立项目计划。")
        return
    milestone_id = milestone_id or project.current_ms
    milestone = (
        project_store.get_milestone(milestone_id) if milestone_id in project.milestone_ids else None
    )
    tasks = project_store.tasks_for_milestone(milestone.id) if milestone else []
    if not tasks or any(t.status != "done" for t in tasks):
        await emit("当前阶段尚未完成交付，请先完成任务后再申请验收。")
        return
    if any(not has_delivery_content(t.output) for t in tasks):
        await emit("当前阶段有任务未提供交付内容，不能只凭完成状态验收。请先补充交付物后重新申请验收。")
        return
    fingerprint = delivery_fingerprint(milestone, tasks)
    preview = "\n".join(
        [
            f"阶段验收：{milestone.name}",
            "验收标准：",
            *milestone.success_criteria,
            "交付记录：",
            *[f"{t.goal}\n任务验收标准：{'；'.join(t.acceptance_criteria) or '按阶段标准验收'}\n交付：{t.output}" for t in tasks],
        ]
    )
    await emit(preview)
    try:
        result = await emitter.request_approval(
            ServerMethod.REQ_COMMAND_APPROVAL,
            {
                "threadId": thread_id,
                "turnId": turn.id,
                "itemId": fingerprint,
                "tool": "project_acceptance",
                "argsPreview": preview,
                "detail": "确认本阶段交付符合标准。此操作记录验收，不自动启动下一阶段。",
                "timeoutMs": 120000,
            },
            timeout=120.0,
        )
    except Exception:
        await emit("验收未完成，项目保持待验收。")
        return
    if (result or {}).get("action") != "accept" or emitter.is_turn_interrupted(turn.id):
        await emit("本阶段尚未通过验收，可以提出修改要求后重新交付。")
        return
    if owner_id:
        from runtime.sensing.gateway.thread_access import ThreadAccessResolver

        access = ThreadAccessResolver(
            thread_store=runtime._thread_store,
            group_store=runtime._cowork_group_store,
            collaboration_store=runtime._collaboration_store,
        ).resolve(thread_id, owner_id, tenant_id)
        if not access.can_manage:
            raise PermissionError("project acceptance access changed")
    current = project_store.project_for_thread(thread_id)
    fresh = project_store.get_milestone(milestone.id)
    if (
        current is None
        or current.id != project.id
        or fresh is None
        or fingerprint
        != delivery_fingerprint(fresh, project_store.tasks_for_milestone(milestone.id))
    ):
        await emit("交付内容或项目已变化，请重新验收最新版本。")
        return
    project_store.append_event(
        project.id,
        kind="project.delivery_accepted",
        payload={"milestone_id": milestone.id, "fingerprint": fingerprint, "actor": owner_id},
    )
    await emit("阶段验收已记录。发送 /project run 可继续推进项目；未自动启动下一阶段。")
