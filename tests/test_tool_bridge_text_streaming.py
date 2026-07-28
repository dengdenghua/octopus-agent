"""Tests for live text streaming in the native tool loop (TTFT fix).

The native loop used to buffer a round's text into ``round_text_chunks``
and only deliver it after the round closed — a condensed checkpoint for
tool rounds, a full dump for the final answer round. TTFT for the final
synthesis therefore equalled its full decode time. Post-tool rounds now
stream text live with a tail-margin holdback and tool-envelope guards;
content delivered is identical, only timing moves earlier. First-round
preambles keep the condensed-checkpoint treatment (their prose is where
protocol echoes cluster, and the checkpoint filters it deliberately).
"""

from __future__ import annotations

from runtime.platform.models import ParsedIntent
from runtime.sensing.gateway.tool_bridge import (
    _NATIVE_TEXT_STREAM_TAIL_MARGIN,
    stream_agentic_fallback,
)
from runtime.sensing.model_router.models import (
    ModelResponse,
    ModelStreamEvent,
    ToolCall,
)
from tests.test_tool_bridge_scope import _agent, _stack

_LIST_CALL = ToolCall(id="t1", name="list_cwd", input={"path": "."})


def _intent(goal: str, tmp_path) -> ParsedIntent:
    return ParsedIntent(
        raw=goal,
        intent_type="task",
        normalized_goal=goal,
        user_context={
            "conversation_id": "native-text-stream-test",
            "metadata": {"mode": "code", "workspace_path": str(tmp_path)},
        },
    )


def _texts(events: list[tuple]) -> list[str]:
    return [str(event[1]) for event in events if event[0] == "text"]


def _router_with_tool_first(final_chunks: list[str]):
    """Round 1 runs one tool; round 2 answers with ``final_chunks``."""

    class Router:
        def __init__(self):
            self.calls = 0

        def call_stream(self, _request):
            self.calls += 1
            if self.calls == 1:
                yield ModelStreamEvent(type="tool_use", tool_call=_LIST_CALL)
                yield ModelStreamEvent(type="done", final=ModelResponse(text=""))
                return
            for piece in final_chunks:
                yield ModelStreamEvent(type="text_delta", delta=piece)
            yield ModelStreamEvent(
                type="done", final=ModelResponse(text="".join(final_chunks))
            )

    return Router()


def test_final_answer_streams_live_during_round(tmp_path) -> None:
    answer = "第一段结论，基于刚才收集到的全部证据展开说明。" * 3  # > margin

    events = list(
        stream_agentic_fallback(
            _stack(_router_with_tool_first([answer[:20], answer[20:60], answer[60:]])),
            _intent("分析项目", tmp_path),
            _agent(),
        )
    )

    texts = _texts(events)
    # Content invariant: exactly the round text, delivered in order.
    assert "".join(texts) == answer
    # Timing: text flowed during the round (slice + held-back tail
    # flush), not one end-of-round dump.
    assert len(texts) >= 2


def test_envelope_marker_suppresses_live_streaming(tmp_path) -> None:
    # ``<function=`` trips the stream guard but not the XML recovery
    # (which only honors ``<tool_call``), so the round still ends as a
    # plain final answer — delivered buffered, like before the change.
    answer = "文档说明：<function=foo> 只是示例文本，并不是真正的调用。"

    events = list(
        stream_agentic_fallback(
            _stack(_router_with_tool_first([answer[:25], answer[25:]])),
            _intent("解释格式", tmp_path),
            _agent(),
        )
    )

    # Any early live slice would produce ≥2 text events (slice + tail
    # flush); a single full-text event proves delivery stayed buffered.
    assert _texts(events) == [answer]


def test_pretool_prose_streaming_skips_duplicate_checkpoint(tmp_path) -> None:
    prose = (
        "我先列一下目录看看整体结构，再逐个核对关键文件的定义和事件流向，"
        "然后再决定下一步怎么做，这样得出的结论才有依据。"
    )
    assert len(prose) > _NATIVE_TEXT_STREAM_TAIL_MARGIN  # must exceed holdback
    answer = "目录结构已经清楚了，这就是最终结论。"

    class Router:
        def __init__(self):
            self.calls = 0

        def call_stream(self, _request):
            self.calls += 1
            if self.calls == 1:
                yield ModelStreamEvent(type="tool_use", tool_call=_LIST_CALL)
                yield ModelStreamEvent(type="done", final=ModelResponse(text=""))
                return
            if self.calls == 2:
                # Post-tool round: narration streams live, then another
                # tool call — the condensed checkpoint must not duplicate
                # the already-visible prose.
                yield ModelStreamEvent(type="text_delta", delta=prose[:30])
                yield ModelStreamEvent(type="text_delta", delta=prose[30:])
                yield ModelStreamEvent(
                    type="tool_use",
                    # Distinct input — an identical repeat of round 1's
                    # call would be deduplicated before dispatch.
                    tool_call=ToolCall(id="t2", name="list_cwd", input={"path": "subdir"}),
                )
                yield ModelStreamEvent(type="done", final=ModelResponse(text=""))
                return
            yield ModelStreamEvent(type="text_delta", delta=answer)
            yield ModelStreamEvent(type="done", final=ModelResponse(text=answer))

    events = list(stream_agentic_fallback(_stack(Router()), _intent("看目录", tmp_path), _agent()))
    kinds = [event[0] for event in events]

    # Pre-tool prose streamed live, ahead of the second tool row.
    assert kinds.index("text") < kinds.index("tool_start", kinds.index("tool_start") + 1)
    # …and the condensed checkpoint is NOT emitted on top of it.
    commentary = [str(e[1]) for e in events if e[0] == "commentary"]
    assert not any("先列一下目录" in c for c in commentary)
    # The streamed narration is only the holdback-safe prefix.
    second_tool_at = kinds.index("tool_start", kinds.index("tool_start") + 1)
    pre_second_tool_texts = [
        str(delta)
        for kind, delta, _final in events[:second_tool_at]
        if kind == "text"
    ]
    assert "".join(pre_second_tool_texts) == prose[
        : len(prose) - _NATIVE_TEXT_STREAM_TAIL_MARGIN
    ]
    # Final answer round delivers in full.
    assert _texts(events)[-1].endswith(answer[-10:])


def test_short_text_under_margin_delivered_at_round_end(tmp_path) -> None:
    answer = "短答复。"  # below the holdback margin — nothing streams early

    events = list(
        stream_agentic_fallback(
            _stack(_router_with_tool_first([answer])),
            _intent("hi", tmp_path),
            _agent(),
        )
    )
    assert _texts(events) == [answer]
