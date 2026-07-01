"""Tests for `_estimate_context_fullness` in react_loop.

Covers the ratio computation, the model-name → budget mapping, and the
[0.0, 1.0] clamp. The injection logic in `stream_react_loop` is left
to be exercised by the wider react_loop suite; unit-testing the helper
covers the hard logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from runtime.core.cerebrum.react_context import (
    _compress_context,
    _content_to_text,
    _estimate_messages_tokens,
)
from runtime.core.cerebrum.react_loop import _estimate_context_fullness


@dataclass
class _Msg:
    """Minimal stand-in for runtime.sensing.model_router.models.Message.

    The helper only reads ``.content`` (via ``str(...)``), so this is
    enough to drive every branch of the budget math.
    """

    content: Any
    role: str = "user"


# ─── 1. Empty / zero-length input ───────────────────────────────


def test_empty_messages_returns_zero() -> None:
    assert _estimate_context_fullness([], "anthropic/claude-4") == 0.0


# ─── 2. Tiny messages → ratio < 0.1 ────────────────────────────


def test_tiny_messages_low_ratio() -> None:
    msgs = [_Msg(content="hi"), _Msg(content="hello world")]
    ratio = _estimate_context_fullness(msgs, "anthropic/claude-4")
    assert 0.0 <= ratio < 0.1


# ─── 3. Pad until > 80% → ratio > 0.8 ───────────────────────────


def test_padded_messages_exceed_eighty_percent() -> None:
    # Default unknown-model budget is ~25k estimated tokens, so 90k ASCII chars
    # (~22.5k tokens) gets us comfortably above the 0.80 threshold.
    big = "x" * 90_000
    ratio = _estimate_context_fullness([_Msg(content=big)], "unknown-model")
    assert ratio > 0.8


# ─── 4. Default budget for unknown model name ──────────────────


def test_unknown_model_uses_default_budget() -> None:
    # 50k ASCII chars ~= 12.5k estimated tokens vs 25k default → 0.5
    msgs = [_Msg(content="x" * 50_000)]
    ratio = _estimate_context_fullness(msgs, "totally-made-up-model")
    assert abs(ratio - 0.5) < 1e-6


# ─── 5. claude-sonnet uses 600k budget ─────────────────────────


def test_claude_sonnet_uses_large_budget() -> None:
    # 60k ASCII chars ~= 15k tokens → 0.1 against the 150k claude budget;
    # same content against the 25k default would be 0.6, so the budget mapping
    # matters here.
    msgs = [_Msg(content="x" * 60_000)]
    ratio = _estimate_context_fullness(msgs, "anthropic/claude-sonnet-4")
    assert abs(ratio - 0.1) < 1e-6


def test_claude_3_5_uses_large_budget() -> None:
    msgs = [_Msg(content="x" * 60_000)]
    ratio = _estimate_context_fullness(msgs, "anthropic/claude-3-5-sonnet")
    assert abs(ratio - 0.1) < 1e-6


def test_gpt_4o_uses_400k_budget() -> None:
    # 40k ASCII chars ~= 10k tokens / 100k budget == 0.1
    msgs = [_Msg(content="x" * 40_000)]
    ratio = _estimate_context_fullness(msgs, "openai/gpt-4o-mini")
    assert abs(ratio - 0.1) < 1e-6


# ─── 6. Ratio clamped to [0.0, 1.0] on overflow ───────────────


def test_overflow_input_is_clamped_to_one() -> None:
    # 10x the default budget — without the clamp this would be 10.0.
    huge = "x" * 1_000_000
    ratio = _estimate_context_fullness([_Msg(content=huge)], "unknown-model")
    assert ratio == 1.0


def test_none_model_treated_as_default_budget() -> None:
    msgs = [_Msg(content="x" * 100_000)]
    ratio = _estimate_context_fullness(msgs, None)
    assert ratio == 1.0


def test_chinese_text_uses_token_proxy_not_raw_chars() -> None:
    # 15k Chinese chars ~= 10k estimated tokens, so default 25k budget => 0.4.
    msgs = [_Msg(content="中" * 15_000)]
    ratio = _estimate_context_fullness(msgs, "unknown-model")
    assert abs(ratio - 0.4) < 0.01


def test_structured_content_blocks_are_counted() -> None:
    msg = _Msg(
        content=[
            {"type": "text", "text": "hello world"},
            {"type": "tool_result", "content": "工具返回：" + ("中" * 300)},
            {"type": "image_url", "image_url": {"url": "https://example.test/a.png"}},
        ]
    )

    text = _content_to_text(msg.content)

    assert "hello world" in text
    assert "工具返回" in text
    assert "https://example.test/a.png" in text
    assert _estimate_messages_tokens([msg]) > 200


def test_structured_content_pressure_not_treated_as_empty() -> None:
    msg = _Msg(
        content=[
            {"type": "tool_result", "content": "x" * 90_000},
        ]
    )

    ratio = _estimate_context_fullness([msg], "unknown-model")

    assert ratio > 0.8


def test_ratio_always_within_bounds_for_varied_inputs() -> None:
    cases = [
        ([], "anything"),
        ([_Msg(content="")], "claude-sonnet"),
        ([_Msg(content="x" * 5)], "gpt-5-turbo"),
        ([_Msg(content="x" * 10_000_000)], "claude-4"),
    ]
    for msgs, model in cases:
        r = _estimate_context_fullness(msgs, model)
        assert 0.0 <= r <= 1.0, f"out of range for ({len(msgs)}, {model!r}): {r}"


def test_compress_context_hard_caps_when_observations_remain_large() -> None:
    messages = [
        _Msg(role="system", content="system prompt"),
        *[
            _Msg(
                role="user",
                content="Observation: web_search\n" + ("x" * 12_000),
            )
            for _ in range(12)
        ],
        _Msg(role="assistant", content="recent answer"),
    ]

    compressed = _compress_context(messages, max_tokens=2_000, router=None)

    assert _estimate_messages_tokens(compressed) <= 2_000
    assert compressed[0].role == "system"
    assert compressed[-1].content == "recent answer"


def test_code_mode_compression_hard_caps_large_file_observations() -> None:
    messages = [
        _Msg(role="system", content="system prompt"),
        *[
            _Msg(
                role="user",
                content="Observation: read_file big.py\n" + ("x" * 20_000),
            )
            for _ in range(10)
        ],
        _Msg(role="assistant", content="next step"),
    ]

    compressed = _compress_context(
        messages,
        max_tokens=3_000,
        router=None,
        is_code_mode=True,
    )

    assert _estimate_messages_tokens(compressed) <= 3_000
    assert compressed[0].role == "system"
    assert compressed[-1].content == "next step"


def test_compress_context_trims_oversized_chinese_tail() -> None:
    messages = [
        _Msg(role="system", content="system prompt"),
        _Msg(role="user", content="中" * 30_000),
    ]

    compressed = _compress_context(messages, max_tokens=2_000, router=None)

    assert _estimate_messages_tokens(compressed) <= 2_000
    assert compressed[-1].content.startswith("[前文因上下文预算已截断]")


def test_compress_context_trims_oversized_structured_tail() -> None:
    messages = [
        _Msg(role="system", content="system prompt"),
        _Msg(
            role="user",
            content=[{"type": "tool_result", "content": "x" * 40_000}],
        ),
    ]

    compressed = _compress_context(messages, max_tokens=2_000, router=None)

    assert _estimate_messages_tokens(compressed) <= 2_000
    assert compressed[-1].content.startswith("[前文因上下文预算已截断]")
