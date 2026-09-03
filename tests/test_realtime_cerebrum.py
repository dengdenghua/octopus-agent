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
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

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

_REAL_STREAM_REACT_LOOP: Any = None


@pytest.fixture(autouse=True)
def _patch_react_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace the real stream_react_loop with a deterministic fake.

    The fake reads its script from a module-level list so individual
    tests can stage the event sequence they want. This is the cleanest
    seam the runtime exposes — substituting the planner keeps LLM,
    tool, and sandbox machinery out of the test.
    """
    import runtime.core.cerebrum.react_loop as rl

    global _REAL_STREAM_REACT_LOOP
    if _REAL_STREAM_REACT_LOOP is None:
        _REAL_STREAM_REACT_LOOP = rl.stream_react_loop

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
    _LAST_STREAM_ARGS.clear()
    _LAST_STREAM_KWARGS.clear()
    _LAST_SESSION.clear()


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
    retry = base[:mid] + "据公开披露约" + base[mid + 6 :]  # same-length fact fix

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
    second = (
        "# 智能睡眠行业调研报告\n\n"
        + "智能睡眠是睡眠经济与 AI 结合的最新赛道，覆盖监测硬件、助眠内容与数字疗法。" * 30
    )

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


def test_codex_partner_routes_to_app_server_before_legacy_cli(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The selected Codex role must enter one and only one inner engine."""
    from types import SimpleNamespace

    from runtime.platform.runtime_policy import feature_flags
    from runtime.sensing.gateway.realtime_cerebrum import CerebrumRuntime
    from runtime.sensing.gateway.realtime_gateway import RealtimeGateway

    monkeypatch.setenv("OCTOPUS_DEPLOYMENT_MODE", "local")
    monkeypatch.delenv("OCTOPUS_CODEX_APP_SERVER_ENABLED", raising=False)
    feature_flags.reload()
    calls: list[str] = []

    async def fake_codex(
        runtime: CerebrumRuntime,
        turn: Any,
        log: Any,
        emitter: Any,
        intent: Any,
        agent: Any,
        provider: Any,
        *,
        text: str,
    ) -> bool:
        del intent, agent, provider
        calls.append(f"app-server:{text}")
        await runtime._emit_agent_message(turn, log, emitter, "由 Codex App Server 完成")
        return True

    monkeypatch.setattr(CerebrumRuntime, "_drive_codex_app_server", fake_codex)
    agent = SimpleNamespace(
        agent_id="coder",
        display_name="Codex CLI 伙伴",
        capabilities={
            "execution_backend": "codex_app_server",
            "codex_app_server_executable": "/opt/octopus/bin/codex",
        },
    )
    runtime = CerebrumRuntime(
        stack=object(),
        agent=agent,
        logs_root=str(tmp_path / "threads"),
    )
    gateway = RealtimeGateway(runtime=runtime, approval_timeout=5.0)
    app = FastAPI()
    app.include_router(gateway.router)

    with TestClient(app) as client, client.websocket_connect("/api/realtime") as ws:
        out = _drive(
            ws,
            {
                "threadId": "th-codex-app-server",
                "input": [{"type": "text", "text": "修复测试"}],
                "approvalPolicy": "on-request",
            },
        )

    assert calls == ["app-server:修复测试"]
    turn = out["response"].result["turn"]
    assert turn["status"] == "completed"
    assert [item["text"] for item in turn["items"] if item["type"] == "agentMessage"] == [
        "由 Codex App Server 完成"
    ]


def test_codex_partner_failure_reports_the_actual_driver(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    from runtime.platform.runtime_policy import feature_flags
    from runtime.sensing.gateway.realtime_cerebrum import CerebrumRuntime
    from runtime.sensing.gateway.realtime_gateway import RealtimeGateway

    monkeypatch.setenv("OCTOPUS_DEPLOYMENT_MODE", "local")
    monkeypatch.delenv("OCTOPUS_CODEX_APP_SERVER_ENABLED", raising=False)
    feature_flags.reload()

    async def fail_codex(*_args: Any, **_kwargs: Any) -> bool:
        raise RuntimeError("codex protocol failed")

    monkeypatch.setattr(CerebrumRuntime, "_drive_codex_app_server", fail_codex)
    agent = SimpleNamespace(
        agent_id="coder",
        display_name="Codex CLI 伙伴",
        capabilities={
            "execution_backend": "codex_app_server",
            "codex_app_server_executable": "/opt/octopus/bin/codex",
        },
    )
    runtime = CerebrumRuntime(
        stack=object(),
        agent=agent,
        logs_root=str(tmp_path / "threads"),
    )
    gateway = RealtimeGateway(runtime=runtime, approval_timeout=5.0)
    app = FastAPI()
    app.include_router(gateway.router)

    with TestClient(app) as client, client.websocket_connect("/api/realtime") as ws:
        out = _drive(
            ws,
            {
                "threadId": "th-codex-app-server-error",
                "input": [{"type": "text", "text": "修复测试"}],
                "approvalPolicy": "on-request",
            },
        )

    turn = out["response"].result["turn"]
    assert turn["status"] == "failed"
    errors = [item for item in turn["items"] if item["type"] == "error"]
    assert errors[-1]["message"] == "codex protocol failed"
    assert errors[-1]["errorInfo"]["driver"] == "codex_app_server"


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


def test_turn_start_surfaces_pending_thread_reports(
    gateway: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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

        drained_reports: list[str] = []

        def _stream_with_initial_steering(*_args: Any, **kwargs: Any) -> Iterator[dict[str, Any]]:
            drained_reports.extend(kwargs["steering_drain"]())
            yield {"type": "react_completed"}

        import runtime.core.cerebrum.react_loop as rl

        monkeypatch.setattr(rl, "stream_react_loop", _stream_with_initial_steering)
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
        assert "[子代理报告] 部分发现" in drained_reports
        assert "[子代理报告] 最终结论" in drained_reports
        # Surfaced reports are claimed (acked) so the next turn does not
        # re-inject them (dsh inbox claim semantics).
        assert store.pending_reports(first.session_id) == []
        assert store.pending_reports(second.session_id) == []
    finally:
        set_subagent_session_store(previous)


def test_subagent_store_lock_does_not_block_turn_started_or_user_message(
    gateway: Any,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A durable session scan cannot hold the visible Send boundary."""

    import runtime.core.cerebrum.react_loop as rl
    from runtime.execution.subagents.sessions import (
        SubagentSessionStore,
        get_subagent_session_store,
        set_subagent_session_store,
    )

    client, logs_root = gateway
    pending_read_finished = threading.Event()
    drained_reports: list[str] = []

    def _fast_react_impl(*args: Any, **kwargs: Any) -> Iterator[dict[str, Any]]:
        drain = kwargs.get("steering_drain")
        if callable(drain):
            drained_reports.extend(drain())
        yield {"type": "react_completed"}

    # Preserve the production stream_react_loop lifecycle wrapper so this
    # regression really exercises mark_thread_busy/idle.  The autouse fake
    # replaces that wrapper wholesale and would make this lock test pass even
    # if those live markers still waited on the durable store lock.
    monkeypatch.setattr(rl, "stream_react_loop", _REAL_STREAM_REACT_LOOP)
    monkeypatch.setattr(rl, "_stream_react_loop_impl", _fast_react_impl)

    class _ObservedStore(SubagentSessionStore):
        def pending_thread_reports(self, thread_id: str) -> Any:
            try:
                return super().pending_thread_reports(thread_id)
            finally:
                pending_read_finished.set()

    store = _ObservedStore(base_dir=Path(logs_root) / "subagent_sessions")
    previous = get_subagent_session_store()
    set_subagent_session_store(store)
    session = store.create(agent_id="researcher", thread_id="th-slow-session-lock")
    store.append_report(session.session_id, content="稍后注入", delivery="quiet")
    lock_held = threading.Event()
    release_lock = threading.Event()
    lock_released = threading.Event()
    injection_attempted = threading.Event()

    import runtime.execution.subagents.sessions as sessions_module

    original_inject = sessions_module.inject_report_into_thread

    def _observe_inject(thread_id: str, content: str) -> bool:
        try:
            return original_inject(thread_id, content)
        finally:
            injection_attempted.set()

    monkeypatch.setattr(sessions_module, "inject_report_into_thread", _observe_inject)

    def _hold_durable_session_lock() -> None:
        # Deliberately model another thread doing a cold all-session scan.
        # Handler/injector registration must use its independent live lock;
        # refill + pending reads must happen only after the user item is sent.
        with store._lock:  # noqa: SLF001 - intentional contention injection
            lock_held.set()
            release_lock.wait(3.0)
        lock_released.set()

    holder = threading.Thread(target=_hold_durable_session_lock, daemon=True)
    holder.start()
    assert lock_held.wait(1.0)
    caplog.set_level(
        "INFO",
        logger="runtime.sensing.gateway.realtime_turn_lifecycle",
    )
    _set_script([{"type": "react_completed"}])
    response: JsonRpcResponse | None = None
    second_response: JsonRpcResponse | None = None
    notifications: list[Notification] = []
    try:
        with client.websocket_connect("/api/realtime") as ws:
            turn_sent_at = time.monotonic()
            ws.send_text(
                encode_message(
                    JsonRpcRequest(
                        id=1,
                        method="turn/start",
                        params={
                            "threadId": "th-slow-session-lock",
                            "userItemId": "itm_client_slow_lock_1",
                            "input": [{"type": "text", "text": "立即显示"}],
                            "approvalPolicy": "never",
                        },
                    )
                )
            )

            user_visible = False
            while not user_visible:
                msg = decode_message(ws.receive_text())
                if isinstance(msg, Notification):
                    notifications.append(msg)
                    item = msg.params.get("item") if isinstance(msg.params, dict) else None
                    user_visible = bool(
                        msg.method == "item/completed"
                        and isinstance(item, dict)
                        and item.get("type") == "userMessage"
                    )
                    continue
                if isinstance(msg, JsonRpcResponse):
                    pytest.fail("turn completed before the user message became visible")

            methods = [notification.method for notification in notifications]
            assert "turn/started" in methods
            assert not lock_released.is_set(), "store lock delayed the visible Send boundary"

            while response is None:
                msg = decode_message(ws.receive_text())
                if isinstance(msg, Notification):
                    notifications.append(msg)
                elif isinstance(msg, JsonRpcResponse) and msg.id == 1:
                    response = msg
            turn_elapsed = time.monotonic() - turn_sent_at
            # The one-second pending-report budget also bounds model start:
            # the real ReAct lifecycle wrapper (including busy+idle markers)
            # and fake model finish while the store's main lock is unavailable.
            assert not lock_released.is_set(), "store lock delayed turn execution"
            assert turn_elapsed < 2.0, f"turn completion waited {turn_elapsed:.2f}s for store lock"
            release_lock.set()
            assert pending_read_finished.wait(2.0)
            assert injection_attempted.wait(2.0)
            # The turn already unregistered its injector before the deferred
            # scan completed. Failed injection must not ack the durable report.
            assert len(store.pending_reports(session.session_id)) == 1

            # The next turn surfaces that same durable report exactly once and
            # only then advances its delivery cursor.
            second = _drive(
                ws,
                {
                    "threadId": "th-slow-session-lock",
                    "userItemId": "itm_client_slow_lock_2",
                    "input": [{"type": "text", "text": "继续处理报告"}],
                    "approvalPolicy": "never",
                },
            )
            second_response = second["response"]
            assert store.pending_reports(session.session_id) == []
    finally:
        release_lock.set()
        holder.join(timeout=3.0)
        set_subagent_session_store(previous)

    assert response is not None and response.error is None
    assert second_response is not None and second_response.error is None
    turn = response.result["turn"]
    assert turn["items"][0]["id"] == "itm_client_slow_lock_1"
    report_text = "[子代理报告] 稍后注入"
    assert drained_reports.count(report_text) == 1
    second_steering = [
        item
        for item in second_response.result["turn"]["items"]
        if item.get("type") == "steeringUserMessage"
    ]
    assert [item["text"] for item in second_steering].count(report_text) == 1
    timing_messages = [record.getMessage() for record in caplog.records]
    assert any(
        "realtime turn startup timing thread_id=th-slow-session-lock" in message
        and "active_register_ms=" in message
        and "created_to_turn_started_ms=" in message
        for message in timing_messages
    )
    assert any(
        "realtime pending reports timing thread_id=th-slow-session-lock" in message
        and "pending_reports_ms=" in message
        for message in timing_messages
    )


def test_subagent_store_lock_does_not_delay_interrupt_terminal(
    gateway: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Interrupt and ReAct busy/idle teardown stay off the durable store lock."""

    import runtime.core.cerebrum.react_loop as rl
    from runtime.execution.subagents.sessions import (
        SubagentSessionStore,
        get_subagent_session_store,
        set_subagent_session_store,
    )
    from runtime.safety.approval.cancellation import current_cancellation_token

    client, logs_root = gateway
    store = SubagentSessionStore(base_dir=Path(logs_root) / "subagent_interrupt_sessions")
    previous = get_subagent_session_store()
    set_subagent_session_store(store)
    producer_started = threading.Event()

    def _interruptible_impl(*args: Any, **kwargs: Any) -> Iterator[dict[str, Any]]:
        yield {
            "type": "react_started",
            "task_id": "task-live-lock-interrupt",
            "thread_id": kwargs.get("thread_id", ""),
        }
        producer_started.set()
        token = current_cancellation_token()
        while not token.is_cancelled:
            time.sleep(0.01)
        yield {"type": "react_cancelled", "iteration": 1}

    monkeypatch.setattr(rl, "stream_react_loop", _REAL_STREAM_REACT_LOOP)
    monkeypatch.setattr(rl, "_stream_react_loop_impl", _interruptible_impl)

    durable_locked = threading.Event()
    release_durable = threading.Event()
    durable_released = threading.Event()

    def _hold_durable_lock() -> None:
        with store._lock:  # noqa: SLF001 - intentional contention injection
            durable_locked.set()
            release_durable.wait(5.0)
        durable_released.set()

    holder = threading.Thread(target=_hold_durable_lock, daemon=True)
    holder.start()
    assert durable_locked.wait(1.0)
    final: JsonRpcResponse | None = None
    interrupt_sent_at: float | None = None
    try:
        with client.websocket_connect("/api/realtime") as ws:
            ws.send_text(
                encode_message(
                    JsonRpcRequest(
                        id=1,
                        method="turn/start",
                        params={
                            "threadId": "th-live-lock-interrupt",
                            "input": [{"type": "text", "text": "开始后立即停止"}],
                            "approvalPolicy": "never",
                        },
                    )
                )
            )
            turn_id: str | None = None
            while turn_id is None:
                message = decode_message(ws.receive_text())
                if isinstance(message, Notification) and message.method == "turn/started":
                    turn_id = message.params["turn"]["id"]
            # This event is set only after the production wrapper successfully
            # entered its inner loop, so a durable-lock-bound mark_thread_busy
            # makes the regression fail here rather than falsely passing.
            assert producer_started.wait(2.0), "ReAct wrapper waited on durable store lock"
            interrupt_sent_at = time.monotonic()
            ws.send_text(
                encode_message(
                    JsonRpcRequest(
                        id=99,
                        method="turn/interrupt",
                        params={
                            "threadId": "th-live-lock-interrupt",
                            "turnId": turn_id,
                        },
                    )
                )
            )
            while final is None:
                message = decode_message(ws.receive_text())
                if isinstance(message, JsonRpcResponse) and message.id == 1:
                    final = message

        assert interrupt_sent_at is not None
        interrupt_elapsed = time.monotonic() - interrupt_sent_at
        assert interrupt_elapsed < 2.0, (
            f"interrupt terminal waited {interrupt_elapsed:.2f}s for durable store lock"
        )
        assert not durable_released.is_set()
        assert final is not None and final.error is None
        assert final.result["turn"]["status"] == "cancelled"
    finally:
        release_durable.set()
        holder.join(timeout=5.0)
        set_subagent_session_store(previous)


def test_turn_start_user_item_id_is_stable_and_retry_is_idempotent(gateway: Any) -> None:
    from runtime.memory.threads.event_log import EventLog, thread_log_path

    client, logs_root = gateway
    params = {
        "threadId": "th-idempotent-user-item",
        "userItemId": "itm_client_retry_1234",
        "input": [
            {
                "type": "text",
                "text": "只执行一次",
                "metadata": {"client_message_id": "client-message-1234"},
            }
        ],
        "approvalPolicy": "never",
    }
    _set_script([{"type": "react_completed"}])
    with client.websocket_connect("/api/realtime") as ws:
        first = _drive(ws, params)
        retry = _drive(ws, params)
        conflicting_retry = _drive(
            ws,
            {
                **params,
                "input": [{"type": "text", "text": "恶意替换成另一条指令"}],
            },
        )

    first_turn = first["response"].result["turn"]
    retry_turn = retry["response"].result["turn"]
    assert retry_turn["id"] == first_turn["id"]
    assert retry["notifications"] == []
    assert conflicting_retry["response"].error is not None
    assert conflicting_retry["response"].error.code == JsonRpcErrorCode.INVALID_PARAMS
    assert conflicting_retry["notifications"] == []
    user_items = [item for item in first_turn["items"] if item["type"] == "userMessage"]
    assert [item["id"] for item in user_items] == ["itm_client_retry_1234"]
    assert first_turn["params"]["userItemId"] == "itm_client_retry_1234"
    assert (
        first_turn["params"]["input"][0]["metadata"]["client_message_id"] == "client-message-1234"
    )

    turns = EventLog(thread_log_path(logs_root, "th-idempotent-user-item")).replay()
    assert [turn.id for turn in turns] == [first_turn["id"]]


@pytest.mark.parametrize(
    "user_item_id",
    ["bad", "msg_not_an_item", "itm_has spaces", f"itm_{'a' * 100}"],
)
def test_turn_start_rejects_invalid_user_item_id(gateway: Any, user_item_id: str) -> None:
    client, logs_root = gateway
    with client.websocket_connect("/api/realtime") as ws:
        out = _drive(
            ws,
            {
                "threadId": "th-invalid-user-item-id",
                "userItemId": user_item_id,
                "input": [{"type": "text", "text": "不要执行"}],
                "approvalPolicy": "never",
            },
        )

    assert out["response"].error is not None
    assert out["response"].error.code == JsonRpcErrorCode.INVALID_PARAMS
    assert out["notifications"] == []
    assert not (Path(logs_root) / "th-invalid-user-item-id.jsonl").exists()


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
    # SUNSET: the embedded workbenchSnapshot no longer ships on
    # turn/plan/updated by default — the identical frame arrives on the
    # dedicated workbench/snapshot notification (asserted below).
    assert "workbenchSnapshot" not in updates[0].params

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


def test_persistent_cowork_chat_without_mention_completes_without_model(
    tmp_path: Path,
) -> None:
    from runtime.memory.cowork.collaboration_store import CollaborationStore
    from runtime.memory.cowork.group_store import GroupStore
    from runtime.memory.cowork.service import invite_member
    from runtime.memory.cowork.session import link_room
    from runtime.sensing.gateway.realtime_cerebrum import CerebrumRuntime
    from runtime.sensing.gateway.realtime_gateway import RealtimeGateway

    groups = GroupStore(base_dir=tmp_path / "cowork")
    collaboration = CollaborationStore(base_dir=tmp_path / "cowork")
    invite_member(groups, "th-project-room", actor="u", target_id="general", kind="agent")
    link_room(groups, "th-project-room", "room-project", actor="u")
    collaboration.upsert_room(
        "th-project-room",
        {"id": "room-project", "name": "Project room", "participants": []},
    )
    _set_script(
        [
            {"type": "text_delta", "delta": "must not run"},
            {"type": "react_completed"},
        ]
    )
    runtime = CerebrumRuntime(
        stack=object(),
        agent=object(),
        logs_root=str(tmp_path / "threads"),
        cowork_group_store=groups,
        collaboration_store=collaboration,
    )
    gateway = RealtimeGateway(runtime=runtime, approval_timeout=5.0)
    app = FastAPI()
    app.include_router(gateway.router)

    with TestClient(app) as client, client.websocket_connect("/api/realtime") as ws:
        out = _drive(
            ws,
            {
                "threadId": "th-project-room",
                "input": [{"type": "text", "text": "这是一条普通项目群消息"}],
                "approvalPolicy": "never",
            },
        )

    turn = out["response"].result["turn"]
    assert turn["status"] == "completed"
    assert turn["outcomeReason"] == "cowork_waiting_for_mention"
    assert [item["type"] for item in turn["items"]] == ["userMessage"]
    assert _LAST_STREAM_ARGS == {}

    messages = collaboration.messages_for_session("th-project-room")
    assert len(messages) == 1
    message = messages[0]
    user_item = turn["items"][0]
    assert message["text"] == "这是一条普通项目群消息"
    assert message["participant_id"] == "anonymous"
    assert message["display_name"] == "我"
    assert message["metadata"]["source_message_id"] == f"thread:{user_item['id']}"

    # Emulate the frontend's lazy Project-action mirror.  The shared source id
    # must resolve to the existing canonical row, never append a second copy.
    repeated_seq = collaboration.append_message(
        "th-project-room",
        room_id="room-project",
        text=message["text"],
        participant_id="anonymous",
        display_name="我",
        metadata={"source_message_id": message["metadata"]["source_message_id"]},
    )
    assert repeated_seq == message["seq"]
    assert len(collaboration.messages_for_session("th-project-room")) == 1


def test_persistent_cowork_chat_mention_drives_addressed_agent(
    tmp_path: Path,
) -> None:
    from runtime.memory.cowork.collaboration_store import CollaborationStore
    from runtime.memory.cowork.group_store import GroupStore
    from runtime.memory.cowork.service import invite_member
    from runtime.memory.cowork.session import link_room
    from runtime.sensing.gateway.realtime_cerebrum import CerebrumRuntime
    from runtime.sensing.gateway.realtime_gateway import RealtimeGateway

    class FakeAgent:
        def __init__(self, agent_id: str) -> None:
            self.agent_id = agent_id
            self.display_name = agent_id.title()

    class Registry:
        def __init__(self, agents: list[FakeAgent]) -> None:
            self.agents = {agent.agent_id: agent for agent in agents}

        def has(self, agent_id: str) -> bool:
            return agent_id in self.agents

        def get(self, agent_id: str) -> FakeAgent:
            return self.agents[agent_id]

    general = FakeAgent("general")
    eve = FakeAgent("eve")
    registry = Registry([general, eve])
    groups = GroupStore(base_dir=tmp_path / "cowork")
    collaboration = CollaborationStore(base_dir=tmp_path / "cowork")
    invite_member(groups, "th-addressed-room", actor="u", target_id="general", kind="agent")
    invite_member(groups, "th-addressed-room", actor="u", target_id="eve", kind="agent")
    link_room(groups, "th-addressed-room", "room-addressed", actor="u")
    collaboration.upsert_room(
        "th-addressed-room",
        {"id": "room-addressed", "name": "Addressed room", "participants": []},
    )
    _set_script(
        [
            {"type": "text_delta", "delta": "Eve handled it"},
            {"type": "react_completed"},
        ]
    )
    runtime = CerebrumRuntime(
        stack=object(),
        agent=general,
        agent_registry=registry,
        logs_root=str(tmp_path / "threads"),
        cowork_group_store=groups,
        collaboration_store=collaboration,
    )
    gateway = RealtimeGateway(runtime=runtime, approval_timeout=5.0)
    app = FastAPI()
    app.include_router(gateway.router)

    with TestClient(app) as client, client.websocket_connect("/api/realtime") as ws:
        out = _drive(
            ws,
            {
                "threadId": "th-addressed-room",
                "input": [{"type": "text", "text": "@agent:eve 请检查一下"}],
                "approvalPolicy": "never",
            },
        )

    turn = out["response"].result["turn"]
    assert turn["status"] == "completed"
    assert _LAST_STREAM_ARGS["args"][2] is eve
    assert [item["text"] for item in turn["items"] if item["type"] == "agentMessage"] == [
        "Eve handled it"
    ]
    messages = collaboration.messages_for_session("th-addressed-room")
    assert len(messages) == 1
    assert messages[0]["text"] == "@agent:eve 请检查一下"


def test_unlinked_single_agent_cowork_chat_keeps_one_to_one_react(
    tmp_path: Path,
) -> None:
    from runtime.memory.cowork.group_store import GroupStore
    from runtime.memory.cowork.service import invite_member
    from runtime.sensing.gateway.realtime_cerebrum import CerebrumRuntime
    from runtime.sensing.gateway.realtime_gateway import RealtimeGateway

    groups = GroupStore(base_dir=tmp_path / "cowork")
    invite_member(groups, "th-private", actor="u", target_id="general", kind="agent")
    _set_script(
        [
            {"type": "text_delta", "delta": "normal reply"},
            {"type": "react_completed"},
        ]
    )
    default_agent = object()
    runtime = CerebrumRuntime(
        stack=object(),
        agent=default_agent,
        logs_root=str(tmp_path / "threads"),
        cowork_group_store=groups,
    )
    gateway = RealtimeGateway(runtime=runtime, approval_timeout=5.0)
    app = FastAPI()
    app.include_router(gateway.router)

    with TestClient(app) as client, client.websocket_connect("/api/realtime") as ws:
        out = _drive(
            ws,
            {
                "threadId": "th-private",
                "input": [{"type": "text", "text": "hello"}],
                "approvalPolicy": "never",
            },
        )

    turn = out["response"].result["turn"]
    assert turn["status"] == "completed"
    assert _LAST_STREAM_ARGS["args"][2] is default_agent
    assert [item["text"] for item in turn["items"] if item["type"] == "agentMessage"] == [
        "normal reply"
    ]


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

    def fake_member_call(
        *,
        agent_id: str,
        prompt: str,
        context: dict[str, Any] | None = None,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        seen.setdefault("member_calls", []).append(
            {
                "agent_id": agent_id,
                "prompt": prompt,
                "context": dict(context or {}),
            }
        )
        return {"success": True, "output": f"{agent_id} replied", "error": None}

    monkeypatch.setattr(
        "runtime.execution.suckers.delegation_skills._call_agent",
        fake_member_call,
    )

    def fake_fanout(message: str, members: list[dict[str, Any]], **_kwargs: Any) -> dict[str, Any]:
        seen["message"] = message
        seen["members"] = members
        caller = _kwargs["agent_caller"]
        for member in members:
            caller(
                agent_id=member["name"],
                prompt=f"fanout prompt for {member['name']}",
            )
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
                "input": [
                    {
                        "type": "text",
                        "text": "大家一起看下",
                        "metadata": {
                            "context": {
                                "agent_mode": "audit",
                                "personal_mode": "research",
                                "personal_instructions": "优先引用一手来源。",
                                "workflow_preset": "audit.deep",
                                "verification_policy": "strict",
                            }
                        },
                    }
                ],
                "approvalPolicy": "never",
            },
        )

    assert seen["message"] == "大家一起看下"
    assert [m["name"] for m in seen["members"]] == ["db-agent", "ui-agent"]
    assert len(seen["member_calls"]) == 2
    for member_call in seen["member_calls"]:
        member_context = member_call["context"]
        assert member_context["agent_mode"] == "audit"
        assert member_context["personal_mode"] == "research"
        assert member_context["personal_instructions"] == "优先引用一手来源。"
        assert member_context["workflow_preset"] == "audit.deep"
        assert member_context["verification_policy"] == "strict"
        assert member_context["tool_allowlist_read_only"] is True
        assert "audit.deep" in member_context["system_addendum"]
        assert "当前任务类型: research" in member_context["system_addendum"]
        assert "audit.deep" in member_call["prompt"]
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


def test_legacy_project_mode_does_not_auto_create_or_run_project_os(tmp_path: Path) -> None:
    from runtime.memory.cowork.group_store import GroupStore
    from runtime.memory.cowork.service import invite_member, set_mode
    from runtime.projectos.store import ProjectStore
    from runtime.sensing.gateway.realtime_cerebrum import CerebrumRuntime
    from runtime.sensing.gateway.realtime_gateway import RealtimeGateway

    store = GroupStore(base_dir=tmp_path / "cowork")
    invite_member(store, "th-project", actor="u", target_id="research-agent", kind="agent")
    invite_member(store, "th-project", actor="u", target_id="build-agent", kind="agent")
    set_mode(store, "th-project", actor="u", mode="project")
    assert store.state("th-project").mode == "chat"
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
    # The canonical chat strategy waits for an @mention in a multi-agent room;
    # critically, the ordinary sentence cannot create or run Project OS.
    assert turn["status"] == "completed"
    assert agent_texts == []
    assert project_store.list_projects() == []
    assert project_store.project_for_thread("th-project") is None


def test_authenticated_explicit_project_command_owns_project_and_subagent_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from runtime.memory.cowork.group_store import GroupStore
    from runtime.memory.cowork.service import invite_member
    from runtime.memory.threads import ThreadStateStore
    from runtime.projectos.llm_hooks import subagent_execute_task
    from runtime.projectos.model import Milestone, Task
    from runtime.projectos.store import ProjectStore
    from runtime.safety.auth import Identity, IdentityStore
    from runtime.safety.auth.scope import TenantScope
    from runtime.sensing.gateway.realtime_cerebrum import CerebrumRuntime
    from runtime.sensing.gateway.realtime_gateway import RealtimeGateway
    from runtime.sensing.gateway.thread_workspace import managed_workspace_path

    thread_id = "th-auth-project"
    groups = GroupStore(base_dir=tmp_path / "cowork")
    invite_member(groups, thread_id, actor="alice", target_id="build-agent", kind="agent")
    projects = ProjectStore(base_dir=tmp_path / "projectos")
    threads = ThreadStateStore()
    workspace_root = tmp_path / "managed"
    dispatched: list[dict[str, Any]] = []

    def fake_call_subagent(_agent: str, _prompt: str, **kwargs: Any) -> dict[str, Any]:
        dispatched.append(dict(kwargs.get("context") or {}))
        return {"success": True, "output": "delivered"}

    monkeypatch.setattr(
        "runtime.execution.subagents.call_subagent",
        fake_call_subagent,
    )

    def milestones(goal: str) -> list[Milestone]:
        return [Milestone(id="MS-auth", name="build", goal=goal)]

    def tasks(milestone: Milestone) -> list[Task]:
        return [
            Task(
                id="MS-auth-T1",
                milestone_id=milestone.id,
                type="code",
                goal="deliver securely",
            )
        ]

    runtime = CerebrumRuntime(
        stack=object(),
        agent=object(),
        logs_root=str(tmp_path / "logs"),
        workspace_root=workspace_root,
        thread_store=threads,
        cowork_group_store=groups,
        project_store=projects,
        project_os_hooks={
            "generate_milestones": milestones,
            "decompose_tasks": tasks,
            "execute_task": subagent_execute_task,
            "qa_task": lambda _task, _milestone: {"approved": True, "reason": "ok"},
        },
    )
    identities = IdentityStore()
    identities.add(
        Identity(actor_id="alice", metadata={"tenant_id": "tenant-a"}),
        api_key_plaintext="sk-alice",
    )
    gateway = RealtimeGateway(
        runtime=runtime,
        approval_timeout=5.0,
        identity_store=identities,
        require_auth=True,
    )
    app = FastAPI()
    app.include_router(gateway.router)
    outside = tmp_path / "client-selected"

    with (
        TestClient(app) as client,
        client.websocket_connect(
            "/api/realtime",
            headers={"Authorization": "Bearer sk-alice"},
        ) as ws,
    ):
        created = _drive(
            ws,
            {
                "threadId": thread_id,
                "cwd": str(outside),
                "input": [
                    {
                        "type": "text",
                        "text": "/project run 交付认证项目",
                        "metadata": {
                            "context": {
                                "workspace_path": str(outside),
                                "extra_workspaces": [str(tmp_path)],
                            }
                        },
                    }
                ],
                "approvalPolicy": "never",
            },
        )
        reported = _drive(
            ws,
            {
                "threadId": thread_id,
                "input": [{"type": "text", "text": "/project report"}],
            },
        )

    assert created["response"].result["turn"]["status"] == "completed"
    report_text = "\n".join(
        item["text"]
        for item in reported["response"].result["turn"]["items"]
        if item["type"] == "agentMessage"
    )
    assert "Project OS 已执行控制命令" in report_text

    project = projects.project_for_thread(thread_id)
    assert project is not None
    assert project.owner_id == "alice"
    assert project.tenant_id == "tenant-a"
    assert projects.with_scope(
        TenantScope(tenant_id="tenant-a", actor_id="alice")
    ).list_projects() == [project]
    assert (
        projects.with_scope(TenantScope(tenant_id="tenant-a", actor_id="bob")).list_projects() == []
    )

    expected = managed_workspace_path(
        workspace_root,
        tenant_id="tenant-a",
        actor_id="alice",
        thread_id=thread_id,
    )
    persisted = threads.get(thread_id)["metadata"]
    assert persisted["workspace_path"] == str(expected)
    assert persisted["owner_actor_id"] == "alice"
    assert persisted["tenant_id"] == "tenant-a"
    assert dispatched
    dispatch = dispatched[0]
    assert dispatch["thread_id"] == thread_id
    assert dispatch["actor"] == "alice"
    assert dispatch["tenant_id"] == "tenant-a"
    assert dispatch["workspace_path"] == str(expected)
    runtime_metadata = dispatch["runtime_session_metadata"]
    assert runtime_metadata["workspace_path"] == str(expected)
    assert runtime_metadata["_artifact_output_root"] == str(expected / "output" / "final")


def test_explicit_project_command_unhandled_failure_reports_driver_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from runtime.memory.cowork.group_store import GroupStore
    from runtime.memory.cowork.service import invite_member
    from runtime.projectos.store import ProjectStore
    from runtime.sensing.gateway.realtime_cerebrum import CerebrumRuntime
    from runtime.sensing.gateway.realtime_gateway import RealtimeGateway

    store = GroupStore(base_dir=tmp_path / "cowork")
    invite_member(store, "th-project-fail", actor="u", target_id="research-agent", kind="agent")

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
                "input": [{"type": "text", "text": "/project run 启动项目"}],
                "approvalPolicy": "never",
            },
        )

    turn = out["response"].result["turn"]
    assert turn["status"] == "failed"
    errors = [item for item in turn["items"] if item["type"] == "error"]
    assert errors[-1]["message"] == "project engine exploded"
    assert errors[-1]["errorInfo"]["code"] == "turn_driver_exception"
    assert errors[-1]["errorInfo"]["driver"] == "project_os"
    assert errors[-1]["errorInfo"]["cowork_mode"] == "chat"


def test_explicit_project_command_reuses_active_project(
    tmp_path: Path,
) -> None:
    from runtime.memory.cowork.group_store import GroupStore
    from runtime.memory.cowork.service import invite_member
    from runtime.projectos.store import ProjectStore
    from runtime.sensing.gateway.realtime_cerebrum import CerebrumRuntime
    from runtime.sensing.gateway.realtime_gateway import RealtimeGateway

    store = GroupStore(base_dir=tmp_path / "cowork")
    invite_member(store, "th-project", actor="u", target_id="research-agent", kind="agent")
    invite_member(store, "th-project", actor="u", target_id="build-agent", kind="agent")
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
                        "text": "/project run 启动项目",
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
                "input": [{"type": "text", "text": "/project run 继续"}],
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
    from runtime.sensing.gateway._realtime_cerebrum_project_os import _is_project_os_command
    from runtime.sensing.gateway.realtime_cerebrum import _parse_project_os_control

    assert _parse_project_os_control("hello") is None
    assert _parse_project_os_control("/project run ship the roadmap") == {
        "type": "run",
        "goal": "ship the roadmap",
    }
    assert _parse_project_os_control("/project start 'secure launch'") == {
        "type": "run",
        "goal": "secure launch",
    }
    assert _is_project_os_command("/projectile report") is False
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


def test_explicit_project_command_accepts_task_control_command(
    tmp_path: Path,
) -> None:
    from runtime.memory.cowork.group_store import GroupStore
    from runtime.memory.cowork.service import invite_member
    from runtime.projectos.store import ProjectStore
    from runtime.sensing.gateway.realtime_cerebrum import CerebrumRuntime
    from runtime.sensing.gateway.realtime_gateway import RealtimeGateway

    store = GroupStore(base_dir=tmp_path / "cowork")
    invite_member(store, "th-project-control", actor="u", target_id="research-agent", kind="agent")
    invite_member(store, "th-project-control", actor="u", target_id="build-agent", kind="agent")
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
                        "text": "/project run 启动项目",
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


def test_explicit_project_command_reports_failed_task_control_command(
    tmp_path: Path,
) -> None:
    from runtime.memory.cowork.group_store import GroupStore
    from runtime.memory.cowork.service import invite_member
    from runtime.projectos.store import ProjectStore
    from runtime.sensing.gateway.realtime_cerebrum import CerebrumRuntime
    from runtime.sensing.gateway.realtime_gateway import RealtimeGateway

    store = GroupStore(base_dir=tmp_path / "cowork")
    invite_member(store, "th-project-control-fail", actor="u", target_id="agent-a", kind="agent")
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
                        "text": "/project run 启动项目",
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


def test_local_context_project_binding_becomes_execution_cwd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from runtime.platform.runtime_policy.workspaces import WorkspaceManager
    from runtime.protocol.items import TurnParams
    from runtime.sensing.gateway.realtime_cerebrum import _build_intent

    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setenv("OCTOPUS_DEPLOYMENT_MODE", "local")
    monkeypatch.setenv("OCTOPUS_FS_ALLOWED_ROOTS", str(tmp_path))
    params = TurnParams.model_validate(
        {
            "threadId": "th-context-project",
            "input": [
                {
                    "type": "text",
                    "text": "inspect the project",
                    "metadata": {
                        "context": {
                            "mode": "code",
                            "workspace_path": str(project),
                            "workspace_scope": "project",
                        }
                    },
                }
            ],
        }
    )

    intent = _build_intent(
        "inspect the project",
        params,
        workspaces=WorkspaceManager(tmp_path / "managed"),
    )

    assert intent.user_context["cwd"] == str(project.resolve())
    assert intent.user_context["workspace_path"] == str(project.resolve())
    assert intent.user_context["workspace_scope"] == "project"


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
            return {"metadata": {"agent": "installed_researcher", "mode": "react"}}

    metadata = build_turn_metadata(
        thread_id="th-opencode",
        body={"context": {"agent_name": "general", "mode": "code"}},
        store=Store(),
    )

    assert metadata["agent"] == "installed_researcher"
    assert metadata["agent_name"] == "installed_researcher"


def test_agent_resolution_prefers_existing_thread_owner() -> None:
    from runtime.protocol.items import TurnParams
    from runtime.sensing.gateway._realtime_cerebrum_thread import _resolve_agent

    owner = object()
    requested = object()

    class Registry:
        agents = {
            "installed_researcher": owner,
            "general": requested,
        }

        def has(self, agent_id: str) -> bool:
            return agent_id in self.agents

        def get(self, agent_id: str) -> object:
            return self.agents[agent_id]

    class Store:
        def get(self, thread_id: str) -> dict[str, object]:
            assert thread_id == "th-opencode"
            return {"metadata": {"agent": "installed_researcher"}}

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


def test_transient_model_disconnect_is_retryable_and_preserves_progress_copy(gateway: Any) -> None:
    client, _ = gateway
    _set_script(
        [
            {"type": "text_delta", "delta": "已完成一部分"},
            {
                "type": "react_error",
                "kind": "RemoteProtocolError",
                "message": "Server disconnected without sending a response",
                "iteration": 2,
            },
        ]
    )
    with client.websocket_connect("/api/realtime") as ws:
        out = _drive(
            ws,
            {
                "threadId": "th-transient-disconnect",
                "input": [{"type": "text", "text": "go"}],
                "approvalPolicy": "never",
            },
        )

    turn = out["response"].result["turn"]
    err = next(item for item in turn["items"] if item["type"] == "error")
    assert err["willRetry"] is True
    assert "已完成的步骤" in err["message"]
    assert err["errorInfo"]["code"] == "model_stream_disconnected"
    assert turn["outcomeReason"] == "model_stream_disconnected"


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
    assert resumed_turn["status"] == "interrupted"
    assert resumed_turn["error"]["code"] == "stale_in_progress_turn"

    replayed = log.replay()
    assert replayed[0].status.value == "interrupted"


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
