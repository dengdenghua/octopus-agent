"""Implementation note."""

from __future__ import annotations

import json
from uuid import uuid4

import pytest

from runtime.core.cerebrum import LLMPlanner
from runtime.execution.suckers import Skill, SkillRegistry
from runtime.memory.hemolymph import ContextComposer
from runtime.memory.journal import InMemoryJournal
from runtime.platform.models import (
    ArmId,
    CostEntry,
    ParsedIntent,
    TaskId,
    Trajectory,
    TrajectoryOutcome,
)
from runtime.sensing.model_router import (
    Message,
    MockModelRouter,
    ModelRequest,
    ModelResponse,
    ModelRouter,
    ModelStreamEvent,
    MultiModelRouter,
)

# ═══════════════════════════════════════════════════════════
# helpers
# ═══════════════════════════════════════════════════════════


class _FailingRouter(ModelRouter):
    """Implementation note."""

    def __init__(self, label: str = "boom") -> None:
        self.label = label
        self.call_count = 0

    def call(self, request: ModelRequest) -> ModelResponse:
        self.call_count += 1
        raise RuntimeError(f"{self.label}#{self.call_count}")


class _TaggedMockRouter(MockModelRouter):
    """Implementation note."""

    def __init__(self, *, default_model: str, response: str) -> None:
        super().__init__(response=response)
        self.default_model = default_model


class _StreamingRouter(ModelRouter):
    def __init__(
        self,
        outcomes: list[Exception | list[ModelStreamEvent]],
        *,
        default_model: str = "stream/default",
    ) -> None:
        self.outcomes = outcomes
        self.default_model = default_model
        self.call_count = 0
        self.stream_count = 0
        self.stream_requests: list[ModelRequest] = []

    def call(self, request: ModelRequest) -> ModelResponse:
        del request
        self.call_count += 1
        raise AssertionError("streaming route must not fall back to call()")

    def call_stream(self, request: ModelRequest):
        self.stream_requests.append(request)
        outcome = self.outcomes[self.stream_count]
        self.stream_count += 1
        if isinstance(outcome, Exception):
            raise outcome
        yield from outcome


def _stream_events(text: str, *, provider: str = "stream-provider") -> list[ModelStreamEvent]:
    response = ModelResponse(
        text=text,
        model="stream/default",
        provider=provider,
        cost=CostEntry(usd=0.01),
    )
    return [
        ModelStreamEvent(type="text_delta", delta=text),
        ModelStreamEvent(type="done", final=response),
    ]


def _make_request(**kw) -> ModelRequest:
    defaults = {
        "model": "any",
        "messages": [Message(role="user", content="hi")],
        "max_tokens": 32,
        "temperature": 0.0,
    }
    defaults.update(kw)
    return ModelRequest(**defaults)


# ═══════════════════════════════════════════════════════════
# Implementation note.
# ═══════════════════════════════════════════════════════════


class TestRouting:
    def test_default_uses_primary(self):
        primary = MockModelRouter(response="primary-ok")
        strong = MockModelRouter(response="strong-ok")
        mr = MultiModelRouter(primary=primary, strong=strong)

        resp = mr.call(_make_request(prefer_strength="default"))
        assert resp.text == "primary-ok"
        assert mr.dispatch_log[-1].final_role == "primary"

    def test_strong_prefer_uses_strong(self):
        primary = MockModelRouter(response="primary-ok")
        strong = MockModelRouter(response="strong-ok")
        mr = MultiModelRouter(primary=primary, strong=strong)

        resp = mr.call(_make_request(prefer_strength="strong"))
        assert resp.text == "strong-ok"
        assert mr.dispatch_log[-1].final_role == "strong"

    def test_strong_prefer_without_strong_falls_to_primary(self):
        primary = MockModelRouter(response="primary-ok")
        mr = MultiModelRouter(primary=primary, strong=None)

        resp = mr.call(_make_request(prefer_strength="strong"))
        assert resp.text == "primary-ok"
        assert mr.dispatch_log[-1].final_role == "primary"


# ═══════════════════════════════════════════════════════════
# Implementation note.
# ═══════════════════════════════════════════════════════════


class TestFallback:
    def test_primary_failure_falls_to_fallback(self):
        primary = _FailingRouter("primary-fail")
        fb = MockModelRouter(response="fb-ok")
        mr = MultiModelRouter(primary=primary, fallbacks=[fb])

        resp = mr.call(_make_request())
        assert resp.text == "fb-ok"
        rec = mr.dispatch_log[-1]
        assert rec.final_role == "fallback[0]"
        assert len(rec.attempts) == 2
        assert rec.attempts[0].success is False
        assert "primary-fail" in rec.attempts[0].error

    def test_strong_failure_falls_back_to_primary(self):
        strong = _FailingRouter("strong-fail")
        primary = MockModelRouter(response="primary-ok")
        mr = MultiModelRouter(primary=primary, strong=strong)

        resp = mr.call(_make_request(prefer_strength="strong"))
        assert resp.text == "primary-ok"
        rec = mr.dispatch_log[-1]
        assert [a.role for a in rec.attempts] == ["strong", "primary"]
        assert rec.final_role == "primary"

    def test_all_fail_raises_last_error(self):
        primary = _FailingRouter("p")
        fb1 = _FailingRouter("fb1")
        fb2 = _FailingRouter("fb2")
        mr = MultiModelRouter(primary=primary, fallbacks=[fb1, fb2])

        with pytest.raises(RuntimeError, match="fb2"):
            mr.call(_make_request())

        rec = mr.dispatch_log[-1]
        assert len(rec.attempts) == 3
        assert all(a.success is False for a in rec.attempts)
        assert rec.final_role is None

    def test_empty_router_chain_raises(self):
        """Implementation note."""
        primary = _FailingRouter("only")
        mr = MultiModelRouter(primary=primary)
        with pytest.raises(RuntimeError):
            mr.call(_make_request())


class TestStreamingRouting:
    def test_uses_native_stream_instead_of_buffered_call(self):
        primary = _StreamingRouter([_stream_events("hello")])
        mr = MultiModelRouter(primary=primary)

        stream = mr.call_stream(_make_request())
        assert next(stream).delta == "hello"
        remaining = list(stream)

        assert remaining[-1].type == "done"
        assert primary.call_count == 0
        assert primary.stream_count == 1
        assert mr.dispatch_log[-1].final_role == "primary"
        assert mr.dispatch_log[-1].attempts[0].response_provider == "stream-provider"

    def test_failure_before_first_event_falls_back_to_next_provider(self):
        primary = _StreamingRouter([RuntimeError("permanent failure")])
        fallback = _StreamingRouter([_stream_events("rescued")])
        mr = MultiModelRouter(primary=primary, fallbacks=[fallback])

        events = list(mr.call_stream(_make_request()))

        assert events[0].delta == "rescued"
        assert primary.stream_count == 1
        assert fallback.stream_count == 1
        assert [attempt.success for attempt in mr.dispatch_log[-1].attempts] == [
            False,
            True,
        ]
        assert mr.dispatch_log[-1].final_role == "fallback[0]"

    def test_transient_failure_retries_same_streaming_provider(self, monkeypatch):
        primary = _StreamingRouter(
            [ConnectionError("connection reset"), _stream_events("retry ok")]
        )
        sleeps: list[float] = []
        monkeypatch.setattr(
            "runtime.sensing.model_router.multi_router.time.sleep",
            sleeps.append,
        )
        mr = MultiModelRouter(
            primary=primary,
            retry_attempts=3,
            retry_base_delay=0.1,
        )

        events = list(mr.call_stream(_make_request()))

        assert events[0].delta == "retry ok"
        assert primary.stream_count == 2
        assert len(sleeps) == 1
        assert 0.075 <= sleeps[0] <= 0.1
        assert len(mr.dispatch_log[-1].attempts) == 1
        assert mr.dispatch_log[-1].attempts[0].success is True

    def test_failure_after_delta_is_not_replayed_on_fallback(self):
        class _PartialRouter(_StreamingRouter):
            def call_stream(self, request: ModelRequest):
                self.stream_requests.append(request)
                self.stream_count += 1
                yield ModelStreamEvent(type="text_delta", delta="visible")
                raise ConnectionError("stream broke")

        primary = _PartialRouter([])
        fallback = _StreamingRouter([_stream_events("must not appear")])
        mr = MultiModelRouter(primary=primary, fallbacks=[fallback])
        stream = mr.call_stream(_make_request())

        assert next(stream).delta == "visible"
        with pytest.raises(ConnectionError, match="stream broke"):
            next(stream)

        assert fallback.stream_count == 0
        assert len(mr.dispatch_log[-1].attempts) == 1
        assert mr.dispatch_log[-1].attempts[0].success is False

    def test_empty_stream_is_not_recorded_as_success(self):
        primary = _StreamingRouter([[]])
        fallback = _StreamingRouter([_stream_events("non-empty")])
        mr = MultiModelRouter(
            primary=primary,
            fallbacks=[fallback],
            retry_attempts=1,
        )

        events = list(mr.call_stream(_make_request()))

        assert events[0].delta == "non-empty"
        assert [attempt.success for attempt in mr.dispatch_log[-1].attempts] == [
            False,
            True,
        ]
        assert "EmptyModelStreamError" in (mr.dispatch_log[-1].attempts[0].error or "")

    def test_streaming_route_rewrites_model_for_strong_provider(self):
        primary = _StreamingRouter([_stream_events("unused")])
        strong = _StreamingRouter(
            [_stream_events("strong")],
            default_model="strong/stream-model",
        )
        mr = MultiModelRouter(primary=primary, strong=strong)

        list(mr.call_stream(_make_request(model="caller-model", prefer_strength="strong")))

        assert strong.stream_requests[0].model == "strong/stream-model"
        assert primary.stream_count == 0


# ═══════════════════════════════════════════════════════════
# Implementation note.
# ═══════════════════════════════════════════════════════════


class TestModelRewrite:
    def test_default_model_rewrites_request(self):
        primary = _TaggedMockRouter(
            default_model="claude-haiku-4-5",
            response="echo",
        )
        strong = _TaggedMockRouter(
            default_model="claude-opus-4-7",
            response="echo",
        )
        mr = MultiModelRouter(primary=primary, strong=strong)

        mr.call(_make_request(model="caller-wrote-this", prefer_strength="strong"))
        # Implementation note.
        seen = strong.call_log[0]
        assert seen.model == "claude-opus-4-7"

        mr.call(_make_request(model="caller-wrote-this", prefer_strength="default"))
        seen2 = primary.call_log[0]
        assert seen2.model == "claude-haiku-4-5"

    def test_router_without_default_model_preserves_model(self):
        primary = MockModelRouter(response="ok")  # Implementation note.
        mr = MultiModelRouter(primary=primary)
        mr.call(_make_request(model="user-specified-model"))
        assert primary.call_log[0].model == "user-specified-model"


# ═══════════════════════════════════════════════════════════
# Implementation note.
# ═══════════════════════════════════════════════════════════


class TestChainDeduplication:
    def test_same_router_instance_not_called_twice(self):
        shared = MockModelRouter(response="shared")
        mr = MultiModelRouter(primary=shared, strong=shared)

        mr.call(_make_request(prefer_strength="strong"))
        assert len(shared.call_log) == 1
        rec = mr.dispatch_log[-1]
        # Implementation note.
        assert len(rec.attempts) == 1


# ═══════════════════════════════════════════════════════════
# Implementation note.
# ═══════════════════════════════════════════════════════════


@pytest.fixture
def registry():
    r = SkillRegistry()
    for name in ["read_file", "hash_text"]:
        r.register(
            Skill(
                name=name,
                trusted_source=f"skill://public/{name}",
                handler=lambda **kw: {"ok": True},
            ),
            verify_tests=False,
        )
    return r


@pytest.fixture
def composer(registry):
    return ContextComposer(registry=registry, journal=InMemoryJournal())


def _seed_losing_journal(recipe_id: str) -> InMemoryJournal:
    j = InMemoryJournal()
    # Implementation note.
    for _ in range(8):
        j.write_trajectory(
            Trajectory(
                task_id=TaskId(uuid4()),
                arm_id=ArmId("a"),
                recipe_id=recipe_id,
                steps=[],
                outcome=TrajectoryOutcome(
                    success=False,
                    cost=CostEntry(tokens_in=50, tokens_out=50, usd=0.01),
                ),
            )
        )
    for _ in range(1):
        j.write_trajectory(
            Trajectory(
                task_id=TaskId(uuid4()),
                arm_id=ArmId("a"),
                recipe_id=recipe_id,
                steps=[],
                outcome=TrajectoryOutcome(
                    success=True,
                    cost=CostEntry(tokens_in=50, tokens_out=50, usd=0.01),
                ),
            )
        )
    return j


class TestLLMPlannerUpgradeOnLosing:
    def test_losing_verdict_drives_strong_upgrade(self, registry, composer):
        """Implementation note."""
        primary = MockModelRouter(
            response=json.dumps({"reasoning": "p", "nodes": [{"skill": "read_file", "args": {}}]}),
        )
        strong = MockModelRouter(
            response=json.dumps({"reasoning": "s", "nodes": [{"skill": "hash_text", "args": {}}]}),
        )
        mr = MultiModelRouter(primary=primary, strong=strong)

        planner = LLMPlanner(router=mr, registry=registry, composer=composer)

        # Implementation note.
        intent = ParsedIntent(raw="x", intent_type="task", normalized_goal="y")
        planner.plan(intent)
        assert mr.dispatch_log[-1].final_role == "primary"
        assert primary.call_log[-1].prefer_strength == "default"

        # Implementation note.
        my_hash = planner.recipe_hash()
        planner.assess_recipe_from_journal(_seed_losing_journal(my_hash))
        assert planner.current_recipe_verdict.verdict == "losing"

        # Implementation note.
        planner.plan(intent)
        assert mr.dispatch_log[-1].final_role == "strong"
        assert strong.call_log[-1].prefer_strength == "strong"

    def test_winning_verdict_stays_on_primary(self, registry, composer):
        """Implementation note."""
        primary = MockModelRouter(
            response=json.dumps({"reasoning": "p", "nodes": [{"skill": "read_file", "args": {}}]}),
        )
        strong = MockModelRouter(
            response=json.dumps({"reasoning": "s", "nodes": [{"skill": "hash_text", "args": {}}]}),
        )
        mr = MultiModelRouter(primary=primary, strong=strong)
        planner = LLMPlanner(router=mr, registry=registry, composer=composer)

        # Implementation note.
        my_hash = planner.recipe_hash()
        j = InMemoryJournal()
        for _ in range(9):
            j.write_trajectory(
                Trajectory(
                    task_id=TaskId(uuid4()),
                    arm_id=ArmId("a"),
                    recipe_id=my_hash,
                    steps=[],
                    outcome=TrajectoryOutcome(
                        success=True,
                        cost=CostEntry(tokens_in=50, tokens_out=50, usd=0.01),
                    ),
                )
            )
        planner.assess_recipe_from_journal(j)
        assert planner.current_recipe_verdict.verdict == "winning"

        intent = ParsedIntent(raw="x", intent_type="task", normalized_goal="y")
        planner.plan(intent)
        assert mr.dispatch_log[-1].final_role == "primary"


class TestDispatchLogBounded:
    def test_dispatch_log_does_not_grow_unbounded(self):
        from runtime.sensing.model_router.multi_router import _DISPATCH_LOG_MAX

        mr = MultiModelRouter(primary=MockModelRouter(response="ok"))
        for _ in range(_DISPATCH_LOG_MAX + 50):
            mr.call(_make_request())
        # Rolling cap: one record per call would otherwise leak forever on a
        # long-lived router. Newest record stays readable (tests use [-1]).
        assert len(mr.dispatch_log) == _DISPATCH_LOG_MAX
        assert mr.dispatch_log[-1].final_role == "primary"
