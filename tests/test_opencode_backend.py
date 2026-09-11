"""OpenCode boundary: credentials, session isolation, terminal errors and abort."""

import asyncio
import json

import httpx
import pytest

from runtime.execution.engines import (
    EngineId,
    ExecutionPhase,
    select_execution_route,
)
from runtime.execution.opencode_backend import (
    MessageEvents,
    OpenCodeError,
    child_environment,
    resolve_zen_model,
    state_directory,
    stream_prompt,
    validate_catalog_model,
)
from runtime.execution.tool_engine.host_mcp import HostMCPConnection
from runtime.platform.models.custom_model_selection import custom_model_selection_id
from runtime.protocol.items import ExecutionSnapshot, TurnParams
from runtime.safety.auth.scope import TenantScope


def test_go_selection_and_child_route_are_isolated_from_zen(tmp_path):
    from runtime.execution.opencode_backend import model_selection_id
    catalog = {provider: {"managed_by_plugin": provider, "models": ["glm-5.3"]} for provider in ("opencode-go", "opencode-zen")}
    selection = custom_model_selection_id("opencode-go", "glm-5.3")
    resolved = resolve_zen_model(selection, catalog)
    assert resolved == "opencode-go/glm-5.3"
    assert model_selection_id(resolved) == selection
    env = child_environment(tmp_path, "test-go-key", "test-password", resolved, False)
    config = json.loads(env["OPENCODE_CONFIG_CONTENT"])
    assert config["model"] == "opencode-go/glm-5.3"
    assert config["small_model"] == config["model"]
    assert set(config["provider"]) == {"opencode-go"}
    assert config["provider"]["opencode-go"]["options"]["baseURL"] == "https://opencode.ai/zen/go/v1"
    with pytest.raises(OpenCodeError, match="Go"):
        child_environment(tmp_path, None, "test-password", resolved, False)
    with pytest.raises(OpenCodeError, match="Go"):
        resolve_zen_model("opencode-go/glm-5.3", {})


@pytest.mark.parametrize("model,package", [
    ("grok-4.6", "@ai-sdk/openai"),
    ("muse-spark-1.3-contributor", "@ai-sdk/openai"),
    ("minimax-m3", "@ai-sdk/anthropic"),
    ("qwen3.8-max", "@ai-sdk/anthropic"),
    ("kimi-k3", "@ai-sdk/openai-compatible"),
])
def test_go_uses_official_model_wire_protocol(tmp_path, model, package):
    env = child_environment(tmp_path, "fake-key", "fake-password", f"opencode-go/{model}", False)
    provider = json.loads(env["OPENCODE_CONFIG_CONTENT"])["provider"]["opencode-go"]
    assert provider["npm"] == package
    assert provider["options"]["headers"]["User-Agent"] == "Echo/1.0"
    assert provider["options"]["headers"]["x-opencode-session"]


def test_text_only_server_reuses_one_warm_process(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from runtime.execution import opencode_backend as backend

    starts = []
    stops = []

    class Client:
        async def get(self, path, **kwargs):
            assert path == "/global/health"
            return SimpleNamespace(status_code=200, json=lambda: {"healthy": True})

    client = Client()
    process = SimpleNamespace(returncode=None, terminate=lambda: None)

    async def start(*args, **kwargs):
        starts.append((args, kwargs))
        return process, client

    async def stop(*args):
        stops.append(args)

    async def validate(*args, **kwargs):
        return None

    monkeypatch.setattr(backend, "_start_server", start)
    monkeypatch.setattr(backend, "_stop_server", stop)
    monkeypatch.setattr(backend, "validate_catalog_model", validate)
    backend._warm_servers.clear()
    backend._warm_lock = None
    backend._warm_lock_loop = None

    async def run():
        seen = []
        for _ in range(2):
            async with backend.managed_server(
                "opencode", tmp_path, None, "big-pickle", False
            ) as current:
                seen.append(current)
        entry = next(iter(backend._warm_servers.values()), None)
        assert entry is not None
        if entry.idle_handle is not None:
            entry.idle_handle.cancel()
        backend._warm_servers.clear()
        await stop(entry.process, entry.client)
        return seen

    assert asyncio.run(run()) == [client, client]
    assert len(starts) == 1
    assert len(stops) == 1


def test_explicit_engine_and_continuations():
    route = select_execution_route(requested_engine=EngineId.OPENCODE, codex_partner=True)
    assert route.engine == EngineId.OPENCODE
    assert {route.driver_for(phase) for phase in ExecutionPhase} == {"opencode_server"}
    assert TurnParams(threadId="test", executionEngine="opencode").execution_engine == "opencode"
    assert (
        ExecutionSnapshot(
            engine="opencode",
            driver=route.driver,
            reason=route.reason,
            phase="primary",
            invocation=1,
        ).engine
        == "opencode"
    )
    group = select_execution_route(requested_engine=EngineId.OPENCODE, group_fanout=True)
    assert group.engine is EngineId.OPENCODE
    assert group.driver_for(ExecutionPhase.PRIMARY) == "group_fanout"
    assert group.driver_for(ExecutionPhase.VERIFICATION) == "opencode_server"


def test_model_selection_keeps_provider_identity():
    catalog = {
        "opencode-zen": {
            "id": "opencode-zen",
            "models": ["big-pickle"],
            "managed_by_plugin": "opencode-zen",
        },
        "other": {"id": "other", "models": ["big-pickle"]},
    }
    assert resolve_zen_model(None, catalog) == "big-pickle"
    assert (
        resolve_zen_model(custom_model_selection_id("opencode-zen", "big-pickle"), catalog)
        == "big-pickle"
    )
    for model in [
        "gpt-5",
        custom_model_selection_id("opencode-zen", "big-pickle", "1m"),
    ]:
        with pytest.raises(OpenCodeError):
            resolve_zen_model(model, catalog)
    shared = custom_model_selection_id("other", "big-pickle")
    assert resolve_zen_model(shared, catalog) == "echo-shared/" + shared


def test_shared_models_use_only_turn_proxy_credentials(tmp_path):
    from runtime.execution.opencode_backend import model_selection_id
    selected = "official/qwen3.5-flash"
    model = resolve_zen_model(selected, {})
    assert model_selection_id(model) == selected
    env = child_environment(tmp_path, "scoped-token", "password", model, False,
                            shared_provider={"base_url": "http://127.0.0.1:1234/v1"})
    config = json.loads(env["OPENCODE_CONFIG_CONTENT"])
    assert config["model"] == "echo-shared/official/qwen3.5-flash"
    assert config["provider"]["echo-shared"]["npm"] == "@ai-sdk/openai"
    assert "scoped-token" not in env["OPENCODE_CONFIG_CONTENT"]
    assert env["OPENCODE_API_KEY"] == "scoped-token"


def test_public_default_does_not_require_a_plugin_or_account(tmp_path, monkeypatch):
    from runtime.execution import opencode_backend as backend

    monkeypatch.setattr(backend, "executable", lambda: "opencode")
    monkeypatch.setattr(backend, "zen_catalog", lambda: {})
    monkeypatch.setattr(backend.CredentialStore, "get_secret", lambda *args: None)
    assert backend.inspect_readiness(None)["available"] is True
    assert backend.zen_key(None) is None
    assert resolve_zen_model("auto", {}) == "big-pickle"
    assert (
        resolve_zen_model(custom_model_selection_id("opencode-zen", "big-pickle"), {})
        == "big-pickle"
    )
    with pytest.raises(OpenCodeError):
        resolve_zen_model("paid-model", {})
    monkeypatch.setenv("OPENCODE_API_KEY", "must-not-inherit")
    env = child_environment(tmp_path, None, "password", "big-pickle", False)
    assert "OPENCODE_API_KEY" not in env
    assert "provider" not in json.loads(env["OPENCODE_CONFIG_CONTENT"])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "cost,allowed",
    [
        ({"input": 0, "output": 0, "cache": {"read": 0, "write": 0}}, True),
        ({"input": 0, "output": 1}, False),
        ({"input": 1, "output": 0}, False),
        ({"input": 0, "output": 0, "cache": {"read": 1}}, False),
        ({"input": 0}, False),
        ({"input": False, "output": 0}, False),
        ({"input": "0", "output": 0}, False),
        (None, False),
    ],
)
async def test_anonymous_execution_requires_live_zero_pricing(cost, allowed):
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200, json={"all": [{"id": "opencode", "models": {"selected": {"cost": cost}}}]}
        )
    )
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
        if allowed:
            await validate_catalog_model(client, "selected", free_only=True)
        else:
            with pytest.raises(OpenCodeError, match="零费用"):
                await validate_catalog_model(client, "selected", free_only=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("available", [False, True])
async def test_selected_model_must_exist_in_the_official_zen_catalog(available):
    calls = []

    def handle(request):
        calls.append((request.method, request.url.path))
        return httpx.Response(
            200,
            json={
                "all": [
                    {"id": "other", "models": {"deepseek-v4-flash-free": {}}},
                    {"id": "opencode", "models": {"big-pickle": {}}},
                ]
            },
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handle), base_url="http://localhost"
    ) as client:
        if available:
            await validate_catalog_model(client, "big-pickle")
        else:
            with pytest.raises(OpenCodeError, match="未提供所选 Zen 模型"):
                await validate_catalog_model(client, "deepseek-v4-flash-free")
    assert calls == [("GET", "/provider")]


@pytest.mark.asyncio
@pytest.mark.parametrize("status,payload", [(200, {}), (200, []), (503, {"error": "private"})])
async def test_unreadable_catalog_is_not_reported_as_an_unavailable_model(status, payload):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(status, json=payload)),
        base_url="http://localhost",
    ) as client:
        with pytest.raises(OpenCodeError, match="无法读取 OpenCode 模型列表"):
            await validate_catalog_model(client, "big-pickle")


@pytest.mark.parametrize("web", [True, False])
def test_child_environment_isolates_credentials_and_denies_local_tools(tmp_path, monkeypatch, web):
    monkeypatch.setenv("OPENAI_API_KEY", "unrelated")
    monkeypatch.setenv("OPENCODE_CLIENT", "untrusted-override")
    monkeypatch.setenv("OPENCODE_CONFIG", "untrusted-config")
    env = child_environment(tmp_path, "zen-test-key", "test-password", "big-pickle", web)
    assert "OPENAI_API_KEY" not in env
    assert "OPENCODE_CLIENT" not in env
    assert "OPENCODE_CONFIG" not in env
    assert env["OPENCODE_API_KEY"] == "zen-test-key"
    config = json.loads(env["OPENCODE_CONFIG_CONTENT"])
    assert "zen-test-key" not in env["OPENCODE_CONFIG_CONTENT"]
    assert config["permission"]["*"] == "deny"
    assert (config["permission"].get("websearch") == "allow") is web
    assert config["small_model"] == config["model"]
    assert config["share"] == "disabled"


def test_state_is_scoped_to_actor_tenant_and_thread():
    scopes = [
        TenantScope(tenant_id="one", actor_id="a"),
        TenantScope(tenant_id="one", actor_id="b"),
        TenantScope(tenant_id="two", actor_id="a"),
    ]
    paths = {state_directory(scope, thread) for scope in scopes for thread in ["x", "../../y"]}
    assert len(paths) == 6
    assert all(len(path.name) == 64 for path in paths)


def test_host_mcp_is_explicit_and_credentials_stay_out_of_config(tmp_path, monkeypatch):
    monkeypatch.setenv("ECHO_HOST_MCP_TOKEN", "ambient-token")
    isolated = child_environment(tmp_path, "zen", "password", "big-pickle", False)
    assert "ECHO_HOST_MCP_TOKEN" not in isolated
    connection = HostMCPConnection("http://127.0.0.1:12345/mcp", "turn-token")
    env = child_environment(tmp_path, "zen", "password", "big-pickle", False, host_mcp=connection)
    config = json.loads(env["OPENCODE_CONFIG_CONTENT"])
    assert config["mcp"]["echo"]["oauth"] is False
    assert "turn-token" not in env["OPENCODE_CONFIG_CONTENT"]
    assert "turn-token" not in repr(connection)
    assert env["ECHO_HOST_MCP_TOKEN"] == "turn-token"
    assert config["permission"] == {"*": "deny", "echo_*": "allow"}


def test_host_tool_events_use_the_native_skill_identity():
    reducer = MessageEvents(set(), tool_names={"echo_read_file": "read_file"})
    event = {
        "info": {"id": "a", "role": "assistant"},
        "parts": [
            {
                "id": "p",
                "type": "tool",
                "tool": "echo_read_file",
                "callID": "c",
                "state": {"status": "completed", "input": {"path": "note.txt"}, "output": "note"},
            }
        ],
    }
    assert {e["tool_name"] for e in reducer.consume([event])} == {"read_file"}


def message(text="OK", error=None):
    return {
        "info": {"id": "assistant-1", "role": "assistant", "finish": "stop", "error": error},
        "parts": [{"id": "text-1", "type": "text", "text": text}],
    }


def test_growing_messages_and_tool_snapshots_are_not_replayed():
    reducer = MessageEvents({"old"})
    assert reducer.consume([{**message(), "info": {"id": "old", "role": "assistant"}}]) == []
    assert reducer.consume([message("O")])[0]["delta"] == "O"
    assert reducer.consume([message("OK")])[0]["delta"] == "K"
    assert reducer.consume([message("OK")]) == []
    tool_message = {
        "info": {"id": "a", "role": "assistant"},
        "parts": [
            {
                "id": "p",
                "callID": "call-1",
                "type": "tool",
                "tool": "websearch",
                "state": {"status": "completed", "input": {"query": "NAS"}, "output": "result"},
            }
        ],
    }
    events = reducer.consume([tool_message])
    assert [e["type"] for e in events] == ["tool_start", "tool_end"]
    assert events[1]["success"]
    assert reducer.consume([tool_message]) == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error", [None, {"name": "APIError", "data": {"statusCode": 429, "message": "private detail"}}]
)
async def test_http_200_is_not_sufficient_for_success(error):
    calls = []

    def handle(request):
        calls.append(request.method)
        if request.method == "GET":
            return httpx.Response(200, json=[] if len(calls) == 1 else [message(error=error)])
        return httpx.Response(200, json=message(error=error))

    events = []
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handle), base_url="http://localhost"
    ) as client:

        async def run():
            async for event in stream_prompt(
                client,
                "ses_test",
                text="hello",
                system="role",
                model="big-pickle",
                interrupted=lambda: False,
                poll_s=0.001,
            ):
                events.append(event)

        if error:
            with pytest.raises(OpenCodeError, match="额度"):
                await run()
            assert not any(e["type"] == "react_completed" for e in events)
        else:
            await run()
            assert events[-1]["type"] == "react_completed"
            assert "".join(e["delta"] for e in events if e["type"] == "text_delta") == "OK"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,detail,expected",
    [
        (400, "Model is unavailable", "模型不可用"),
        (401, "invalid credentials", "连接已失效"),
        (500, "internal provider failure", "调用模型失败"),
    ],
)
async def test_http_provider_failure_is_not_a_local_connection_error(status, detail, expected):
    def handle(request):
        if request.method == "GET":
            return httpx.Response(200, json=[])
        return httpx.Response(status, json={"error": detail, "private": "secret-test-token"})

    events = []
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handle), base_url="http://localhost"
    ) as client:
        with pytest.raises(OpenCodeError, match=expected) as failure:
            async for event in stream_prompt(
                client,
                "ses_test",
                text="hello",
                system="role",
                model="big-pickle",
                interrupted=lambda: False,
                poll_s=0.001,
            ):
                events.append(event)
    assert "secret-test-token" not in str(failure.value)
    assert not any(event["type"] == "react_completed" for event in events)


@pytest.mark.asyncio
async def test_stop_aborts_the_official_session():
    submitted = asyncio.Event()
    aborted = asyncio.Event()

    async def handle(request):
        if request.url.path.endswith("/abort"):
            aborted.set()
            return httpx.Response(200, json=True)
        if request.method == "POST":
            submitted.set()
            await asyncio.Event().wait()
        return httpx.Response(200, json=[])

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handle), base_url="http://localhost"
    ) as client:
        events = [
            event
            async for event in stream_prompt(
                client,
                "ses_test",
                text="hello",
                system="role",
                model="big-pickle",
                interrupted=submitted.is_set,
                poll_s=0.001,
            )
        ]
    assert aborted.is_set()
    assert events == [{"type": "react_cancelled", "reason": "用户停止了任务"}]


@pytest.mark.asyncio
@pytest.mark.parametrize("resumed", [False, True])
async def test_engine_prompt_bootstraps_fresh_history_and_only_sends_resume_delta(resumed):
    posted = []
    calls = 0

    def handle(request):
        nonlocal calls
        calls += 1
        if request.method == "POST":
            posted.append(json.loads(request.content))
            return httpx.Response(200, json=message())
        if calls == 1:
            return httpx.Response(200, json=[{"info": {"id": "old"}}] if resumed else [])
        return httpx.Response(200, json=[message()])

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handle), base_url="http://localhost"
    ) as client:
        events = [
            event
            async for event in stream_prompt(
                client,
                "ses_test",
                text="MISSING_HISTORY\nLATEST",
                fresh_thread_text="FULL_HISTORY\nLATEST",
                system="current role",
                model="big-pickle",
                interrupted=lambda: False,
                poll_s=0.001,
            )
        ]
    assert events[-1]["type"] == "react_completed"
    assert posted[0]["parts"] == [
        {
            "type": "text",
            "text": ("MISSING_HISTORY" if resumed else "FULL_HISTORY") + "\nLATEST",
        }
    ]
    assert posted[0]["system"] == "current role"


@pytest.mark.asyncio
@pytest.mark.parametrize("effort,variants,expected", [
    ("high", {"high": {}, "low": {}}, "high"),
    ("off", {"none": {}, "high": {}}, "none"),
    ("high", {}, None),
])
async def test_reasoning_variant_reaches_native_request(effort, variants, expected):
    posted = []
    def handle(request):
        if request.url.path == "/provider":
            return httpx.Response(200, json={"all": [{"id": "opencode", "models": {
                "big-pickle": {"variants": variants}}}]})
        if request.url.path == "/event":
            return httpx.Response(200, text="")
        if request.method == "POST":
            posted.append(json.loads(request.content))
            return httpx.Response(200, json=message())
        return httpx.Response(200, json=[message()] if posted else [])
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle), base_url="http://localhost") as client:
        events = [event async for event in stream_prompt(client, "ses_test", text="hello",
            system="role", model="big-pickle", interrupted=lambda: False, reasoning_effort=effort)]
    assert posted[0].get("variant") == expected
    assert events[-1]["completion_receipt"]["reasoning_variant"] == expected


@pytest.mark.asyncio
async def test_unsupported_variant_fails_before_sending_task():
    def handle(request):
        assert request.url.path == "/provider"
        return httpx.Response(200, json={"all": [{"id": "opencode", "models": {
            "big-pickle": {"variants": {"high": {}}}}}]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle), base_url="http://localhost") as client:
        with pytest.raises(OpenCodeError, match="推理档位"):
            _ = [event async for event in stream_prompt(client, "ses_test", text="hello",
                system="role", model="big-pickle", interrupted=lambda: False, reasoning_effort="low")]
