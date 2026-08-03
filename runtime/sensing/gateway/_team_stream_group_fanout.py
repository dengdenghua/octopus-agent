"""Group fan-out stream driver — 蜂群 / 冒泡 cowork dispatch.

Extracted from ``realtime_team_stream.py``. Fans a message out to every
member agent in parallel and emits each persona reply as its own
group-chat bubble. Falls back to single-agent ReAct when the room has
<2 member agents or nobody answers, so the turn never stalls.

Public API (re-exported by ``realtime_team_stream``):

* ``_drive_group_fanout`` — fan the message out to every member agent.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from typing import Any

from runtime.memory.threads.event_log import EventLog
from runtime.platform.models import ParsedIntent
from runtime.protocol import (
    AgentMessageItem,
    ItemStatus,
    McpToolCallItem,
    ReasoningItem,
    ServerMethod,
    SubagentItem,
    Turn,
)
from runtime.sensing.gateway.realtime_approval import GatewayApprovalProvider
from runtime.sensing.gateway.realtime_gateway import EventEmitter

_logger = logging.getLogger(__name__)


async def _drive_group_fanout(
    runtime: Any,
    turn: Turn,
    log: EventLog,
    emitter: EventEmitter,
    intent: ParsedIntent,
    *,
    text: str,
) -> None:
    """蜂群 / 冒泡: fan the message out to every member agent in parallel and
    emit each persona reply as its own group-chat bubble — the "boss speaks,
    everyone chimes in" experience. Falls back to single-agent ReAct when the
    room has <2 member agents or nobody answers, so the turn never stalls.
    """
    ctx = getattr(intent, "user_context", None) or {}
    roster = ctx.get("agent_roster") or []
    members = [
        {
            "name": str(r.get("agent_id")),
            "display_name": str(r.get("display_name") or r.get("agent_id")),
        }
        for r in roster
        if isinstance(r, dict) and r.get("agent_id")
    ]

    async def _emit(
        body: str,
        *,
        display_name: str | None = None,
        agent_id: str | None = None,
        icon: str | None = None,
    ) -> None:
        # Tag the bubble with its real author so the UI shows that member's
        # avatar + name instead of the turn leader's. Use the shared resolver so
        # the URL carries ``?v=<mtime>`` — that cache-busts when an agent's
        # avatar file changes (e.g. swapping in a brand logo).
        avatar_url: str | None = None
        if agent_id:
            try:
                from runtime.sensing.gateway.agents_router import _avatar_url_for

                avatar_url = _avatar_url_for(agent_id)
            except Exception:  # noqa: BLE001 — avatar is decoration; never break the turn
                avatar_url = None
            avatar_url = avatar_url or f"/api/agents/{agent_id}/avatar"
        item = AgentMessageItem(
            text=body,
            status=ItemStatus.COMPLETED,
            agent_display_name=display_name,
            agent_avatar_url=avatar_url,
            agent_icon=icon,
        )
        turn.items.append(item)
        with contextlib.suppress(Exception):
            log.item_started(turn.thread_id, turn.id, item)
            log.item_completed(turn.thread_id, turn.id, item)
        payload = {
            "threadId": turn.thread_id,
            "turnId": turn.id,
            "item": item.model_dump(by_alias=True, mode="json"),
        }
        with contextlib.suppress(Exception):
            await emitter.notify(ServerMethod.ITEM_STARTED, payload)
            await emitter.notify(ServerMethod.ITEM_COMPLETED, payload)

    async def _fallback_to_react() -> None:
        loop = asyncio.get_running_loop()
        gateway_provider = GatewayApprovalProvider(
            emitter,
            loop,
            thread_id=intent.user_context.get("thread_id", turn.thread_id),
            turn_id=turn.id,
            trace_store=runtime._trace_store,
        )
        provider = runtime._wrap_with_policy(gateway_provider)
        from runtime.protocol.items import TurnParams

        agent = None
        with contextlib.suppress(Exception):
            agent = runtime._resolve_agent(
                TurnParams(threadId=turn.thread_id, input=[]),  # type: ignore[call-arg]
            )
        await runtime._drive_react(turn, log, emitter, intent, provider, agent)

    def _record_fallback_audit(reason: str, exc: BaseException | None = None) -> None:
        payload: dict[str, Any] = {
            "schema": "octopus.group_fanout_fallback.v1",
            "reason": reason,
            "fallback": "react",
        }
        if exc is not None:
            payload.update(
                {
                    "exception_type": type(exc).__name__,
                    "message": str(exc),
                }
            )
        with contextlib.suppress(Exception):
            audit_item = ReasoningItem(
                summary=["Group fanout fallback"],
                content=json.dumps(payload, ensure_ascii=False, sort_keys=True),
                status=ItemStatus.COMPLETED,
            )
            turn.items.append(audit_item)
            log.item_started(turn.thread_id, turn.id, audit_item)
            log.item_completed(turn.thread_id, turn.id, audit_item)

    async def _notify_started(item: Any) -> None:
        turn.items.append(item)
        with contextlib.suppress(Exception):
            log.item_started(turn.thread_id, turn.id, item)
        payload = {
            "threadId": turn.thread_id,
            "turnId": turn.id,
            "item": item.model_dump(by_alias=True, mode="json"),
        }
        with contextlib.suppress(Exception):
            await emitter.notify(ServerMethod.ITEM_STARTED, payload)

    async def _notify_completed(item: Any) -> None:
        with contextlib.suppress(Exception):
            log.item_completed(turn.thread_id, turn.id, item)
        payload = {
            "threadId": turn.thread_id,
            "turnId": turn.id,
            "item": item.model_dump(by_alias=True, mode="json"),
        }
        with contextlib.suppress(Exception):
            await emitter.notify(ServerMethod.ITEM_COMPLETED, payload)

    team_trace_item: McpToolCallItem | None = None
    member_trace_items: dict[str, SubagentItem] = {}
    team_trace_started = 0.0
    planned_group_capacity: dict[str, Any] = {}

    async def _start_group_trace(
        group_members: list[dict[str, str]],
        *,
        max_members: int,
        max_concurrency: int,
        scale_mode: str,
    ) -> None:
        """Expose lightweight cowork fanout as a first-class team run.

        Kimi-style swarm UX depends on the user seeing who was dispatched before
        the replies arrive. The fanout itself is still conversational, but the
        runtime now records a replayable parent ``team_swarm`` item plus one
        ``SubagentItem`` lane per member.
        """
        nonlocal team_trace_item, team_trace_started
        if not group_members:
            return
        nonlocal planned_group_capacity
        team_trace_started = time.monotonic()
        dispatched_members = group_members[:max_members]
        planned_group_capacity = {
            "schema": "octopus.group_fanout_capacity.v1",
            "requested_members": len(group_members),
            "dispatched_members": len(dispatched_members),
            "dropped_members": max(0, len(group_members) - len(dispatched_members)),
            "max_members": max_members,
            "max_concurrency": max_concurrency,
            "concurrency": max(1, min(len(dispatched_members), max_concurrency)),
            "scale_mode": scale_mode,
            "capacity_tier": "kimi_scale"
            if len(group_members) >= 300
            else "large"
            if len(dispatched_members) >= 64
            else "team_scale"
            if len(dispatched_members) >= 16
            else "room_scale"
            if len(dispatched_members) >= 2
            else "single",
        }
        specs = [
            {
                "agent_id": member["name"],
                "display_name": member["display_name"],
                "role": "cowork",
                "task": text[:500],
            }
            for member in dispatched_members
        ]
        team_trace_item = McpToolCallItem(
            server="team",
            tool="team_swarm",
            arguments={
                "schema": "octopus.group_fanout_run.v1",
                "mode": "cowork_swarm",
                "message": text[:1000],
                "specs": specs,
                "capacity": planned_group_capacity,
            },
            status=ItemStatus.IN_PROGRESS,
        )
        await _notify_started(team_trace_item)
        for member in dispatched_members:
            agent_id = member["name"]
            display = member["display_name"]
            item = SubagentItem(
                subagent_id=agent_id,
                role="cowork",
                name=display,
                codename=display,
                parent_item_id=team_trace_item.id,
                summary="waiting for cowork fanout reply",
                status=ItemStatus.IN_PROGRESS,
            )
            member_trace_items[agent_id] = item
            await _notify_started(item)

    async def _complete_group_trace(result: dict[str, Any]) -> None:
        replies = [reply for reply in result.get("replies", []) if isinstance(reply, dict)]
        by_agent = {str(reply.get("agent_id") or ""): reply for reply in replies}
        for agent_id, item in member_trace_items.items():
            reply = by_agent.get(agent_id, {})
            body = str(reply.get("reply") or "").strip()
            err = str(reply.get("error") or "").strip()
            ok = bool(reply.get("ok")) and bool(body)
            item.status = ItemStatus.COMPLETED if ok else ItemStatus.FAILED
            item.summary = body[:2000] if body else None
            item.error = None if ok else (err or "empty cowork fanout reply")
            item.iteration_count = 1
            await _notify_completed(item)
        if team_trace_item is not None:
            ok = bool(result.get("ok"))
            team_trace_item.status = ItemStatus.COMPLETED if ok else ItemStatus.FAILED
            team_trace_item.result = {
                "schema": "octopus.group_fanout_result.v1",
                "count": result.get("count"),
                "spoke": result.get("spoke"),
                "dropped": result.get("dropped", 0),
                "capacity": result.get("capacity") or planned_group_capacity,
                "arbitration": result.get("arbitration"),
                "synthesis": result.get("synthesis"),
                "replies": replies,
            }
            team_trace_item.error = None if ok else str(result.get("error") or "no member replied")
            team_trace_item.duration_ms = max(
                0,
                int((time.monotonic() - team_trace_started) * 1000),
            )
            await _notify_completed(team_trace_item)

    async def _fail_group_trace(exc: BaseException) -> None:
        for item in member_trace_items.values():
            if item.status == ItemStatus.IN_PROGRESS:
                item.status = ItemStatus.FAILED
                item.error = f"{type(exc).__name__}: {exc}"
                await _notify_completed(item)
        if team_trace_item is not None and team_trace_item.status == ItemStatus.IN_PROGRESS:
            team_trace_item.status = ItemStatus.FAILED
            team_trace_item.error = f"{type(exc).__name__}: {exc}"
            team_trace_item.duration_ms = max(
                0,
                int((time.monotonic() - team_trace_started) * 1000),
            )
            await _notify_completed(team_trace_item)

    def _group_summary(result: dict[str, Any]) -> str | None:
        arbitration = result.get("arbitration")
        if not isinstance(arbitration, dict):
            return None
        synthesis = result.get("synthesis")
        answered = arbitration.get("answered_agent_ids")
        failed = arbitration.get("failed_agent_ids")
        empty = arbitration.get("empty_agent_ids")
        if isinstance(synthesis, dict):
            primary = str(synthesis.get("primary_agent_id") or "").strip()
            recommended = str(
                synthesis.get("recommended_next_action") or "",
            ).strip()
        else:
            primary = str(arbitration.get("primary_agent_id") or "").strip()
            recommended = str(arbitration.get("recommended_next_action") or "").strip()
        if not isinstance(answered, list):
            answered = []
        if not isinstance(failed, list):
            failed = []
        if not isinstance(empty, list):
            empty = []
        if len(answered) < 2 and not failed and not empty:
            return None
        parts = [
            f"协作汇总: {len(answered)} 位成员已回应",
        ]
        if primary:
            parts.append(f"优先采纳 {primary} 的视角继续")
        if recommended and recommended != "use_primary_response":
            parts.append(f"下一步建议: {_group_next_action_label(recommended)}")
        blocked = [str(x) for x in [*failed, *empty] if x]
        if blocked:
            parts.append(f"{len(blocked)} 位成员需要补看")
        return "；".join(parts) + "。"

    def _group_next_action_label(action: str) -> str:
        labels = {
            "use_primary_response": "采纳主视角继续",
            "use_primary_and_retry_failed_members": "采纳主视角，同时补看失败成员",
            "ask_members_to_expand": "请成员补充展开",
            "retry_or_fallback_to_single_agent": "重试成员或回退单 Agent",
            "fallback_to_single_agent": "回退单 Agent",
        }
        return labels.get(action, action.replace("_", " "))

    if len(members) < 2:
        # Not a real group → one agent answers (the normal single-agent path).
        _record_fallback_audit("insufficient_members")
        await _fallback_to_react()
        return

    try:
        import os

        from runtime.execution.agents.cli_team import (
            detect_installed_partners,
            run_cli_team,
        )
        from runtime.execution.agents.group_fanout import run_group_fanout
        from runtime.execution.agents.local_partner_bridge import run_local_partner
        from runtime.execution.suckers.delegation_skills import _call_agent

        # agent_id → {partner_id, command} for the CLIs actually on this machine.
        detected = {d["agent_id"]: d for d in detect_installed_partners()}

        def _mentioned(display: str) -> bool:
            parts = display.split()
            cands = {display, parts[0] if parts else display, display.replace(" ", "")}
            return any(c and ("@" + c) in text for c in cands)

        # Cheap cue that the user wants a CLI partner to actually DO work (run
        # in a worktree) rather than just chime in. Conservative — defaults to
        # chat so a casual "@Codex 在么" never fires a heavyweight run.
        task_cues = (
            "改",
            "写",
            "修",
            "实现",
            "重构",
            "添加",
            "新增",
            "删",
            "创建",
            "生成",
            "优化",
            "修复",
            "测试",
            "运行",
            "跑",
            "重命名",
            "替换",
            "集成",
            "接入",
            "fix",
            "add",
            "implement",
            "refactor",
            "write",
            "create",
            "run",
            "test",
            "build",
            "rename",
            "replace",
            "update",
            "bug",
        )

        def _looks_like_task(t: str) -> bool:
            low = t.lower()
            return len(t.strip()) >= 6 and any(cue in low for cue in task_cues)

        # Split: local partners @-mentioned WITH a task → real worktree run;
        # everyone else (persona agents + partners just chatting) → group bubble.
        work_members = [
            m
            for m in members
            if m["name"] in detected and _mentioned(m["display_name"]) and _looks_like_task(text)
        ]
        work_ids = {m["name"] for m in work_members}
        chat_members = [m for m in members if m["name"] not in work_ids]
        # @-mentioned chat members first so a small fan-out cap never drops them.
        chat_members.sort(key=lambda m: 0 if _mentioned(m["display_name"]) else 1)

        def _member_caller(agent_id: str, prompt: str, timeout_s: int = 90) -> dict[str, Any]:
            """Persona agents run in-process; local CLI partners bridge to their
            real CLI for a short, conversational group-chat bubble."""
            info = detected.get(agent_id)
            if info is not None:
                r = run_local_partner(
                    partner_id=info["partner_id"],
                    command=info["command"],
                    prompt=prompt,
                    timeout=min(int(timeout_s), 60),
                )
                return {
                    "success": bool(r.ok),
                    "output": r.output or "",
                    "error": r.error,
                }
            return _call_agent(agent_id=agent_id, prompt=prompt, timeout_s=timeout_s)

        spoke = 0
        if chat_members:
            scale_mode = (
                str(ctx.get("swarm_scale_mode") or ctx.get("fanout_scale_mode") or "safe")
                .strip()
                .lower()
            )
            if scale_mode not in {"safe", "full"}:
                scale_mode = "safe"
            requested_limit = ctx.get("swarm_max_members") or ctx.get("max_members")
            try:
                requested_limit_int = int(requested_limit) if requested_limit is not None else 0
            except (TypeError, ValueError):
                requested_limit_int = 0
            fanout_limit = (
                min(512, max(2, requested_limit_int or len(chat_members)))
                if scale_mode == "full"
                else min(32, max(2, requested_limit_int or len(chat_members)))
            )
            try:
                fanout_concurrency = int(ctx.get("swarm_max_concurrency") or 32)
            except (TypeError, ValueError):
                fanout_concurrency = 32
            fanout_concurrency = max(1, min(64, fanout_concurrency))
            await _start_group_trace(
                chat_members,
                max_members=fanout_limit,
                max_concurrency=fanout_concurrency,
                scale_mode=scale_mode,
            )
            result = await asyncio.to_thread(
                run_group_fanout,
                text,
                chat_members,
                agent_caller=_member_caller,
                # Cover the whole roster (was hard-capped at 5, which silently
                # dropped members ordered last — e.g. the local CLI partners).
                max_members=fanout_limit,
                max_concurrency=fanout_concurrency,
                scale_mode=scale_mode,
                turn_id=turn.id,
            )
            await _complete_group_trace(result)
            arbitration = result.get("arbitration")
            if isinstance(arbitration, dict):
                with contextlib.suppress(Exception):
                    audit_item = ReasoningItem(
                        content=json.dumps(
                            {
                                "schema": "octopus.group_fanout_audit.v1",
                                "arbitration": arbitration,
                                "capacity": result.get("capacity") or planned_group_capacity,
                            },
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                        status=ItemStatus.COMPLETED,
                    )
                    turn.items.append(audit_item)
                    log.item_started(turn.thread_id, turn.id, audit_item)
                    log.item_completed(turn.thread_id, turn.id, audit_item)
            for reply in result.get("replies", []):
                body = str(reply.get("reply") or "").strip()
                if reply.get("ok") and body:
                    await _emit(
                        body,
                        display_name=str(reply.get("display_name") or ""),
                        agent_id=str(reply.get("agent_id") or ""),
                    )
                    spoke += 1
            summary = _group_summary(result)
            if summary:
                await _emit(summary)

        # Each @-mentioned partner with a task runs it in its OWN git worktree
        # (no collision with the live tree) and reports the diff for review.
        for wm in work_members:
            disp = wm["display_name"]
            info = detected[wm["name"]]
            await _emit(
                "收到，正在独立 worktree 里处理这个任务，"
                "完成后把 diff 给你 review（不会自动合并）……",
                display_name=disp,
                agent_id=wm["name"],
            )
            try:
                cli = await asyncio.to_thread(
                    run_cli_team, text, [info], repo_root=os.getcwd(), turn_id=turn.id
                )
                mem = (cli.get("members") or [{}])[0]
                diff = str(mem.get("diff") or "").strip()
                if mem.get("ok") and diff:
                    files = mem.get("files") or []
                    flist = "、".join(files[:8]) + ("…" if len(files) > 8 else "")
                    shown = (
                        diff
                        if len(diff) <= 1500
                        else diff[:1500] + "\n…(diff 截断，完整在 worktree)"
                    )
                    await _emit(
                        f"✅ 已在隔离 worktree 完成 · 改动 {len(files)} 个文件"
                        + (f"：{flist}" if files else "")
                        + f"。diff 待 review：\n\n```diff\n{shown}\n```",
                        display_name=disp,
                        agent_id=wm["name"],
                    )
                else:
                    err = str(mem.get("error") or "没有产生改动")
                    await _emit(
                        f"⚠️ 这次没能完成：{err[:400]}",
                        display_name=disp,
                        agent_id=wm["name"],
                    )
                spoke += 1
            except Exception as exc:  # noqa: BLE001 — isolate one partner's failure
                await _emit(
                    f"⚠️ 运行出错：{type(exc).__name__}: {exc}",
                    display_name=disp,
                    agent_id=wm["name"],
                )

        if spoke == 0:
            _record_fallback_audit("no_member_response")
            await _fallback_to_react()
    except Exception as exc:  # noqa: BLE001 — never break the turn on a fan-out fault
        _logger.warning(
            "group fan-out failed (%s: %s) — falling back to react",
            type(exc).__name__,
            exc,
        )
        await _fail_group_trace(exc)
        _record_fallback_audit("exception", exc)
        await _fallback_to_react()
