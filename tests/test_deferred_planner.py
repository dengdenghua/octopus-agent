from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from runtime.execution.model_services import native_model_services
from runtime.platform.config import builder
from runtime.platform.config.schema import AgentConfig, PlannerConfig


def test_external_stack_defers_native_factory_until_requested(monkeypatch):
    native_router = SimpleNamespace(call=Mock(return_value="answer"))
    planner = SimpleNamespace(router=native_router)
    factory = Mock(return_value=planner)
    monkeypatch.setattr(builder, "_build_planner", factory)
    config = AgentConfig(
        enable_web_skills=False, planner=PlannerConfig(type="llm", model="native-model")
    )
    stack = builder.build_from_config(config)
    assert stack.is_llm_planner
    assert stack.native_planner_model == "native-model"
    assert stack.background_router is None
    router = stack.native_router
    assert native_model_services(stack) == (router, "native-model")
    assert stack.approval_router is router
    factory.assert_not_called()
    assert router.call("request") == "answer"
    assert stack.planner is planner
    assert stack.approval_router is native_router
    factory.assert_called_once()
    native_router.call.assert_called_once_with("request")


@pytest.mark.parametrize(
    "settings",
    [
        {"execution": {"member_engine": "octopus"}},
        {"execution": {"background_model_calls": True}},
        {"learn": {"learn_from_journal": "missing-preload.jsonl"}},
        {"planner": {"type": "llm", "model": "mock/planner"}},
    ],
)
def test_explicit_native_services_and_mock_planners_keep_eager_construction(monkeypatch, settings):
    factory = Mock(return_value=SimpleNamespace(router=object()))
    monkeypatch.setattr(builder, "_build_planner", factory)
    config = AgentConfig.model_validate(
        {
            "enable_web_skills": False,
            "planner": {"type": "llm", "model": "native-model"},
            **settings,
        }
    )
    stack = builder.build_from_config(config)
    factory.assert_called_once()
    assert stack.planner is factory.return_value


def test_concurrent_first_access_constructs_one_native_planner(monkeypatch):
    planner = SimpleNamespace(router=object())
    factory = Mock(return_value=planner)
    monkeypatch.setattr(builder, "_build_planner", factory)
    config = AgentConfig(
        enable_web_skills=False, planner=PlannerConfig(type="llm", model="native-model")
    )
    stack = builder.build_from_config(config)
    barrier = Barrier(4, timeout=5)

    def access():
        barrier.wait()
        return stack.planner

    with ThreadPoolExecutor(max_workers=4) as pool:
        values = list(pool.map(lambda _: access(), range(4)))
    assert all(value is planner for value in values)
    factory.assert_called_once()


def test_native_services_keep_legacy_and_absent_stack_contracts():
    router = object()
    assert native_model_services(None) == (None, None)
    assert native_model_services(SimpleNamespace(planner=None)) == (None, None)
    assert native_model_services(
        SimpleNamespace(planner=SimpleNamespace(router=router, planner_model="legacy-model"))
    ) == (router, "legacy-model")


@pytest.mark.parametrize("materialize_first", [False, True])
def test_gateway_configuration_precedes_first_router_call(monkeypatch, materialize_first):
    from runtime.platform.ui._app_fallback_routers import _attach_oct_fallback_router

    configured = []
    dispatcher = SimpleNamespace(set_fallback=configured.append)

    def call(request):
        assert len(configured) == 1
        return "configured answer"

    dispatcher.call = call
    factory = Mock(return_value=SimpleNamespace(router=dispatcher, planner_model="native-model"))
    monkeypatch.setattr(builder, "_build_planner", factory)
    fallback = object()
    fallback_factory = Mock(return_value=fallback)
    monkeypatch.setattr(
        "runtime.sensing.model_router.openai_router.build_fallback_router_from_custom_models",
        fallback_factory,
    )
    stack = builder.build_from_config(
        AgentConfig(
            enable_web_skills=False,
            planner=PlannerConfig(type="llm", model="native-model"),
        )
    )
    if materialize_first:
        assert stack.planner is factory.return_value
    store = object()
    _attach_oct_fallback_router(
        stack=stack, oct_config=SimpleNamespace(default_model="gateway-model"), link_store=store
    )
    if not materialize_first:
        factory.assert_not_called()
        fallback_factory.assert_not_called()
        assert configured == []
    assert stack.native_router.call("request") == "configured answer"
    factory.assert_called_once()
    fallback_factory.assert_called_once_with("native-model")
    assert configured[0]._link_store is store
    assert configured[0]._self is fallback
    assert configured[0]._oct.default_model == "gateway-model"


def test_wiki_mount_and_empty_context_do_not_construct_native_planner(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import runtime.memory.hemolymph.repo_context as repo_context
    from runtime.sensing.gateway.wiki_router import _answer_from_wiki, create_wiki_router

    native_router = SimpleNamespace(call=Mock(return_value=SimpleNamespace(text="Wiki answer")))
    factory = Mock(return_value=SimpleNamespace(router=native_router))
    monkeypatch.setattr(builder, "_build_planner", factory)
    stack = builder.build_from_config(
        AgentConfig(
            enable_web_skills=False,
            planner=PlannerConfig(type="llm", model="native-model"),
        )
    )
    router, model = native_model_services(stack)
    app = FastAPI()
    app.include_router(create_wiki_router(model_router=router, model=model))
    with TestClient(app) as client:
        assert client.get("/api/wiki/graph").status_code == 200
    monkeypatch.setattr(repo_context, "build_codebase_context", lambda *a, **kw: ("", []))
    assert not _answer_from_wiki("q", model_router=router, model=model)["grounded"]
    factory.assert_not_called()
    monkeypatch.setattr(
        repo_context,
        "build_codebase_context",
        lambda *a, **kw: ("relevant evidence", [{"path": "example.md"}]),
    )
    assert _answer_from_wiki("q", model_router=router, model=model)["answer"] == "Wiki answer"
    factory.assert_called_once()
    assert native_router.call.call_args.args[0].model == "native-model"
