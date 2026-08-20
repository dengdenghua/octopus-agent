"""Tests for CerebrumRuntime — the react_loop→item/* adapter.

These tests substitute a fake ``stream_react_loop`` to keep the test
surface narrow: we care about the *bridge*, not the planner. A fake
stream yields a deterministic sequence of legacy react events; the
runtime must translate each into the correct ``item/*`` notification and
persist the right JSONL lines.

Also covers the approval round-trip through the WebSocket (integration
with RealtimeGateway), which is where the old global-dict approval_gate
couldn't be tested without monkey-patching.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
except ImportError:  # pragma: no cover
    FastAPI = None  # type: ignore[assignment]
    TestClient = None  # type: ignore[assignment]

from runtime.protocol import (
    JsonRpcErrorCode,
    JsonRpcRequest,
    JsonRpcResponse,
    Notification,
    decode_message,
    encode_message,
)

pytestmark = pytest.mark.skipif(
    FastAPI is None, reason="fastapi required for realtime gateway tests"
)


@pytest.fixture(autouse=True)
def _patch_react_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace the real stream_react_loop with a deterministic fake.

    The fake reads its script from a module-level list so individual
    tests can stage the event sequence they want. This is the cleanest
    seam the runtime exposes — substituting the planner keeps LLM,
    tool, and sandbox machinery out of the test.
    """
    import runtime.core.cerebrum.react_loop as rl

    def fake_stream(*args: Any, **kwargs: Any) -> Iterator[dict[str, Any]]:
        from runtime.platform.process.session import current_session

        _LAST_STREAM_ARGS.clear()
        _LAST_STREAM_ARGS.update({"args": args, "kwargs": kwargs})
        _LAST_STREAM_KWARGS.clear()
        _LAST_STREAM_KWARGS.update(kwargs)
        active_session = current_session()
        _LAST_SESSION.clear()
        _LAST_SESSION.update(
            {
                "thread_id": active_session.thread_id if active_session else None,
                "metadata": dict(active_session.metadata) if active_session else {},
            }
        )
        approval_provider = kwargs.get("approval_provider")
        if _SCRIPT_POP_ONCE:
            # Consume the script on the first drive so a verification
            # loop-back re-drive sees an empty stream instead of replaying
            # the same events (which would double-emit file changes).
            script = _SCRIPT[:]
            _SCRIPT.clear()
        else:
            script = _SCRIPT[:]
        for event in script:
            if event.get("__approve__"):
                # Translate into an approval round-trip using the
                # injected provider (mirrors what the real loop does).
                from runtime.safety.approval.approval_gate import ApprovalRequest

                decision = approval_provider.request(
                    ApprovalRequest(
                        thread_id=kwargs.get("thread_id", ""),
                        tool_name=event.get("tool_name", "x"),
                        tool_call_id=event.get("tool_call_id", "c1"),
                    )
                )
                yield {
                    "type": "tool_end",
                    "tool_name": event.get("tool_name", "x"),
                    "tool_call_id": event.get("tool_call_id", "c1"),
                    "iteration": 1,
                    "status": "success" if decision.approved else "rejected",
                    "output_preview": decision.reason or ("ok" if decision.approved else "denied"),
                    "duration_ms": 1,
                }
                continue
            yield event

    monkeypatch.setattr(rl, "stream_react_loop", fake_stream)


_SCRIPT: list[dict[str, Any]] = []
_SCRIPT_POP_ONCE: bool = False
_LAST_STREAM_ARGS: dict[str, Any] = {}
_LAST_STREAM_KWARGS: dict[str, Any] = {}
_LAST_SESSION: dict[str, Any] = {}


def _set_script(events: list[dict[str, Any]]) -> None:
    global _SCRIPT_POP_ONCE
    _SCRIPT.clear()
    _SCRIPT.extend(events)
    _SCRIPT_POP_ONCE = False
    _LAST_STREAM_KWARGS.clear()
    _LAST_SESSION.clear()


def test_flatten_merges_post_final_trace_items_into_delivered_answer() -> None:
    from runtime.protocol import Turn
    from runtime.sensing.gateway.realtime_cerebrum import _flatten_turns_to_messages

    turn = Turn.model_validate(
        {
            "id": "turn-1",
            "threadId": "thread-1",
            "status": "completed",
            "startedAt": "2026-06-01T18:53:24Z",
            "completedAt": "2026-06-01T19:03:00Z",
            "items": [
                {
                    "id": "u1",
                    "type": "userMessage",
                    "status": "completed",
                    "createdAt": "2026-06-01T18:53:24Z",
                    "text": "research a niche market",
                    "attachments": [],
                },
                {
                    "id": "r1",
                    "type": "reasoning",
                    "status": "completed",
                    "createdAt": "2026-06-01T18:53:26Z",
                    "summary": [],
                    "content": "collect initial evidence",
                },
                {
                    "id": "a1",
                    "type": "agentMessage",
                    "status": "completed",
                    "createdAt": "2026-06-01T19:03:00Z",
                    "text": "# Report\n\nOpportunity, competitors, risks, and next steps.",
                },
                {
                    "id": "r2",
                    "type": "reasoning",
                    "status": "completed",
                    "createdAt": "2026-06-01T19:02:50Z",
                    "summary": [],
                    "content": "The todo-protocol guard keeps blocking my final answer.",
                },
                {
                    "id": "c1",
                    "type": "commandExecution",
                    "status": "completed",
                    "createdAt": "2026-06-01T19:02:47Z",
                    "command": "todo_write",
                    "inputPreview": {},
                    "cwd": None,
                    "aggregatedOutput": "ok",
                    "exitCode": 0,
                    "processId": None,
                    "networkAccess": False,
                },
            ],
            "error": None,
        }
    )

    messages, _, _ = _flatten_turns_to_messages([turn])

    assert len(messages) == 2
    ai = messages[1]
    assert ai["content"].startswith("# Report")
    assert "reasoning_content" not in ai["additional_kwargs"]
    assert "public_reasoning_summary" not in ai["additional_kwargs"]
    assert [tool["name"] for tool in ai["tool_calls"]] == ["todo_write"]


def test_flatten_collapses_near_identical_resent_report() -> None:
    """Regression: a guard-rejected report draft and its near-identical retry
    (thread t0Wn5Zhvh3VUFwoAR2uP4M: two AI4S reports, 3665 vs 3670 chars, only
    a '诺华'→'据公开披露约' fact fixed, 0.9988 similarity) were both persisted
    into the sidebar and both re-sent to the model. The flatten adapter must
    collapse them to a single message, keeping the newest copy while
    preserving real tool calls attached to the earlier draft."""
    from runtime.protocol import Turn
    from runtime.sensing.gateway.realtime_cerebrum import _flatten_turns_to_messages

    sentences = [
        "AI for Science 正在从单点工具应用走向科研范式级别的重构，全球主要经济体都把 AI4S 写进了各自的国家科技战略。",
        "蛋白质结构预测领域，AlphaFold 系列模型把过去需要数年冷冻电镜实验才能解析的结构，压缩到数小时之内完成端到端预测。",
        "材料设计方向出现了一批生成式模型，能够在给定目标力学性能的前提下逆向搜索候选晶体结构，大幅压缩实验试错周期。",
        "气象与气候建模方面，高分辨率风场与降水模型已经开始辅助极端天气预警，相关论文连续出现在 Nature 与 Science 的正刊上。",
        "药物发现管线里，分子对接、亲和力预测与毒性筛选正在被统一到同一套预训练框架里，临床前研究的人力成本显著下降。",
        "产业端的热钱正在涌入这一赛道，一级市场多笔亿元级融资集中在通用科学模型与垂直行业基座模型两类标的。",
        "风险层面，跨学科评估仍然缺乏统一基准，部分模型在训练分布外场景的泛化能力仍不达预期，存在被过度宣传的问题。",
    ]
    body = "".join(sentences) * 4
    base = "# AI4S（AI for Science）领域调研报告\n\n## 一、执行摘要\n\n" + body
    mid = len(base) // 2
    draft = base
    retry = base[:mid] + "据公开披露约" + base[mid + 6:]  # same-length fact fix

    turn = Turn.model_validate(
        {
            "id": "turn-dup-report",
            "threadId": "thread-dup",
            "status": "completed",
            "startedAt": "2026-06-01T18:53:24Z",
            "completedAt": "2026-06-01T19:03:00Z",
            "items": [
                {
                    "id": "u1",
                    "type": "userMessage",
                    "status": "completed",
                    "createdAt": "2026-06-01T18:53:24Z",
                    "text": "调研一下 AI4S",
                    "attachments": [],
                },
                {
                    "id": "tc1",
                    "type": "commandExecution",
                    "status": "completed",
                    "createdAt": "2026-06-01T19:02:47Z",
                    "command": "todo_write",
                    "inputPreview": {},
                    "cwd": None,
                    "aggregatedOutput": "ok",
                    "exitCode": 0,
                    "processId": None,
                    "networkAccess": False,
                },
                {
                    "id": "a1",
                    "type": "agentMessage",
                    "status": "completed",
                    "createdAt": "2026-06-01T19:03:00Z",
                    "text": draft,
                },
                {
                    "id": "r2",
                    "type": "reasoning",
                    "status": "completed",
                    "createdAt": "2026-06-01T19:03:01Z",
                    "summary": ["guard rejected the draft, fixing the number"],
                    "content": "",
                },
                {
                    "id": "a2",
                    "type": "agentMessage",
                    "status": "completed",
                    "createdAt": "2026-06-01T19:03:02Z",
                    "text": retry,
                },
            ],
            "error": None,
        }
    )

    messages, _, _ = _flatten_turns_to_messages([turn])

    ai = [m for m in messages if m.get("type") == "ai"]
    reports = [m for m in ai if (m.get("content") or "").startswith("# AI4S")]
    assert len(reports) == 1, "near-identical re-sent report must be collapsed"
    kept = reports[0]
    assert kept["content"] == retry, "newest (guard-passed) copy must win"
    # The todo_write action attached to the earlier draft must survive.
    assert [tool["name"] for tool in (kept.get("tool_calls") or [])] == ["todo_write"]


def test_flatten_keeps_genuinely_different_answers_apart() -> None:
    """The near-duplicate collapse must NOT merge two genuinely different
    consecutive assistant answers (e.g. a real follow-up after a report)."""
    from runtime.protocol import Turn
    from runtime.sensing.gateway.realtime_cerebrum import _flatten_turns_to_messages

    first = "# AI4S 领域调研报告\n\n" + "AI for Science 正在走向科研范式重构。" * 40
    second = "# 智能睡眠行业调研报告\n\n" + "智能睡眠是睡眠经济与 AI 结合的最新赛道，覆盖监测硬件、助眠内容与数字疗法。" * 30

    turn = Turn.model_validate(
        {
            "id": "turn-distinct",
            "threadId": "thread-distinct",
            "status": "completed",
            "startedAt": "2026-06-01T18:53:24Z",
            "completedAt": "2026-06-01T19:03:00Z",
            "items": [
                {
                    "id": "u1",
                    "type": "userMessage",
                    "status": "completed",
                    "createdAt": "2026-06-01T18:53:24Z",
                    "text": "调研一下",
                    "attachments": [],
                },
                {
                    "id": "a1",
                    "type": "agentMessage",
                    "status": "completed",
                    "createdAt": "2026-06-01T19:03:00Z",
                    "text": first,
                },
                {
                    "id": "a2",
                    "type": "agentMessage",
                    "status": "completed",
                    "createdAt": "2026-06-01T19:03:02Z",
                    "text": second,
                },
            ],
            "error": None,
        }
    )

    messages, _, _ = _flatten_turns_to_messages([turn])
    ai = [m for m in messages if m.get("type") == "ai"]
    assert len(ai) == 2, "genuinely different answers must not be collapsed"


def test_flatten_keeps_reasoning_private_and_commentary_explicit() -> None:
    from runtime.protocol import Turn
    from runtime.sensing.gateway.realtime_cerebrum import _flatten_turns_to_messages

    shared_text = "接下来检查前端测试，再审查代码差异。"
    turn = Turn.model_validate(
        {
            "id": "turn-visibility",
            "threadId": "thread-visibility",
            "status": "completed",
            "startedAt": "2026-08-10T08:00:00Z",
            "completedAt": "2026-08-10T08:00:01Z",
            "items": [
                {
                    "id": "u1",
                    "type": "userMessage",
                    "status": "completed",
                    "createdAt": "2026-08-10T08:00:00Z",
                    "text": "继续",
                    "attachments": [],
                },
                {
                    "id": "r1",
                    "type": "reasoning",
                    "status": "completed",
                    "createdAt": "2026-08-10T08:00:00Z",
                    "summary": [shared_text],
                    "content": "raw provider reasoning",
                },
                {
                    "id": "p1",
                    "type": "agentMessage",
                    "status": "completed",
                    "createdAt": "2026-08-10T08:00:01Z",
                    "text": shared_text,
                    "messageKind": "commentary",
                },
            ],
            "error": None,
        }
    )

    messages, _, _ = _flatten_turns_to_messages([turn])

    commentary = messages[1]
    assert commentary["content"] == shared_text
    assert commentary["additional_kwargs"] == {
        "reasoning_content": shared_text,
        "message_kind": "commentary",
        "public_progress": True,
    }
    assert "public_reasoning_summary" not in commentary["additional_kwargs"]


def test_flatten_file_change_tool_calls_are_json_serializable() -> None:
    """Regression: FileChange pydantic models leaked into the flattened
    ``tool_calls[].args.changes``, so the ThreadStateStore snapshot write
    (``json.dumps`` with no ``default=``) raised TypeError and the whole
    turn-state update was silently swallowed — thread status / updated_at
    froze at creation time. Flattened output must be JSON-safe.
    """
    import json as _json

    from runtime.protocol import Turn
    from runtime.sensing.gateway.realtime_cerebrum import _flatten_turns_to_messages

    turn = Turn.model_validate(
        {
            "id": "turn-fc",
            "threadId": "thread-fc",
            "status": "completed",
            "startedAt": "2026-06-01T18:53:24Z",
            "completedAt": "2026-06-01T19:03:00Z",
            "items": [
                {
                    "id": "u1",
                    "type": "userMessage",
                    "status": "completed",
                    "createdAt": "2026-06-01T18:53:24Z",
                    "text": "fix the config",
                    "attachments": [],
                },
                {
                    "id": "a1",
                    "type": "agentMessage",
                    "status": "completed",
                    "createdAt": "2026-06-01T19:03:00Z",
                    "text": "done",
                },
                {
                    "id": "fc1",
                    "type": "fileChange",
                    "status": "completed",
                    "createdAt": "2026-06-01T19:02:47Z",
                    "changes": [
                        {
                            "path": "/repo/commitlint.config.js",
                            "op": "update",
                            "diff": "--- a\n+++ b\n@@ -1 +1 @@\n-old\n+new",
                            "diffTruncated": False,
                            "hunks": [],
                        }
                    ],
                    "grantRoot": "/repo",
                },
            ],
            "error": None,
        }
    )

    messages, artifacts, _ = _flatten_turns_to_messages([turn])

    # The file path must still surface in artifacts.
    assert artifacts == ["/repo/commitlint.config.js"]
    ai = messages[-1]
    tool_calls = ai.get("tool_calls") or []
    assert any(tc.get("name") == "file_change" for tc in tool_calls)
    # The flattened transcript must be plain JSON — no pydantic models.
    dumped = _json.dumps(messages, ensure_ascii=False)
    assert "/repo/commitlint.config.js" in dumped
    change = next(tc["args"]["changes"][0] for tc in tool_calls if tc.get("name") == "file_change")
    assert isinstance(change, dict)
    assert change["path"] == "/repo/commitlint.config.js"
    assert change["op"] == "update"


def test_flatten_preserves_subagent_lifecycle_result_for_history() -> None:
    """A refreshed thread must retain the finish marker's public envelope."""
    from runtime.protocol import Turn
    from runtime.sensing.gateway.realtime_cerebrum import _flatten_turns_to_messages

    turn = Turn.model_validate(
        {
            "id": "turn-subagent-history",
            "threadId": "thread-subagent-history",
            "status": "completed",
            "startedAt": "2026-08-17T08:00:00Z",
            "completedAt": "2026-08-17T08:00:03Z",
            "items": [
                {
                    "id": "u1",
                    "type": "userMessage",
                    "status": "completed",
                    "createdAt": "2026-08-17T08:00:00Z",
                    "text": "审计项目",
                },
                {
                    "id": "finish-prism",
                    "type": "mcpToolCall",
                    "status": "failed",
                    "createdAt": "2026-08-17T08:00:03Z",
                    "server": "runtime",
                    "tool": "__subagent_finished__",
                    "arguments": {"parent_tool_use_id": "orchestration-1"},
                    "result": {
                        "agent_id": "reviewer",
                        "role": "reviewer",
                        "codename": "Prism-fcc",
                        "ok": False,
                        "error": "verification failed",
                        "iteration_count": 4,
                        "files_touched": ["frontend/src/page.tsx"],
                    },
                    "durationMs": 2300,
                },
                {
                    "id": "a1",
                    "type": "agentMessage",
                    "status": "completed",
                    "createdAt": "2026-08-17T08:00:03Z",
                    "text": "审计结束",
                },
            ],
        }
    )

    messages, _, _ = _flatten_turns_to_messages([turn])

    finish = messages[-1]["tool_calls"][0]
    assert finish["name"] == "runtime.__subagent_finished__"
    assert finish["args"] == {
        "agent_id": "reviewer",
        "role": "reviewer",
        "codename": "Prism-fcc",
        "ok": False,
        "error": "verification failed",
        "iteration_count": 4,
        "files_touched": ["frontend/src/page.tsx"],
        "parent_tool_use_id": "orchestration-1",
        "status": "failed",
        "duration_ms": 2300,
    }


def test_flatten_preserves_first_class_subagent_item_for_history() -> None:
    from runtime.protocol import Turn
    from runtime.sensing.gateway.realtime_cerebrum import _flatten_turns_to_messages

    turn = Turn.model_validate(
        {
            "id": "turn-first-class-subagent",
            "threadId": "thread-first-class-subagent",
            "status": "completed",
            "startedAt": "2026-08-17T08:00:00Z",
            "completedAt": "2026-08-17T08:00:03Z",
            "items": [
                {
                    "id": "u1",
                    "type": "userMessage",
                    "status": "completed",
                    "createdAt": "2026-08-17T08:00:00Z",
                    "text": "并行审计",
                },
                {
                    "id": "sub-1",
                    "type": "subagent",
                    "status": "completed",
                    "createdAt": "2026-08-17T08:00:01Z",
                    "subagentId": "reviewer",
                    "role": "reviewer",
                    "name": "Prism-fcc",
                    "codename": "Prism-fcc",
                    "avatar": "🛡️",
                    "summary": "检查了前端回放",
                    "iterationCount": 3,
                    "filesTouched": ["frontend/src/page.tsx"],
                },
                {
                    "id": "a1",
                    "type": "agentMessage",
                    "status": "completed",
                    "createdAt": "2026-08-17T08:00:03Z",
                    "text": "完成",
                },
            ],
        }
    )

    messages, _, _ = _flatten_turns_to_messages([turn])

    tool_call = messages[-1]["tool_calls"][0]
    assert tool_call["name"] == "subagent"
    assert tool_call["args"]["codename"] == "Prism-fcc"
    assert tool_call["args"]["iteration_count"] == 3
    assert tool_call["args"]["files_touched"] == ["frontend/src/page.tsx"]


@pytest.fixture()
def gateway(tmp_path: Path) -> Any:
    from runtime.sensing.gateway.realtime_cerebrum import CerebrumRuntime
    from runtime.sensing.gateway.realtime_gateway import RealtimeGateway

    runtime = CerebrumRuntime(
        stack=object(),  # unused by the fake loop
        agent=object(),
        logs_root=str(tmp_path / "threads"),
    )
    gateway = RealtimeGateway(runtime=runtime, approval_timeout=5.0)
    app = FastAPI()
    app.include_router(gateway.router)
    with TestClient(app) as client:
        yield client, tmp_path / "threads"


def _drive(ws: Any, params: dict[str, Any], approve: bool = True) -> dict[str, Any]:
    ws.send_text(encode_message(JsonRpcRequest(id=1, method="turn/start", params=params)))
    notifications: list[Notification] = []
    response: JsonRpcResponse | None = None
    while True:
        msg = decode_message(ws.receive_text())
        if isinstance(msg, JsonRpcRequest):
            ws.send_text(
                encode_message(
                    JsonRpcResponse(
                        id=msg.id, result={"action": "accept" if approve else "decline"}
                    )
                )
            )
            continue
        if isinstance(msg, Notification):
            notifications.append(msg)
            continue
        if isinstance(msg, JsonRpcResponse) and msg.id == 1:
            response = msg
            break
    assert response is not None
    return {"response": response, "notifications": notifications}


def test_text_delta_maps_to_agent_message(gateway: Any) -> None:
    client, _ = gateway
    _set_script(
        [
            {"type": "text_delta", "delta": "hello "},
            {"type": "text_delta", "delta": "world"},
            {"type": "react_completed"},
        ]
    )
    with client.websocket_connect("/api/realtime") as ws:
        out = _drive(
            ws,
            {
                "threadId": "th-text",
                "input": [{"type": "text", "text": "say hi"}],
                "approvalPolicy": "never",
            },
        )

    methods = [n.method for n in out["notifications"]]
    assert "turn/started" in methods
    assert methods.count("item/started") >= 1
    assert "item/agentMessage/delta" in methods

    deltas = [
        n.params["delta"] for n in out["notifications"] if n.method == "item/agentMessage/delta"
    ]
    assert "".join(deltas) == "hello world"

    # Final snapshot carries one completed agentMessage item.
    turn = out["response"].result["turn"]
    agent_items = [it for it in turn["items"] if it["type"] == "agentMessage"]
    assert len(agent_items) == 1
    assert agent_items[0]["text"] == "hello world"
    assert agent_items[0]["status"] == "completed"


def test_user_turn_refills_subagent_wake_budget(gateway: Any, tmp_path: Path) -> None:
    from runtime.execution.subagents.sessions import (
        SubagentSessionStore,
        get_subagent_session_store,
        set_subagent_session_store,
    )

    client, logs_root = gateway
    seen: list[str] = []
    store = SubagentSessionStore(
        base_dir=Path(logs_root) / "subagent_sessions",
        on_report=lambda sid, report: seen.append(report.content),
        max_consecutive_wakes=1,
    )
    previous = get_subagent_session_store()
    set_subagent_session_store(store)
    try:
        session = store.create(agent_id="researcher", thread_id="th-refill")
        store.append_report(session.session_id, content="w1", delivery="wakeup")
        assert seen == ["w1"]
        # Budget spent → the next wakeup report degrades to quiet.
        store.append_report(session.session_id, content="w2", delivery="wakeup")
        assert seen == ["w1"]
        assert store.get(session.session_id).reports[-1].delivery == "quiet"

        # A human turn on the same thread refills the budget (dsh
        # ``agent/inbox/claimed`` with a user-authored message).
        _set_script([{"type": "react_completed"}])
        with client.websocket_connect("/api/realtime") as ws:
            out = _drive(
                ws,
                {
                    "threadId": "th-refill",
                    "input": [{"type": "text", "text": "继续"}],
                    "approvalPolicy": "never",
                },
            )
        assert out["response"].result["turn"]["threadId"] == "th-refill"

        store.append_report(session.session_id, content="w3", delivery="wakeup")
        assert seen == ["w1", "w3"]
    finally:
        set_subagent_session_store(previous)


# ─── queued-report → running-turn steering injection (dsh ``inject``) ────


class _TurnLike:
    thread_id = "th-inject"

    def __init__(self) -> None:
        self.items: list[Any] = []


class _SteeringRuntime:
    def __init__(self) -> None:
        import threading
        from queue import SimpleQueue

        self._turn_steering: dict[str, Any] = {}
        self._turn_steering_accepting: dict[str, bool] = {}
        self._active_turns: dict[str, tuple[Any, Any]] = {}
        self._turn_steering_seen: dict[str, set[str]] = {}
        self._turn_steering_notified: dict[str, set[str]] = {}
        self._turn_steering_last_sync: dict[str, float] = {}
        self._turn_steering_log_offsets: dict[str, int] = {}
        self._turn_timeline: dict[str, tuple[int, Any]] = {}
        self._turn_steering_lock = threading.Lock()
        self._queue_factory = SimpleQueue


def test_thread_steering_injection_into_running_turn() -> None:
    from runtime.sensing.gateway._realtime_cerebrum_steering import (
        _inject_thread_steering,
        _register_thread_turn,
        _unregister_thread_turn,
    )

    runtime = _SteeringRuntime()
    turn = _TurnLike()
    runtime._turn_steering["turn-1"] = runtime._queue_factory()
    runtime._turn_steering_accepting["turn-1"] = True
    runtime._active_turns["turn-1"] = (turn, None)

    _register_thread_turn("th-inject", runtime, "turn-1")
    try:
        assert _inject_thread_steering("th-inject", "报告文本") is True
        item_id, text = runtime._turn_steering["turn-1"].get_nowait()
        assert text == "报告文本"
        assert item_id
        assert len(turn.items) == 1
        assert turn.items[0].text == "报告文本"
        assert turn.items[0].source == "user"
    finally:
        _unregister_thread_turn("th-inject", runtime, "turn-1")

    # After the turn ends the same thread has no accepting turn → no-op.
    assert _inject_thread_steering("th-inject", "之后") is False


def test_thread_steering_injection_skips_not_accepting_or_unknown() -> None:
    from runtime.sensing.gateway._realtime_cerebrum_steering import (
        _inject_thread_steering,
        _register_thread_turn,
        _unregister_thread_turn,
    )

    runtime = _SteeringRuntime()
    turn = _TurnLike()
    runtime._turn_steering["turn-1"] = runtime._queue_factory()
    runtime._turn_steering_accepting["turn-1"] = False
    runtime._active_turns["turn-1"] = (turn, None)
    _register_thread_turn("th-inject", runtime, "turn-1")
    try:
        assert _inject_thread_steering("th-inject", "x") is False
        assert _inject_thread_steering("th-unknown", "x") is False
        assert runtime._turn_steering["turn-1"].qsize() == 0
        assert turn.items == []
    finally:
        _unregister_thread_turn("th-inject", runtime, "turn-1")


def test_thread_turn_registry_ignores_empty_thread() -> None:
    from runtime.sensing.gateway._realtime_cerebrum_steering import (
        _register_thread_turn,
        _unregister_thread_turn,
    )

    runtime = _SteeringRuntime()
    _register_thread_turn("", runtime, "turn-1")  # no raise
    _unregister_thread_turn("", runtime, "turn-1")  # no raise


def test_drain_returns_injected_steering_text() -> None:
    from runtime.sensing.gateway._realtime_cerebrum_steering import (
        _drain_turn_steering,
        _inject_thread_steering,
        _register_thread_turn,
        _unregister_thread_turn,
    )

    class _FakeLog:
        def tail_events(self, offset: int) -> tuple[list[Any], int]:
            return [], offset

    runtime = _SteeringRuntime()
    turn = _TurnLike()
    runtime._turn_steering["turn-1"] = runtime._queue_factory()
    runtime._turn_steering_accepting["turn-1"] = True
    runtime._active_turns["turn-1"] = (turn, _FakeLog())
    runtime._turn_steering_seen["turn-1"] = set()
    runtime._turn_steering_notified["turn-1"] = set()
    runtime._turn_steering_last_sync["turn-1"] = 0.0
    runtime._turn_steering_log_offsets["turn-1"] = 0

    _register_thread_turn("th-inject", runtime, "turn-1")
    try:
        assert _inject_thread_steering("th-inject", "[子代理报告] 中途发现") is True
        # This is the exact function the react loop's steering_drain calls at
        # its nearest step boundary — the injected text reaches the model.
        assert _drain_turn_steering(runtime, "turn-1") == ["[子代理报告] 中途发现"]
    finally:
        _unregister_thread_turn("th-inject", runtime, "turn-1")


def test_subagent_report_steering_is_marked_internal() -> None:
    from runtime.sensing.gateway._realtime_cerebrum_steering import (
        _inject_thread_steering,
        _register_thread_turn,
        _unregister_thread_turn,
    )

    runtime = _SteeringRuntime()
    turn = _TurnLike()
    runtime._turn_steering["turn-1"] = runtime._queue_factory()
    runtime._turn_steering_accepting["turn-1"] = True
    runtime._active_turns["turn-1"] = (turn, None)

    _register_thread_turn("th-inject", runtime, "turn-1")
    try:
        assert (
            _inject_thread_steering(
                "th-inject",
                "[子代理报告] 完成",
                source="subagent_report",
            )
            is True
        )
        assert turn.items[0].source == "subagent_report"
    finally:
        _unregister_thread_turn("th-inject", runtime, "turn-1")


def test_inject_writes_durable_log_and_never_delivers_twice() -> None:
    from runtime.sensing.gateway._realtime_cerebrum_steering import (
        _drain_turn_steering,
        _inject_thread_steering,
        _register_thread_turn,
        _unregister_thread_turn,
    )

    class _CaptureLog:
        def __init__(self) -> None:
            self.writes: list[dict[str, Any]] = []

        def item_completed(self, thread_id: str, turn_id: str, item: Any) -> None:
            self.writes.append({"thread_id": thread_id, "turn_id": turn_id, "item": item})

        def tail_events(self, offset: int) -> tuple[list[Any], int]:
            events = []
            for index in range(offset, len(self.writes)):
                write = self.writes[index]
                event = type(
                    "_Event",
                    (),
                    {
                        "event": "item_completed",
                        "turn_id": write["turn_id"],
                        "payload": {"item": write["item"].model_dump(by_alias=True, mode="json")},
                    },
                )()
                events.append(event)
            return events, len(self.writes)

    runtime = _SteeringRuntime()
    turn = _TurnLike()
    log = _CaptureLog()
    runtime._turn_steering["turn-1"] = runtime._queue_factory()
    runtime._turn_steering_accepting["turn-1"] = True
    runtime._active_turns["turn-1"] = (turn, log)
    runtime._turn_steering_seen["turn-1"] = set()
    runtime._turn_steering_notified["turn-1"] = set()
    runtime._turn_steering_last_sync["turn-1"] = 0.0
    runtime._turn_steering_log_offsets["turn-1"] = 0

    _register_thread_turn("th-inject", runtime, "turn-1")
    try:
        assert _inject_thread_steering("th-inject", "报告文本") is True
        assert len(log.writes) == 1
        item = log.writes[0]["item"]
        assert item.text == "报告文本"
        assert item.id in runtime._turn_steering_seen["turn-1"]
        assert item.id in runtime._turn_steering_notified["turn-1"]

        # The steering sync discovers the durable row, but the seen-mark
        # prevents a second delivery: exactly one drain, then empty.
        assert _drain_turn_steering(runtime, "turn-1") == ["报告文本"]
        assert _drain_turn_steering(runtime, "turn-1") == []
    finally:
        _unregister_thread_turn("th-inject", runtime, "turn-1")


def test_turn_start_surfaces_pending_thread_reports(gateway: Any, tmp_path: Path) -> None:
    from runtime.execution.subagents.sessions import (
        SubagentSessionStore,
        get_subagent_session_store,
        set_subagent_session_store,
    )

    client, logs_root = gateway
    store = SubagentSessionStore(base_dir=Path(logs_root) / "subagent_sessions")
    previous = get_subagent_session_store()
    set_subagent_session_store(store)
    try:
        first = store.create(agent_id="researcher", thread_id="th-surface")
        second = store.create(agent_id="coder", thread_id="th-surface")
        store.append_report(first.session_id, content="部分发现", delivery="quiet")
        store.append_report(second.session_id, content="最终结论", delivery="quiet")

        _set_script([{"type": "react_completed"}])
        with client.websocket_connect("/api/realtime") as ws:
            out = _drive(
                ws,
                {
                    "threadId": "th-surface",
                    "input": [{"type": "text", "text": "继续"}],
                    "approvalPolicy": "never",
                },
            )

        turn = out["response"].result["turn"]
        steering = [item for item in turn["items"] if item.get("type") == "steeringUserMessage"]
        texts = [item["text"] for item in steering]
        assert "[子代理报告] 部分发现" in texts
        assert "[子代理报告] 最终结论" in texts
        # Surfaced reports are claimed (acked) so the next turn does not
        # re-inject them (dsh inbox claim semantics).
        assert store.pending_reports(first.session_id) == []
        assert store.pending_reports(second.session_id) == []
    finally:
        set_subagent_session_store(previous)


def test_commentary_delta_maps_to_non_terminal_agent_message(gateway: Any) -> None:
    client, _ = gateway
    _set_script(
        [
            {"type": "thinking_delta", "delta": "private"},
            {
                "type": "commentary_delta",
                "delta": "已确认第一组数据一致。",
                "progress_source": "model",
            },
            {
                "type": "tool_start",
                "tool_name": "echo",
                "tool_call_id": "commentary-tool",
                "iteration": 1,
            },
            {
                "type": "tool_end",
                "tool_name": "echo",
                "tool_call_id": "commentary-tool",
                "iteration": 1,
                "status": "success",
            },
            {"type": "text_delta", "delta": "最终答案"},
            {"type": "react_completed"},
        ]
    )

    with client.websocket_connect("/api/realtime") as ws:
        out = _drive(
            ws,
            {
                "threadId": "th-commentary",
                "input": [{"type": "text", "text": "long task"}],
                "approvalPolicy": "never",
            },
        )

    turn = out["response"].result["turn"]
    messages = [item for item in turn["items"] if item["type"] == "agentMessage"]
    assert [item["text"] for item in messages] == [
        "已确认第一组数据一致。",
        "最终答案",
    ]
    assert messages[0]["messageKind"] == "commentary"
    assert messages[0].get("progressKind") is None
    tool_item = next(item for item in turn["items"] if item["type"] == "commandExecution")
    coordinated = [item for item in turn["items"] if item.get("timelineSequence") is not None]
    assert [item["timelineSequence"] for item in coordinated] == list(
        range(1, len(coordinated) + 1)
    )
    assert tool_item["parentItemId"] == messages[0]["id"]
    assert messages[1]["parentItemId"] == tool_item["id"]
    assert messages[1]["messageKind"] == "answer"
    assert all(item["status"] == "completed" for item in messages)


def test_codebase_grounding_is_attached_to_the_turn_snapshot(gateway: Any) -> None:
    client, _ = gateway
    sources = [
        {
            "kind": "source",
            "title": "realtime-adapter.ts",
            "path": "frontend/src/core/threads/realtime-adapter.ts:439",
        }
    ]
    _set_script(
        [
            {"type": "codebase_grounding", "sources": sources},
            {"type": "text_delta", "delta": "最终答案"},
            {"type": "react_completed"},
        ]
    )

    with client.websocket_connect("/api/realtime") as ws:
        out = _drive(
            ws,
            {
                "threadId": "th-grounding-snapshot",
                "input": [{"type": "text", "text": "inspect adapter"}],
                "approvalPolicy": "never",
            },
        )

    turn = out["response"].result["turn"]
    assert turn["grounding"] == sources
    grounding_notifications = [
        notification
        for notification in out["notifications"]
        if notification.method == "turn/grounding"
    ]
    assert grounding_notifications[-1].params["sources"] == sources


def test_commentary_event_boundary_starts_a_new_timeline_item(gateway: Any) -> None:
    client, _ = gateway
    _set_script(
        [
            {
                "type": "commentary_delta",
                "delta": "我先核对关键文件。",
            },
            {
                "type": "commentary_delta",
                "delta": "证据已经够了，开始收束。",
            },
            {"type": "text_delta", "delta": "最终答案"},
            {"type": "react_completed"},
        ]
    )

    with client.websocket_connect("/api/realtime") as ws:
        out = _drive(
            ws,
            {
                "threadId": "th-commentary-phases",
                "input": [{"type": "text", "text": "compare two files"}],
                "approvalPolicy": "never",
            },
        )

    messages = [
        item for item in out["response"].result["turn"]["items"] if item["type"] == "agentMessage"
    ]
    assert [item["text"] for item in messages] == [
        "我先核对关键文件。",
        "证据已经够了，开始收束。",
        "最终答案",
    ]
    assert all(item.get("progressKind") is None for item in messages)
    assert messages[0]["progressSequence"] == 1
    assert messages[0]["phaseId"].endswith(":progress:1")
    assert messages[0]["parentItemId"] is None
    assert messages[1]["progressSequence"] == 2
    assert messages[1]["phaseId"].endswith(":progress:2")
    assert messages[1]["parentItemId"] == messages[0]["id"]
    assert messages[2]["parentItemId"] == messages[1]["id"]


def test_commentary_stream_chunks_extend_one_timeline_item(gateway: Any) -> None:
    client, _ = gateway
    _set_script(
        [
            {
                "type": "commentary_delta",
                "delta": "四个目标文件均已",
                "progress_source": "model",
                "start_new_segment": True,
            },
            {
                "type": "commentary_delta",
                "delta": "读取，事件顺序已经确认。",
                "progress_source": "model",
                "start_new_segment": False,
            },
            {"type": "text_delta", "delta": "最终答案"},
            {"type": "react_completed"},
        ]
    )

    with client.websocket_connect("/api/realtime") as ws:
        out = _drive(
            ws,
            {
                "threadId": "th-commentary-stream",
                "input": [{"type": "text", "text": "inspect event ordering"}],
                "approvalPolicy": "never",
            },
        )

    messages = [
        item for item in out["response"].result["turn"]["items"] if item["type"] == "agentMessage"
    ]
    assert [message["text"] for message in messages] == [
        "四个目标文件均已读取，事件顺序已经确认。",
        "最终答案",
    ]
    assert messages[0]["messageKind"] == "commentary"
    assert messages[0]["progressSequence"] == 1
    commentary_deltas = [
        notification.params["delta"]
        for notification in out["notifications"]
        if notification.method == "item/agentMessage/delta"
        and notification.params["itemId"] == messages[0]["id"]
    ]
    assert "".join(commentary_deltas) == "四个目标文件均已读取，事件顺序已经确认。"


def test_duplicate_public_commentary_is_collapsed(gateway: Any) -> None:
    client, _ = gateway
    _set_script(
        [
            {
                "type": "commentary_delta",
                "delta": "关键文件已经确认，下一步核对事件顺序。",
                "progress_source": "model",
            },
            {
                "type": "commentary_delta",
                "delta": "  关键文件已经确认，下一步核对事件顺序。  ",
                "progress_source": "model",
            },
            {"type": "text_delta", "delta": "最终答案"},
            {"type": "react_completed"},
        ]
    )

    with client.websocket_connect("/api/realtime") as ws:
        out = _drive(
            ws,
            {
                "threadId": "th-commentary-dedupe",
                "input": [{"type": "text", "text": "inspect ordering"}],
                "approvalPolicy": "never",
            },
        )

    messages = [
        item for item in out["response"].result["turn"]["items"] if item["type"] == "agentMessage"
    ]
    assert [message["text"] for message in messages] == [
        "关键文件已经确认，下一步核对事件顺序。",
        "最终答案",
    ]


def test_silent_tool_round_does_not_manufacture_public_narrative(gateway: Any) -> None:
    client, _ = gateway
    _set_script(
        [
            {
                "type": "tool_start",
                "tool_name": "exec_shell",
                "tool_call_id": "silent-tool",
                "iteration": 1,
                "input_preview": {
                    "command": "cat ~/.ssh/id_rsa && pnpm test",
                    "cwd": "/Users/alice/Public/octopus/octopus-agent",  # lint: allow-user-path
                    "token": "super-secret",
                },
            },
            {
                "type": "tool_end",
                "tool_name": "exec_shell",
                "tool_call_id": "silent-tool",
                "iteration": 1,
                "status": "success",
                "output_preview": "ok",
            },
            {"type": "text_delta", "delta": "最终答案"},
            {"type": "react_completed"},
        ]
    )

    with client.websocket_connect("/api/realtime") as ws:
        out = _drive(
            ws,
            {
                "threadId": "th-tool-public-narrative",
                "input": [{"type": "text", "text": "check it"}],
                "approvalPolicy": "never",
            },
        )

    turn = out["response"].result["turn"]
    messages = [item for item in turn["items"] if item["type"] == "agentMessage"]
    assert [item["messageKind"] for item in messages] == ["answer"]
    public_text = "\n".join(item["text"] for item in messages)
    assert public_text == "最终答案"
    assert "exec_shell" not in public_text
    assert "cat ~/.ssh/id_rsa" not in public_text
    assert "/Users/alice/Public" not in public_text  # lint: allow-user-path
    assert "super-secret" not in public_text


def test_tool_public_description_overrides_generic_runtime_narrative(
    gateway: Any,
) -> None:
    client, _ = gateway
    _set_script(
        [
            {
                "type": "tool_start",
                "tool_name": "read_file",
                "tool_call_id": "described-tool",
                "iteration": 1,
                "input_preview": {
                    "path": "runtime/protocol/items.py",
                    "public_description": "我先核对协议字段的真实定义。",
                },
            },
            {
                "type": "tool_end",
                "tool_name": "read_file",
                "tool_call_id": "described-tool",
                "iteration": 1,
                "status": "success",
                "public_result": "已确认三个字段都在协议层存在。",
                "output_preview": "private raw output",
            },
            {"type": "text_delta", "delta": "最终答案"},
            {"type": "react_completed"},
        ]
    )

    with client.websocket_connect("/api/realtime") as ws:
        out = _drive(
            ws,
            {
                "threadId": "th-tool-public-description",
                "input": [{"type": "text", "text": "check fields"}],
                "approvalPolicy": "never",
            },
        )

    messages = [
        item for item in out["response"].result["turn"]["items"] if item["type"] == "agentMessage"
    ]
    public_text = "\n".join(item["text"] for item in messages)
    assert "我先核对协议字段的真实定义。" in public_text
    assert "已确认三个字段都在协议层存在。" in public_text
    assert "我先核对相关上下文。" not in public_text
    assert "关键上下文已经确认。" not in public_text
    assert "read_file" not in public_text
    assert "private raw output" not in public_text


def test_final_answer_starts_after_public_commentary_completes(
    gateway: Any,
) -> None:
    client, _ = gateway
    _set_script(
        [
            {
                "type": "commentary_delta",
                "delta": "证据已经确认，开始收束。",
                "progress_source": "model",
            },
            {"type": "text_delta", "delta": "最终答案"},
            {"type": "react_completed"},
        ]
    )

    with client.websocket_connect("/api/realtime") as ws:
        out = _drive(
            ws,
            {
                "threadId": "th-commentary-before-answer",
                "input": [{"type": "text", "text": "summarize"}],
                "approvalPolicy": "never",
            },
        )

    notifications = out["notifications"]
    commentary_item_id = None
    answer_item_id = None
    commentary_completed_index = -1
    answer_started_index = -1
    for index, notification in enumerate(notifications):
        if notification.method != "item/started":
            continue
        item = notification.params["item"]
        if item["type"] != "agentMessage":
            continue
        if item.get("messageKind") == "commentary":
            commentary_item_id = item["id"]
        else:
            answer_item_id = item["id"]
            answer_started_index = index
            break

    assert commentary_item_id is not None
    assert answer_item_id is not None
    for index, notification in enumerate(notifications):
        if notification.method != "item/completed":
            continue
        item = notification.params["item"]
        if item["id"] == commentary_item_id:
            commentary_completed_index = index
            break

    assert commentary_completed_index != -1
    assert commentary_completed_index < answer_started_index


def test_tool_without_call_id_still_completes(gateway: Any) -> None:
    client, _ = gateway
    _set_script(
        [
            {
                "type": "tool_start",
                "tool_name": "read_file",
                "iteration": 1,
                "input_preview": {"public_description": "我先核对一个必要上下文。"},
            },
            {
                "type": "tool_end",
                "tool_name": "read_file",
                "iteration": 1,
                "status": "success",
                "public_result": "必要上下文已经确认。",
            },
            {"type": "text_delta", "delta": "最终答案"},
            {"type": "react_completed"},
        ]
    )

    with client.websocket_connect("/api/realtime") as ws:
        out = _drive(
            ws,
            {
                "threadId": "th-tool-without-call-id",
                "input": [{"type": "text", "text": "check"}],
                "approvalPolicy": "never",
            },
        )

    turn = out["response"].result["turn"]
    tools = [item for item in turn["items"] if item["type"] == "commandExecution"]
    messages = [item for item in turn["items"] if item["type"] == "agentMessage"]
    assert len(tools) == 1
    assert tools[0]["id"].startswith("itm_")
    assert tools[0]["status"] == "completed"
    assert [message["text"] for message in messages] == [
        "我先核对一个必要上下文。",
        "必要上下文已经确认。",
        "最终答案",
    ]


def test_unsafe_tool_public_description_is_omitted_without_leaking(
    gateway: Any,
) -> None:
    client, _ = gateway
    _set_script(
        [
            {
                "type": "tool_start",
                "tool_name": "read_file",
                "tool_call_id": "unsafe-described-tool",
                "iteration": 1,
                "input_preview": {
                    "public_description": "读取 /Users/alice/secret.txt token=super-secret",  # lint: allow-user-path
                },
            },
            {
                "type": "tool_end",
                "tool_name": "read_file",
                "tool_call_id": "unsafe-described-tool",
                "iteration": 1,
                "status": "success",
                "public_result": "完成 token=super-secret",
            },
            {"type": "text_delta", "delta": "最终答案"},
            {"type": "react_completed"},
        ]
    )

    with client.websocket_connect("/api/realtime") as ws:
        out = _drive(
            ws,
            {
                "threadId": "th-tool-unsafe-public-description",
                "input": [{"type": "text", "text": "check fields"}],
                "approvalPolicy": "never",
            },
        )

    messages = [
        item for item in out["response"].result["turn"]["items"] if item["type"] == "agentMessage"
    ]
    public_text = "\n".join(item["text"] for item in messages)
    assert public_text == "最终答案"
    assert "/Users/alice/secret.txt" not in public_text  # lint: allow-user-path
    assert "super-secret" not in public_text


def test_runtime_generated_commentary_is_not_shown_as_model_progress(gateway: Any) -> None:
    client, _ = gateway
    _set_script(
        [
            {
                "type": "commentary_delta",
                "delta": "runtime-only status",
                "progress_source": "runtime",
            },
            {"type": "text_delta", "delta": "最终答案"},
            {"type": "react_completed"},
        ]
    )

    with client.websocket_connect("/api/realtime") as ws:
        out = _drive(
            ws,
            {
                "threadId": "th-runtime-commentary-filter",
                "input": [{"type": "text", "text": "compare two files"}],
                "approvalPolicy": "never",
            },
        )

    messages = [
        item for item in out["response"].result["turn"]["items"] if item["type"] == "agentMessage"
    ]
    assert [(item["text"], item.get("progressKind")) for item in messages] == [("最终答案", None)]


def test_runtime_timeout_status_is_visible_before_recovery(gateway: Any) -> None:
    client, _ = gateway
    _set_script(
        [
            {
                "type": "commentary_delta",
                "delta": "当前模型响应过慢，已保留现有结果并切换备用模型继续。",
                "progress_source": "runtime",
                "public_status": True,
            },
            {"type": "text_delta", "delta": "备用模型已经完成回答。"},
            {"type": "react_completed"},
        ]
    )

    with client.websocket_connect("/api/realtime") as ws:
        out = _drive(
            ws,
            {
                "threadId": "th-runtime-timeout-status",
                "input": [{"type": "text", "text": "perform a long task"}],
                "approvalPolicy": "never",
            },
        )

    messages = [
        item for item in out["response"].result["turn"]["items"] if item["type"] == "agentMessage"
    ]
    assert [item["text"] for item in messages] == [
        "当前模型响应过慢，已保留现有结果并切换备用模型继续。",
        "备用模型已经完成回答。",
    ]


def test_grounded_runtime_evidence_is_shown_between_batches(gateway: Any) -> None:
    client, _ = gateway
    _set_script(
        [
            {
                "type": "commentary_delta",
                "delta": "已完整取得 items.py 的 21,204 字节内容；接下来核对 reducer.ts。",
                "progress_source": "runtime",
                "public_evidence": True,
                "start_new_segment": True,
            },
            {"type": "text_delta", "delta": "最终答案"},
            {"type": "react_completed"},
        ]
    )

    with client.websocket_connect("/api/realtime") as ws:
        out = _drive(
            ws,
            {
                "threadId": "th-grounded-runtime-evidence",
                "input": [{"type": "text", "text": "compare two files in order"}],
                "approvalPolicy": "never",
            },
        )

    messages = [
        item for item in out["response"].result["turn"]["items"] if item["type"] == "agentMessage"
    ]
    assert [item["text"] for item in messages] == [
        "已完整取得 items.py 的 21,204 字节内容；接下来核对 reducer.ts。",
        "最终答案",
    ]


def test_commentary_without_terminal_event_fails_instead_of_completing(gateway: Any) -> None:
    client, _ = gateway
    _set_script(
        [
            {"type": "commentary_delta", "delta": "阶段结果已保留。"},
        ]
    )

    with client.websocket_connect("/api/realtime") as ws:
        out = _drive(
            ws,
            {
                "threadId": "th-commentary-no-final",
                "input": [{"type": "text", "text": "long task"}],
                "approvalPolicy": "never",
            },
        )

    turn = out["response"].result["turn"]
    assert turn["status"] == "failed"
    errors = [item for item in turn["items"] if item["type"] == "error"]
    assert errors
    assert "最终答案" in errors[0]["message"]


def test_complete_answer_without_terminal_event_is_recovered(gateway: Any) -> None:
    client, _ = gateway
    _set_script(
        [
            {"type": "thinking_delta", "delta": "整理证据"},
            {"type": "text_delta", "delta": "这是已经生成的完整答案。"},
        ]
    )

    with client.websocket_connect("/api/realtime") as ws:
        out = _drive(
            ws,
            {
                "threadId": "th-answer-no-terminal",
                "input": [{"type": "text", "text": "research"}],
                "approvalPolicy": "never",
            },
        )

    turn = out["response"].result["turn"]
    assert turn["status"] == "completed"
    answers = [
        item
        for item in turn["items"]
        if item["type"] == "agentMessage" and item.get("messageKind") == "answer"
    ]
    assert [item["text"] for item in answers] == ["这是已经生成的完整答案。"]
    assert not [item for item in turn["items"] if item["type"] == "error"]


def test_empty_react_completion_becomes_visible_error(gateway: Any) -> None:
    client, _ = gateway
    _set_script([{"type": "react_completed"}])

    with client.websocket_connect("/api/realtime") as ws:
        out = _drive(
            ws,
            {
                "threadId": "th-empty-output",
                "input": [{"type": "text", "text": "do work"}],
                "approvalPolicy": "never",
            },
        )

    turn = out["response"].result["turn"]
    assert turn["status"] == "failed"
    error_items = [it for it in turn["items"] if it["type"] == "error"]
    assert len(error_items) == 1
    assert error_items[0]["errorInfo"]["code"] == "empty_model_output"
    completed_errors = [
        n.params["item"]
        for n in out["notifications"]
        if n.method == "item/completed" and n.params["item"]["type"] == "error"
    ]
    assert completed_errors


def test_todo_write_emits_plan_update_and_resume_snapshot(gateway: Any) -> None:
    client, _ = gateway
    _set_script(
        [
            {
                "type": "tool_start",
                "tool_name": "todo_write",
                "tool_call_id": "todo-1",
                "input_preview": {
                    "items": [
                        {"content": "Inspect context", "status": "completed"},
                        {"content": "Patch realtime protocol", "status": "in_progress"},
                        {"content": "Verify behavior", "status": "pending"},
                    ]
                },
            },
            {
                "type": "tool_end",
                "tool_name": "todo_write",
                "tool_call_id": "todo-1",
                "status": "success",
                "output_preview": "ok",
            },
            {"type": "react_completed"},
        ]
    )
    with client.websocket_connect("/api/realtime") as ws:
        out = _drive(
            ws,
            {
                "threadId": "th_plan_update",
                "input": [{"type": "text", "text": "plan"}],
                "approvalPolicy": "never",
            },
        )
        ws.send_text(
            encode_message(
                JsonRpcRequest(
                    id=2,
                    method="thread/resume",
                    params={"threadId": "th_plan_update"},
                )
            )
        )
        resume: JsonRpcResponse | None = None
        while True:
            msg = decode_message(ws.receive_text())
            if isinstance(msg, JsonRpcResponse) and msg.id == 2:
                resume = msg
                break

    updates = [n for n in out["notifications"] if n.method == "turn/plan/updated"]
    assert updates
    phases = updates[0].params["phases"]
    assert [phase["title"] for phase in phases] == [
        "Inspect context",
        "Patch realtime protocol",
        "Verify behavior",
    ]
    assert phases[1]["status"] == "running"
    assert phases[1]["activeItemId"] == "todo-1"
    assert updates[0].params["workspaceFocus"]["view"] == "trace"
    assert updates[0].params["workbenchSnapshot"]["schemaVersion"] == 2
    assert updates[0].params["workbenchSnapshot"]["currentItemId"] == "todo-1"

    snapshots = [n for n in out["notifications"] if n.method == "workbench/snapshot"]
    assert snapshots
    assert snapshots[0].params["snapshot"]["version"] == 1
    assert snapshots[0].params["snapshot"]["workspaceFocus"]["view"] == "trace"
    assert snapshots[1].params["snapshot"]["version"] == 2
    assert snapshots[1].params["snapshot"]["phases"][1]["status"] == "running"
    final_snapshot = snapshots[-1].params["snapshot"]
    assert final_snapshot["version"] == 3
    assert [phase["status"] for phase in final_snapshot["phases"]] == [
        "done",
        "pending",
        "pending",
    ]
    assert all(phase.get("activeItemId") is None for phase in final_snapshot["phases"])
    assert final_snapshot["currentItemId"] is None

    turn = out["response"].result["turn"]
    assert turn["phases"][1]["status"] == "pending"
    assert turn["workspaceFocus"]["itemId"] == "todo-1"
    assert turn["workbenchSnapshot"]["currentPhaseId"] == "todo-phase:1"
    assert turn["workbenchSnapshot"]["currentItemId"] is None
    assert turn["workbenchSnapshot"]["version"] == 3
    assert resume is not None and resume.result is not None
    resumed_turn = resume.result["turns"][0]
    assert resumed_turn["phases"][1]["title"] == "Patch realtime protocol"
    assert resumed_turn["workspaceFocus"]["view"] == "trace"
    assert resumed_turn["workbenchSnapshot"]["currentItemId"] is None
    assert resumed_turn["workbenchSnapshot"]["version"] == 3


def test_team_subagent_lifecycle_maps_to_first_class_item(
    gateway: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from runtime.safety.organization import (
        AgentSpec,
        CoordinationProtocol,
        Role,
        TeamTopology,
    )
    from runtime.safety.organization.team_runner import TeamRunResult

    client, _ = gateway
    topology = TeamTopology(
        name="test_topology",
        protocol=CoordinationProtocol.SEQUENTIAL,
        agents={Role.PLANNER: AgentSpec(agent_id="planner_a")},
    )

    class FakeTeamRunner:
        def __init__(self, *args: Any, event_emitter: Any = None, **kwargs: Any) -> None:
            self._emit = event_emitter

        def run(self, topology: Any, text: str, context: dict[str, Any]) -> TeamRunResult:
            assert self._emit is not None
            assert context["model_name"] == "kimi-k3"
            self._emit(
                {
                    "type": "subagent_spawned",
                    "agent_id": "planner_a",
                    "role": "planner",
                    "codename": "Plan-abc",
                    "avatar": "P",
                }
            )
            self._emit(
                {
                    "type": "subagent_finished",
                    "agent_id": "planner_a",
                    "role": "planner",
                    "codename": "Plan-abc",
                    "avatar": "P",
                    "ok": True,
                    "iteration_count": 2,
                    "files_touched": ["plan.md"],
                    "status": "done",
                }
            )
            return TeamRunResult(
                topology_name=topology.name,
                topology_fingerprint=topology.fingerprint,
                task_bucket=topology.task_bucket,
                success=True,
                final_output="done",
            )

    monkeypatch.setattr(
        "runtime.safety.organization.forge.load_registry",
        lambda: {"test_topology": topology},
    )
    monkeypatch.setattr(
        "runtime.safety.organization.team_runner.TeamRunner",
        FakeTeamRunner,
    )
    monkeypatch.setattr(
        "runtime.safety.organization.performance_log.record_run",
        lambda *args, **kwargs: None,
    )

    with client.websocket_connect("/api/realtime") as ws:
        out = _drive(
            ws,
            {
                "threadId": "th-team-subagent",
                "input": [{"type": "text", "text": "run topology"}],
                "approvalPolicy": "never",
                "model": "kimi-k3",
                "topologyId": "test_topology",
            },
        )

    started = [n.params["item"] for n in out["notifications"] if n.method == "item/started"]
    completed = [n.params["item"] for n in out["notifications"] if n.method == "item/completed"]
    sub_started = [item for item in started if item["type"] == "subagent"]
    sub_completed = [item for item in completed if item["type"] == "subagent"]
    assert len(sub_started) == 1
    assert len(sub_completed) == 1
    assert sub_started[0]["subagentId"] == "planner_a"
    assert sub_started[0]["status"] == "inProgress"
    assert sub_completed[0]["id"] == sub_started[0]["id"]
    assert sub_completed[0]["status"] == "completed"
    assert sub_completed[0]["iterationCount"] == 2
    assert sub_completed[0]["filesTouched"] == ["plan.md"]

    turn = out["response"].result["turn"]
    sub_items = [it for it in turn["items"] if it["type"] == "subagent"]
    assert len(sub_items) == 1
    assert sub_items[0]["status"] == "completed"


def test_cowork_swarm_plan_drives_group_fanout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from runtime.memory.cowork.group_store import GroupStore
    from runtime.memory.cowork.service import invite_member, set_mode
    from runtime.sensing.gateway.realtime_cerebrum import CerebrumRuntime
    from runtime.sensing.gateway.realtime_gateway import RealtimeGateway

    store = GroupStore(base_dir=tmp_path / "cowork")
    invite_member(store, "th-cowork", actor="u", target_id="db-agent", kind="agent")
    invite_member(store, "th-cowork", actor="u", target_id="ui-agent", kind="agent")
    set_mode(store, "th-cowork", actor="u", mode="swarm")
    seen: dict[str, Any] = {}

    def fake_fanout(message: str, members: list[dict[str, Any]], **_kwargs: Any) -> dict[str, Any]:
        seen["message"] = message
        seen["members"] = members
        return {
            "ok": True,
            "count": len(members),
            "spoke": len(members),
            "capacity": {
                "schema": "octopus.group_fanout_capacity.v1",
                "requested_members": len(members),
                "dispatched_members": len(members),
                "dropped_members": 0,
                "max_members": _kwargs.get("max_members"),
                "concurrency": len(members),
                "capacity_tier": "room_scale",
            },
            "arbitration": {
                "schema": "octopus.group_fanout_arbitration.v1",
                "primary_agent_id": members[0]["name"],
                "primary_response_id": "resp-1",
                "recommended_next_action": "use_primary_and_retry_failed_members",
                "answered_agent_ids": [member["name"] for member in members],
                "failed_agent_ids": ["qa-agent"],
                "empty_agent_ids": [],
                "ranking": [],
                "outcomes": [],
            },
            "synthesis": {
                "schema": "octopus.group_fanout_synthesis.v1",
                "primary_agent_id": members[0]["name"],
                "primary_reply": f"{members[0]['name']} replied",
                "supporting_agent_ids": [members[1]["name"]],
                "retry_agent_ids": ["qa-agent"],
                "answered_count": len(members),
                "total_count": len(members),
                "recommended_next_action": "use_primary_and_retry_failed_members",
                "ready": True,
            },
            "replies": [
                {
                    "agent_id": member["name"],
                    "display_name": member["display_name"],
                    "ok": True,
                    "reply": f"{member['name']} replied",
                }
                for member in members
            ],
        }

    monkeypatch.setattr(
        "runtime.execution.agents.group_fanout.run_group_fanout",
        fake_fanout,
    )
    _set_script(
        [
            {"type": "text_delta", "delta": "react should not run"},
            {"type": "react_completed"},
        ]
    )
    runtime = CerebrumRuntime(
        stack=object(),
        agent=object(),
        logs_root=str(tmp_path / "threads"),
        cowork_group_store=store,
    )
    gateway = RealtimeGateway(runtime=runtime, approval_timeout=5.0)
    app = FastAPI()
    app.include_router(gateway.router)

    with TestClient(app) as client, client.websocket_connect("/api/realtime") as ws:
        out = _drive(
            ws,
            {
                "threadId": "th-cowork",
                "input": [{"type": "text", "text": "大家一起看下"}],
                "approvalPolicy": "never",
            },
        )

    assert seen["message"] == "大家一起看下"
    assert [m["name"] for m in seen["members"]] == ["db-agent", "ui-agent"]
    turn = out["response"].result["turn"]
    team_items = [
        item
        for item in turn["items"]
        if item["type"] == "mcpToolCall" and item["tool"] == "team_swarm"
    ]
    assert len(team_items) == 1
    assert team_items[0]["status"] == "completed"
    assert team_items[0]["arguments"]["schema"] == "octopus.group_fanout_run.v1"
    assert team_items[0]["arguments"]["capacity"]["schema"] == ("octopus.group_fanout_capacity.v1")
    assert team_items[0]["result"]["schema"] == "octopus.group_fanout_result.v1"
    assert team_items[0]["result"]["capacity"]["requested_members"] == 2
    assert team_items[0]["result"]["capacity"]["dispatched_members"] == 2
    subagent_items = [
        item
        for item in turn["items"]
        if item["type"] == "subagent" and item.get("parentItemId") == team_items[0]["id"]
    ]
    assert {item["subagentId"] for item in subagent_items} == {"db-agent", "ui-agent"}
    assert all(item["status"] == "completed" for item in subagent_items)
    agent_texts = [item["text"] for item in turn["items"] if item["type"] == "agentMessage"]
    assert "db-agent replied" in agent_texts
    assert "ui-agent replied" in agent_texts
    summary_text = next(text for text in agent_texts if text.startswith("协作汇总:"))
    assert "采纳主视角，同时补看失败成员" in summary_text
    assert "use_primary_and_retry_failed_members" not in summary_text
    assert "react should not run" not in agent_texts
    audit_items = [
        item
        for item in turn["items"]
        if item["type"] == "reasoning"
        and "octopus.group_fanout_audit.v1" in item.get("content", "")
    ]
    assert len(audit_items) == 1
    assert "use_primary_and_retry_failed_members" in audit_items[0]["content"]
    assert "octopus.group_fanout_capacity.v1" in audit_items[0]["content"]


def test_cowork_swarm_failure_reports_group_fanout_driver(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from runtime.memory.cowork.group_store import GroupStore
    from runtime.memory.cowork.service import invite_member, set_mode
    from runtime.sensing.gateway.realtime_cerebrum import CerebrumRuntime
    from runtime.sensing.gateway.realtime_gateway import RealtimeGateway

    store = GroupStore(base_dir=tmp_path / "cowork")
    invite_member(store, "th-cowork-fail", actor="u", target_id="db-agent", kind="agent")
    invite_member(store, "th-cowork-fail", actor="u", target_id="ui-agent", kind="agent")
    set_mode(store, "th-cowork-fail", actor="u", mode="swarm")

    def fail_fanout(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("fanout exploded")

    monkeypatch.setattr(
        "runtime.execution.agents.group_fanout.run_group_fanout",
        fail_fanout,
    )
    _set_script(
        [
            {"type": "text_delta", "delta": "fallback react"},
            {"type": "react_completed"},
        ]
    )
    runtime = CerebrumRuntime(
        stack=object(),
        agent=object(),
        logs_root=str(tmp_path / "threads"),
        cowork_group_store=store,
    )
    gateway = RealtimeGateway(runtime=runtime, approval_timeout=5.0)
    app = FastAPI()
    app.include_router(gateway.router)

    with TestClient(app) as client, client.websocket_connect("/api/realtime") as ws:
        out = _drive(
            ws,
            {
                "threadId": "th-cowork-fail",
                "input": [{"type": "text", "text": "大家一起看下"}],
                "approvalPolicy": "never",
            },
        )

    turn = out["response"].result["turn"]
    assert turn["status"] == "completed"
    agent_texts = [item["text"] for item in turn["items"] if item["type"] == "agentMessage"]
    assert agent_texts[-1] == "fallback react"
    audit_items = [
        item
        for item in turn["items"]
        if item["type"] == "reasoning"
        and "octopus.group_fanout_fallback.v1" in item.get("content", "")
    ]
    assert len(audit_items) == 1
    audit = json.loads(audit_items[0]["content"])
    assert audit["reason"] == "exception"
    assert audit["exception_type"] == "RuntimeError"
    assert audit["fallback"] == "react"


def test_cowork_project_mode_runs_project_os(
    tmp_path: Path,
) -> None:
    from runtime.memory.cowork.group_store import GroupStore
    from runtime.memory.cowork.service import invite_member, set_mode
    from runtime.projectos.store import ProjectStore
    from runtime.sensing.gateway.realtime_cerebrum import CerebrumRuntime
    from runtime.sensing.gateway.realtime_gateway import RealtimeGateway

    store = GroupStore(base_dir=tmp_path / "cowork")
    invite_member(store, "th-project", actor="u", target_id="research-agent", kind="agent")
    invite_member(store, "th-project", actor="u", target_id="build-agent", kind="agent")
    set_mode(store, "th-project", actor="u", mode="project")
    project_store = ProjectStore(base_dir=tmp_path / "projectos")
    _set_script(
        [
            {"type": "text_delta", "delta": "react should not run"},
            {"type": "react_completed"},
        ]
    )
    runtime = CerebrumRuntime(
        stack=object(),
        agent=object(),
        logs_root=str(tmp_path / "threads"),
        cowork_group_store=store,
        project_store=project_store,
    )
    gateway = RealtimeGateway(runtime=runtime, approval_timeout=5.0)
    app = FastAPI()
    app.include_router(gateway.router)

    with TestClient(app) as client, client.websocket_connect("/api/realtime") as ws:
        out = _drive(
            ws,
            {
                "threadId": "th-project",
                "input": [{"type": "text", "text": "交付一个研究到实现的项目"}],
                "approvalPolicy": "never",
            },
        )

    turn = out["response"].result["turn"]
    agent_texts = [item["text"] for item in turn["items"] if item["type"] == "agentMessage"]
    assert len(agent_texts) == 1
    assert "Project OS 已接管并运行项目" in agent_texts[0]
    assert "react should not run" not in agent_texts[0]
    todo_items = [item for item in turn["items"] if item["type"] == "todo-list"]
    assert len(todo_items) == 1
    assert todo_items[0]["explanation"].startswith("Project OS")
    assert all(entry["status"] == "completed" for entry in todo_items[0]["plan"])
    trace_items = [
        item
        for item in turn["items"]
        if item["type"] == "reasoning"
        and "octopus.projectos.run_trace.v1" in item.get("content", "")
    ]
    assert len(trace_items) == 1
    trace = json.loads(trace_items[0]["content"])
    assert trace["schema"] == "octopus.projectos.run_trace.v1"
    assert trace["tick_events"]
    projects = project_store.list_projects()
    assert len(projects) == 1
    project = projects[0]
    assert project.status == "done"
    assigned = {
        task.assigned_agent
        for milestone in project_store.milestones_for(project.id)
        for task in project_store.tasks_for_milestone(milestone.id)
    }
    assert assigned <= {"research-agent", "build-agent"}
    assert assigned


def test_cowork_project_mode_unhandled_failure_reports_driver_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from runtime.memory.cowork.group_store import GroupStore
    from runtime.memory.cowork.service import invite_member, set_mode
    from runtime.projectos.store import ProjectStore
    from runtime.sensing.gateway.realtime_cerebrum import CerebrumRuntime
    from runtime.sensing.gateway.realtime_gateway import RealtimeGateway

    store = GroupStore(base_dir=tmp_path / "cowork")
    invite_member(store, "th-project-fail", actor="u", target_id="research-agent", kind="agent")
    set_mode(store, "th-project-fail", actor="u", mode="project")

    def fail_project(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("project engine exploded")

    monkeypatch.setattr(
        "runtime.projectos.cowork_bridge.run_project_from_group",
        fail_project,
    )
    runtime = CerebrumRuntime(
        stack=object(),
        agent=object(),
        logs_root=str(tmp_path / "threads"),
        cowork_group_store=store,
        project_store=ProjectStore(base_dir=tmp_path / "projectos"),
    )
    gateway = RealtimeGateway(runtime=runtime, approval_timeout=5.0)
    app = FastAPI()
    app.include_router(gateway.router)

    with TestClient(app) as client, client.websocket_connect("/api/realtime") as ws:
        out = _drive(
            ws,
            {
                "threadId": "th-project-fail",
                "input": [{"type": "text", "text": "启动项目"}],
                "approvalPolicy": "never",
            },
        )

    turn = out["response"].result["turn"]
    assert turn["status"] == "failed"
    errors = [item for item in turn["items"] if item["type"] == "error"]
    assert errors[-1]["message"] == "project engine exploded"
    assert errors[-1]["errorInfo"]["code"] == "turn_driver_exception"
    assert errors[-1]["errorInfo"]["driver"] == "project_os"
    assert errors[-1]["errorInfo"]["cowork_mode"] == "project"


def test_cowork_project_mode_reuses_active_project(
    tmp_path: Path,
) -> None:
    from runtime.memory.cowork.group_store import GroupStore
    from runtime.memory.cowork.service import invite_member, set_mode
    from runtime.projectos.store import ProjectStore
    from runtime.sensing.gateway.realtime_cerebrum import CerebrumRuntime
    from runtime.sensing.gateway.realtime_gateway import RealtimeGateway

    store = GroupStore(base_dir=tmp_path / "cowork")
    invite_member(store, "th-project", actor="u", target_id="research-agent", kind="agent")
    invite_member(store, "th-project", actor="u", target_id="build-agent", kind="agent")
    set_mode(store, "th-project", actor="u", mode="project")
    project_store = ProjectStore(base_dir=tmp_path / "projectos")
    runtime = CerebrumRuntime(
        stack=object(),
        agent=object(),
        logs_root=str(tmp_path / "threads"),
        cowork_group_store=store,
        project_store=project_store,
    )
    gateway = RealtimeGateway(runtime=runtime, approval_timeout=5.0)
    app = FastAPI()
    app.include_router(gateway.router)

    with TestClient(app) as client, client.websocket_connect("/api/realtime") as ws:
        first = _drive(
            ws,
            {
                "threadId": "th-project",
                "input": [
                    {
                        "type": "text",
                        "text": "启动项目",
                        "metadata": {"context": {"project_os_max_ticks": 1}},
                    }
                ],
                "approvalPolicy": "never",
            },
        )
        first_project_id = project_store.project_for_thread("th-project").id
        assert project_store.get_project(first_project_id).status == "running"

        second = _drive(
            ws,
            {
                "threadId": "th-project",
                "input": [{"type": "text", "text": "继续"}],
                "approvalPolicy": "never",
            },
        )

    assert len(project_store.list_projects()) == 1
    assert project_store.project_for_thread("th-project").id == first_project_id
    first_text = "\n".join(
        item["text"]
        for item in first["response"].result["turn"]["items"]
        if item["type"] == "agentMessage"
    )
    second_text = "\n".join(
        item["text"]
        for item in second["response"].result["turn"]["items"]
        if item["type"] == "agentMessage"
    )
    first_todos = [
        item for item in first["response"].result["turn"]["items"] if item["type"] == "todo-list"
    ]
    second_todos = [
        item for item in second["response"].result["turn"]["items"] if item["type"] == "todo-list"
    ]
    second_trace_items = [
        item
        for item in second["response"].result["turn"]["items"]
        if item["type"] == "reasoning"
        and "octopus.projectos.run_trace.v1" in item.get("content", "")
    ]
    assert "Project OS 已接管并运行项目" in first_text
    assert "Project OS 已继续推进项目" in second_text
    assert first_todos
    assert any(entry["status"] == "in_progress" for entry in first_todos[-1]["plan"])
    assert second_todos
    assert all(entry["status"] == "completed" for entry in second_todos[-1]["plan"])
    assert second_trace_items
    second_trace = json.loads(second_trace_items[-1]["content"])
    assert second_trace["reused"] is True
    assert second_trace["project_id"] == first_project_id


def test_project_os_blocked_result_does_not_claim_auto_continue() -> None:
    from runtime.sensing.gateway.realtime_cerebrum import _format_project_os_result

    text = _format_project_os_result(
        {
            "project": {
                "id": "P-blocked",
                "name": "blocked project",
                "status": "blocked",
            },
            "result": {"final_status": "blocked", "ticks": 2},
            "milestones": [
                {"id": "MS1", "name": "build", "status": "blocked"},
            ],
            "tasks": {
                "MS1": [
                    {
                        "id": "MS1-T1",
                        "status": "failed",
                        "assigned_agent": "coder",
                    }
                ]
            },
            "roster": ["coder"],
        }
    )

    assert "状态：blocked" in text
    assert "项目已阻塞" in text
    assert "后续回合会继续" not in text
    # 对话框交互引导：阻塞项目提示可用命令（恢复/PM 驾驶舱/复盘）。
    assert "下一步可输入" in text
    assert "/project recover（恢复项目）" in text
    assert "/project report（PM 驾驶舱）" in text


def test_project_os_control_parser() -> None:
    from runtime.sensing.gateway.realtime_cerebrum import _parse_project_os_control

    assert _parse_project_os_control("hello") is None
    assert _parse_project_os_control("/project recover tasks=MS1-T1,MS1-T2 run") == {
        "type": "recover",
        "task_ids": ["MS1-T1", "MS1-T2"],
        "run": True,
    }
    assert _parse_project_os_control(
        "/project task MS1-T1 reassign agent=build-agent reason=handoff run"
    ) == {
        "type": "task",
        "task_id": "MS1-T1",
        "action": "reassign",
        "assigned_agent": "build-agent",
        "assigned_role": None,
        "reason": "handoff",
        "output": None,
        "run": True,
        "cascade": True,
    }
    assert _parse_project_os_control(
        '/project task MS1-T1 complete output="manual result" reason="manual review"'
    ) == {
        "type": "task",
        "task_id": "MS1-T1",
        "action": "complete",
        "assigned_agent": None,
        "assigned_role": None,
        "reason": "manual review",
        "output": "manual result",
        "run": False,
        "cascade": True,
    }


def test_cowork_project_mode_accepts_task_control_command(
    tmp_path: Path,
) -> None:
    from runtime.memory.cowork.group_store import GroupStore
    from runtime.memory.cowork.service import invite_member, set_mode
    from runtime.projectos.store import ProjectStore
    from runtime.sensing.gateway.realtime_cerebrum import CerebrumRuntime
    from runtime.sensing.gateway.realtime_gateway import RealtimeGateway

    store = GroupStore(base_dir=tmp_path / "cowork")
    invite_member(store, "th-project-control", actor="u", target_id="research-agent", kind="agent")
    invite_member(store, "th-project-control", actor="u", target_id="build-agent", kind="agent")
    set_mode(store, "th-project-control", actor="u", mode="project")
    project_store = ProjectStore(base_dir=tmp_path / "projectos")
    runtime = CerebrumRuntime(
        stack=object(),
        agent=object(),
        logs_root=str(tmp_path / "threads"),
        cowork_group_store=store,
        project_store=project_store,
    )
    gateway = RealtimeGateway(runtime=runtime, approval_timeout=5.0)
    app = FastAPI()
    app.include_router(gateway.router)

    with TestClient(app) as client, client.websocket_connect("/api/realtime") as ws:
        _drive(
            ws,
            {
                "threadId": "th-project-control",
                "input": [
                    {
                        "type": "text",
                        "text": "启动项目",
                        "metadata": {"context": {"project_os_max_ticks": 1}},
                    }
                ],
                "approvalPolicy": "never",
            },
        )
        project_id = project_store.project_for_thread("th-project-control").id
        out = _drive(
            ws,
            {
                "threadId": "th-project-control",
                "input": [
                    {
                        "type": "text",
                        "text": "/project task MS1-T1 reassign agent=build-agent run",
                    }
                ],
                "approvalPolicy": "never",
            },
        )

    task = project_store.get_task("MS1-T1")
    assert task.assigned_agent == "build-agent"
    assert task.status == "done"
    events = project_store.events_for_project(project_id)
    kinds = [event["kind"] for event in events]
    # "reassign … run" audits chronologically: the intervention first,
    # then the trailing run requested by the same command.
    intervention_idx = max(i for i, kind in enumerate(kinds) if kind == "task.intervention")
    assert events[intervention_idx]["payload"]["action"] == "reassign"
    assert "project.run" in kinds[intervention_idx + 1 :]

    turn = out["response"].result["turn"]
    agent_text = "\n".join(item["text"] for item in turn["items"] if item["type"] == "agentMessage")
    assert "Project OS 已执行控制命令" in agent_text
    trace_items = [
        item
        for item in turn["items"]
        if item["type"] == "reasoning"
        and "octopus.projectos.control_trace.v1" in item.get("content", "")
    ]
    assert trace_items
    trace = json.loads(trace_items[-1]["content"])
    assert trace["control"]["action"] == "reassign"
    assert trace["available_actions"] == ["inspect", "report"]
    assert trace["action_specs"][0]["action"] == "inspect"
    assert "task.intervention" in [e["kind"] for e in trace["audit_events"]]


def test_cowork_project_mode_reports_failed_task_control_command(
    tmp_path: Path,
) -> None:
    from runtime.memory.cowork.group_store import GroupStore
    from runtime.memory.cowork.service import invite_member, set_mode
    from runtime.projectos.store import ProjectStore
    from runtime.sensing.gateway.realtime_cerebrum import CerebrumRuntime
    from runtime.sensing.gateway.realtime_gateway import RealtimeGateway

    store = GroupStore(base_dir=tmp_path / "cowork")
    invite_member(store, "th-project-control-fail", actor="u", target_id="agent-a", kind="agent")
    set_mode(store, "th-project-control-fail", actor="u", mode="project")
    project_store = ProjectStore(base_dir=tmp_path / "projectos")
    runtime = CerebrumRuntime(
        stack=object(),
        agent=object(),
        logs_root=str(tmp_path / "threads"),
        cowork_group_store=store,
        project_store=project_store,
    )
    gateway = RealtimeGateway(runtime=runtime, approval_timeout=5.0)
    app = FastAPI()
    app.include_router(gateway.router)

    with TestClient(app) as client, client.websocket_connect("/api/realtime") as ws:
        _drive(
            ws,
            {
                "threadId": "th-project-control-fail",
                "input": [
                    {
                        "type": "text",
                        "text": "启动项目",
                        "metadata": {"context": {"project_os_max_ticks": 1}},
                    }
                ],
                "approvalPolicy": "never",
            },
        )
        project_id = project_store.project_for_thread("th-project-control-fail").id
        out = _drive(
            ws,
            {
                "threadId": "th-project-control-fail",
                "input": [{"type": "text", "text": "/project task MS1-T1 teleport"}],
                "approvalPolicy": "never",
            },
        )

    events = project_store.events_for_project(project_id)
    assert events[-1]["kind"] == "task.intervention_rejected"
    turn = out["response"].result["turn"]
    agent_text = "\n".join(item["text"] for item in turn["items"] if item["type"] == "agentMessage")
    assert "Project OS 任务控制命令未执行" in agent_text
    assert "unknown_task_action:teleport" in agent_text
    assert not [
        item
        for item in turn["items"]
        if item["type"] == "reasoning"
        and "octopus.projectos.control_trace.v1" in item.get("content", "")
    ]


def test_blocked_topology_id_falls_back_to_react(
    gateway: Any,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from runtime.safety.evolution.subagent_policy import SubagentPolicyStore
    from runtime.safety.organization import (
        AgentSpec,
        CoordinationProtocol,
        Role,
        TeamTopology,
    )

    client, _ = gateway
    data_dir = tmp_path / "data"
    data_dir.mkdir(exist_ok=True)
    monkeypatch.setenv("OCTOPUS_DATA_DIR", str(data_dir))
    SubagentPolicyStore(data_dir / "subagent_policy.json").decide(
        "planner_a",
        action="retire",
        reason="operator retired planner_a",
        actor="operator-test",
    )
    topology = TeamTopology(
        name="test_topology",
        protocol=CoordinationProtocol.SEQUENTIAL,
        agents={Role.PLANNER: AgentSpec(agent_id="planner_a")},
    )
    called = {"team_runner": False}

    class FakeTeamRunner:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def run(self, *args: Any, **kwargs: Any) -> Any:
            called["team_runner"] = True
            raise AssertionError("blocked topology should not enter TeamRunner")

    monkeypatch.setattr(
        "runtime.safety.organization.forge.load_registry",
        lambda: {"test_topology": topology},
    )
    monkeypatch.setattr(
        "runtime.safety.organization.team_runner.TeamRunner",
        FakeTeamRunner,
    )
    _set_script(
        [
            {"type": "text_delta", "delta": "fallback react"},
            {"type": "react_completed"},
        ]
    )

    with client.websocket_connect("/api/realtime") as ws:
        out = _drive(
            ws,
            {
                "threadId": "th-blocked-topology",
                "input": [{"type": "text", "text": "run blocked topology"}],
                "approvalPolicy": "never",
                "topologyId": "test_topology",
            },
        )

    assert called["team_runner"] is False
    turn = out["response"].result["turn"]
    agent_items = [it for it in turn["items"] if it["type"] == "agentMessage"]
    assert agent_items[-1]["text"] == "fallback react"
    audit = json.loads((data_dir / "promotion_audit.json").read_text(encoding="utf-8"))
    assert audit["records"][0]["event_type"] == "topology_policy_block"
    assert audit["records"][0]["target"] == "topology_policy"
    assert audit["records"][0]["status"] == "blocked"
    assert audit["records"][0]["artifact"]["topology_id"] == "test_topology"
    assert audit["records"][0]["decision_context"]["turn_id"] == turn["id"]


def test_background_tool_item_completes_after_turn_response(gateway: Any) -> None:
    import sys
    import time

    from runtime.execution.suckers.write_skills import _background_exec
    from runtime.memory.threads.event_log import EventLog
    from runtime.protocol.items import ItemStatus

    client, logs_dir = gateway
    started = _background_exec(
        command=[
            sys.executable,
            "-c",
            (
                "import time; "
                "print('bg-ready', flush=True); "
                "time.sleep(1.0); "
                "print('bg-done', flush=True)"
            ),
        ],
    )
    task_id = started["task_id"]
    _set_script(
        [
            {
                "type": "tool_start",
                "tool_name": "background_exec",
                "tool_call_id": "c_bg",
                "iteration": 1,
                "input_preview": {"command": "python -c ..."},
            },
            {
                "type": "tool_background",
                "tool_name": "background_exec",
                "tool_call_id": "c_bg",
                "iteration": 1,
                "task_id": task_id,
                "snapshot": started,
                "duration_ms": 1,
            },
            {"type": "react_completed"},
        ]
    )

    with client.websocket_connect("/api/realtime") as ws:
        out = _drive(
            ws,
            {
                "threadId": "th-bg",
                "input": [{"type": "text", "text": "start bg"}],
                "approvalPolicy": "never",
            },
        )

        turn = out["response"].result["turn"]
        cmd_items = [it for it in turn["items"] if it["type"] == "commandExecution"]
        assert len(cmd_items) == 1
        assert cmd_items[0]["status"] == "inProgress"
        assert cmd_items[0]["inputPreview"]["background"] is True
        assert cmd_items[0]["inputPreview"]["task_id"] == task_id

        log = EventLog(logs_dir / "th-bg.jsonl")
        deadline = time.time() + 3.0
        final_item: Any | None = None
        while time.time() < deadline:
            turns = log.replay()
            items = [
                it
                for turn_obj in turns
                for it in turn_obj.items
                if getattr(it, "id", None) == "c_bg"
            ]
            if items and getattr(items[-1], "status", None) == ItemStatus.COMPLETED:
                final_item = items[-1]
                break
            time.sleep(0.05)

    assert final_item is not None
    assert "bg-ready" in final_item.aggregated_output
    assert "bg-done" in final_item.aggregated_output


def test_stale_background_watchers_reaped_on_next_turn(tmp_path: Path) -> None:
    """Watchers from a previous turn must be cancelled when a new
    turn starts on the same thread, otherwise long-running shells
    keep streaming output into the prior conversation while the
    user is on a new topic."""
    import sys
    import time

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from runtime.execution.suckers.write_skills import _background_exec
    from runtime.sensing.gateway.realtime_cerebrum import CerebrumRuntime
    from runtime.sensing.gateway.realtime_gateway import RealtimeGateway

    runtime = CerebrumRuntime(
        stack=object(),
        agent=object(),
        logs_root=str(tmp_path / "threads"),
    )
    rt_gateway = RealtimeGateway(runtime=runtime, approval_timeout=5.0)
    app = FastAPI()
    app.include_router(rt_gateway.router)

    started = _background_exec(
        command=[
            sys.executable,
            "-c",
            "import time; print('boot', flush=True); time.sleep(30.0)",
        ],
    )
    task_id = started["task_id"]
    _set_script(
        [
            {
                "type": "tool_start",
                "tool_name": "background_exec",
                "tool_call_id": "c_bg2",
                "iteration": 1,
                "input_preview": {"command": "python -c ..."},
            },
            {
                "type": "tool_background",
                "tool_name": "background_exec",
                "tool_call_id": "c_bg2",
                "iteration": 1,
                "task_id": task_id,
                "snapshot": started,
                "duration_ms": 1,
            },
            {"type": "react_completed"},
        ]
    )

    with TestClient(app) as client, client.websocket_connect("/api/realtime") as ws:
        _drive(
            ws,
            {
                "threadId": "th-reap",
                "input": [{"type": "text", "text": "first"}],
                "approvalPolicy": "never",
            },
        )
        bucket = runtime._thread_background_tasks.get("th-reap")
        assert bucket and any(not t.done() for t in bucket), (
            "expected at least one running watcher after first turn"
        )

        # Second turn — reaper at start_turn entry must cancel the
        # leftover watcher before the new turn proceeds.
        _set_script(
            [
                {"type": "text_delta", "delta": "second"},
                {"type": "react_completed"},
            ]
        )
        _drive(
            ws,
            {
                "threadId": "th-reap",
                "input": [{"type": "text", "text": "second"}],
                "approvalPolicy": "never",
            },
        )

        # Reap is awaited inside ``start_turn`` so the bucket
        # should be empty (or all done) by the time the second
        # turn returns. Allow a tiny grace window for done-callbacks.
        deadline = time.time() + 1.0
        while time.time() < deadline:
            bucket = runtime._thread_background_tasks.get("th-reap") or []
            if all(t.done() for t in bucket):
                break
            time.sleep(0.05)
        bucket = runtime._thread_background_tasks.get("th-reap") or []
        assert all(t.done() for t in bucket), (
            "reaper failed to cancel stale watchers from prior turn"
        )


def test_simple_question_uses_reflection_fast_path(tmp_path: Path) -> None:
    from fastapi import FastAPI

    from runtime.sensing.gateway.realtime_cerebrum import CerebrumRuntime
    from runtime.sensing.gateway.realtime_gateway import RealtimeGateway
    from runtime.sensing.model_router.models import ModelResponse, ModelStreamEvent

    class FakeRouter:
        def __init__(self) -> None:
            self.calls = 0

        def call_stream(self, _request: Any) -> Iterator[ModelStreamEvent]:
            self.calls += 1
            yield ModelStreamEvent(type="thinking_delta", delta="quick reflection")
            yield ModelStreamEvent(type="text_delta", delta="4")
            yield ModelStreamEvent(
                type="done",
                final=ModelResponse(text="4", thinking="quick reflection"),
            )

    class FakePlanner:
        planner_model = "fake"

        def __init__(self, router: FakeRouter) -> None:
            self.router = router

    class FakeStack:
        def __init__(self, router: FakeRouter) -> None:
            self.planner = FakePlanner(router)
            self.journal = None

    router = FakeRouter()
    runtime = CerebrumRuntime(
        stack=FakeStack(router),
        agent=None,
        logs_root=str(tmp_path / "threads"),
    )
    gateway = RealtimeGateway(runtime=runtime, approval_timeout=5.0)
    app = FastAPI()
    app.include_router(gateway.router)

    _set_script(
        [
            {"type": "tool_start", "tool_name": "list_cwd", "tool_call_id": "should-not-run"},
            {"type": "react_completed"},
        ]
    )
    with TestClient(app) as client, client.websocket_connect("/api/realtime") as ws:
        out = _drive(
            ws,
            {
                "threadId": "th-fast",
                "input": [{"type": "text", "text": "2+2等于几？"}],
                "approvalPolicy": "never",
                "model": "fake",
            },
        )

    assert router.calls == 1
    turn = out["response"].result["turn"]
    # Thinking is now surfaced as a ReasoningItem (streaming-UX work);
    # the fast path itself is unchanged — one router call, no tools.
    item_types = [it["type"] for it in turn["items"]]
    assert item_types[0] == "userMessage"
    assert item_types[-1] == "agentMessage"
    assert "reasoning" in item_types
    assert turn["items"][-1]["text"] == "4"


def test_chat_mode_tool_intent_bypasses_reflection_fast_path(tmp_path: Path) -> None:
    from runtime.protocol.items import TurnParams
    from runtime.sensing.gateway.realtime_cerebrum import CerebrumRuntime

    class FakePlanner:
        router = object()

    class FakeStack:
        planner = FakePlanner()

    runtime = CerebrumRuntime(
        stack=FakeStack(),
        agent=None,
        logs_root=str(tmp_path / "threads"),
    )
    params = TurnParams.model_validate(
        {
            "threadId": "th-inspiration-tool",
            "input": [
                {
                    "type": "text",
                    "text": "搜索一下 OpenClaw 的官方仓库",
                    "metadata": {"context": {"mode": "chat"}},
                },
            ],
            "approvalPolicy": "never",
        }
    )

    assert (
        runtime._should_use_reflection_fast_path(
            "搜索一下 OpenClaw 的官方仓库",
            params,
        )
        is False
    )


def test_react_mode_ambiguous_topic_bypasses_reflection_fast_path(tmp_path: Path) -> None:
    from runtime.protocol.items import TurnParams
    from runtime.sensing.gateway.realtime_cerebrum import CerebrumRuntime

    class FakePlanner:
        router = object()

    class FakeStack:
        planner = FakePlanner()

    runtime = CerebrumRuntime(
        stack=FakeStack(),
        agent=None,
        logs_root=str(tmp_path / "threads"),
    )
    params = TurnParams.model_validate(
        {
            "threadId": "th-react-topic",
            "input": [
                {
                    "type": "text",
                    "text": "AI 家庭机器人（扫地/陪伴/安防）",
                    "metadata": {"context": {"mode": "react"}},
                },
            ],
            "approvalPolicy": "never",
        }
    )

    assert (
        runtime._should_use_reflection_fast_path(
            "AI 家庭机器人（扫地/陪伴/安防）",
            params,
        )
        is False
    )


def test_default_mode_ambiguous_topic_bypasses_reflection_fast_path(tmp_path: Path) -> None:
    from runtime.protocol.items import TurnParams
    from runtime.sensing.gateway.realtime_cerebrum import CerebrumRuntime

    class FakePlanner:
        router = object()

    class FakeStack:
        planner = FakePlanner()

    runtime = CerebrumRuntime(
        stack=FakeStack(),
        agent=None,
        logs_root=str(tmp_path / "threads"),
    )
    params = TurnParams.model_validate(
        {
            "threadId": "th-default-topic",
            "input": [{"type": "text", "text": "AI 家庭机器人（扫地/陪伴/安防）"}],
            "approvalPolicy": "never",
        }
    )

    assert (
        runtime._should_use_reflection_fast_path(
            "AI 家庭机器人（扫地/陪伴/安防）",
            params,
        )
        is False
    )


def test_react_mode_contextual_confirm_bypasses_reflection_fast_path(
    tmp_path: Path,
) -> None:
    from runtime.protocol.items import TurnParams
    from runtime.sensing.gateway.realtime_cerebrum import CerebrumRuntime

    class FakePlanner:
        router = object()

    class FakeStack:
        planner = FakePlanner()

    runtime = CerebrumRuntime(
        stack=FakeStack(),
        agent=None,
        logs_root=str(tmp_path / "threads"),
    )
    params = TurnParams.model_validate(
        {
            "threadId": "th-react-confirm",
            "input": [
                {
                    "type": "text",
                    "text": "好",
                    "metadata": {"context": {"mode": "react"}},
                },
            ],
            "approvalPolicy": "never",
        }
    )

    assert (
        runtime._should_use_reflection_fast_path(
            "好",
            params,
            conversation_messages=[
                {
                    "role": "assistant",
                    "content": "选定后我可以直接启动 deep research。",
                },
            ],
        )
        is False
    )


def test_react_mode_contextual_research_topic_bypasses_reflection_fast_path(
    tmp_path: Path,
) -> None:
    from runtime.protocol.items import TurnParams
    from runtime.sensing.gateway.realtime_cerebrum import CerebrumRuntime

    class FakePlanner:
        router = object()

    class FakeStack:
        planner = FakePlanner()

    runtime = CerebrumRuntime(
        stack=FakeStack(),
        agent=None,
        logs_root=str(tmp_path / "threads"),
    )
    params = TurnParams.model_validate(
        {
            "threadId": "th-react-research-topic",
            "input": [
                {
                    "type": "text",
                    "text": "AI应用",
                    "metadata": {"context": {"mode": "react"}},
                },
            ],
            "approvalPolicy": "never",
        }
    )

    assert (
        runtime._should_use_reflection_fast_path(
            "AI应用",
            params,
            conversation_messages=[
                {
                    "role": "assistant",
                    "content": (
                        "这个方向很宽泛，我需要一个聚焦点才能给出有价值的调研。\n\n"
                        "给我一个大致方向，我马上开始调研。"
                    ),
                },
            ],
        )
        is False
    )


def test_react_mode_simple_question_still_uses_reflection_fast_path(
    tmp_path: Path,
) -> None:
    from runtime.protocol.items import TurnParams
    from runtime.sensing.gateway.realtime_cerebrum import CerebrumRuntime

    class FakePlanner:
        router = object()

    class FakeStack:
        planner = FakePlanner()

    runtime = CerebrumRuntime(
        stack=FakeStack(),
        agent=None,
        logs_root=str(tmp_path / "threads"),
    )
    params = TurnParams.model_validate(
        {
            "threadId": "th-react-qa",
            "input": [
                {
                    "type": "text",
                    "text": "2+2等于几？",
                    "metadata": {"context": {"mode": "react"}},
                },
            ],
            "approvalPolicy": "never",
        }
    )

    assert runtime._should_use_reflection_fast_path("2+2等于几？", params) is True


def test_react_mode_explicit_no_tool_reply_uses_reflection_fast_path(
    tmp_path: Path,
) -> None:
    from runtime.protocol.items import TurnParams
    from runtime.sensing.gateway.realtime_cerebrum import CerebrumRuntime

    class FakePlanner:
        router = object()

    class FakeStack:
        planner = FakePlanner()

    runtime = CerebrumRuntime(
        stack=FakeStack(),
        agent=None,
        logs_root=str(tmp_path / "threads"),
    )
    params = TurnParams.model_validate(
        {
            "threadId": "th-react-no-tools",
            "input": [
                {
                    "type": "text",
                    "text": "普通模式回归：请只用一句话回复收到，不要调用工具。",
                    "metadata": {"context": {"mode": "react"}},
                },
            ],
            "approvalPolicy": "never",
        }
    )

    assert (
        runtime._should_use_reflection_fast_path(
            "普通模式回归：请只用一句话回复收到，不要调用工具。",
            params,
        )
        is True
    )


def test_input_metadata_capability_mode_reaches_react_intent() -> None:
    from runtime.protocol.items import TurnParams
    from runtime.sensing.gateway.realtime_cerebrum import _build_intent

    params = TurnParams.model_validate(
        {
            "threadId": "th-code",
            "input": [
                {
                    "type": "text",
                    "text": "fix the tests",
                    "metadata": {
                        "context": {
                            "mode": "code",
                            "capability_mode": "code",
                            "code_mode": "solo",
                            "permission_mode": "default",
                            "sandbox_mode": "sandbox",
                            "execution_environment": "sandbox",
                        },
                    },
                },
            ],
            "approvalPolicy": "never",
        }
    )

    intent = _build_intent(
        "fix the tests",
        params,
        allow_client_auto_approve=True,
    )

    assert intent.user_context["mode"] == "code"
    assert intent.user_context["capability_mode"] == "code"
    assert intent.user_context["code_mode"] == "solo"
    assert intent.user_context["permission_mode"] == "default"
    assert intent.user_context["sandbox_mode"] == "sandbox"
    assert intent.user_context["auto_approve"] is True


def test_audit_intent_sets_audit_mode_in_user_context() -> None:
    from runtime.protocol.items import TurnParams
    from runtime.sensing.gateway.realtime_cerebrum import _build_intent

    params = TurnParams.model_validate(
        {
            "threadId": "th-audit",
            "input": [
                {
                    "type": "text",
                    "text": "审计项目",
                    "metadata": {
                        "context": {
                            "mode": "code",
                            "workspace_path": "/tmp/repo",
                            "workspace_scope": "project",
                        },
                    },
                },
            ],
            "approvalPolicy": "never",
        }
    )

    intent = _build_intent("审计项目", params, allow_client_auto_approve=True)
    assert intent.user_context.get("audit_mode") is True


def test_non_audit_intent_does_not_set_audit_mode() -> None:
    from runtime.protocol.items import TurnParams
    from runtime.sensing.gateway.realtime_cerebrum import _build_intent

    params = TurnParams.model_validate(
        {
            "threadId": "th-fix",
            "input": [
                {
                    "type": "text",
                    "text": "修复登录页的 bug",
                    "metadata": {
                        "context": {
                            "mode": "code",
                            "workspace_path": "/tmp/repo",
                            "workspace_scope": "project",
                        },
                    },
                },
            ],
            "approvalPolicy": "never",
        }
    )

    intent = _build_intent("修复登录页的 bug", params, allow_client_auto_approve=True)
    assert intent.user_context.get("audit_mode") is None


def test_code_capability_without_project_gets_personal_workspace(tmp_path: Path) -> None:
    from runtime.platform.runtime_policy.workspaces import WorkspaceManager
    from runtime.protocol.items import TurnParams
    from runtime.sensing.gateway.realtime_cerebrum import _build_intent

    params = TurnParams.model_validate(
        {
            "threadId": "th-personal-code",
            "input": [
                {
                    "type": "text",
                    "text": "create a tiny python script",
                    "metadata": {
                        "context": {
                            "mode": "code",
                            "capability_mode": "code",
                            "code_mode": "solo",
                            "personal_workspace_enabled": True,
                        },
                    },
                },
            ],
        }
    )

    intent = _build_intent(
        "create a tiny python script",
        params,
        workspaces=WorkspaceManager(tmp_path / "workspaces"),
    )

    workspace = tmp_path / "workspaces" / "th-personal-code"
    assert intent.user_context["workspace_scope"] == "personal"
    assert intent.user_context["personal_workspace_path"] == str(workspace.resolve())
    assert intent.user_context["cwd"] == str(workspace.resolve())
    assert "workspace_path" not in intent.user_context


def test_attachment_read_root_is_derived_from_thread_workspace(tmp_path: Path) -> None:
    from runtime.platform.runtime_policy.workspaces import WorkspaceManager
    from runtime.protocol.items import TurnParams
    from runtime.sensing.gateway.realtime_cerebrum import _build_intent

    manager = WorkspaceManager(tmp_path / "workspaces")
    params = TurnParams.model_validate(
        {
            "threadId": "th-with-doc",
            "input": [
                {
                    "type": "text",
                    "text": "summarize this deck",
                    "attachments": [
                        {
                            "filename": "deck.pptx",
                            # Deliberately malicious client path: authorization
                            # must still come from WorkspaceManager.
                            "path": "/tmp/not-authoritative/deck.pptx",
                        }
                    ],
                }
            ],
        }
    )

    intent = _build_intent(
        "summarize this deck",
        params,
        workspaces=manager,
    )

    expected = manager.layout("th-with-doc").upload.resolve()
    assert intent.user_context["attachment_read_roots"] == [str(expected)]
    assert intent.user_context["attachments"][0]["path"] == ("/tmp/not-authoritative/deck.pptx")


def test_explicit_turn_cwd_becomes_code_workspace(tmp_path: Path) -> None:
    from runtime.platform.runtime_policy.workspaces import WorkspaceManager
    from runtime.protocol.items import TurnParams
    from runtime.sensing.gateway.realtime_cerebrum import _build_intent

    params = TurnParams.model_validate(
        {
            "threadId": "th-explicit-cwd",
            "cwd": str(tmp_path),
            "input": [{"type": "text", "text": "inspect and fix the project"}],
        }
    )

    intent = _build_intent(
        "inspect and fix the project",
        params,
        workspaces=WorkspaceManager(tmp_path / "managed"),
    )

    assert intent.user_context["cwd"] == str(tmp_path)
    assert intent.user_context["workspace_path"] == str(tmp_path)
    assert intent.user_context["workspace_scope"] == "project"
    assert intent.user_context["mode"] == "code"


def test_explicit_chat_turn_does_not_inherit_personal_code_metadata(tmp_path: Path) -> None:
    from runtime.sensing.gateway.turn_session import build_turn_metadata

    class Store:
        def get(self, thread_id: str) -> dict[str, object]:
            assert thread_id == "th-personal-code"
            return {
                "metadata": {
                    "mode": "code",
                    "capability_mode": "code",
                    "code_mode": "solo",
                    "workspace_scope": "personal",
                    "personal_workspace_enabled": True,
                    "personal_workspace_path": str(tmp_path),
                    "personal_mode": "research",
                    "personal_instructions": "private personal rule",
                    "workflow_preset": "develop.iterate",
                }
            }

    metadata = build_turn_metadata(
        thread_id="th-personal-code",
        body={"context": {"mode": "chat"}},
        store=Store(),
    )

    assert metadata["mode"] == "chat"
    assert "capability_mode" not in metadata
    assert "code_mode" not in metadata
    assert "workspace_scope" not in metadata
    assert "personal_workspace_enabled" not in metadata
    assert "personal_mode" not in metadata
    assert "personal_instructions" not in metadata
    assert "workflow_preset" not in metadata


def test_existing_thread_keeps_its_agent_when_turn_context_disagrees() -> None:
    from runtime.sensing.gateway.turn_session import build_turn_metadata

    class Store:
        def get(self, thread_id: str) -> dict[str, object]:
            assert thread_id == "th-opencode"
            return {"metadata": {"agent": "local_opencode_cli", "mode": "react"}}

    metadata = build_turn_metadata(
        thread_id="th-opencode",
        body={"context": {"agent_name": "general", "mode": "code"}},
        store=Store(),
    )

    assert metadata["agent"] == "local_opencode_cli"
    assert metadata["agent_name"] == "local_opencode_cli"


def test_agent_resolution_prefers_existing_thread_owner() -> None:
    from runtime.protocol.items import TurnParams
    from runtime.sensing.gateway._realtime_cerebrum_thread import _resolve_agent

    owner = object()
    requested = object()

    class Registry:
        agents = {
            "local_opencode_cli": owner,
            "general": requested,
        }

        def has(self, agent_id: str) -> bool:
            return agent_id in self.agents

        def get(self, agent_id: str) -> object:
            return self.agents[agent_id]

    class Store:
        def get(self, thread_id: str) -> dict[str, object]:
            assert thread_id == "th-opencode"
            return {"metadata": {"agent": "local_opencode_cli"}}

    class Runtime:
        _thread_store = Store()
        _agent_registry = Registry()
        _default_agent = object()

    params = TurnParams.model_validate(
        {
            "threadId": "th-opencode",
            "input": [
                {
                    "type": "text",
                    "text": "continue",
                    "metadata": {"context": {"agent_name": "general"}},
                }
            ],
        }
    )

    assert _resolve_agent(Runtime(), params) is owner


def test_turn_metadata_preserves_declared_write_scope(tmp_path: Path) -> None:
    from runtime.sensing.gateway.turn_session import build_turn_metadata

    metadata = build_turn_metadata(
        thread_id="th-declared-write-scope",
        body={
            "context": {
                "mode": "code",
                "workspace_path": str(tmp_path),
                "allowed_write_paths": [" cache.py ", "tests/test_cache.py", ""],
            }
        },
        store=None,
    )

    assert metadata["allowed_write_paths"] == ["cache.py", "tests/test_cache.py"]


def test_turn_metadata_preserves_personal_and_project_workflow_contracts() -> None:
    from runtime.sensing.gateway.turn_session import build_turn_metadata

    metadata = build_turn_metadata(
        thread_id="th-mode-contracts",
        body={
            "context": {
                "mode": "code",
                "personal_mode": "research",
                "personal_instructions": "Prefer primary sources.",
                "workflow_preset": "audit.ultracode",
                "skill_pack_profile": "audit",
                "verification_policy": "strict",
                "default_skill_packs": ["research", "review"],
                "default_plugins": ["browser"],
                "browser_regression_enabled": True,
            }
        },
        store=None,
    )

    assert metadata["personal_mode"] == "research"
    assert metadata["personal_instructions"] == "Prefer primary sources."
    assert metadata["workflow_preset"] == "audit.ultracode"
    assert metadata["skill_pack_profile"] == "audit"
    assert metadata["verification_policy"] == "strict"
    assert metadata["default_skill_packs"] == ["research", "review"]
    assert metadata["default_plugins"] == ["browser"]
    assert metadata["browser_regression_enabled"] is True


def test_tool_question_keeps_react_path_when_router_exists(tmp_path: Path) -> None:
    from fastapi import FastAPI

    from runtime.sensing.gateway.realtime_cerebrum import CerebrumRuntime
    from runtime.sensing.gateway.realtime_gateway import RealtimeGateway
    from runtime.sensing.model_router.models import ModelStreamEvent

    class FakeRouter:
        def __init__(self) -> None:
            self.calls = 0

        def call_stream(self, _request: Any) -> Iterator[ModelStreamEvent]:
            self.calls += 1
            raise AssertionError("tool turns must not use reflection fast path")

    class FakePlanner:
        planner_model = "fake"

        def __init__(self, router: FakeRouter) -> None:
            self.router = router

    class FakeStack:
        def __init__(self, router: FakeRouter) -> None:
            self.planner = FakePlanner(router)
            self.journal = None

    router = FakeRouter()
    runtime = CerebrumRuntime(
        stack=FakeStack(router),
        agent=None,
        logs_root=str(tmp_path / "threads"),
    )
    gateway = RealtimeGateway(runtime=runtime, approval_timeout=5.0)
    app = FastAPI()
    app.include_router(gateway.router)

    _set_script(
        [
            {"type": "tool_start", "tool_name": "list_cwd", "tool_call_id": "call-1"},
            {
                "type": "tool_end",
                "tool_name": "list_cwd",
                "tool_call_id": "call-1",
                "status": "success",
                "output_preview": "ok",
            },
            {"type": "react_completed"},
        ]
    )
    with TestClient(app) as client, client.websocket_connect("/api/realtime") as ws:
        out = _drive(
            ws,
            {
                "threadId": "th-tool-router",
                "input": [{"type": "text", "text": "列一下当前目录"}],
                "approvalPolicy": "never",
            },
        )

    assert router.calls == 0
    assert _LAST_STREAM_KWARGS["max_iterations"] == 30
    turn = out["response"].result["turn"]
    cmd_items = [it for it in turn["items"] if it["type"] == "commandExecution"]
    assert cmd_items[0]["command"] == "list_cwd"


def test_realtime_react_binds_thread_artifact_session(tmp_path: Path) -> None:
    from fastapi import FastAPI

    from runtime.sensing.gateway.realtime_cerebrum import CerebrumRuntime
    from runtime.sensing.gateway.realtime_gateway import RealtimeGateway

    runtime = CerebrumRuntime(
        stack=object(),
        agent=None,
        logs_root=str(tmp_path / "threads"),
        workspace_root=str(tmp_path / "workspaces"),
    )
    gateway = RealtimeGateway(runtime=runtime, approval_timeout=5.0)
    app = FastAPI()
    app.include_router(gateway.router)

    _set_script([{"type": "react_completed"}])
    with TestClient(app) as client, client.websocket_connect("/api/realtime") as ws:
        _drive(
            ws,
            {
                "threadId": "th-artifacts",
                "input": [{"type": "text", "text": "write a report file"}],
                "approvalPolicy": "on-request",
            },
        )

    assert _LAST_SESSION["thread_id"] == "th-artifacts"
    assert Path(_LAST_SESSION["metadata"]["_artifact_output_root"]) == (
        tmp_path / "workspaces" / "th-artifacts" / "output" / "final"
    )


def test_resume_proposal_block_is_parsed_into_sanitized_session_metadata() -> None:
    from runtime.protocol import TurnParams
    from runtime.sensing.gateway.realtime_cerebrum import _build_intent

    resume_text = """
Resume this agent run from the selected durable checkpoint.

<octopus_resume_proposal>
{
  "schema": "octopus.resume_proposal.v1",
  "checkpoint_id": 7,
  "task_id": "task-1",
  "checkpoint_type": "react",
  "iteration": 3,
  "phase": "implementation",
  "progress": "trace store wired",
  "working_set": ["runtime/memory/trace_store.py"],
  "resume_plan": ["Continue from iteration 4."],
  "raw_state_included": false,
  "raw_message_snapshots_included": false,
  "messages_snapshot": ["message body"]
}
</octopus_resume_proposal>
""".strip()
    intent = _build_intent(
        resume_text,
        TurnParams(
            threadId="th-resume-intent",
            input=[{"type": "text", "text": resume_text}],
            approvalPolicy="on-request",
        ),
    )
    resume_intent = intent.user_context["resume_intent"]
    assert resume_intent == {
        "schema": "octopus.resume_intent.v1",
        "requires_confirmation": True,
        "source": "resume_proposal_block",
        "checkpoint_id": 7,
        "task_id": "task-1",
        "checkpoint_type": "react",
        "iteration": 3,
        "continue_from_iteration": 4,
        "phase": "implementation",
        "progress": "trace store wired",
        "working_set": ["runtime/memory/trace_store.py"],
        "resume_plan": ["Continue from iteration 4."],
        "safety": {
            "raw_state_included": False,
            "raw_message_snapshots_included": False,
        },
    }
    assert "messages_snapshot" not in resume_intent
    assert "message body" not in str(resume_intent)


def test_codex_composer_marker_is_stripped_into_intent_metadata() -> None:
    from runtime.protocol import TurnParams
    from runtime.sensing.gateway.realtime_cerebrum import _build_intent

    text = "/codex goal\nFinish the hardening pass"
    intent = _build_intent(
        text,
        TurnParams(
            threadId="th-codex-goal",
            input=[{"type": "text", "text": text}],
            approvalPolicy="on-request",
        ),
    )

    assert intent.raw == "Finish the hardening pass"
    assert intent.normalized_goal == "Finish the hardening pass"
    assert intent.user_context["workflow_mode"] == "goal"
    assert intent.user_context["completion_policy"] == "goal"
    assert intent.user_context["goal_mode"] is True
    assert intent.user_context["mode_preset"] == "goal.mode"
    assert intent.user_context["workflow_preset"] == "goal.mode"


def test_mode_composer_marker_is_stripped_into_intent_metadata() -> None:
    from runtime.protocol import TurnParams
    from runtime.sensing.gateway.realtime_cerebrum import _build_intent

    text = "/mode goal\nFinish the hardening pass"
    intent = _build_intent(
        text,
        TurnParams(
            threadId="th-mode-goal",
            input=[{"type": "text", "text": text}],
            approvalPolicy="on-request",
        ),
    )

    assert intent.raw == "Finish the hardening pass"
    assert intent.normalized_goal == "Finish the hardening pass"
    assert intent.user_context["workflow_mode"] == "goal"
    assert intent.user_context["completion_policy"] == "goal"
    assert intent.user_context["goal_mode"] is True
    assert intent.user_context["mode_preset"] == "goal.mode"
    assert intent.user_context["workflow_preset"] == "goal.mode"


def test_resume_proposal_block_preserves_sanitized_tool_context() -> None:
    from runtime.protocol import TurnParams
    from runtime.sensing.gateway.realtime_cerebrum import _build_intent

    fake_api_key = "sk-kimi-" + ("A" * 32)
    proposal = {
        "schema": "octopus.resume_proposal.v1",
        "checkpoint_id": 8,
        "task_id": "task-tools",
        "checkpoint_type": "react",
        "iteration": 4,
        "phase": "verify",
        "recent_tool_calls": [
            {
                "iteration": 3,
                "tool": "exec_shell",
                "input_preview": f"pytest tests/test_x.py -q --token {fake_api_key}",
                "observation_preview": ("failed for ops@example.com: assertion message body"),
            },
        ],
        "raw_state_included": False,
        "raw_message_snapshots_included": False,
    }
    resume_text = f"""
Resume this agent run from the selected durable checkpoint.

<octopus_resume_proposal>
{json.dumps(proposal, ensure_ascii=False, indent=2)}
</octopus_resume_proposal>
""".strip()
    intent = _build_intent(
        resume_text,
        TurnParams(
            threadId="th-resume-tool-context",
            input=[{"type": "text", "text": resume_text}],
            approvalPolicy="on-request",
        ),
    )

    resume_intent = intent.user_context["resume_intent"]
    assert resume_intent["recent_tool_calls"] == [
        {
            "iteration": 3,
            "tool": "exec_shell",
            "input_preview": "pytest tests/test_x.py -q --token [REDACTED:api_key]",
            "observation_preview": ("failed for [REDACTED:email]: assertion message body"),
        }
    ]
    assert resume_intent["safety"]["raw_state_included"] is False
    assert "messages_snapshot" not in str(resume_intent)
    assert "sk-kimi-" not in str(resume_intent)
    assert "ops@example.com" not in str(resume_intent)


def test_resume_proposal_block_prepares_confirmation_without_running_react(
    gateway: Any,
) -> None:
    client, _ = gateway
    _set_script([{"type": "text_delta", "delta": "should not run"}, {"type": "react_completed"}])
    resume_text = """
Resume this agent run from the selected durable checkpoint.

<octopus_resume_proposal>
{
  "schema": "octopus.resume_proposal.v1",
  "checkpoint_id": 9,
  "task_id": "task-9",
  "checkpoint_type": "react",
  "iteration": 4,
  "phase": "implementation",
  "progress": "private message body must not leak",
  "working_set": ["runtime/memory/trace_store.py"],
  "resume_plan": ["Inspect sanitized checkpoint metadata.", "message body must not leak"],
  "raw_state_included": false,
  "raw_message_snapshots_included": false,
  "messages_snapshot": ["message body"]
}
</octopus_resume_proposal>
""".strip()
    with client.websocket_connect("/api/realtime") as ws:
        out = _drive(
            ws,
            {
                "threadId": "th-resume-confirm",
                "input": [{"type": "text", "text": resume_text}],
                "approvalPolicy": "on-request",
            },
        )

    assert _LAST_STREAM_KWARGS == {}
    turn = out["response"].result["turn"]
    assert turn["status"] == "completed"
    agent_items = [it for it in turn["items"] if it["type"] == "agentMessage"]
    assert len(agent_items) == 1
    text = agent_items[0]["text"]
    assert "恢复请求已准备" in text
    assert "checkpoint #9" in text
    assert "需要你明确确认" in text
    assert "建议恢复计划：2 步" in text
    assert "message body" not in text
    assert "messages_snapshot" not in text
    assert "raw_state" not in text


def test_confirmed_resume_intent_runs_react_once_and_is_consumed(gateway: Any) -> None:
    client, _ = gateway
    resume_text = """
Resume this agent run from the selected durable checkpoint.

<octopus_resume_proposal>
{
  "schema": "octopus.resume_proposal.v1",
  "checkpoint_id": 12,
  "task_id": "task-12",
  "checkpoint_type": "react",
  "iteration": 2,
  "phase": "implementation",
  "progress": "private message body must not leak",
  "working_set": ["runtime/sensing/siphon/realtime_cerebrum.py"],
  "resume_plan": ["Continue from iteration 3."],
  "recent_tool_calls": [
    {
      "iteration": 2,
      "tool": "read_file",
      "input_preview": "{\\"path\\": \\"runtime/sensing/siphon/realtime_cerebrum.py\\"}",
      "observation_preview": "read file"
    }
  ],
  "raw_state_included": false,
  "raw_message_snapshots_included": false,
  "messages_snapshot": ["message body"]
}
</octopus_resume_proposal>
""".strip()
    with client.websocket_connect("/api/realtime") as ws:
        _set_script(
            [{"type": "text_delta", "delta": "should not run"}, {"type": "react_completed"}]
        )
        _drive(
            ws,
            {
                "threadId": "th-resume-consume",
                "input": [{"type": "text", "text": resume_text}],
                "approvalPolicy": "on-request",
            },
        )
        assert _LAST_STREAM_KWARGS == {}

        _set_script([{"type": "react_completed"}])
        _drive(
            ws,
            {
                "threadId": "th-resume-consume",
                "input": [{"type": "text", "text": "确认恢复 checkpoint #12"}],
                "approvalPolicy": "on-request",
            },
        )
        assert _LAST_STREAM_KWARGS["thread_id"] == "th-resume-consume"
        resume_intent = _LAST_SESSION["metadata"]["resume_intent"]
        assert resume_intent["checkpoint_id"] == 12
        assert resume_intent["requires_confirmation"] is False
        assert resume_intent["confirmed"] is True
        assert resume_intent["recent_tool_calls"][0]["tool"] == "read_file"
        assert "message body" not in str(resume_intent)

        _set_script([{"type": "react_completed"}])
        _drive(
            ws,
            {
                "threadId": "th-resume-consume",
                "input": [{"type": "text", "text": "继续"}],
                "approvalPolicy": "on-request",
            },
        )
        assert "resume_intent" not in _LAST_SESSION["metadata"]


def test_confirmed_resume_intent_passes_task_id_to_react(gateway: Any) -> None:
    client, _ = gateway
    task_id = str(uuid4())
    resume_text = f"""
Resume this agent run from the selected durable checkpoint.

<octopus_resume_proposal>
{{
  "schema": "octopus.resume_proposal.v1",
  "checkpoint_id": 33,
  "task_id": "{task_id}",
  "checkpoint_type": "react",
  "iteration": 5,
  "phase": "implementation",
  "resume_plan": ["Continue from iteration 6."],
  "raw_state_included": false,
  "raw_message_snapshots_included": false
}}
</octopus_resume_proposal>
""".strip()
    with client.websocket_connect("/api/realtime") as ws:
        _set_script([{"type": "react_completed"}])
        _drive(
            ws,
            {
                "threadId": "th-resume-task-id",
                "input": [{"type": "text", "text": resume_text}],
                "approvalPolicy": "on-request",
            },
        )
        assert _LAST_STREAM_KWARGS == {}

        _set_script([{"type": "react_completed"}])
        _drive(
            ws,
            {
                "threadId": "th-resume-task-id",
                "input": [{"type": "text", "text": "确认恢复 checkpoint #33"}],
                "approvalPolicy": "on-request",
            },
        )

    assert str(_LAST_STREAM_KWARGS["resume_task_id"]) == task_id


def test_react_resumed_emits_thread_status_changed(gateway: Any) -> None:
    client, _ = gateway
    _set_script(
        [
            {
                "type": "react_resumed",
                "task_id": "task-123",
                "checkpoint_iteration": 2,
                "resume_from_iteration": 2,
                "restored_step_count": 1,
                "has_final_answer": False,
                "current_phase": "execute",
            },
            {"type": "react_completed"},
        ]
    )
    with client.websocket_connect("/api/realtime") as ws:
        out = _drive(
            ws,
            {
                "threadId": "th-resumed-status",
                "input": [{"type": "text", "text": "continue"}],
                "approvalPolicy": "never",
            },
        )

    status_events = [n for n in out["notifications"] if n.method == "thread/status/changed"]
    assert status_events
    assert status_events[0].params["status"]["type"] == "resumed"
    assert status_events[0].params["status"]["resumeFromIteration"] == 2


def test_confirmed_resume_intent_survives_runtime_restart_when_trace_store_exists(
    tmp_path: Path,
) -> None:
    from fastapi import FastAPI

    from runtime.memory.diagnostics.trace_store import AgentTraceStore
    from runtime.sensing.gateway.realtime_cerebrum import CerebrumRuntime
    from runtime.sensing.gateway.realtime_gateway import RealtimeGateway

    trace = AgentTraceStore(tmp_path / "trace.sqlite")
    runtime_a = CerebrumRuntime(
        stack=object(),
        agent=None,
        logs_root=str(tmp_path / "threads-a"),
        trace_store=trace,
    )
    app_a = FastAPI()
    app_a.include_router(RealtimeGateway(runtime=runtime_a, approval_timeout=5.0).router)
    resume_text = """
Resume this agent run from the selected durable checkpoint.

<octopus_resume_proposal>
{
  "schema": "octopus.resume_proposal.v1",
  "checkpoint_id": 21,
  "task_id": "task-21",
  "checkpoint_type": "react",
  "iteration": 6,
  "phase": "implementation",
  "progress": "private message body must not leak",
  "working_set": ["runtime/memory/trace_store.py"],
  "resume_plan": ["message body must not leak"],
  "raw_state_included": false,
  "raw_message_snapshots_included": false,
  "messages_snapshot": ["message body"]
}
</octopus_resume_proposal>
""".strip()
    with TestClient(app_a) as client, client.websocket_connect("/api/realtime") as ws:
        _set_script([{"type": "react_completed"}])
        _drive(
            ws,
            {
                "threadId": "th-resume-restart",
                "input": [{"type": "text", "text": resume_text}],
                "approvalPolicy": "on-request",
            },
        )
    assert trace.latest_pending_resume_request(thread_id="th-resume-restart") is not None

    runtime_b = CerebrumRuntime(
        stack=object(),
        agent=None,
        logs_root=str(tmp_path / "threads-b"),
        trace_store=trace,
    )
    app_b = FastAPI()
    app_b.include_router(RealtimeGateway(runtime=runtime_b, approval_timeout=5.0).router)
    with TestClient(app_b) as client, client.websocket_connect("/api/realtime") as ws:
        _set_script([{"type": "react_completed"}])
        _drive(
            ws,
            {
                "threadId": "th-resume-restart",
                "input": [{"type": "text", "text": "确认恢复 checkpoint #21"}],
                "approvalPolicy": "on-request",
            },
        )

    resume_intent = _LAST_SESSION["metadata"]["resume_intent"]
    assert resume_intent["checkpoint_id"] == 21
    assert resume_intent["confirmed"] is True
    assert "message body" not in str(resume_intent)
    assert trace.latest_pending_resume_request(thread_id="th-resume-restart") is None
    requests = trace.resume_requests(thread_id="th-resume-restart")
    assert requests[0]["status"] == "consumed"


def test_user_prompt_hook_can_rewrite_prompt_before_react_loop(
    gateway: Any,
) -> None:
    client, _ = gateway
    _set_script(
        [
            {"type": "text_delta", "delta": "expanded"},
            {"type": "react_completed"},
        ]
    )
    from runtime.safety.hooks import HookDecision, UserPromptSubmitEvent, register_hook

    @register_hook(UserPromptSubmitEvent)
    def _rewrite(event):
        assert event.prompt_text == "before hook"
        return HookDecision.modify_prompt("after hook")

    with client.websocket_connect("/api/realtime") as ws:
        out = _drive(
            ws,
            {
                "threadId": "th-user-hook",
                "input": [{"type": "text", "text": "before hook"}],
                "approvalPolicy": "on-request",
                "context": {"mode": "deep"},
            },
        )

    assert _LAST_STREAM_ARGS["args"][1].raw == "after hook"
    turn = out["response"].result["turn"]
    assert turn["status"] == "completed"


def test_complex_turn_defaults_to_planning_mode_in_react_loop(
    gateway: Any,
) -> None:
    client, _ = gateway
    _set_script(
        [
            {"type": "text_delta", "delta": "plan only"},
            {"type": "react_completed"},
        ]
    )

    with client.websocket_connect("/api/realtime") as ws:
        out = _drive(
            ws,
            {
                "threadId": "th-default-plan",
                "input": [{"type": "text", "text": "请完整实现这个功能并测试"}],
                "approvalPolicy": "on-request",
            },
        )

    assert _LAST_STREAM_KWARGS["planning_mode"] is True
    turn = out["response"].result["turn"]
    assert turn["params"]["planningMode"] is True


def test_turn_effort_reaches_react_loop(gateway: Any) -> None:
    client, _ = gateway
    _set_script(
        [
            {"type": "text_delta", "delta": "reasoned"},
            {"type": "react_completed"},
        ]
    )

    with client.websocket_connect("/api/realtime") as ws:
        _drive(
            ws,
            {
                "threadId": "th-effort",
                "input": [{"type": "text", "text": "solve this hard bug"}],
                "approvalPolicy": "never",
                "effort": "xhigh",
            },
        )

    assert _LAST_STREAM_KWARGS["reasoning_effort"] == "xhigh"
    assert _LAST_SESSION["metadata"]["reasoning_effort"] == "xhigh"


def test_thinking_delta_is_streamed_as_reasoning(gateway: Any) -> None:
    # Since the streaming-UX work (live thinking typewriter + foldable
    # reasoning rows), provider thinking deltas are surfaced as a
    # ReasoningItem instead of being dropped as private chain-of-thought.
    client, _ = gateway
    _set_script(
        [
            {"type": "thinking_delta", "delta": "step 1\n"},
            {"type": "thinking_delta", "delta": "step 2"},
            {"type": "react_completed"},
        ]
    )
    with client.websocket_connect("/api/realtime") as ws:
        out = _drive(
            ws,
            {
                "threadId": "th-think",
                "input": [{"type": "text", "text": "reason"}],
                "approvalPolicy": "never",
            },
        )

    reasoning_deltas = [n for n in out["notifications"] if n.method == "item/reasoning/textDelta"]
    assert len(reasoning_deltas) >= 1
    assert "".join(n.params["delta"] for n in reasoning_deltas) == "step 1\nstep 2"

    turn = out["response"].result["turn"]
    r_items = [it for it in turn["items"] if it["type"] == "reasoning"]
    assert len(r_items) == 1
    assert r_items[0]["content"] == "step 1\nstep 2"


def test_tool_round_trip_with_approval(gateway: Any) -> None:
    client, logs_root = gateway
    _set_script(
        [
            {"type": "text_delta", "delta": "running "},
            {
                "type": "tool_start",
                "tool_name": "exec_shell",
                "tool_call_id": "call-1",
                "iteration": 1,
                "input_preview": "ls",
            },
            {
                "__approve__": True,
                "tool_name": "exec_shell",
                "tool_call_id": "call-1",
            },
            {"type": "text_delta", "delta": "done"},
            {"type": "react_completed"},
        ]
    )
    with client.websocket_connect("/api/realtime") as ws:
        out = _drive(
            ws,
            {
                "threadId": "th-tool",
                "input": [{"type": "text", "text": "do it"}],
                "approvalPolicy": "on-request",
            },
            approve=True,
        )

    methods = [n.method for n in out["notifications"]]
    # Before tool, the prose item should have completed (flush on
    # tool_start) and a commandExecution item should have started.
    assert methods.index("item/completed") < methods.index(
        "item/started", methods.index("item/started") + 1
    )

    turn = out["response"].result["turn"]
    cmd_items = [it for it in turn["items"] if it["type"] == "commandExecution"]
    assert len(cmd_items) == 1
    assert cmd_items[0]["command"] == "exec_shell"
    assert cmd_items[0]["inputPreview"] == "ls"
    assert cmd_items[0]["status"] == "completed"

    # The event log preserves the full sequence.
    log_file = logs_root / "th-tool.jsonl"
    assert log_file.exists()


def test_duplicate_tool_call_ids_keep_both_completion_receipts(gateway: Any) -> None:
    """A provider may reuse a call id inside one streamed turn.

    The bridge must complete calls in start order instead of overwriting the
    first item or dropping the second tool_end receipt.
    """
    client, _ = gateway
    _set_script(
        [
            {
                "type": "tool_start",
                "tool_name": "read_file",
                "tool_call_id": "duplicate",
                "iteration": 1,
                "input_preview": {"path": "first.txt"},
            },
            {
                "type": "tool_start",
                "tool_name": "read_file",
                "tool_call_id": "duplicate",
                "iteration": 1,
                "input_preview": {"path": "second.txt"},
            },
            {
                "type": "tool_end",
                "tool_name": "read_file",
                "tool_call_id": "duplicate",
                "status": "success",
                "output_preview": "first receipt",
            },
            {
                "type": "tool_end",
                "tool_name": "read_file",
                "tool_call_id": "duplicate",
                "status": "success",
                "output_preview": "second receipt",
            },
            {"type": "react_completed", "success": True},
        ]
    )

    with client.websocket_connect("/api/realtime") as ws:
        out = _drive(
            ws,
            {
                "threadId": "th-duplicate-tool-id",
                "input": [{"type": "text", "text": "read both"}],
                "approvalPolicy": "never",
            },
        )

    turn = out["response"].result["turn"]
    commands = [item for item in turn["items"] if item["type"] == "commandExecution"]
    assert len(commands) == 2
    assert [item["status"] for item in commands] == ["completed", "completed"]
    assert [item["aggregatedOutput"] for item in commands] == [
        "first receipt",
        "second receipt",
    ]


def test_tool_rejected_propagates(gateway: Any) -> None:
    client, _ = gateway
    _set_script(
        [
            {
                "type": "tool_start",
                "tool_name": "exec_shell",
                "tool_call_id": "call-2",
                "iteration": 1,
            },
            {
                "__approve__": True,
                "tool_name": "exec_shell",
                "tool_call_id": "call-2",
            },
            {"type": "react_completed"},
        ]
    )
    with client.websocket_connect("/api/realtime") as ws:
        out = _drive(
            ws,
            {
                "threadId": "th-reject",
                "input": [{"type": "text", "text": "nope"}],
                "approvalPolicy": "on-request",
            },
            approve=False,
        )

    turn = out["response"].result["turn"]
    cmd_items = [it for it in turn["items"] if it["type"] == "commandExecution"]
    assert cmd_items[0]["status"] == "declined"


def test_react_error_becomes_error_item(gateway: Any) -> None:
    client, _ = gateway
    _set_script(
        [
            {"type": "text_delta", "delta": "partial "},
            {"type": "react_error", "kind": "RuntimeError", "message": "boom", "iteration": 1},
        ]
    )
    with client.websocket_connect("/api/realtime") as ws:
        out = _drive(
            ws,
            {
                "threadId": "th-err",
                "input": [{"type": "text", "text": "go"}],
                "approvalPolicy": "never",
            },
        )

    turn = out["response"].result["turn"]
    err_items = [it for it in turn["items"] if it["type"] == "error"]
    assert err_items and err_items[0]["message"] == "boom"


def test_resume_after_turn_rebuilds_from_disk(gateway: Any) -> None:
    client, _ = gateway
    _set_script([{"type": "text_delta", "delta": "persist me"}, {"type": "react_completed"}])
    with client.websocket_connect("/api/realtime") as ws:
        _drive(
            ws,
            {
                "threadId": "th-resume",
                "input": [{"type": "text", "text": "hi"}],
                "approvalPolicy": "never",
            },
        )
    with client.websocket_connect("/api/realtime") as ws:
        ws.send_text(
            encode_message(
                JsonRpcRequest(id=7, method="thread/resume", params={"threadId": "th-resume"})
            )
        )
        while True:
            msg = decode_message(ws.receive_text())
            if isinstance(msg, JsonRpcResponse) and msg.id == 7:
                break
        assert msg.result is not None
        resume_msg = msg
        ws.send_text(
            encode_message(
                JsonRpcRequest(
                    id=8,
                    method="thread/resume",
                    params={
                        "threadId": "th-resume",
                        "afterSequence": resume_msg.result["nextEventSequence"],
                    },
                )
            )
        )
        while True:
            msg = decode_message(ws.receive_text())
            if isinstance(msg, JsonRpcResponse) and msg.id == 8:
                break
        incremental_msg = msg
    turns = resume_msg.result["turns"]
    assert len(turns) == 1
    agent = [it for it in turns[0]["items"] if it["type"] == "agentMessage"]
    assert agent and agent[0]["text"] == "persist me"
    assert resume_msg.result["incremental"] is False
    assert incremental_msg.result["incremental"] is True
    assert incremental_msg.result["turns"] == []
    assert incremental_msg.result["nextEventSequence"] == resume_msg.result["nextEventSequence"]


def test_thread_list_via_cerebrum(gateway: Any) -> None:
    client, _ = gateway
    _set_script([{"type": "text_delta", "delta": "hi"}, {"type": "react_completed"}])
    with client.websocket_connect("/api/realtime") as ws:
        _drive(
            ws,
            {
                "threadId": "th_cb_one",
                "input": [{"type": "text", "text": "hi"}],
                "approvalPolicy": "never",
            },
        )
        _drive(
            ws,
            {
                "threadId": "th_cb_two",
                "input": [{"type": "text", "text": "hi"}],
                "approvalPolicy": "never",
            },
        )
    with client.websocket_connect("/api/realtime") as ws:
        ws.send_text(encode_message(JsonRpcRequest(id=99, method="thread/list", params={})))
        while True:
            msg = decode_message(ws.receive_text())
            if isinstance(msg, JsonRpcResponse) and msg.id == 99:
                break
    assert msg.result is not None
    ids = sorted(t["threadId"] for t in msg.result["threads"])
    assert ids == ["th_cb_one", "th_cb_two"]


def test_thread_archive_via_cerebrum(gateway: Any) -> None:
    client, _ = gateway
    _set_script([{"type": "text_delta", "delta": "hi"}, {"type": "react_completed"}])
    with client.websocket_connect("/api/realtime") as ws:
        _drive(
            ws,
            {
                "threadId": "th_cb_archive",
                "input": [{"type": "text", "text": "hi"}],
                "approvalPolicy": "never",
            },
        )
    with client.websocket_connect("/api/realtime") as ws:
        ws.send_text(
            encode_message(
                JsonRpcRequest(
                    id=77,
                    method="thread/archive",
                    params={"threadId": "th_cb_archive"},
                )
            )
        )
        while True:
            msg = decode_message(ws.receive_text())
            if isinstance(msg, JsonRpcResponse) and msg.id == 77:
                break
    assert msg.result == {"threadId": "th_cb_archive", "archived": True}


def test_thread_archive_blocks_cerebrum_resume(gateway: Any) -> None:
    client, _ = gateway
    _set_script([{"type": "text_delta", "delta": "hi"}, {"type": "react_completed"}])
    with client.websocket_connect("/api/realtime") as ws:
        _drive(
            ws,
            {
                "threadId": "th_cb_archived_resume",
                "input": [{"type": "text", "text": "hi"}],
                "approvalPolicy": "never",
            },
        )
        ws.send_text(
            encode_message(
                JsonRpcRequest(
                    id=78,
                    method="thread/archive",
                    params={"threadId": "th_cb_archived_resume"},
                )
            )
        )
        while True:
            msg = decode_message(ws.receive_text())
            if isinstance(msg, JsonRpcResponse) and msg.id == 78:
                break
        ws.send_text(
            encode_message(
                JsonRpcRequest(
                    id=79,
                    method="thread/resume",
                    params={"threadId": "th_cb_archived_resume"},
                )
            )
        )
        while True:
            msg = decode_message(ws.receive_text())
            if isinstance(msg, JsonRpcResponse) and msg.id == 79:
                break
    assert msg.error is not None
    assert msg.error.code == JsonRpcErrorCode.THREAD_NOT_FOUND


def test_tool_end_with_diff_emits_file_change_item(gateway: Any) -> None:
    """When react_loop emits a ``tool_end`` carrying a unified diff,
    the bridge must promote it to a structured FileChangeItem so the
    UI can render hunk-level controls."""
    client, _ = gateway
    diff = "--- a/src/foo.py\n+++ b/src/foo.py\n@@ -1,3 +1,3 @@\n x\n-old\n+new\n y\n"
    _set_script(
        [
            {
                "type": "tool_start",
                "tool_name": "edit_text_file",
                "tool_call_id": "call-edit",
            },
            {
                "type": "tool_end",
                "tool_name": "edit_text_file",
                "tool_call_id": "call-edit",
                "iteration": 1,
                "status": "success",
                "output_preview": "ok",
                "duration_ms": 1,
                "diff": diff,
            },
            {"type": "react_completed"},
        ]
    )
    # The unverified code change trips the agent-driven verification
    # loop-back (one extra drive). Consume the script on the first drive so
    # that loop-back does not replay the edit and double-emit the change.
    global _SCRIPT_POP_ONCE
    _SCRIPT_POP_ONCE = True
    with client.websocket_connect("/api/realtime") as ws:
        out = _drive(
            ws,
            {
                "threadId": "th_filechange",
                "input": [{"type": "text", "text": "edit"}],
                "approvalPolicy": "never",
            },
        )

    hunk_deltas = [n for n in out["notifications"] if n.method == "item/fileChange/hunkDelta"]
    assert len(hunk_deltas) == 1
    assert hunk_deltas[0].params["path"] == "src/foo.py"
    assert hunk_deltas[0].params["workspaceFocus"]["view"] == "diff"
    assert hunk_deltas[0].params["hunk"]["decision"] == "pending"

    turn = out["response"].result["turn"]
    file_items = [it for it in turn["items"] if it["type"] == "fileChange"]
    assert len(file_items) == 1
    fci = file_items[0]
    assert len(fci["changes"]) == 1
    change = fci["changes"][0]
    assert change["path"] == "src/foo.py"
    assert change["op"] == "update"
    assert len(change["hunks"]) == 1
    hunk = change["hunks"][0]
    assert hunk["oldStart"] == 1 and hunk["newStart"] == 1
    assert hunk["decision"] == "pending"
    # The promoted item must land as completed, not stay inProgress and get
    # swept to failed by _close_turn when the turn ends.
    assert fci["status"] == "completed"
    completed_events = [
        n.params["item"]
        for n in out["notifications"]
        if n.method == "item/completed" and n.params["item"].get("type") == "fileChange"
    ]
    assert len(completed_events) == 1
    assert completed_events[0]["status"] == "completed"


def test_code_file_change_without_verification_fails_turn(gateway: Any) -> None:
    client, logs_root = gateway
    diff = "--- a/src/foo.py\n+++ b/src/foo.py\n@@ -1,2 +1,2 @@\n-old\n+new\n"
    _set_script(
        [
            {
                "type": "tool_start",
                "tool_name": "edit_file",
                "tool_call_id": "call-edit",
            },
            {
                "type": "tool_end",
                "tool_name": "edit_file",
                "tool_call_id": "call-edit",
                "iteration": 1,
                "status": "success",
                "output_preview": "ok",
                "duration_ms": 1,
                "diff": diff,
            },
            {"type": "react_completed"},
        ]
    )
    with client.websocket_connect("/api/realtime") as ws:
        out = _drive(
            ws,
            {
                "threadId": "th_unverified_code_change",
                "input": [{"type": "text", "text": "edit"}],
                "approvalPolicy": "never",
            },
        )

    turn = out["response"].result["turn"]
    assert turn["status"] == "failed"
    verification_items = [it for it in turn["items"] if it["type"] == "verification"]
    assert len(verification_items) == 1
    assert verification_items[0]["kind"] == "manual"
    assert verification_items[0]["status"] == "failed"
    assert verification_items[0]["relatedFiles"] == ["src/foo.py"]
    assert "Recommended verification commands:" in verification_items[0]["stdoutTail"]
    assert "python -m ruff check src/foo.py" in verification_items[0]["stdoutTail"]

    ledger_path = logs_root.parent / "proposal_ledger.jsonl"
    lines = ledger_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["kind"] == "turn_failure"
    assert entry["proposer"] == "realtime_cerebrum"
    assert entry["metadata"]["failure_source"] == "verification_required"
    assert entry["metadata"]["code_change_paths"] == ["src/foo.py"]
    assert entry["metadata"]["turn_id"] == turn["id"]
    assert entry["metadata"]["verification_plan"]["schema"] == "octopus.verification_plan.v1"
    assert entry["metadata"]["verification_plan"]["commands"][0]["command"] == (
        "python -m ruff check src/foo.py"
    )


def test_code_file_change_auto_runs_safe_verification(
    gateway: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("OCTOPUS_DATA_DIR", str(data_dir))
    client, _logs_root = gateway
    src = tmp_path / "src"
    src.mkdir()
    (src / "foo.py").write_text("value = 1\n", encoding="utf-8")
    diff = "--- a/src/foo.py\n+++ b/src/foo.py\n@@ -1,1 +1,1 @@\n-value = 0\n+value = 1\n"
    _set_script(
        [
            {
                "type": "tool_start",
                "tool_name": "edit_file",
                "tool_call_id": "call-edit",
            },
            {
                "type": "tool_end",
                "tool_name": "edit_file",
                "tool_call_id": "call-edit",
                "iteration": 1,
                "status": "success",
                "output_preview": "ok",
                "duration_ms": 1,
                "diff": diff,
            },
            {"type": "react_completed"},
        ]
    )
    with client.websocket_connect("/api/realtime") as ws:
        out = _drive(
            ws,
            {
                "threadId": "th_auto_verified_code_change",
                "cwd": str(tmp_path),
                "input": [{"type": "text", "text": "edit"}],
                "approvalPolicy": "never",
                "sandboxPolicy": {"type": "workspaceWrite", "networkAccess": False},
            },
        )

    turn = out["response"].result["turn"]
    assert turn["status"] == "completed"
    verification_items = [it for it in turn["items"] if it["type"] == "verification"]
    assert len(verification_items) == 1
    assert verification_items[0]["command"] == "python -m ruff check src/foo.py"
    assert verification_items[0]["kind"] == "lint"
    assert verification_items[0]["status"] == "completed"
    assert verification_items[0]["relatedFiles"] == ["src/foo.py"]

    metrics = (data_dir / "auto_verifier_metrics.jsonl").read_text(encoding="utf-8")
    assert '"family": "ruff"' in metrics
    assert '"ok": true' in metrics
    decisions = (data_dir / "auto_verifier_decisions.jsonl").read_text(encoding="utf-8")
    assert '"selected_command": "python -m ruff check src/foo.py"' in decisions
    assert "no history for ruff" in decisions


def test_code_file_change_with_successful_verification_can_complete(gateway: Any) -> None:
    client, _ = gateway
    diff = "--- a/src/foo.py\n+++ b/src/foo.py\n@@ -1,2 +1,2 @@\n-old\n+new\n"
    _set_script(
        [
            {
                "type": "tool_start",
                "tool_name": "edit_file",
                "tool_call_id": "call-edit",
            },
            {
                "type": "tool_end",
                "tool_name": "edit_file",
                "tool_call_id": "call-edit",
                "iteration": 1,
                "status": "success",
                "output_preview": "ok",
                "duration_ms": 1,
                "diff": diff,
                "verification": {
                    "command": "pytest tests/test_foo.py",
                    "kind": "test",
                    "exit_code": 0,
                    "success": True,
                    "stdout_tail": "1 passed",
                },
            },
            {"type": "react_completed"},
        ]
    )
    with client.websocket_connect("/api/realtime") as ws:
        out = _drive(
            ws,
            {
                "threadId": "th_verified_code_change",
                "input": [{"type": "text", "text": "edit"}],
                "approvalPolicy": "never",
            },
        )

    turn = out["response"].result["turn"]
    assert turn["status"] == "completed"
    file_items = [it for it in turn["items"] if it["type"] == "fileChange"]
    verification_items = [it for it in turn["items"] if it["type"] == "verification"]
    assert len(file_items) == 1
    assert len(verification_items) == 1
    assert verification_items[0]["status"] == "completed"
    assert verification_items[0]["relatedFiles"] == ["src/foo.py"]
    assert verification_items[0]["relatedChangeItemIds"] == [file_items[0]["id"]]


def test_code_file_change_with_failed_verification_fails_turn(gateway: Any) -> None:
    client, logs_root = gateway
    diff = "--- a/src/foo.py\n+++ b/src/foo.py\n@@ -1,2 +1,2 @@\n-old\n+new\n"
    _set_script(
        [
            {
                "type": "tool_start",
                "tool_name": "edit_file",
                "tool_call_id": "call-edit",
            },
            {
                "type": "tool_end",
                "tool_name": "edit_file",
                "tool_call_id": "call-edit",
                "iteration": 1,
                "status": "success",
                "output_preview": "tests failed",
                "duration_ms": 1,
                "diff": diff,
                "verification": {
                    "command": "pytest tests/test_foo.py",
                    "kind": "test",
                    "exit_code": 1,
                    "success": False,
                    "stdout_tail": "1 failed",
                },
            },
            {"type": "react_completed"},
        ]
    )
    with client.websocket_connect("/api/realtime") as ws:
        out = _drive(
            ws,
            {
                "threadId": "th_failed_verified_code_change",
                "input": [{"type": "text", "text": "edit"}],
                "approvalPolicy": "never",
            },
        )

    turn = out["response"].result["turn"]
    assert turn["status"] == "failed"
    verification_items = [it for it in turn["items"] if it["type"] == "verification"]
    assert len(verification_items) == 1
    assert verification_items[0]["status"] == "failed"
    assert verification_items[0]["relatedFiles"] == ["src/foo.py"]

    ledger_path = logs_root.parent / "proposal_ledger.jsonl"
    entries = [json.loads(line) for line in ledger_path.read_text(encoding="utf-8").splitlines()]
    failures = [entry for entry in entries if entry["kind"] == "turn_failure"]
    assert failures[-1]["metadata"]["failure_source"] == "verification_failed"
    assert failures[-1]["metadata"]["failed_verifications"][0]["command"] == (
        "pytest tests/test_foo.py"
    )
    assert (
        failures[-1]["metadata"]["failed_verifications"][0]["diagnosis"]["category"]
        == "test_failure"
    )
    assert (
        failures[-1]["metadata"]["failed_verifications"][0]["diagnosis"]["action"]
        == "fix_code_or_test_expectation"
    )
    route = failures[-1]["metadata"]["failed_verifications"][0]["diagnosis"]["repair_route"]
    assert route["route"] == "test_driven_repair"
    assert route["strategy"] == "reproduce_and_patch_behavior"
    assert failures[-1]["metadata"]["primary_repair_route"] == "test_driven_repair"


def test_non_code_file_change_without_verification_can_complete(gateway: Any) -> None:
    client, logs_root = gateway
    diff = "--- a/notes.md\n+++ b/notes.md\n@@ -1,2 +1,2 @@\n-old\n+new\n"
    _set_script(
        [
            {
                "type": "tool_start",
                "tool_name": "write_text_file",
                "tool_call_id": "call-write",
            },
            {
                "type": "tool_end",
                "tool_name": "write_text_file",
                "tool_call_id": "call-write",
                "iteration": 1,
                "status": "success",
                "output_preview": "ok",
                "duration_ms": 1,
                "diff": diff,
            },
            {"type": "react_completed"},
        ]
    )
    with client.websocket_connect("/api/realtime") as ws:
        out = _drive(
            ws,
            {
                "threadId": "th_unverified_note_change",
                "input": [{"type": "text", "text": "write notes"}],
                "approvalPolicy": "never",
            },
        )

    turn = out["response"].result["turn"]
    assert turn["status"] == "completed"
    ledger_path = logs_root.parent / "proposal_ledger.jsonl"
    entries = [json.loads(line) for line in ledger_path.read_text(encoding="utf-8").splitlines()]
    success = [entry for entry in entries if entry["kind"] == "turn_success"]
    assert len(success) == 1
    assert success[0]["metadata"]["goal"] == "write notes"

    turn = out["response"].result["turn"]
    assert turn["status"] == "completed"
    assert not [it for it in turn["items"] if it["type"] == "verification"]


def test_tool_end_with_post_write_diagnostics_emits_verification_item(gateway: Any) -> None:
    client, _ = gateway
    diagnostics = (
        "ok\n\n"
        "[post-write diagnostics]\n"
        "ruff diagnostics (foo.py):\n"
        "E999 SyntaxError: expected ':'\n"
    )
    _set_script(
        [
            {
                "type": "tool_start",
                "tool_name": "write_text_file",
                "tool_call_id": "call-write",
                "input_preview": {"path": "src/foo.py"},
            },
            {
                "type": "tool_end",
                "tool_name": "write_text_file",
                "tool_call_id": "call-write",
                "iteration": 1,
                "status": "success",
                "output_preview": diagnostics,
                "duration_ms": 1,
            },
            {"type": "react_completed"},
        ]
    )
    with client.websocket_connect("/api/realtime") as ws:
        out = _drive(
            ws,
            {
                "threadId": "th_verify",
                "input": [{"type": "text", "text": "write"}],
                "approvalPolicy": "never",
            },
        )

    completed = [n.params["item"] for n in out["notifications"] if n.method == "item/completed"]
    verification_events = [it for it in completed if it["type"] == "verification"]
    assert len(verification_events) == 1
    assert verification_events[0]["kind"] == "diagnostic"
    assert verification_events[0]["status"] == "failed"
    assert verification_events[0]["exitCode"] == 1
    assert verification_events[0]["relatedFiles"] == ["src/foo.py"]

    turn = out["response"].result["turn"]
    verification_items = [it for it in turn["items"] if it["type"] == "verification"]
    assert len(verification_items) == 1
    assert "ruff diagnostics" in verification_items[0]["stdoutTail"]
    assert turn["status"] == "failed"


def test_tool_end_with_explicit_verification_metadata_emits_verification_item(gateway: Any) -> None:
    client, _ = gateway
    _set_script(
        [
            {
                "type": "tool_start",
                "tool_name": "run_tests",
                "tool_call_id": "call-test",
            },
            {
                "type": "tool_end",
                "tool_name": "run_tests",
                "tool_call_id": "call-test",
                "iteration": 1,
                "status": "success",
                "output_preview": "tests failed",
                "duration_ms": 1,
                "verification": {
                    "command": "pnpm test",
                    "kind": "test",
                    "exit_code": 1,
                    "success": False,
                    "stdout_tail": "1 failed",
                },
            },
            {"type": "react_completed"},
        ]
    )
    with client.websocket_connect("/api/realtime") as ws:
        out = _drive(
            ws,
            {
                "threadId": "th_explicit_verify",
                "input": [{"type": "text", "text": "test"}],
                "approvalPolicy": "never",
            },
        )

    turn = out["response"].result["turn"]
    verification_items = [it for it in turn["items"] if it["type"] == "verification"]
    assert len(verification_items) == 1
    assert verification_items[0]["command"] == "pnpm test"
    assert verification_items[0]["kind"] == "test"
    assert verification_items[0]["status"] == "failed"
    assert verification_items[0]["exitCode"] == 1
    assert verification_items[0]["stdoutTail"] == "1 failed"


def test_tool_end_verification_without_success_uses_event_failure(gateway: Any) -> None:
    client, _ = gateway
    _set_script(
        [
            {
                "type": "tool_start",
                "tool_name": "exec_shell",
                "tool_call_id": "call-typecheck",
            },
            {
                "type": "tool_end",
                "tool_name": "exec_shell",
                "tool_call_id": "call-typecheck",
                "iteration": 1,
                "status": "error",
                "output_preview": "command failed",
                "duration_ms": 1,
                "verification": {
                    "command": "npx -y tsc --noEmit",
                    "kind": "typecheck",
                    "stderr_tail": "[WinError 2] file not found",
                },
            },
            {"type": "react_completed", "success": False},
        ]
    )
    with client.websocket_connect("/api/realtime") as ws:
        out = _drive(
            ws,
            {
                "threadId": "th_verify_unknown_failed",
                "input": [{"type": "text", "text": "test"}],
                "approvalPolicy": "never",
            },
        )

    turn = out["response"].result["turn"]
    verification_items = [it for it in turn["items"] if it["type"] == "verification"]
    assert len(verification_items) == 1
    assert verification_items[0]["command"] == "npx -y tsc --noEmit"
    assert verification_items[0]["kind"] == "typecheck"
    assert verification_items[0]["status"] == "failed"
    assert turn["status"] == "failed"


def test_failed_verification_metadata_classifies_missing_tool(
    gateway: Any,
) -> None:
    client, logs_root = gateway
    diff = "--- a/src/foo.ts\n+++ b/src/foo.ts\n@@ -1,2 +1,2 @@\n-old\n+new\n"
    _set_script(
        [
            {
                "type": "tool_start",
                "tool_name": "edit_file",
                "tool_call_id": "call-edit",
            },
            {
                "type": "tool_end",
                "tool_name": "edit_file",
                "tool_call_id": "call-edit",
                "iteration": 1,
                "status": "success",
                "output_preview": "typecheck failed",
                "duration_ms": 1,
                "diff": diff,
                "verification": {
                    "command": "npx --no-install tsc --noEmit",
                    "kind": "typecheck",
                    "exit_code": 1,
                    "success": False,
                    "stderr_tail": "[WinError 2] file not found",
                },
            },
            {"type": "react_completed"},
        ]
    )
    with client.websocket_connect("/api/realtime") as ws:
        out = _drive(
            ws,
            {
                "threadId": "th_failed_missing_tool",
                "input": [{"type": "text", "text": "edit"}],
                "approvalPolicy": "never",
            },
        )

    turn = out["response"].result["turn"]
    assert turn["status"] == "failed"
    ledger_path = logs_root.parent / "proposal_ledger.jsonl"
    failures = [
        json.loads(line)
        for line in ledger_path.read_text(encoding="utf-8").splitlines()
        if json.loads(line)["kind"] == "turn_failure"
    ]
    diagnosis = failures[-1]["metadata"]["failed_verifications"][0]["diagnosis"]
    assert diagnosis["category"] == "environment_missing_tool"
    assert diagnosis["action"] == "install_or_select_available_verifier"
    assert diagnosis["retryable"] is True
    assert diagnosis["repair_route"]["route"] == "environment_repair"
    assert failures[-1]["metadata"]["primary_repair_route"] == "environment_repair"


def test_hunk_decide_rejected_reverts_file(gateway: Any, tmp_path: Path) -> None:
    """Client rejecting a hunk reverse-applies its diff to the file."""
    client, _ = gateway
    target = tmp_path / "sample.txt"
    target.write_text("x\nnew\ny\n", encoding="utf-8")
    diff = "--- a/sample.txt\n+++ b/sample.txt\n@@ -1,3 +1,3 @@\n x\n-old\n+new\n y\n"
    with client.websocket_connect("/api/realtime") as ws:
        ws.send_text(
            encode_message(
                JsonRpcRequest(
                    id=42,
                    method="item/fileChange/hunkDecide",
                    params={
                        "threadId": "th",
                        "turnId": "tn",
                        "itemId": "it",
                        "hunkId": "h1",
                        "path": str(target),
                        "decision": "rejected",
                        "diff": diff,
                    },
                )
            )
        )
        while True:
            msg = decode_message(ws.receive_text())
            if isinstance(msg, JsonRpcResponse) and msg.id == 42:
                break
    assert msg.error is None
    assert msg.result["decision"] == "rejected"
    assert target.read_text(encoding="utf-8") == "x\nold\ny\n"


def test_hunk_decide_accepted_does_not_touch_file(gateway: Any, tmp_path: Path) -> None:
    client, _ = gateway
    target = tmp_path / "kept.txt"
    target.write_text("after-edit\n", encoding="utf-8")
    with client.websocket_connect("/api/realtime") as ws:
        ws.send_text(
            encode_message(
                JsonRpcRequest(
                    id=43,
                    method="item/fileChange/hunkDecide",
                    params={
                        "path": str(target),
                        "decision": "accepted",
                    },
                )
            )
        )
        while True:
            msg = decode_message(ws.receive_text())
            if isinstance(msg, JsonRpcResponse) and msg.id == 43:
                break
    assert msg.error is None
    assert msg.result["decision"] == "accepted"
    assert target.read_text(encoding="utf-8") == "after-edit\n"


def test_throughput_event_maps_to_token_usage(gateway: Any) -> None:
    """react_loop emits periodic ``throughput`` events during long
    streams. The bridge must forward them as ``thread/tokenUsage/updated``
    notifications so the UI can show a live tokens-per-second indicator."""
    client, _ = gateway
    _set_script(
        [
            {"type": "text_delta", "delta": "hello "},
            {
                "type": "throughput",
                "chars": 6,
                "elapsed_ms": 500,
                "chars_per_sec": 12.0,
            },
            {"type": "text_delta", "delta": "world"},
            {"type": "react_completed"},
        ]
    )
    with client.websocket_connect("/api/realtime") as ws:
        result = _drive(
            ws,
            params={
                "threadId": "th_tp",
                "input": [{"type": "text", "text": "stream"}],
                "approvalPolicy": "never",
            },
        )
    tp_notes = [n for n in result["notifications"] if n.method == "thread/tokenUsage/updated"]
    assert tp_notes, "expected at least one tokenUsage notification"
    usage = tp_notes[0].params["tokenUsage"]
    assert usage["chars"] == 6
    assert usage["charsPerSec"] == 12.0
    assert usage["elapsedMs"] == 500


def test_turn_interrupt_kills_in_flight_subprocess(
    gateway: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end: client sends turn/interrupt while a tool is running
    a long subprocess → stream_run sees cancellation → proc killed →
    tool_end carries status=cancelled → turn.status = cancelled."""
    import sys
    import time

    import runtime.core.cerebrum.react_loop as rl
    from runtime.platform.process.streaming import stream_run

    tool_completed_naturally = {"flag": False}

    def fake_stream_with_real_subprocess(
        *args: Any,
        **kwargs: Any,
    ) -> Iterator[dict[str, Any]]:
        # tool_start lets the bridge create a commandExecution item.
        yield {
            "type": "tool_start",
            "tool_name": "sleep_long",
            "tool_call_id": "c_cancel",
            "iteration": 1,
            "input_preview": {"seconds": 10},
        }
        t0 = time.monotonic()
        # Real subprocess — would sleep 10s if not cancelled.
        r = stream_run(
            [sys.executable, "-c", "import time; time.sleep(10); print('done')"],
            timeout=15,
        )
        elapsed = time.monotonic() - t0
        if r.get("cancelled"):
            yield {
                "type": "tool_end",
                "tool_name": "sleep_long",
                "tool_call_id": "c_cancel",
                "iteration": 1,
                "status": "cancelled",
                "output_preview": "(已取消)",
                "duration_ms": int(elapsed * 1000),
            }
            yield {"type": "react_cancelled", "iteration": 1}
            return
        tool_completed_naturally["flag"] = True  # should NOT happen
        yield {
            "type": "tool_end",
            "tool_name": "sleep_long",
            "tool_call_id": "c_cancel",
            "iteration": 1,
            "status": "success",
            "output_preview": r.get("stdout", ""),
            "duration_ms": int(elapsed * 1000),
        }
        yield {"type": "react_completed"}

    monkeypatch.setattr(rl, "stream_react_loop", fake_stream_with_real_subprocess)

    client, _ = gateway
    t0 = time.monotonic()
    with client.websocket_connect("/api/realtime") as ws:
        ws.send_text(
            encode_message(
                JsonRpcRequest(
                    id=1,
                    method="turn/start",
                    params={
                        "threadId": "th_cancel",
                        "input": [{"type": "text", "text": "sleep please"}],
                        "approvalPolicy": "never",
                    },
                )
            )
        )

        # Send interrupt after we see the tool_start item
        interrupted = False
        final: JsonRpcResponse | None = None
        notifications: list[Notification] = []
        turn_id: str | None = None
        while final is None:
            msg = decode_message(ws.receive_text())
            if isinstance(msg, Notification):
                notifications.append(msg)
                if msg.method == "turn/started":
                    turn_id = msg.params["turn"]["id"]
                if (
                    msg.method == "item/started"
                    and msg.params.get("item", {}).get("type") == "commandExecution"
                    and not interrupted
                ):
                    ws.send_text(
                        encode_message(
                            JsonRpcRequest(
                                id=99,
                                method="turn/interrupt",
                                params={"threadId": "th_cancel", "turnId": turn_id},
                            )
                        )
                    )
                    interrupted = True
                continue
            if isinstance(msg, JsonRpcResponse) and msg.id == 1:
                final = msg
                break
            # ignore the interrupt ack

    elapsed = time.monotonic() - t0
    assert final is not None
    # Must complete in well under the 10s sleep — cancellation must
    # propagate through the async watcher + stream_run kill path.
    assert elapsed < 3.0, f"interrupt took {elapsed:.1f}s, expected < 3s"
    assert tool_completed_naturally["flag"] is False
    assert final.result["turn"]["status"] == "cancelled"


def test_thread_resume_closes_stale_in_progress_turn(tmp_path: Path) -> None:
    from fastapi import FastAPI

    from runtime.memory.threads.event_log import EventLog
    from runtime.protocol.items import ItemStatus, Turn, TurnParams, UserMessageItem
    from runtime.sensing.gateway.realtime_cerebrum import CerebrumRuntime
    from runtime.sensing.gateway.realtime_gateway import RealtimeGateway

    logs_root = tmp_path / "threads"
    log = EventLog(logs_root / "stale-thread.jsonl")
    turn = Turn(
        threadId="stale-thread",
        params=TurnParams(
            threadId="stale-thread",
            input=[{"type": "text", "text": "will never finish"}],
        ),
    )
    user_item = UserMessageItem(text="will never finish")
    user_item.status = ItemStatus.COMPLETED
    log.thread_started("stale-thread")
    log.turn_started("stale-thread", turn)
    log.item_started("stale-thread", turn.id, user_item)
    log.item_completed("stale-thread", turn.id, user_item)

    runtime = CerebrumRuntime(
        stack=object(),
        agent=object(),
        logs_root=str(logs_root),
    )
    gateway = RealtimeGateway(runtime=runtime, approval_timeout=5.0)
    app = FastAPI()
    app.include_router(gateway.router)

    with TestClient(app) as client, client.websocket_connect("/api/realtime") as ws:
        ws.send_text(
            encode_message(
                JsonRpcRequest(
                    id=1,
                    method="thread/resume",
                    params={"threadId": "stale-thread"},
                )
            )
        )
        msg = decode_message(ws.receive_text())

    assert isinstance(msg, JsonRpcResponse)
    resumed_turn = msg.result["turns"][0]
    assert resumed_turn["status"] == "failed"
    assert resumed_turn["error"]["code"] == "stale_in_progress_turn"

    replayed = log.replay()
    assert replayed[0].status.value == "failed"


@pytest.mark.asyncio()
async def test_hunk_decide_rejects_paths_outside_thread_workspace(tmp_path: Path) -> None:
    from runtime.sensing.gateway.realtime_cerebrum import CerebrumRuntime
    from runtime.sensing.gateway.realtime_gateway import _RpcError

    outside = tmp_path / "outside.txt"
    outside.write_text("new\n", encoding="utf-8")
    runtime = CerebrumRuntime(
        stack=object(),
        agent=object(),
        logs_root=str(tmp_path / "threads"),
        workspace_root=str(tmp_path / "workspaces"),
    )

    class Emitter:
        async def notify(self, method: str, params: dict[str, Any]) -> None:
            raise AssertionError("no hunk decision should be broadcast for invalid paths")

    diff = "--- a/outside.txt\n+++ b/outside.txt\n@@ -1 +1 @@\n-old\n+new\n"
    with pytest.raises(_RpcError) as exc:
        await runtime._handle_hunk_decide(  # type: ignore[attr-defined]
            {
                "threadId": "thread-a",
                "turnId": "turn-a",
                "itemId": "item-a",
                "hunkId": "hunk-a",
                "path": str(outside),
                "decision": "rejected",
                "diff": diff,
            },
            Emitter(),
        )

    assert exc.value.code == JsonRpcErrorCode.INVALID_PARAMS
    assert outside.read_text(encoding="utf-8") == "new\n"


def test_meta_skill_hint_emitted_when_prompt_matches_pack(tmp_path: Path) -> None:
    """Soft hand-off: when ``match_meta_skill`` finds a strong
    keyword overlap (e.g. the bug-hunt pack's trigger phrase), the
    runtime emits ``turn/metaSkill/hint`` BEFORE ReAct kicks in. The
    ReAct loop continues normally — hint is informational so the
    user gets an answer even if they don't follow the link to the
    catalog page.

    We use the bug-hunt pack's actual trigger words ("安全审计") so
    the test stays grounded in the shipped catalog rather than a
    hand-rolled fixture that could drift from real behavior."""
    from fastapi import FastAPI

    from runtime.sensing.gateway.realtime_cerebrum import CerebrumRuntime
    from runtime.sensing.gateway.realtime_gateway import RealtimeGateway
    from runtime.sensing.model_router.models import ModelResponse, ModelStreamEvent

    class FakeRouter:
        def call_stream(self, _request: Any) -> Iterator[ModelStreamEvent]:
            yield ModelStreamEvent(type="text_delta", delta="ack")
            yield ModelStreamEvent(type="done", final=ModelResponse(text="ack"))

    class FakePlanner:
        planner_model = "fake"

        def __init__(self, router: FakeRouter) -> None:
            self.router = router

    class FakeStack:
        def __init__(self, router: FakeRouter) -> None:
            self.planner = FakePlanner(router)
            self.journal = None

    runtime = CerebrumRuntime(
        stack=FakeStack(FakeRouter()),
        agent=None,
        logs_root=str(tmp_path / "threads"),
    )
    gateway = RealtimeGateway(runtime=runtime, approval_timeout=5.0)
    app = FastAPI()
    app.include_router(gateway.router)

    _set_script(
        [
            {"type": "react_completed"},
        ]
    )
    with TestClient(app) as client, client.websocket_connect("/api/realtime") as ws:
        out = _drive(
            ws,
            {
                "threadId": "th-meta-hint",
                # Two keyword tokens that overlap bug-hunt's
                # ``when_to_use``: 安全审计 / 渗透 / 漏洞 /...
                "input": [{"type": "text", "text": "帮我做一次安全审计 渗透测试"}],
                "approvalPolicy": "never",
                "model": "fake",
            },
        )

    notifications = out["notifications"]
    hints = [n for n in notifications if n.method == "turn/metaSkill/hint"]
    assert len(hints) == 1, [n.method for n in notifications]
    payload = hints[0].params
    assert payload["threadId"] == "th-meta-hint"
    assert payload["name"] == "bug-hunt"
    assert payload["stepCount"] >= 1
    assert "security" in payload["affinity"]


def test_meta_skill_hint_silent_when_no_match(tmp_path: Path) -> None:
    """Casual prompts that don't match any pack must NOT trigger a
    hint — the chip is reserved for real workflow intent. A plain
    ``2+2等于几`` should pass through with zero meta-skill events."""
    from fastapi import FastAPI

    from runtime.sensing.gateway.realtime_cerebrum import CerebrumRuntime
    from runtime.sensing.gateway.realtime_gateway import RealtimeGateway
    from runtime.sensing.model_router.models import ModelResponse, ModelStreamEvent

    class FakeRouter:
        def call_stream(self, _request: Any) -> Iterator[ModelStreamEvent]:
            yield ModelStreamEvent(type="text_delta", delta="4")
            yield ModelStreamEvent(type="done", final=ModelResponse(text="4"))

    class FakePlanner:
        planner_model = "fake"

        def __init__(self, router: FakeRouter) -> None:
            self.router = router

    class FakeStack:
        def __init__(self, router: FakeRouter) -> None:
            self.planner = FakePlanner(router)
            self.journal = None

    runtime = CerebrumRuntime(
        stack=FakeStack(FakeRouter()),
        agent=None,
        logs_root=str(tmp_path / "threads"),
    )
    gateway = RealtimeGateway(runtime=runtime, approval_timeout=5.0)
    app = FastAPI()
    app.include_router(gateway.router)

    _set_script([{"type": "react_completed"}])
    with TestClient(app) as client, client.websocket_connect("/api/realtime") as ws:
        out = _drive(
            ws,
            {
                "threadId": "th-no-hint",
                "input": [{"type": "text", "text": "2+2等于几？"}],
                "approvalPolicy": "never",
                "model": "fake",
            },
        )

    hints = [n for n in out["notifications"] if n.method == "turn/metaSkill/hint"]
    assert hints == []


def test_turn_survives_ws_disconnect_and_runs_server_side(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Audit T-01: a dropped WebSocket must NOT cancel a running turn.

    Before the fix, the turn ran inside the WS request task: closing
    the socket cancelled the consumer, whose finally tripped
    ``cancel_source`` and killed the producer thread — a network
    hiccup, lid-close or network switch destroyed a long turn. Turns
    now run as server-resident tasks behind a detached emitter, so the
    fake producer below is expected to run to NATURAL completion after
    the disconnect (its cancellation token is never tripped) and the
    resident task must drain on its own with nobody connected.
    """
    import threading
    import time

    import runtime.core.cerebrum.react_loop as rl
    from runtime.safety.approval.cancellation import current_cancellation_token
    from runtime.sensing.gateway.realtime_cerebrum import CerebrumRuntime
    from runtime.sensing.gateway.realtime_gateway import RealtimeGateway

    observed: dict[str, Any] = {"token_tripped": None}
    first_event_sent = threading.Event()

    def fake_stream(*args: Any, **kwargs: Any) -> Iterator[dict[str, Any]]:
        # Yield one event so the turn is clearly in-flight, then keep
        # the producer thread alive for a while, polling the
        # cancellation token. Under T-01 the token must NEVER trip as a
        # consequence of the disconnect; the thread returns naturally.
        yield {"type": "text_delta", "delta": "working"}
        first_event_sent.set()
        token = current_cancellation_token()
        deadline = time.monotonic() + 1.5
        while time.monotonic() < deadline:
            if token.is_cancelled:
                observed["token_tripped"] = True
                return
            time.sleep(0.05)
        observed["token_tripped"] = False

    monkeypatch.setattr(rl, "stream_react_loop", fake_stream)

    runtime = CerebrumRuntime(
        stack=object(),
        agent=object(),
        logs_root=str(tmp_path / "threads"),
    )
    gateway = RealtimeGateway(runtime=runtime, approval_timeout=5.0)
    app = FastAPI()
    app.include_router(gateway.router)

    with TestClient(app) as client:
        # Nested (not combined) on purpose: we exit the inner ws context
        # to simulate a mid-turn disconnect while staying inside client
        # to poll the outcome afterward.
        with client.websocket_connect("/api/realtime") as ws:
            ws.send_text(
                encode_message(
                    JsonRpcRequest(
                        id=1,
                        method="turn/start",
                        params={
                            "threadId": "th-disconnect",
                            "input": [{"type": "text", "text": "go"}],
                            "approvalPolicy": "never",
                        },
                    )
                )
            )
            # Wait until the producer has started streaming, then leave
            # the context → WebSocket disconnects mid-turn.
            assert first_event_sent.wait(timeout=5.0), "producer never started"
        # ws is now closed; the server-resident turn must keep running.

        deadline = time.monotonic() + 5.0
        while observed["token_tripped"] is None and time.monotonic() < deadline:
            time.sleep(0.05)

        assert observed["token_tripped"] is False, (
            "turn was cancelled by the ws disconnect — long turns must "
            "survive connection loss and run on server-side (audit T-01)"
        )

        # The resident task finishes on its own with nobody connected.
        deadline = time.monotonic() + 10.0
        while gateway._resident_turn_tasks and time.monotonic() < deadline:
            time.sleep(0.05)
        assert not gateway._resident_turn_tasks, (
            "resident turn did not drain after the requester left"
        )


def test_full_turn_dispatches_session_start_and_stop(
    gateway: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """dsh ``SessionStart`` / ``Stop``: a complete turn fires both hooks.

    The gateway must dispatch ``session_start`` once at turn entry and
    ``stop`` with success=True at the single exit funnel, regardless of
    how the turn ended.
    """
    import runtime.safety.hooks.runner as hook_runner

    calls: list[tuple[str, dict[str, Any]]] = []

    def _record(name: str) -> Any:
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            calls.append((name, kwargs))
            return None

        return wrapper

    monkeypatch.setattr(hook_runner, "dispatch_session_start", _record("session_start"))
    monkeypatch.setattr(hook_runner, "dispatch_stop", _record("stop"))

    client, _ = gateway
    _set_script([{"type": "text_delta", "delta": "ok"}, {"type": "react_completed"}])
    with client.websocket_connect("/api/realtime") as ws:
        out = _drive(
            ws,
            {
                "threadId": "th-hooks-ok",
                "input": [{"type": "text", "text": "go"}],
                "approvalPolicy": "never",
            },
        )

    assert out["response"].result["turn"]["status"] == "completed"
    assert [name for name, _ in calls] == ["session_start", "stop"]
    assert calls[0][1]["thread_id"] == "th-hooks-ok"
    stop_kwargs = calls[1][1]
    assert stop_kwargs["success"] is True
    assert stop_kwargs["thread_id"] == "th-hooks-ok"


def test_failed_turn_dispatches_stop_with_success_false(
    gateway: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """dsh ``Stop``: an error-ending turn still fires the stop hook, with
    success=False so downstream audit/metrics hooks can tell them apart.
    """
    import runtime.safety.hooks.runner as hook_runner

    calls: list[tuple[str, dict[str, Any]]] = []

    def _record(name: str) -> Any:
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            calls.append((name, kwargs))
            return None

        return wrapper

    monkeypatch.setattr(hook_runner, "dispatch_session_start", _record("session_start"))
    monkeypatch.setattr(hook_runner, "dispatch_stop", _record("stop"))

    client, _ = gateway
    _set_script(
        [
            {"type": "text_delta", "delta": "partial "},
            {"type": "react_error", "kind": "RuntimeError", "message": "boom", "iteration": 1},
        ]
    )
    with client.websocket_connect("/api/realtime") as ws:
        out = _drive(
            ws,
            {
                "threadId": "th-hooks-err",
                "input": [{"type": "text", "text": "go"}],
                "approvalPolicy": "never",
            },
        )

    assert out["response"].result["turn"]["status"] == "failed"
    assert [name for name, _ in calls] == ["session_start", "stop"]
    assert calls[1][1]["success"] is False
    assert calls[1][1]["thread_id"] == "th-hooks-err"


# ─── subagent wakeup → auto parent turn (dsh report lane) ─────────────


def _recv_deadline(ws: Any, timeout_s: float = 6.0) -> Any:
    """Receive one WS frame with a hard deadline (TestClient has none)."""
    import concurrent.futures

    ex = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        future = ex.submit(ws.receive_text)
        return decode_message(future.result(timeout=timeout_s))
    finally:
        # A timed-out receive stays blocked in the worker thread; do not
        # wait for it (the context-manager shutdown would deadlock).
        ex.shutdown(wait=False, cancel_futures=True)


def _wait_for_turn_event(ws: Any, method: str, timeout_s: float = 6.0) -> Notification:
    """Read frames until a ``turn/started`` / ``turn/completed`` arrives."""
    for _ in range(40):
        msg = _recv_deadline(ws, timeout_s=timeout_s)
        if isinstance(msg, Notification) and msg.method == method:
            return msg
    raise AssertionError(f"{method} never arrived")


def test_wakeup_report_opens_idle_parent_turn(gateway: Any, tmp_path: Path) -> None:
    from runtime.execution.subagents.sessions import (
        SubagentSessionStore,
        get_subagent_session_store,
        set_subagent_session_store,
    )

    client, logs_root = gateway
    store = SubagentSessionStore(
        base_dir=Path(logs_root) / "subagent_sessions",
        max_consecutive_wakes=2,
    )
    previous = get_subagent_session_store()
    set_subagent_session_store(store)
    try:
        session = store.create(agent_id="researcher", thread_id="th-auto")
        _set_script([{"type": "react_completed"}])
        with client.websocket_connect("/api/realtime") as ws:
            _drive(
                ws,
                {
                    "threadId": "th-auto",
                    "input": [{"type": "text", "text": "开始"}],
                    "approvalPolicy": "never",
                },
            )
            # Human turn registered the thread watcher.
            assert store.registered_thread_wake_handler("th-auto") is not None

            # A wakeup report while the thread is idle opens a NEW parent
            # turn with no client RPC — the report lane's production half.
            store.append_report(session.session_id, content="研究完成", delivery="wakeup")
            started = _wait_for_turn_event(ws, "turn/started")
            assert started.params["turn"]["threadId"] == "th-auto"
            auto_input = started.params["turn"]["params"]["input"][0]
            assert auto_input["text"] == "[子代理报告]"
            assert auto_input["metadata"]["context"]["auto_wake"] is True
            # The auto turn completes on its own.
            completed = _wait_for_turn_event(ws, "turn/completed")
            assert completed.params["turn"]["id"] == started.params["turn"]["id"]

            # The auto turn did NOT refill the consecutive-wake budget: a
            # second wakeup (budget 2, one spent) still wakes, but the third
            # degrades to quiet instead of chaining another turn.
            store.append_report(session.session_id, content="w2", delivery="wakeup")
            _wait_for_turn_event(ws, "turn/started")
            store.append_report(session.session_id, content="w3", delivery="wakeup")
            assert store.get(session.session_id).reports[-1].delivery == "quiet"
        # Connection close unwatches the thread: the store handler is gone.
        assert store.registered_thread_wake_handler("th-auto") is None
    finally:
        set_subagent_session_store(previous)


def test_auto_wake_turn_does_not_refill_budget(gateway: Any, tmp_path: Path) -> None:
    from runtime.execution.subagents.sessions import (
        SubagentSessionStore,
        get_subagent_session_store,
        set_subagent_session_store,
    )

    client, logs_root = gateway
    store = SubagentSessionStore(
        base_dir=Path(logs_root) / "subagent_sessions",
        max_consecutive_wakes=1,
    )
    previous = get_subagent_session_store()
    set_subagent_session_store(store)
    try:
        session = store.create(agent_id="researcher", thread_id="th-norefill")
        _set_script([{"type": "react_completed"}])
        with client.websocket_connect("/api/realtime") as ws:
            _drive(
                ws,
                {
                    "threadId": "th-norefill",
                    "input": [{"type": "text", "text": "开始"}],
                    "approvalPolicy": "never",
                },
            )
            # Wake 1 fires an auto turn and spends the only wake slot.
            store.append_report(session.session_id, content="w1", delivery="wakeup")
            _wait_for_turn_event(ws, "turn/started")
            _wait_for_turn_event(ws, "turn/completed")

            # Budget spent → next wakeup degrades to quiet, no auto turn.
            store.append_report(session.session_id, content="w2", delivery="wakeup")
            assert store.get(session.session_id).reports[-1].delivery == "quiet"
            # Quiet delivery is decided synchronously at the store and never
            # fires the wake handler, so the next human turn must be the only
            # turn on the stream (no stray auto turn ahead of it).
            out = _drive(
                ws,
                {
                    "threadId": "th-norefill",
                    "input": [{"type": "text", "text": "人工继续"}],
                    "approvalPolicy": "never",
                },
            )
            started_count = sum(1 for n in out["notifications"] if n.method == "turn/started")
            assert started_count == 1

            # A HUMAN turn refills the budget; the next wakeup wakes again.
            store.append_report(session.session_id, content="w3", delivery="wakeup")
            started = _wait_for_turn_event(ws, "turn/started")
            assert started.params["turn"]["threadId"] == "th-norefill"
    finally:
        set_subagent_session_store(previous)
