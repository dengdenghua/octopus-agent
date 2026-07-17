from __future__ import annotations

from runtime.sensing.model_router.dispatch_router import ModelDispatchRouter
from runtime.sensing.model_router.models import (
    Message,
    ModelRequest,
    ModelResponse,
    ModelRouter,
    ModelStreamEvent,
)


class _Unavailable(ModelRouter):
    def call(self, request: ModelRequest) -> ModelResponse:
        raise RuntimeError("http_402: insufficient_balance")

    def call_stream(self, request: ModelRequest):
        raise RuntimeError("http_402: insufficient_balance")
        yield  # pragma: no cover


class _Healthy(ModelRouter):
    def __init__(self) -> None:
        self.models: list[str] = []

    def call(self, request: ModelRequest) -> ModelResponse:
        self.models.append(request.model)
        return ModelResponse(text="recovered")

    def call_stream(self, request: ModelRequest):
        self.models.append(request.model)
        yield ModelStreamEvent(type="text_delta", delta="recovered")
        yield ModelStreamEvent(type="done", final=ModelResponse(text="recovered"))


def _request() -> ModelRequest:
    return ModelRequest(
        model="unfunded",
        messages=[Message(role="user", content="fix code")],
    )


def _router() -> tuple[ModelDispatchRouter, _Healthy]:
    unavailable = _Unavailable()
    healthy = _Healthy()
    router = ModelDispatchRouter(fallback=unavailable)
    router.register("unfunded-entry", unavailable)
    router.register("unfunded", unavailable)
    router.register("healthy", healthy)
    return router, healthy


def test_named_provider_balance_error_falls_back_for_call() -> None:
    router, healthy = _router()

    response = router.call(_request())

    assert response.text == "recovered"
    assert response.model == "healthy"
    assert healthy.models == ["healthy"]


def test_named_provider_balance_error_falls_back_for_stream() -> None:
    router, healthy = _router()

    events = list(router.call_stream(_request()))

    assert [event.type for event in events] == ["text_delta", "done"]
    assert events[-1].final is not None
    assert events[-1].final.model == "healthy"
    assert healthy.models == ["healthy"]


def test_partial_stream_never_replays_on_another_provider() -> None:
    class _Partial(ModelRouter):
        def call(self, request: ModelRequest) -> ModelResponse:
            raise NotImplementedError

        def call_stream(self, request: ModelRequest):
            yield ModelStreamEvent(type="text_delta", delta="partial")
            raise RuntimeError("http_402: insufficient_balance")

    healthy = _Healthy()
    router = ModelDispatchRouter(fallback=_Partial())
    router.register("unfunded", router._fallback)
    router.register("healthy", healthy)

    try:
        list(router.call_stream(_request()))
    except RuntimeError as exc:
        assert "http_402" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("partial stream must surface the original failure")
    assert healthy.models == []


def test_provider_rescue_prefers_pro_over_earlier_chat_route() -> None:
    unavailable = _Unavailable()
    chat = _Healthy()
    pro = _Healthy()
    router = ModelDispatchRouter(fallback=unavailable)
    router.register("unfunded", unavailable)
    router.register("deepseek-chat", chat)
    router.register("deepseek-v4-flash", _Healthy())
    router.register("deepseek-v4-pro", pro)

    response = router.call(_request())

    assert response.text == "recovered"
    assert chat.models == []
    assert pro.models == ["deepseek-v4-pro"]
