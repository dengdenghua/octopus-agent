from __future__ import annotations

import time

import pytest

from runtime.memory.cowork.context_engines import (
    AdaptiveRecallCoworkContextEngine,
    CoworkContextEngineHost,
    HybridCoworkContextEngine,
    RecencyCoworkContextEngine,
    load_cowork_context_engine,
    register_cowork_context_engine,
)
from runtime.memory.cowork.context_steward import CoworkContextCandidate, plan_group_context


def _candidate(
    source_id: str,
    order: int,
    *,
    content: str | None = None,
    score: float = 1.0,
    estimated_tokens: int = 1,
    kind: str = "conversation",
) -> CoworkContextCandidate:
    return CoworkContextCandidate(
        source_id=source_id,
        content=content or source_id,
        estimated_tokens=estimated_tokens,
        score=score,
        order=order,
        kind=kind,
    )


def test_default_uses_builtin_hybrid_without_loading_a_plugin(monkeypatch) -> None:
    monkeypatch.delenv("OCTOPUS_COWORK_CONTEXT_ENGINE", raising=False)

    assert isinstance(load_cowork_context_engine(), AdaptiveRecallCoworkContextEngine)
    assert isinstance(load_cowork_context_engine("default"), AdaptiveRecallCoworkContextEngine)
    assert load_cowork_context_engine("deterministic") is None
    assert load_cowork_context_engine("none") is None


def test_hybrid_engine_spends_budget_on_diverse_relevant_facts() -> None:
    engine = HybridCoworkContextEngine()
    selected = engine.select_context(
        section="role_relevant_context",
        budget_tokens=8,
        candidates=(
            _candidate(
                "duplicate-old",
                1,
                content="数据库迁移必须先备份并准备回滚",
                score=10,
                estimated_tokens=4,
            ),
            _candidate(
                "unique",
                3,
                content="API compatibility contract must remain stable",
                score=8,
                estimated_tokens=4,
            ),
            _candidate(
                "duplicate-new",
                4,
                content="数据库迁移必须先备份并准备回滚",
                score=9.8,
                estimated_tokens=4,
            ),
        ),
    )

    assert list(selected) == ["duplicate-new", "unique"]


def test_adaptive_engine_escalates_old_decisions_only_for_recall_intent() -> None:
    engine = AdaptiveRecallCoworkContextEngine()
    candidates = (
        _candidate(
            "old-decision",
            1,
            content="决定：最初采用事件溯源以支持完整审计",
            score=5,
            estimated_tokens=5,
            kind="decision",
        ),
        _candidate(
            "recent-chat",
            99,
            content="最近的普通状态同步",
            score=10,
            estimated_tokens=5,
            kind="conversation",
        ),
    )

    ordinary = engine.select_context(
        message="继续处理",
        section="shared_brief",
        budget_tokens=5,
        candidates=candidates,
    )
    recalled = engine.select_context(
        message="为什么之前决定采用这个方案？",
        section="shared_brief",
        budget_tokens=5,
        candidates=candidates,
    )

    assert list(ordinary) == ["recent-chat"]
    assert list(recalled) == ["old-decision"]


def test_named_builtin_engine_is_loaded_and_orders_by_recency() -> None:
    engine = load_cowork_context_engine("recency")

    assert isinstance(engine, RecencyCoworkContextEngine)
    assert list(
        engine.select_context(candidates=(_candidate("older", 1), _candidate("newer", 2)))
    ) == ["newer", "older"]


def test_registered_engine_is_selected_only_by_explicit_name() -> None:
    engine = object()

    class FixtureEngine:
        name = "fixture-registry"

        def select_context(self, **_kwargs):
            return []

    register_cowork_context_engine("fixture-registry", FixtureEngine, replace=True)

    loaded = load_cowork_context_engine("fixture-registry")
    assert isinstance(loaded, FixtureEngine)
    assert loaded is not engine


def test_unknown_or_malformed_engine_fails_without_importing_arbitrary_path() -> None:
    with pytest.raises(LookupError, match="unknown"):
        load_cowork_context_engine("missing-engine")
    with pytest.raises(ValueError, match="invalid"):
        load_cowork_context_engine("../../unsafe")


def test_entry_point_plugin_is_loaded_only_when_named(monkeypatch) -> None:
    from runtime.memory.cowork import context_engines

    loads: list[str] = []

    class ExternalEngine:
        name = "external-fixture"

        def select_context(self, **_kwargs):
            return []

    class Point:
        name = "external-fixture"

        def load(self):
            loads.append(self.name)
            return ExternalEngine

    class Points(list):
        def select(self, *, group, name):
            assert group == "octopus.cowork_context_engines"
            return [point for point in self if point.name == name]

    monkeypatch.setattr(context_engines.metadata, "entry_points", lambda: Points([Point()]))

    assert loads == []
    assert isinstance(load_cowork_context_engine("external-fixture"), ExternalEngine)
    assert loads == ["external-fixture"]


def test_realtime_runtime_loads_configured_engine_and_falls_back_safely(
    tmp_path,
    monkeypatch,
) -> None:
    from runtime.sensing.gateway.realtime_cerebrum import CerebrumRuntime

    monkeypatch.setenv("OCTOPUS_COWORK_CONTEXT_ENGINE", "recency")
    runtime = CerebrumRuntime(stack=object(), logs_root=str(tmp_path / "threads"))
    assert isinstance(runtime._cowork_context_engine, RecencyCoworkContextEngine)

    monkeypatch.setenv("OCTOPUS_COWORK_CONTEXT_ENGINE", "missing-engine")
    fallback = CerebrumRuntime(stack=object(), logs_root=str(tmp_path / "threads-2"))
    assert fallback._cowork_context_engine is None


def test_versioned_engine_host_runs_full_lifecycle_without_trusting_prompt_output() -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    class LifecycleEngine:
        name = "lifecycle-fixture"
        api_version = "1"
        capabilities = {"assemble", "compact", "commit_turn"}

        def bootstrap(self, **kwargs):
            calls.append(("bootstrap", kwargs))

        def ingest(self, **kwargs):
            calls.append(("ingest", kwargs))

        def assemble(self, **kwargs):
            calls.append(("assemble", kwargs))
            return {"selected_source_ids": [kwargs["candidates"][0].source_id]}

        def compact(self, **kwargs):
            calls.append(("compact", kwargs))

        def commit_turn(self, **kwargs):
            calls.append(("commit_turn", kwargs))

        def maintain(self, **kwargs):
            calls.append(("maintain", kwargs))

        def on_member_start(self, **kwargs):
            calls.append(("on_member_start", kwargs))

        def on_member_end(self, **kwargs):
            calls.append(("on_member_end", kwargs))

    host = CoworkContextEngineHost(LifecycleEngine())
    first_bootstrap = host.bootstrap_session("team-session")
    repeated_bootstrap = host.bootstrap_session("team-session")
    ingest = host.invoke_hook(
        "ingest",
        session_id="team-session",
        turn_id="turn-1",
        message="private request body",
    )
    plan = plan_group_context(
        "检查发布",
        [{"name": "reviewer", "description": "发布审查"}],
        [{"role": "assistant", "content": "决定：采用蓝绿发布"}],
        selection_engine=host,
        session_id="team-session",
        turn_id="turn-1",
    )
    receipt = plan.lifecycle_receipt()
    compact = host.invoke_hook(
        "compact",
        session_id="team-session",
        turn_id="turn-1",
        reason="test",
        statistics={"full_tokens": 10, "selected_tokens": 2},
    )
    committed = host.invoke_hook(
        "commit_turn",
        session_id="team-session",
        turn_id="turn-1",
        advancement_key="team-session:turn-1",
        receipt=receipt,
        outcomes=[],
    )
    maintained = host.invoke_hook(
        "maintain",
        session_id="team-session",
        turn_id="turn-1",
        outcome={"status": "committed"},
    )

    assert first_bootstrap["status"] == "completed"
    assert repeated_bootstrap["status"] == "already_bootstrapped"
    assert ingest["status"] == "completed"
    assert compact["status"] == "completed"
    assert committed["status"] == "completed"
    assert maintained["status"] == "completed"
    assemble_call = next(kwargs for hook, kwargs in calls if hook == "assemble")
    assert assemble_call["session_id"] == "team-session"
    assert assemble_call["turn_id"] == "turn-1"
    assert "蓝绿发布" in plan.prompt_for("reviewer")
    diagnostics = host.describe()
    assert diagnostics["api_version"] == "1"
    assert diagnostics["quarantined"] is False
    assert "private request body" not in str(diagnostics)


def test_engine_host_times_out_quarantines_and_never_exposes_exception_body() -> None:
    class BrokenEngine:
        name = "broken-fixture"
        api_version = "1"

        def assemble(self, **_kwargs):
            time.sleep(0.03)
            raise RuntimeError("secret plugin failure body")

    host = CoworkContextEngineHost(
        BrokenEngine(),
        timeout_seconds=0.01,
        quarantine_after=1,
    )
    plan = plan_group_context(
        "发布审查",
        [{"name": "reviewer", "description": "发布审查"}],
        [{"role": "assistant", "content": "发布审查证据已验证"}],
        selection_engine=host,
        session_id="team-session",
        turn_id="turn-timeout",
        shared_token_budget=0,
    )

    audit = plan.audit_dict()
    diagnostics = host.describe()
    assert audit["selection_engine_fallbacks"] == 1
    assert diagnostics["quarantined"] is True
    assert diagnostics["timeouts"] == 1
    assert diagnostics["last_error_type"] == "TimeoutError"
    assert "secret plugin failure body" not in str(audit)
    assert "secret plugin failure body" not in str(diagnostics)


def test_unknown_context_engine_api_version_is_rejected_before_realtime_use() -> None:
    class FutureEngine:
        name = "future-engine"
        api_version = "999"

        def assemble(self, **_kwargs):
            return []

    register_cowork_context_engine("future-engine", FutureEngine, replace=True)

    with pytest.raises(ValueError, match="unsupported cowork context engine api version"):
        load_cowork_context_engine("future-engine")
