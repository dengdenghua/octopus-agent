from __future__ import annotations

import asyncio
import sys

import pytest
from a2a.server.agent_execution import RequestContext
from a2a.server.context import ServerCallContext
from a2a.types import Message, Part, Role, SendMessageRequest, Task, TaskState
from fastapi.testclient import TestClient

from runtime.execution.workbuddy_remote import (
    WorkBuddyConfig,
    WorkBuddyError,
    discover_command,
    stream_workbuddy,
)
from runtime.sensing.gateway.workbuddy_bridge import WorkBuddyExecutor, create_app


def config(tmp_path, **kwargs):
    return WorkBuddyConfig(command=(sys.executable,), data_dir=tmp_path, **kwargs)


def send(client, context_id=""):
    return client.post(
        "/a2a/rpc",
        headers={"A2A-Version": "1.0"},
        json={
            "jsonrpc": "2.0",
            "id": "req",
            "method": "SendMessage",
            "params": {
                "message": {
                    "messageId": "msg",
                    "contextId": context_id,
                    "role": "ROLE_USER",
                    "parts": [{"text": "Write a report"}],
                }
            },
        },
    )


def test_a2a_result_files_and_session_resume_survive_restart(tmp_path, monkeypatch):
    calls = []

    async def fake(config, **kwargs):
        calls.append(kwargs)
        yield {"type": "system", "subtype": "init", "session_id": "native-session-1"}
        yield {
            "type": "stream_event",
            "event": {"delta": {"type": "text_delta", "text": "progress " * 60}},
        }
        (kwargs["workspace"] / "report.txt").write_text("delivered", encoding="utf-8")
        (kwargs["workspace"] / ".secret").write_text("never export")
        yield {"type": "result", "subtype": "success", "is_error": False, "result": "Report ready"}

    monkeypatch.setattr("runtime.sensing.gateway.workbuddy_bridge.stream_workbuddy", fake)
    with TestClient(create_app(config(tmp_path)), base_url="http://127.0.0.1") as client:
        assert client.get("/.well-known/agent-card.json").json()["name"] == "WorkBuddy"
        response = send(client)
        assert response.status_code == 200, response.text
        task = response.json()["result"]["task"]
        assert task["status"]["state"] == "TASK_STATE_COMPLETED"
        assert task["history"][-1]["parts"][0]["text"] == "Report ready"
        files = [a for a in task["artifacts"] if a["name"] == "report.txt"]
        assert files[0]["parts"][0]["raw"] == "ZGVsaXZlcmVk"
        assert all(a["name"] != ".secret" for a in task["artifacts"])
    with TestClient(create_app(config(tmp_path)), base_url="http://127.0.0.1") as client:
        response = client.post(
            "/a2a/rpc",
            headers={"A2A-Version": "1.0"},
            json={"jsonrpc": "2.0", "id": "get", "method": "GetTask", "params": {"id": task["id"]}},
        )
        assert response.json()["result"]["status"]["state"] == "TASK_STATE_COMPLETED"
        response = send(client, task["contextId"])
        assert response.json()["result"]["task"]["status"]["state"] == "TASK_STATE_COMPLETED"
    assert calls[0]["resume"] is None
    assert calls[1]["resume"] == "native-session-1"
    assert calls[0]["workspace"] == calls[1]["workspace"]


def test_failure_and_browser_access(tmp_path, monkeypatch):
    async def fake(*args, **kwargs):
        yield {"type": "result", "subtype": "error", "is_error": True, "result": "secret-token"}

    monkeypatch.setattr("runtime.sensing.gateway.workbuddy_bridge.stream_workbuddy", fake)
    with TestClient(create_app(config(tmp_path)), base_url="http://127.0.0.1") as client:
        assert (
            client.post("/a2a/rpc", headers={"Origin": "https://evil.example"}).status_code == 403
        )
        assert client.get("/health", headers={"Host": "evil.example"}).status_code == 403
        response = send(client)
        assert "secret-token" not in response.text
        assert response.json()["result"]["task"]["status"]["state"] == "TASK_STATE_FAILED"
    with pytest.raises(ValueError, match="loopback"):
        create_app(config(tmp_path), public_url="http://0.0.0.0:8321")


class Queue:
    def __init__(self):
        self.events = []

    async def enqueue_event(self, event):
        self.events.append(event)


@pytest.mark.asyncio
async def test_cancel_closes_runner_before_reporting_canceled(tmp_path, monkeypatch):
    started, closed = asyncio.Event(), asyncio.Event()

    async def fake(*args, **kwargs):
        try:
            started.set()
            yield {"type": "system", "subtype": "init", "session_id": "session-1"}
            await asyncio.Event().wait()
        finally:
            closed.set()

    monkeypatch.setattr("runtime.sensing.gateway.workbuddy_bridge.stream_workbuddy", fake)
    executor = WorkBuddyExecutor(config(tmp_path))
    context = RequestContext(
        call_context=ServerCallContext(),
        task_id="task1",
        context_id="ctx1",
        request=SendMessageRequest(
            message=Message(message_id="m", role=Role.ROLE_USER, parts=[Part(text="run")])
        ),
    )
    execute_queue, cancel_queue = Queue(), Queue()
    running = asyncio.create_task(executor.execute(context, execute_queue))
    await asyncio.wait_for(started.wait(), 2)
    await executor.cancel(context, cancel_queue)
    assert closed.is_set()
    assert running.done()
    assert cancel_queue.events[-1].status.state == TaskState.TASK_STATE_CANCELED
    assert not any(
        isinstance(e, Task) and e.status.state == TaskState.TASK_STATE_COMPLETED
        for e in execute_queue.events
    )


@pytest.mark.asyncio
async def test_runner_passes_prompt_on_stdin_and_detects_missing_result(tmp_path):
    script = tmp_path / "fake_cli.py"
    script.write_text(
        "import sys,json\n"
        "text=sys.stdin.buffer.read().decode('utf-8')\n"
        "print(json.dumps({'type':'result','subtype':'success','is_error':False,'result':text}))\n",
        encoding="utf-8",
    )
    cfg = WorkBuddyConfig(command=(sys.executable, str(script)), data_dir=tmp_path)
    prompt = '中文 $(echo never) " --resume foreign-session'
    events = [event async for event in stream_workbuddy(cfg, prompt=prompt, workspace=tmp_path)]
    assert events[-1]["result"] == prompt
    script.write_text("print('not a protocol result')", encoding="utf-8")
    with pytest.raises(WorkBuddyError, match="未返回"):
        async for _ in stream_workbuddy(cfg, prompt="test", workspace=tmp_path):
            pass


@pytest.mark.asyncio
async def test_runner_timeout_terminates_child(tmp_path, monkeypatch):
    original = asyncio.create_subprocess_exec
    processes = []

    async def launch(*args, **kwargs):
        process = await original(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", launch)
    script = tmp_path / "sleep.py"
    script.write_text("import time\ntime.sleep(60)", encoding="utf-8")
    cfg = WorkBuddyConfig(command=(sys.executable, str(script)), data_dir=tmp_path, timeout=0.2)
    with pytest.raises(WorkBuddyError, match="超时"):
        async for _ in stream_workbuddy(cfg, prompt="test", workspace=tmp_path):
            pass
    assert processes and all(process.returncode is not None for process in processes)


def test_discovery_explicit_missing_does_not_fall_back(tmp_path):
    with pytest.raises(WorkBuddyError, match="未找到"):
        discover_command(str(tmp_path / "missing.exe"))


@pytest.mark.timeout(15)
def test_cancel_through_official_a2a_handler(tmp_path, monkeypatch):
    import threading

    started, closed = threading.Event(), threading.Event()

    async def fake(*args, **kwargs):
        try:
            started.set()
            yield {"type": "system", "subtype": "init", "session_id": "cancel-session"}
            await asyncio.Event().wait()
        finally:
            closed.set()

    monkeypatch.setattr("runtime.sensing.gateway.workbuddy_bridge.stream_workbuddy", fake)
    with TestClient(create_app(config(tmp_path)), base_url="http://127.0.0.1") as client:
        sent = client.post(
            "/a2a/rpc",
            headers={"A2A-Version": "1.0"},
            json={
                "jsonrpc": "2.0",
                "id": "start",
                "method": "SendMessage",
                "params": {
                    "configuration": {"returnImmediately": True},
                    "message": {
                        "messageId": "m1",
                        "role": "ROLE_USER",
                        "parts": [{"text": "wait"}],
                    },
                },
            },
        )
        assert sent.status_code == 200, sent.text
        task_id = sent.json()["result"]["task"]["id"]
        assert started.wait(3)
        canceled = client.post(
            "/a2a/rpc",
            headers={"A2A-Version": "1.0"},
            json={
                "jsonrpc": "2.0",
                "id": "cancel",
                "method": "CancelTask",
                "params": {"id": task_id},
            },
        )
        assert canceled.status_code == 200, canceled.text
        assert canceled.json()["result"]["status"]["state"] == "TASK_STATE_CANCELED"
        assert closed.is_set()
