
from __future__ import annotations

import functools
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any, TypeVar

try:
    from opentelemetry import trace  # type: ignore[import-untyped]
    from opentelemetry.trace import Status, StatusCode  # type: ignore[import-untyped]

    OTEL_AVAILABLE = True
except ImportError:  # pragma: no cover - tested via test_tracing_noop path
    OTEL_AVAILABLE = False

    class _NoopSpan:
        def set_attribute(self, *a: Any, **kw: Any) -> None: ...
        def set_status(self, *a: Any, **kw: Any) -> None: ...
        def record_exception(self, *a: Any, **kw: Any) -> None: ...
        def end(self) -> None: ...
        def __enter__(self) -> _NoopSpan:
            return self
        def __exit__(self, *a: Any) -> None: ...

    class _NoopTracer:
        def start_as_current_span(self, name: str, **kw: Any) -> _NoopSpan:
            return _NoopSpan()
        def start_span(self, name: str, **kw: Any) -> _NoopSpan:
            return _NoopSpan()

    class _NoopStatusCode:
        OK = "OK"
        ERROR = "ERROR"

    class _NoopStatus:
        def __init__(self, code: str, description: str = "") -> None:
            self.code = code

    Status = _NoopStatus  # type: ignore[assignment,misc]
    StatusCode = _NoopStatusCode  # type: ignore[assignment,misc]



OCTOPUS_ATTR_STAGE = "octopus.stage"          # Implementation note.
OCTOPUS_ATTR_TASK_ID = "octopus.task_id"
OCTOPUS_ATTR_ARM = "octopus.arm_id"
OCTOPUS_ATTR_SUCKER = "octopus.sucker_id"
OCTOPUS_ATTR_RECIPE = "octopus.recipe_id"
OCTOPUS_ATTR_GENOME = "octopus.genome_version"
OCTOPUS_ATTR_COST_USD = "octopus.cost_usd"
OCTOPUS_ATTR_COST_TOKENS = "octopus.cost_tokens"

GEN_AI_ATTR_SYSTEM = "gen_ai.system"
GEN_AI_ATTR_MODEL = "gen_ai.request.model"
GEN_AI_ATTR_INPUT_TOKENS = "gen_ai.usage.input_tokens"
GEN_AI_ATTR_OUTPUT_TOKENS = "gen_ai.usage.output_tokens"
GEN_AI_ATTR_FINISH_REASONS = "gen_ai.response.finish_reasons"



def get_tracer(name: str = "runtime") -> Any:
    if OTEL_AVAILABLE:
        return trace.get_tracer(name)
    return _NoopTracer()  # type: ignore[name-defined]


@contextmanager
def _span_scope(name: str) -> Iterator[Any]:
    """Create a span without attaching it to the global current context.

    Starlette can run sync generators and worker callbacks in different
    contextvars contexts. ``start_as_current_span`` attaches a token that must
    be detached from the same context; when that invariant breaks,
    OpenTelemetry logs noisy "Failed to detach context" tracebacks. A plain
    span still records attributes/status/events while avoiding attach/detach.
    """
    span = get_tracer().start_span(name)
    try:
        yield span
    finally:
        span.end()



F = TypeVar("F", bound=Callable[..., Any])


def traced(
    span_name: str | None = None,
    stage: str | None = None,
    attributes: dict[str, Any] | None = None,
) -> Callable[[F], F]:
    static_attrs = dict(attributes or {})

    def decorator(fn: F) -> F:
        name = span_name or f"{fn.__module__}.{fn.__qualname__}"

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            with _span_scope(name) as span:
                if stage:
                    span.set_attribute(OCTOPUS_ATTR_STAGE, stage)
                for k, v in static_attrs.items():
                    span.set_attribute(k, v)
                try:
                    result = fn(*args, **kwargs)
                    span.set_status(Status(StatusCode.OK))
                    return result
                except Exception as e:
                    span.record_exception(e)
                    span.set_status(Status(StatusCode.ERROR, str(e)))
                    raise

        return wrapper  # type: ignore[return-value]

    return decorator




@contextmanager
def trace_stage(
    name: str,
    stage: str | None = None,
    task_id: str | None = None,
    arm_id: str | None = None,
    **extra: Any,
) -> Iterator[Any]:
    with _span_scope(name) as span:
        if stage:
            span.set_attribute(OCTOPUS_ATTR_STAGE, stage)
        if task_id:
            span.set_attribute(OCTOPUS_ATTR_TASK_ID, task_id)
        if arm_id:
            span.set_attribute(OCTOPUS_ATTR_ARM, arm_id)
        for k, v in extra.items():
            span.set_attribute(k, v)
        try:
            yield span
            span.set_status(Status(StatusCode.OK))
        except Exception as e:
            span.record_exception(e)
            span.set_status(Status(StatusCode.ERROR, str(e)))
            raise




def record_gen_ai_cost(
    span: Any,
    *,
    system: str,
    model: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    usd: float = 0.0,
    finish_reasons: list[str] | None = None,
) -> None:
    span.set_attribute(GEN_AI_ATTR_SYSTEM, system)
    span.set_attribute(GEN_AI_ATTR_MODEL, model)
    span.set_attribute(GEN_AI_ATTR_INPUT_TOKENS, input_tokens)
    span.set_attribute(GEN_AI_ATTR_OUTPUT_TOKENS, output_tokens)
    if finish_reasons:
        span.set_attribute(GEN_AI_ATTR_FINISH_REASONS, finish_reasons)
    span.set_attribute(OCTOPUS_ATTR_COST_USD, float(usd))
    span.set_attribute(OCTOPUS_ATTR_COST_TOKENS, int(input_tokens + output_tokens))
