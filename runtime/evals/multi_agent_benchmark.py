"""Deterministic multi-agent release benchmark.

This is intentionally not an LLM leaderboard.  It locks down the platform
properties that must hold regardless of model choice: addressing, context
economy, evidence envelopes, recovery, deduplication, and bounded latency.
"""

from __future__ import annotations

import json
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from runtime.adapters.channels.operations import ChannelOperationsStore
from runtime.execution.agents.group_fanout import run_group_fanout
from runtime.execution.subagents.governance import (
    SubagentGovernanceStore,
    root_token_limit,
)
from runtime.memory.cowork.collaboration_store import CollaborationStore
from runtime.memory.cowork.context_steward import plan_group_context
from runtime.memory.threads.event_log import EventLog, thread_log_path
from runtime.protocol import AgentMessageItem, ItemStatus, Turn
from runtime.sensing.gateway._team_stream_group_fanout import _select_fanout_members
from runtime.sensing.gateway.collaboration_delivery_outbox import (
    drain_collaboration_delivery_outbox,
)

_THRESHOLDS = {
    "context_reduction_ratio": 0.60,
    "max_selected_context_tokens": 20_000,
    "addressing_precision": 1.0,
    "response_success_ratio": 1.0,
    "evidence_coverage_ratio": 1.0,
    "recovery_success_ratio": 1.0,
    "visible_duplicate_count": 0,
    "durable_subtree_concurrency": 1.0,
    "actual_usage_breaker": 1.0,
    "durable_collector": 1.0,
    "collector_retry_retention": 1.0,
    "channel_claim_winners": 1,
    "wall_time_ms": 2_000.0,
}


def _members() -> list[dict[str, Any]]:
    roles = (
        ("architect", "架构师", "事件溯源 架构 一致性"),
        ("coder", "工程师", "前端 后端 代码 修复"),
        ("researcher", "研究员", "竞品 证据 官方文档"),
        ("reviewer", "审查员", "质量 风险 测试 验收"),
        ("operator", "运维", "部署 恢复 监控"),
    )
    return [
        {"name": name, "display_name": display, "description": description}
        for name, display, description in roles
    ]


def _context_metrics() -> dict[str, Any]:
    history = [
        {
            "role": "assistant",
            "content": f"普通进展 {index}：本轮无关键变更，继续记录。",
        }
        for index in range(195)
    ]
    history.extend(
        [
            {"role": "user", "content": "决定：事件溯源以单调序列号保证一致性。"},
            {"role": "assistant", "content": "前端代码需要修复消息列表溢出。"},
            {"role": "assistant", "content": "研究结论必须引用官方文档证据。"},
            {"role": "assistant", "content": "验收必须包含重启恢复测试。"},
            {"role": "assistant", "content": "部署需要检查恢复队列和监控。"},
        ]
    )
    audit = plan_group_context(
        "分别复核架构、代码、研究证据、验收和部署恢复",
        _members(),
        history,
    ).audit_dict()
    return {
        "context_reduction_ratio": float(audit["estimated_reduction_ratio"]),
        "selected_context_tokens": int(audit["selected_estimated_tokens"]),
        "member_budget_violations": sum(
            1
            for member in audit["members"]
            if int(member["estimated_tokens"]) > int(member["token_budget"])
        ),
    }


def _fanout_metrics() -> dict[str, Any]:
    members = _members()
    selected, routing = _select_fanout_members(
        {"cowork_plan": {"addressed": ["researcher"]}, "cowork_responders": ["researcher"]},
        members,
    )
    started = time.perf_counter()

    def _caller(*, agent_id: str, prompt: str, **_kwargs: Any) -> dict[str, Any]:
        return {
            "success": True,
            "output": (
                f"{agent_id} 已验证任务要求；依据官方文档 "
                f"https://example.test/evidence/{agent_id}，建议执行测试步骤 1。"
            ),
            "error": None,
        }

    result = run_group_fanout(
        "验证多人协作结果并提供证据",
        members,
        agent_caller=_caller,
        max_members=len(members),
        max_concurrency=len(members),
        turn_id="benchmark-turn",
        semantic_reviewer=lambda **_kwargs: {
            "success": True,
            "output": json.dumps(
                {
                    "verdict": "pass",
                    "confidence": 0.99,
                    "accepted_response_ids": [
                        f"benchmark-turn:resp:{index}:{member['name']}"
                        for index, member in enumerate(members)
                    ],
                    "issues": [],
                    "summary": "fixed evidence fixtures are internally consistent",
                }
            ),
        },
        semantic_reviewer_agent_id="benchmark-verifier",
    )
    elapsed_ms = (time.perf_counter() - started) * 1000
    contributions = (result.get("delivery") or {}).get("contributions") or []
    evidence_count = sum(bool(item.get("evidence_refs")) for item in contributions)
    return {
        "addressing_precision": (
            1.0
            if [member["name"] for member in selected] == ["researcher"]
            and routing["excluded_agent_ids"]
            == [
                "architect",
                "coder",
                "reviewer",
                "operator",
            ]
            else 0.0
        ),
        "response_success_ratio": float(result.get("spoke") or 0) / len(members),
        "evidence_coverage_ratio": evidence_count / max(1, len(contributions)),
        "semantic_review_ready": bool((result.get("delivery") or {}).get("ready")),
        "wall_time_ms": elapsed_ms,
    }


def _recovery_metrics(root: Path) -> dict[str, Any]:
    store = CollaborationStore(root / "cowork")
    logs_root = root / "threads"
    log = EventLog(thread_log_path(logs_root, "benchmark-thread"))
    log.thread_started("benchmark-thread")
    log.turn_started(
        "benchmark-thread",
        Turn(id="benchmark-turn", thread_id="benchmark-thread"),
    )
    item = AgentMessageItem(
        id="benchmark-result",
        text="durable result",
        status=ItemStatus.COMPLETED,
    )
    store.enqueue_collaboration_delivery(
        delivery_id="benchmark-delivery",
        session_id="benchmark-thread",
        turn_id="benchmark-turn",
        payload={"item": item.model_dump(by_alias=True, mode="json")},
    )
    first = drain_collaboration_delivery_outbox(
        store,
        logs_root=logs_root,
        session_id="benchmark-thread",
    )
    second = drain_collaboration_delivery_outbox(
        store,
        logs_root=logs_root,
        session_id="benchmark-thread",
    )
    visible = [entry.id for entry in log.replay()[0].items]
    return {
        "recovery_success_ratio": 1.0 if first["delivered"] == 1 else 0.0,
        "visible_duplicate_count": max(0, visible.count("benchmark-result") - 1),
        "second_drain_due": int(second["due"]),
    }


def _governance_metrics(root: Path) -> dict[str, Any]:
    path = root / "subagent-governance.db"
    first = SubagentGovernanceStore(path)
    lease = first.acquire(
        "benchmark-root",
        depth=1,
        global_limit=2,
        root_limit=1,
        owner_id="benchmark-worker-a",
    )
    second = SubagentGovernanceStore(path)
    blocked_acquire = second.acquire(
        "benchmark-root",
        depth=2,
        global_limit=2,
        root_limit=1,
        owner_id="benchmark-worker-b",
    )
    if lease is not None:
        first.release(str(lease["lease_id"]))
    usage = second.record_usage(
        "benchmark-spend-root",
        usage_id="benchmark-provider-call",
        input_tokens=root_token_limit(),
        output_tokens=0,
        cost_usd=0.0,
    )
    return {
        "durable_subtree_concurrency": (
            1.0 if lease is not None and blocked_acquire is None else 0.0
        ),
        "actual_usage_breaker": 1.0 if usage["breaker"] == "tripped" else 0.0,
    }


def _collector_metrics(root: Path) -> dict[str, Any]:
    """Prove fan-out children converge after a coordinator restart."""

    store = CollaborationStore(root / "collector-cowork")
    store.create_collaboration_run(
        run_id="benchmark-collector",
        session_id="benchmark-thread",
        kind="group_fanout",
    )
    store.claim_collaboration_run("benchmark-collector", worker_id="benchmark-worker")
    store.create_collaboration_collector(
        run_id="benchmark-collector",
        child_ids=["architect", "coder", "reviewer"],
        completion_policy="all",
    )
    store.record_collaboration_collector_result(
        "benchmark-collector",
        child_id="architect",
        status="success",
        result={"answer": "A"},
    )
    restarted = CollaborationStore(root / "collector-cowork")
    restarted.record_collaboration_collector_result(
        "benchmark-collector",
        child_id="coder",
        status="failed",
        result={"error": "transient"},
    )
    restarted.record_collaboration_collector_result(
        "benchmark-collector",
        child_id="reviewer",
        status="success",
        result={"answer": "C"},
    )
    reopened = restarted.reopen_collaboration_collector("benchmark-collector")
    settled = restarted.record_collaboration_collector_result(
        "benchmark-collector",
        child_id="coder",
        status="success",
        result={"answer": "B"},
    )
    event_count = len(restarted.collaboration_run_events("benchmark-collector"))
    duplicate = restarted.record_collaboration_collector_result(
        "benchmark-collector",
        child_id="coder",
        status="success",
        result={"answer": "B"},
    )
    return {
        "durable_collector": (
            1.0
            if settled["status"] == "completed"
            and settled["success_count"] == 3
            and settled["cancellation_requested_child_ids"] == []
            and duplicate == settled
            and len(restarted.collaboration_run_events("benchmark-collector")) == event_count
            else 0.0
        ),
        "collector_retry_retention": (
            1.0
            if reopened["active_retry_child_ids"] == ["coder"]
            and reopened["remaining_child_ids"] == ["coder"]
            and settled["attempt_count"] == 4
            and [
                (item["child_id"], item["attempt"], item["status"])
                for item in restarted.collaboration_collector_attempts("benchmark-collector")
            ]
            == [
                ("architect", 1, "success"),
                ("coder", 1, "failed"),
                ("coder", 2, "success"),
                ("reviewer", 1, "success"),
            ]
            else 0.0
        ),
    }


def _channel_ingress_metrics(root: Path) -> dict[str, Any]:
    path = root / "channel-operations.json"
    stores = [ChannelOperationsStore(path), ChannelOperationsStore(path)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(
            pool.map(
                lambda store: store.claim_inbound("slack", "message_id:benchmark-event"),
                stores,
            )
        )
    return {
        "channel_claim_winners": sum(bool(claim) for claim in claims),
        "channel_duplicate_executions": max(0, sum(bool(claim) for claim in claims) - 1),
    }


def run_multi_agent_benchmark(*, workspace: Path | str | None = None) -> dict[str, Any]:
    """Run the fixed suite and return a machine-readable release verdict."""

    if workspace is None:
        with tempfile.TemporaryDirectory(prefix="octopus-multi-agent-benchmark-") as temp:
            return run_multi_agent_benchmark(workspace=Path(temp))
    root = Path(workspace)
    root.mkdir(parents=True, exist_ok=True)
    metrics = {
        **_context_metrics(),
        **_fanout_metrics(),
        **_recovery_metrics(root),
        **_governance_metrics(root),
        **_collector_metrics(root),
        **_channel_ingress_metrics(root),
    }
    checks = {
        "context_reduction": metrics["context_reduction_ratio"]
        >= _THRESHOLDS["context_reduction_ratio"],
        "context_budget": metrics["selected_context_tokens"]
        <= _THRESHOLDS["max_selected_context_tokens"]
        and metrics["member_budget_violations"] == 0,
        "addressing": metrics["addressing_precision"] >= _THRESHOLDS["addressing_precision"],
        "response_success": metrics["response_success_ratio"]
        >= _THRESHOLDS["response_success_ratio"],
        "evidence": metrics["evidence_coverage_ratio"] >= _THRESHOLDS["evidence_coverage_ratio"]
        and metrics["semantic_review_ready"],
        "recovery": metrics["recovery_success_ratio"] >= _THRESHOLDS["recovery_success_ratio"],
        "deduplication": metrics["visible_duplicate_count"]
        <= _THRESHOLDS["visible_duplicate_count"],
        "durable_subtree_concurrency": metrics["durable_subtree_concurrency"]
        >= _THRESHOLDS["durable_subtree_concurrency"],
        "actual_usage_breaker": metrics["actual_usage_breaker"]
        >= _THRESHOLDS["actual_usage_breaker"],
        "durable_collector": metrics["durable_collector"]
        >= _THRESHOLDS["durable_collector"],
        "collector_retry_retention": metrics["collector_retry_retention"]
        >= _THRESHOLDS["collector_retry_retention"],
        "channel_ingress_dedup": metrics["channel_claim_winners"]
        == _THRESHOLDS["channel_claim_winners"]
        and metrics["channel_duplicate_executions"] == 0,
        "latency": metrics["wall_time_ms"] <= _THRESHOLDS["wall_time_ms"],
    }
    return {
        "schema": "octopus.multi_agent_benchmark.v1",
        "passed": all(checks.values()),
        "checks": checks,
        "metrics": metrics,
        "thresholds": dict(_THRESHOLDS),
    }


def main() -> int:
    result = run_multi_agent_benchmark()
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
