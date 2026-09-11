import pytest

from runtime.execution.model_services import SharedExecutionRouter
from runtime.platform.models.llm import ModelRequest, ModelResponse


class RecordingRouter:
    def __init__(self):
        self.models = []

    def call(self, request):
        self.models.append(request.model)
        return ModelResponse(text="ok")


def test_official_selection_does_not_fall_back_to_custom_api():
    official = RecordingRouter()
    custom = RecordingRouter()
    custom.official_router = official
    custom.has = lambda name: name == "custom-route"
    router = SharedExecutionRouter(custom)
    router.call(ModelRequest(model="official/qwen", messages=[]))
    router.call(ModelRequest(model="custom-route", messages=[]))
    assert official.models == ["qwen"]
    assert custom.models == ["custom-route"]
    with pytest.raises(ValueError):
        router.call(ModelRequest(model="unknown", messages=[]))


def test_unavailable_official_service_never_uses_fallback():
    router = SharedExecutionRouter(RecordingRouter())
    assert not router.has("official/qwen")
    with pytest.raises(ValueError):
        router.call(ModelRequest(model="official/qwen", messages=[]))


def test_responses_stream_announces_items_before_deltas_and_completion():
    import json
    from runtime.execution.codex_backend.responses_proxy import _responses_sse
    wire = _responses_sse({"output": [{"id": "msg_test", "type": "message", "role": "assistant", "status": "completed", "content": [{"type": "output_text", "text": "ok", "annotations": []}]}]})
    events = [json.loads(line[6:]) for line in wire.decode().splitlines() if line.startswith("data: ")]
    names = [event["type"] for event in events]
    assert names.index("response.output_item.added") < names.index("response.output_text.delta") < names.index("response.output_item.done")
    assert names[-1] == "response.completed"
    assert [event["sequence_number"] for event in events] == list(range(len(events)))
