"""Exercise the inner SSE boundary without a provider account or model calls."""

import asyncio
import json

import httpx
import pytest

from runtime.execution.opencode_backend import MessageEvents, stream_prompt
from runtime.execution.opencode_events import TurnEvents, message_id, receive_events


class EventStream(httpx.AsyncByteStream):
    def __init__(self):
        self.queue = asyncio.Queue()
        self.closed = False

    async def __aiter__(self):
        while True:
            event = await self.queue.get()
            if event is None:
                return
            yield ("data: " + json.dumps(event) + "\n\n").encode()

    async def aclose(self):
        self.closed = True


def assistant(parent, text="Hello"):
    return {
        "info": {
            "id": "msg_answer",
            "sessionID": "ses_test",
            "role": "assistant",
            "parentID": parent,
            "finish": "stop",
        },
        "parts": [
            {
                "id": "prt_text",
                "messageID": "msg_answer",
                "sessionID": "ses_test",
                "type": "text",
                "text": text,
            }
        ],
    }


def test_current_turn_identity_and_unknown_reasoning_never_leak():
    p = TurnEvents("ses_test", "msg_user", MessageEvents(set()))
    owned = assistant("msg_user", "H")
    alien = assistant("another_user", "private")
    p.consume({"type": "message.updated", "properties": {"info": alien["info"]}})
    assert (
        p.consume({"type": "message.part.updated", "properties": {"part": alien["parts"][0]}}) == []
    )
    p.consume({"type": "message.updated", "properties": {"info": owned["info"]}})
    props = {
        "sessionID": "ses_test",
        "messageID": "msg_answer",
        "partID": "unknown",
        "field": "text",
        "delta": "private reasoning",
    }
    assert p.consume({"type": "message.part.delta", "properties": props}) == []
    assert p.snapshots([assistant("another_user")]) == []
    assert (
        p.consume({"type": "message.part.updated", "properties": {"part": owned["parts"][0]}})[0][
            "delta"
        ]
        == "H"
    )
    props.update(partID="prt_text", delta="i")
    assert p.consume({"type": "message.part.delta", "properties": props})[0]["delta"] == "i"
    assert (
        p.consume({"type": "message.part.updated", "properties": {"part": owned["parts"][0]}}) == []
    )
    assert p.snapshots([assistant("msg_user", "Hi!")])[0]["delta"] == "!"


def test_message_ids_are_native_shaped_and_ordered():
    ids = [message_id() for _ in range(100)]
    assert ids == sorted(set(ids))
    assert all(len(value) == 30 and value.startswith("msg_") for value in ids)


@pytest.mark.asyncio
@pytest.mark.parametrize("disconnect", [False, True])
async def test_streams_before_post_finishes_and_reconciles_without_resubmitting(disconnect):
    stream = EventStream()
    release = asyncio.Event()
    submitted = asyncio.Event()
    calls = []
    parent = ""

    async def handle(request):
        nonlocal parent
        calls.append((request.method, request.url.path))
        if request.url.path == "/event":
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=stream)
        if request.method == "POST":
            parent = json.loads(request.content)["messageID"]
            submitted.set()
            msg = assistant(parent, "")
            for event in [
                {"type": "message.updated", "properties": {"info": msg["info"]}},
                {"type": "message.part.updated", "properties": {"part": msg["parts"][0]}},
                {
                    "id": "evt_one",
                    "type": "message.part.delta",
                    "properties": {
                        "sessionID": "ses_test",
                        "messageID": "msg_answer",
                        "partID": "prt_text",
                        "field": "text",
                        "delta": "Hel",
                    },
                },
            ]:
                await stream.queue.put(event)
            await stream.queue.put(event)  # Same event ID must not append twice.
            if disconnect:
                await stream.queue.put(None)
            await release.wait()
            return httpx.Response(200, json=assistant(parent))
        return httpx.Response(200, json=[assistant(parent)] if submitted.is_set() else [])

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handle), base_url="http://localhost"
    ) as client:
        events = stream_prompt(
            client,
            "ses_test",
            text="hello",
            system="role",
            model="big-pickle",
            interrupted=lambda: False,
            poll_s=0.005,
        )
        first = await asyncio.wait_for(anext(events), 1)
        assert first["delta"] == "Hel"
        assert not release.is_set()
        if disconnect:
            # Native snapshot repairs the missing suffix after a stream gap.
            assert (await asyncio.wait_for(anext(events), 1))["delta"] == "lo"
        release.set()
        rest = [event async for event in events]
        assert rest[-1]["type"] == "react_completed"
        if not disconnect:
            assert (
                first["delta"] + "".join(e["delta"] for e in rest if e["type"] == "text_delta")
                == "Hello"
            )
    assert calls.count(("POST", "/session/ses_test/message")) == 1
    assert calls.count(("GET", "/session/ses_test/message")) == (3 if disconnect else 2)
    assert stream.closed


@pytest.mark.asyncio
async def test_cancel_waits_for_idle_and_marks_client_for_retirement():
    submitted = asyncio.Event()
    idle = asyncio.Event()
    status_checked = asyncio.Event()

    async def handle(request):
        if request.url.path == "/event":
            return httpx.Response(404)
        if request.url.path.endswith("/abort"):
            return httpx.Response(200, json=True)
        if request.url.path == "/session/status":
            status_checked.set()
            return httpx.Response(
                200, json={"ses_test": {"type": "idle" if idle.is_set() else "busy"}}
            )
        if request.method == "POST":
            submitted.set()
            await asyncio.Event().wait()
        return httpx.Response(200, json=[])

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handle), base_url="http://localhost"
    ) as client:

        async def collect():
            return [
                e
                async for e in stream_prompt(
                    client,
                    "ses_test",
                    text="hello",
                    system="role",
                    model="big-pickle",
                    interrupted=submitted.is_set,
                    poll_s=0.001,
                )
            ]

        task = asyncio.create_task(collect())
        await asyncio.wait_for(status_checked.wait(), 1)
        assert not task.done()
        idle.set()
        events = await asyncio.wait_for(task, 1)
        assert events == [{"type": "react_cancelled", "reason": "用户停止了任务"}]
        assert client._echo_reusable is False


@pytest.mark.asyncio
async def test_sse_queue_backpressure_and_shutdown():
    stream = EventStream()
    for i in range(500):
        stream.queue.put_nowait({"id": str(i), "type": "server.heartbeat"})
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200, headers={"content-type": "text/event-stream"}, stream=stream
            )
        ),
        base_url="http://localhost",
    ) as client:
        queue = asyncio.Queue(maxsize=2)
        ready = asyncio.Event()
        task = asyncio.create_task(receive_events(client, queue, ready))
        await ready.wait()
        await asyncio.sleep(0.01)
        assert queue.qsize() == 2
        assert not task.done()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        assert stream.closed


@pytest.mark.asyncio
@pytest.mark.parametrize("abort_status", [200, 500])
async def test_task_cancellation_aborts_and_retires_warm_process(
    tmp_path, monkeypatch, abort_status
):
    from types import SimpleNamespace

    from runtime.execution import opencode_backend as backend

    submitted = asyncio.Event()
    aborted = []
    stopped = []
    post_closed = asyncio.Event()
    stream = EventStream()

    async def handle(request):
        if request.url.path == "/event":
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=stream)
        if request.url.path.endswith("/abort"):
            aborted.append(request.url.path)
            return httpx.Response(abort_status, json=True)
        if request.url.path == "/session/status":
            return httpx.Response(200, json={})
        if request.method == "POST":
            submitted.set()
            try:
                await asyncio.Event().wait()
            finally:
                post_closed.set()
        return httpx.Response(200, json=[])

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handle), base_url="http://localhost"
    ) as client:
        process = SimpleNamespace(returncode=None)

        async def start(*args, **kwargs):
            return process, client

        async def stop(*args):
            stopped.append(args)

        monkeypatch.setattr(backend, "_start_server", start)
        monkeypatch.setattr(backend, "_stop_server", stop)
        monkeypatch.setattr(backend, "_warm_servers", {})
        monkeypatch.setattr(backend, "_warm_lock", None)
        monkeypatch.setattr(backend, "_warm_lock_loop", None)

        async def run():
            async with backend.managed_server(
                "opencode", tmp_path, None, "big-pickle", False
            ) as current:
                async for _ in stream_prompt(
                    current,
                    "ses_test",
                    text="hello",
                    system="role",
                    model="big-pickle",
                    interrupted=lambda: False,
                ):
                    pass

        task = asyncio.create_task(run())
        await asyncio.wait_for(submitted.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 1)
        assert aborted == ["/session/ses_test/abort"]
        assert stopped == [(process, client)]
        assert not backend._warm_servers
        assert post_closed.is_set()
        assert stream.closed
