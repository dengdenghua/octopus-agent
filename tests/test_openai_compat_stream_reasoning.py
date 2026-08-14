from __future__ import annotations

from runtime.sensing.model_router.openai_compat_stream import iter_openai_sse


class _FakeSSE:
    def __init__(self, lines: list[str]) -> None:
        self._lines = lines

    def iter_lines(self):
        yield from self._lines


def test_iter_openai_sse_preserves_reasoning_content():
    response = _FakeSSE(
        [
            'data: {"choices":[{"delta":{"reasoning_content":"plan"}}]}',
            'data: {"choices":[{"delta":{"content":"answer"}}]}',
            'data: {"usage":{"prompt_tokens":2,"completion_tokens":3},"choices":[]}',
            "data: [DONE]",
        ]
    )

    events = list(iter_openai_sse(response, model="deepseek-v4-pro"))

    assert [event.type for event in events] == [
        "thinking_delta",
        "text_delta",
        "done",
    ]
    assert events[0].delta == "plan"
    assert events[1].delta == "answer"
    assert events[-1].final is not None
    assert events[-1].final.thinking == "plan"
    assert events[-1].final.text == "answer"
    assert events[-1].final.input_tokens == 2
    assert events[-1].final.output_tokens == 3


def test_iter_openai_sse_preserves_reasoning_aliases_and_byte_lines():
    response = _FakeSSE(
        [
            b'data: {"choices":[{"delta":{"reasoning":"step "}}]}',
            b'data: {"choices":[{"delta":{"thinking":"two"}}]}',
            b'data: {"choices":[{"delta":{"content":[{"type":"text","text":"answer"}]}}]}',
            b"data: [DONE]",
        ]
    )

    events = list(iter_openai_sse(response, model="glm-4.6"))

    assert [event.type for event in events] == [
        "thinking_delta",
        "thinking_delta",
        "text_delta",
        "done",
    ]
    assert events[-1].final is not None
    assert events[-1].final.thinking == "step two"
    assert events[-1].final.text == "answer"


def test_iter_openai_sse_emits_streamed_tool_call():
    response = _FakeSSE(
        [
            (
                'data: {"choices":[{"delta":{"tool_calls":[{"index":0,'
                '"id":"call_1","type":"function","function":{"name":"read_file",'
                '"arguments":"{\\"path\\""}}]}}]}'
            ),
            (
                'data: {"choices":[{"delta":{"tool_calls":[{"index":0,'
                '"function":{"arguments":":\\"README.md\\"}"}}]}}]}'
            ),
            'data: {"usage":{"prompt_tokens":5,"completion_tokens":7},"choices":[]}',
            "data: [DONE]",
        ]
    )

    events = list(iter_openai_sse(response, model="gpt-4o-mini"))

    assert [event.type for event in events] == [
        "tool_call_delta",
        "tool_call_delta",
        "tool_call_delta",
        "tool_use",
        "done",
    ]
    name_delta, first_args, second_args = events[0], events[1], events[2]
    assert name_delta.index == 0
    assert name_delta.call_id == "call_1"
    assert name_delta.name == "read_file"
    assert name_delta.arguments_delta == ""
    assert first_args.index == 0
    assert first_args.call_id == "call_1"
    assert first_args.arguments_delta == '{"path"'
    assert second_args.index == 0
    assert second_args.call_id == "call_1"
    assert second_args.arguments_delta == ':"README.md"}'
    tool_event = events[3]
    assert tool_event.tool_call is not None
    assert tool_event.tool_call.id == "call_1"
    assert tool_event.tool_call.name == "read_file"
    assert tool_event.tool_call.input == {"path": "README.md"}
    assert events[-1].final is not None
    assert events[-1].final.tool_calls == [tool_event.tool_call]


def test_iter_openai_sse_accepts_python_repr_tool_arguments():
    response = _FakeSSE(
        [
            (
                'data: {"choices":[{"delta":{"tool_calls":[{"index":0,'
                '"id":"call_1","type":"function","function":{"name":"read_file",'
                "\"arguments\":\"{'path': 'README.md'}\"}}]}}]}"
            ),
            "data: [DONE]",
        ]
    )

    events = list(iter_openai_sse(response, model="glm-4.6"))

    assert [event.type for event in events] == [
        "tool_call_delta",
        "tool_call_delta",
        "tool_use",
        "done",
    ]
    name_delta, args_delta = events[0], events[1]
    assert name_delta.name == "read_file"
    assert name_delta.arguments_delta == ""
    assert args_delta.arguments_delta == "{'path': 'README.md'}"
    assert events[2].tool_call is not None
    assert events[2].tool_call.input == {"path": "README.md"}


def test_iter_openai_sse_accepts_legacy_function_call_delta():
    response = _FakeSSE(
        [
            (
                'data: {"choices":[{"delta":{"function_call":'
                '{"name":"read_file","arguments":"{\\"path\\""}}}]}'
            ),
            ('data: {"choices":[{"delta":{"function_call":{"arguments":":\\"README.md\\"}"}}}]}'),
            "data: [DONE]",
        ]
    )

    events = list(iter_openai_sse(response, model="glm-4.6"))

    assert [event.type for event in events] == [
        "tool_call_delta",
        "tool_call_delta",
        "tool_call_delta",
        "tool_use",
        "done",
    ]
    name_delta, first_args, second_args = events[0], events[1], events[2]
    assert name_delta.index == 0
    assert name_delta.call_id == "function_call_0"
    assert name_delta.name == "read_file"
    assert name_delta.arguments_delta == ""
    assert first_args.index == 0
    assert first_args.call_id == "function_call_0"
    assert first_args.arguments_delta == '{"path"'
    assert second_args.index == 0
    assert second_args.call_id == "function_call_0"
    assert second_args.arguments_delta == ':"README.md"}'
    tool_event = events[3]
    assert tool_event.tool_call is not None
    assert tool_event.tool_call.id == "function_call_0"
    assert tool_event.tool_call.name == "read_file"
    assert tool_event.tool_call.input == {"path": "README.md"}
    assert events[-1].final is not None
    assert events[-1].final.tool_calls == [tool_event.tool_call]


def test_iter_openai_sse_preserves_finish_reason():
    response = _FakeSSE(
        [
            'data: {"choices":[{"delta":{"content":"part one"},"finish_reason":"length"}]}',
            "data: [DONE]",
        ]
    )

    events = list(iter_openai_sse(response, model="gpt-4o-mini"))

    assert events[-1].final is not None
    assert events[-1].final.finish_reason == "length"


def test_iter_openai_sse_handles_multiline_data_events():
    response = _FakeSSE(
        [
            "data: {",
            'data: "choices":[{"delta":{"content":"multi"}}]',
            "data: }",
            "",
            'data:{"choices":[{"delta":{"content":" line"}}]}',
            "",
            ": keepalive",
            "data: [DONE]",
            "",
        ]
    )

    events = list(iter_openai_sse(response, model="qwen-plus"))

    assert [event.type for event in events] == ["text_delta", "text_delta", "done"]
    assert events[0].delta == "multi"
    assert events[1].delta == " line"
    assert events[-1].final is not None
    assert events[-1].final.text == "multi line"


def test_iter_openai_sse_splits_inline_think_tags_out_of_content():
    """Reasoning inlined in ``content`` must not surface as the answer.

    Measured on minimax-m3 via a relay: the message carries no
    ``reasoning_content`` at all and instead returns
    ``"<think>…</think>4"`` in ``content``.
    """
    response = _FakeSSE(
        [
            'data: {"choices":[{"delta":{"content":"<think>weigh it up</think>"}}]}',
            'data: {"choices":[{"delta":{"content":"4"}}]}',
            "data: [DONE]",
        ]
    )

    events = list(iter_openai_sse(response, model="minimax-m3"))

    assert events[-1].final is not None
    assert events[-1].final.text == "4"
    assert events[-1].final.thinking == "weigh it up"
    assert "<think>" not in events[-1].final.text


def test_iter_openai_sse_handles_a_think_tag_split_across_chunks():
    """A tag can straddle chunk boundaries, so buffering must be correct."""
    response = _FakeSSE(
        [
            'data: {"choices":[{"delta":{"content":"<thi"}}]}',
            'data: {"choices":[{"delta":{"content":"nk>hidden"}}]}',
            'data: {"choices":[{"delta":{"content":"</thi"}}]}',
            'data: {"choices":[{"delta":{"content":"nk>visible"}}]}',
            "data: [DONE]",
        ]
    )

    events = list(iter_openai_sse(response, model="minimax-m3"))

    assert events[-1].final is not None
    assert events[-1].final.text == "visible"
    assert events[-1].final.thinking == "hidden"


def test_iter_openai_sse_leaves_an_unopened_angle_bracket_alone():
    """Content that merely resembles a tag prefix must survive verbatim.

    A stream ending on ``"<thi"`` never completed a tag, so it was literal
    text and belongs in the answer rather than being swallowed.
    """
    response = _FakeSSE(
        [
            'data: {"choices":[{"delta":{"content":"compare a <thi"}}]}',
            "data: [DONE]",
        ]
    )

    events = list(iter_openai_sse(response, model="minimax-m3"))

    assert events[-1].final is not None
    assert events[-1].final.text == "compare a <thi"
    assert events[-1].final.thinking == ""


def test_iter_openai_sse_keeps_plain_content_byte_identical():
    """The common path must be untouched by the splitter."""
    response = _FakeSSE(
        [
            'data: {"choices":[{"delta":{"content":"a < b and c > d"}}]}',
            "data: [DONE]",
        ]
    )

    events = list(iter_openai_sse(response, model="deepseek-v4-flash"))

    assert events[-1].final is not None
    assert events[-1].final.text == "a < b and c > d"
    assert events[-1].final.thinking == ""


def test_iter_openai_sse_streams_parallel_tool_call_deltas():
    response = _FakeSSE(
        [
            (
                'data: {"choices":[{"delta":{"tool_calls":['
                '{"index":0,"id":"call_a","type":"function",'
                '"function":{"name":"read_file","arguments":"{\\"path\\":\\""}},'
                '{"index":1,"id":"call_b","type":"function",'
                '"function":{"name":"grep","arguments":"{\\"pattern\\":\\""}}'
                "]}}]}"
            ),
            (
                'data: {"choices":[{"delta":{"tool_calls":['
                '{"index":0,"function":{"arguments":"a.txt\\"}"}},'
                '{"index":1,"function":{"arguments":"TODO\\"}"}}'
                "]}}]}"
            ),
            "data: [DONE]",
        ]
    )

    events = list(iter_openai_sse(response, model="deepseek-v4-pro"))

    assert [event.type for event in events] == [
        "tool_call_delta",
        "tool_call_delta",
        "tool_call_delta",
        "tool_call_delta",
        "tool_call_delta",
        "tool_call_delta",
        "tool_use",
        "tool_use",
        "done",
    ]
    deltas = [e for e in events if e.type == "tool_call_delta"]
    assert [(d.index, d.call_id, d.name, d.arguments_delta) for d in deltas] == [
        (0, "call_a", "read_file", ""),
        (0, "call_a", "read_file", '{"path":"'),
        (1, "call_b", "grep", ""),
        (1, "call_b", "grep", '{"pattern":"'),
        (0, "call_a", "read_file", 'a.txt"}'),
        (1, "call_b", "grep", 'TODO"}'),
    ]
    tool_events = [e for e in events if e.type == "tool_use"]
    assert [t.tool_call.id for t in tool_events] == ["call_a", "call_b"]
    assert tool_events[0].tool_call.input == {"path": "a.txt"}
    assert tool_events[1].tool_call.input == {"pattern": "TODO"}
