"""Implementation note."""

from __future__ import annotations

from contextlib import contextmanager

import pytest

from runtime.platform.models import CostEntry
from runtime.platform.models.llm import ModelStreamEvent
from runtime.safety.budget_breaker import BreakerModelRouter, CircuitBreaker, CircuitOpen
from runtime.sensing.model_router import (
    Message,
    MockModelRouter,
    ModelRequest,
    ModelResponse,
    ModelRouter,
)

# ═══════════════════════════════════════════════════════════
# Implementation note.
# ═══════════════════════════════════════════════════════════


class _Clock:
    def __init__(self, t: float = 1000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


@pytest.fixture
def clock():
    return _Clock()


@pytest.fixture
def patched_time(clock, monkeypatch):
    """Implementation note."""
    monkeypatch.setattr(
        "runtime.safety.budget_breaker.breaker.time.monotonic",
        clock,
    )
    return clock


# ═══════════════════════════════════════════════════════════
# Implementation note.
# ═══════════════════════════════════════════════════════════


class TestClosedState:
    def test_initial_closed(self, patched_time):
        b = CircuitBreaker(window_seconds=60.0)
        assert b.state == "closed"
        assert b.check() == "closed"

    def test_record_stays_closed_under_threshold(self, patched_time):
        b = CircuitBreaker(
            window_seconds=60.0,
            max_calls_per_window=10,
        )
        for _ in range(5):
            b.check()
            b.record(success=True)
        assert b.state == "closed"


# ═══════════════════════════════════════════════════════════
# Implementation note.
# ═══════════════════════════════════════════════════════════


class TestTrips:
    def test_max_calls_trip(self, patched_time):
        b = CircuitBreaker(
            window_seconds=60.0,
            max_calls_per_window=3,
            cooldown_seconds=30.0,
        )
        # Implementation note.
        for _ in range(4):
            b.check()
            b.record(success=True)
        assert b.state == "open"
        # Implementation note.
        with pytest.raises(CircuitOpen):
            b.check()

    def test_max_cost_trip(self, patched_time):
        b = CircuitBreaker(
            window_seconds=60.0,
            max_cost_usd_per_window=0.10,
        )
        b.check()
        b.record(success=True, cost_usd=0.15)  # Implementation note.
        assert b.state == "open"

    def test_max_errors_trip(self, patched_time):
        b = CircuitBreaker(
            window_seconds=60.0,
            max_errors_per_window=2,
        )
        for _ in range(3):
            b.check()
            b.record(success=False)
        assert b.state == "open"

    def test_circuit_open_carries_reason(self, patched_time):
        b = CircuitBreaker(
            window_seconds=60.0,
            max_errors_per_window=0,
            cooldown_seconds=5.0,
        )
        b.check()
        b.record(success=False)
        try:
            b.check()
        except CircuitOpen as e:
            assert "max_errors" in e.reason
            assert e.cooldown_seconds == 5.0


# ═══════════════════════════════════════════════════════════
# Implementation note.
# ═══════════════════════════════════════════════════════════


class TestSlidingWindow:
    def test_old_events_pruned(self, patched_time):
        b = CircuitBreaker(
            window_seconds=10.0,
            max_calls_per_window=3,
        )
        for _ in range(3):
            b.check()
            b.record(success=True)
        assert b.state == "closed"

        # Implementation note.
        patched_time.advance(11.0)

        # Implementation note.
        b.check()
        b.record(success=True)
        assert b.state == "closed"
        assert b.snapshot()["calls_in_window"] == 1


# ═══════════════════════════════════════════════════════════
# cooldown → half_open → closed / open
# ═══════════════════════════════════════════════════════════


class TestHalfOpen:
    def test_cooldown_transitions_to_half_open(self, patched_time):
        b = CircuitBreaker(
            window_seconds=60.0,
            max_errors_per_window=0,
            cooldown_seconds=5.0,
        )
        b.check()
        b.record(success=False)
        assert b.state == "open"

        # Implementation note.
        patched_time.advance(4.0)
        with pytest.raises(CircuitOpen):
            b.check()

        # Implementation note.
        patched_time.advance(2.0)
        state = b.check()
        assert state == "half_open"

    def test_half_open_probe_success_resets(self, patched_time):
        b = CircuitBreaker(
            window_seconds=60.0,
            max_errors_per_window=0,
            cooldown_seconds=5.0,
        )
        b.check()
        b.record(success=False)
        patched_time.advance(6.0)
        b.check()  # half_open
        b.record(success=True)  # Implementation note.
        assert b.state == "closed"
        assert b.snapshot()["calls_in_window"] >= 1

    def test_half_open_probe_failure_re_opens(self, patched_time):
        b = CircuitBreaker(
            window_seconds=60.0,
            max_errors_per_window=0,
            cooldown_seconds=5.0,
        )
        b.check()
        b.record(success=False)
        patched_time.advance(6.0)
        b.check()  # Implementation note.
        b.record(success=False)  # Implementation note.
        assert b.state == "open"
        # Implementation note.
        with pytest.raises(CircuitOpen):
            b.check()

    def test_half_open_rejects_concurrent_probes(self, patched_time):
        """Implementation note."""
        b = CircuitBreaker(
            window_seconds=60.0,
            max_errors_per_window=0,
            cooldown_seconds=5.0,
        )
        b.check()
        b.record(success=False)
        patched_time.advance(6.0)
        b.check()  # Implementation note.
        with pytest.raises(CircuitOpen, match="probe in flight"):
            b.check()  # Implementation note.


# ═══════════════════════════════════════════════════════════
# reset
# ═══════════════════════════════════════════════════════════


class TestReset:
    def test_reset_clears_state(self, patched_time):
        b = CircuitBreaker(
            window_seconds=60.0,
            max_calls_per_window=1,
        )
        b.check()
        b.record(success=True)
        b.check()
        b.record(success=True)
        assert b.state == "open"

        b.reset()
        assert b.state == "closed"
        assert b.snapshot()["calls_in_window"] == 0


# ═══════════════════════════════════════════════════════════
# BreakerModelRouter
# ═══════════════════════════════════════════════════════════


class _FailingInner(ModelRouter):
    def __init__(self) -> None:
        self.call_count = 0

    def call(self, request: ModelRequest) -> ModelResponse:
        self.call_count += 1
        raise RuntimeError("always fails")


class _StreamingInner(ModelRouter):
    def __init__(self, *, fail_after_first_delta: bool = False) -> None:
        self.call_count = 0
        self.stream_count = 0
        self.fail_after_first_delta = fail_after_first_delta

    def call(self, request: ModelRequest) -> ModelResponse:  # noqa: ARG002
        self.call_count += 1
        return ModelResponse(text="non-stream fallback")

    def call_stream(self, request: ModelRequest):  # noqa: ARG002
        self.stream_count += 1
        yield ModelStreamEvent(type="text_delta", delta="hello")
        if self.fail_after_first_delta:
            raise RuntimeError("stream failed")
        yield ModelStreamEvent(type="text_delta", delta=" world")
        yield ModelStreamEvent(
            type="done",
            final=ModelResponse(
                text="hello world",
                cost=CostEntry(usd=0.25),
            ),
        )


def _req() -> ModelRequest:
    return ModelRequest(
        model="x",
        messages=[Message(role="user", content="hi")],
    )


class _SpanRecorder:
    def __init__(self) -> None:
        self.attributes: dict[str, object] = {}

    def set_attribute(self, key: str, value: object) -> None:
        self.attributes[key] = value


class TestBreakerModelRouter:
    def test_normal_pass_through(self, patched_time):
        inner = MockModelRouter(response="ok")
        breaker = CircuitBreaker(window_seconds=60.0)
        router = BreakerModelRouter(inner=inner, breaker=breaker)

        resp = router.call(_req())
        assert resp.text == "ok"
        assert breaker.state == "closed"

    def test_inner_failures_trip_breaker(self, patched_time):
        inner = _FailingInner()
        breaker = CircuitBreaker(
            window_seconds=60.0,
            max_errors_per_window=2,
            cooldown_seconds=10.0,
        )
        router = BreakerModelRouter(inner=inner, breaker=breaker)

        # Implementation note.
        for _ in range(3):
            with pytest.raises(RuntimeError, match="always fails"):
                router.call(_req())
        assert breaker.state == "open"

        # Implementation note.
        with pytest.raises(CircuitOpen):
            router.call(_req())
        assert inner.call_count == 3  # Implementation note.

    def test_open_rejection_is_traced(self, patched_time, monkeypatch):
        spans: list[_SpanRecorder] = []

        @contextmanager
        def fake_trace_stage(_name: str):
            span = _SpanRecorder()
            spans.append(span)
            yield span

        monkeypatch.setattr(
            "runtime.safety.budget_breaker.breaker_router.trace_stage",
            fake_trace_stage,
        )
        inner = _FailingInner()
        breaker = CircuitBreaker(
            window_seconds=60.0,
            max_errors_per_window=0,
            cooldown_seconds=10.0,
        )
        router = BreakerModelRouter(inner=inner, breaker=breaker)

        with pytest.raises(RuntimeError, match="always fails"):
            router.call(_req())
        assert breaker.state == "open"
        with pytest.raises(CircuitOpen):
            router.call(_req())

        rejected = spans[-1].attributes
        assert rejected["octopus.breaker.state_before_check"] == "open"
        assert rejected["octopus.breaker.state_on_entry"] == "open"
        assert rejected["octopus.breaker.state_after"] == "open"
        assert rejected["octopus.breaker.rejected"] is True
        assert "max_errors" in str(rejected["octopus.breaker.reject_reason"])
        assert inner.call_count == 1

    def test_inner_failure_records_trace_state_after(self, patched_time, monkeypatch):
        spans: list[_SpanRecorder] = []

        @contextmanager
        def fake_trace_stage(_name: str):
            span = _SpanRecorder()
            spans.append(span)
            yield span

        monkeypatch.setattr(
            "runtime.safety.budget_breaker.breaker_router.trace_stage",
            fake_trace_stage,
        )
        inner = _FailingInner()
        breaker = CircuitBreaker(
            window_seconds=60.0,
            max_errors_per_window=0,
            cooldown_seconds=10.0,
        )
        router = BreakerModelRouter(inner=inner, breaker=breaker)

        with pytest.raises(RuntimeError, match="always fails"):
            router.call(_req())

        attrs = spans[-1].attributes
        assert attrs["octopus.breaker.state_before_check"] == "closed"
        assert attrs["octopus.breaker.state_on_entry"] == "closed"
        assert attrs["octopus.breaker.inner_error"] == "RuntimeError"
        assert attrs["octopus.breaker.state_after"] == "open"

    def test_cost_accumulates_from_response(self, patched_time):
        inner = MockModelRouter(response="x" * 100)
        breaker = CircuitBreaker(
            window_seconds=60.0,
            max_cost_usd_per_window=1e-5,
            cooldown_seconds=10.0,
        )
        router = BreakerModelRouter(inner=inner, breaker=breaker)

        # Implementation note.
        # Implementation note.
        router.call(_req())
        snap = breaker.snapshot()
        assert snap["cost_in_window_usd"] > 0
        # Implementation note.
        with pytest.raises(CircuitOpen):
            router.call(_req())

    def test_half_open_via_router(self, patched_time):
        """Implementation note."""
        inner = MockModelRouter(response="ok")
        breaker = CircuitBreaker(
            window_seconds=60.0,
            max_calls_per_window=1,
            cooldown_seconds=5.0,
        )
        router = BreakerModelRouter(inner=inner, breaker=breaker)

        router.call(_req())
        router.call(_req())  # Implementation note.
        assert breaker.state == "open"
        with pytest.raises(CircuitOpen):
            router.call(_req())

        # Implementation note.
        patched_time.advance(6.0)
        # Implementation note.
        resp = router.call(_req())
        assert resp.text == "ok"
        assert breaker.state == "closed"

    def test_call_stream_preserves_inner_streaming_and_records_cost(self, patched_time):
        inner = _StreamingInner()
        breaker = CircuitBreaker(
            window_seconds=60.0,
            max_cost_usd_per_window=0.20,
            cooldown_seconds=10.0,
        )
        router = BreakerModelRouter(inner=inner, breaker=breaker)

        events = list(router.call_stream(_req()))

        assert [e.type for e in events] == ["text_delta", "text_delta", "done"]
        assert "".join(e.delta for e in events if e.type == "text_delta") == "hello world"
        assert inner.stream_count == 1
        assert inner.call_count == 0
        assert breaker.snapshot()["cost_in_window_usd"] == 0.25
        assert breaker.state == "open"

    def test_call_stream_failure_counts_toward_breaker(self, patched_time):
        inner = _StreamingInner(fail_after_first_delta=True)
        breaker = CircuitBreaker(
            window_seconds=60.0,
            max_errors_per_window=0,
            cooldown_seconds=10.0,
        )
        router = BreakerModelRouter(inner=inner, breaker=breaker)

        with pytest.raises(RuntimeError, match="stream failed"):
            list(router.call_stream(_req()))

        assert inner.stream_count == 1
        assert inner.call_count == 0
        assert breaker.state == "open"
        with pytest.raises(CircuitOpen):
            list(router.call_stream(_req()))
        assert inner.stream_count == 1
