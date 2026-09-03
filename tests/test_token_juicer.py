"""Tests for runtime.core.cerebrum.token_juicer.

Each test isolates one compression pass and verifies (a) the pass
fires when expected, (b) it doesn't strip protected sentinels, and
(c) JuiceStats correctly accounts before/after sizes.
"""

from __future__ import annotations

import pytest

from runtime.core.cerebrum.token_juicer import (
    JuiceStats,
    is_enabled,
    juice,
)


def test_empty_input_passes_through() -> None:
    out, stats = juice("")
    assert out == ""
    assert stats == JuiceStats(0, 0, ())


def test_short_plain_text_unchanged() -> None:
    out, stats = juice("hello world")
    assert out == "hello world"
    assert stats.passes == ()
    assert stats.saved == 0


def test_html_pass_strips_tags_keeps_visible_text() -> None:
    raw = (
        "<html><body>"
        "<p>Hello <b>world</b></p>"
        "<script>evil()</script>"
        "<style>.x{color:red}</style>"
        "<p>second line</p>"
        "</body></html>"
    )
    out, stats = juice(
        raw, enable_url=False, enable_dedup=False, enable_array=False, enable_cap=False
    )
    assert "evil()" not in out, out
    assert "color:red" not in out, out
    assert "Hello world" in out, out
    assert "second line" in out, out
    assert "html" in stats.passes
    assert stats.after < stats.before


def test_url_shortening_collapses_long_urls() -> None:
    raw = "see https://example.com/very/long/path?a=" + "x" * 200 + " for details"
    out, stats = juice(
        raw, enable_html=False, enable_dedup=False, enable_array=False, enable_cap=False
    )
    assert "<example.com/" in out, out
    assert "x" * 200 not in out
    assert "for details" in out
    assert "url" in stats.passes


def test_url_shortening_leaves_short_urls_alone() -> None:
    raw = "go to https://example.com/page now"
    out, stats = juice(
        raw, enable_html=False, enable_dedup=False, enable_array=False, enable_cap=False
    )
    assert out == raw
    assert "url" not in stats.passes


def test_url_shortening_preserves_generated_media_artifact_url() -> None:
    url = (
        "https://platform-outputs.agnes-ai.space/images/t2i/"
        "task_7gR7XZXfTYMXgvxuSu95r6SCxwxQ5cbf/"
        "output_347e8230aae943b69e86f19f45ccf574.png"
    )
    raw = (
        "(real tool execution succeeded) generate_image\n"
        f'{{"ok": true, "url": "{url}", "model": "agnes-image-2.5-flash"}}'
    )

    out, stats = juice(
        raw,
        enable_html=False,
        enable_dedup=False,
        enable_array=False,
        enable_cap=False,
    )

    assert out == raw
    assert url in out
    assert "url" not in stats.passes


def test_dedup_collapses_repeated_lines() -> None:
    raw = "starting\n" + "warning: x\n" * 8 + "done"
    out, stats = juice(
        raw, enable_html=False, enable_url=False, enable_array=False, enable_cap=False
    )
    assert "× 8 times" in out, out
    assert "starting" in out
    assert "done" in out
    assert "dedup" in stats.passes


def test_dedup_leaves_short_runs_alone() -> None:
    raw = "a\nb\nb\nb\nc"  # 3 b's — under threshold of 4
    out, stats = juice(
        raw, enable_html=False, enable_url=False, enable_array=False, enable_cap=False
    )
    assert out == raw
    assert "dedup" not in stats.passes


def test_prefix_dedup_preserves_heterogeneous_short_list() -> None:
    """A run of 12+ DISTINCT short lines (a todo list, test results, a
    grep-across-files inventory) must survive intact — every line is
    data the model may need to reason over, even when lines share a
    common prefix like `src/`. Regression for the removed prefix-run
    collapse, which guessed that prefix-sharing meant redundancy."""
    distinct = "\n".join(f"item-{i}: {chr(97 + i)}value" for i in range(14))
    out, _stats = juice(
        distinct,
        enable_html=False,
        enable_url=False,
        enable_array=False,
        enable_cap=False,
    )
    # No line dropped — all 14 distinct lines survive.
    for i in range(14):
        assert f"item-{i}:" in out, f"line item-{i} was dropped: {out!r}"
    assert "omitted" not in out


def test_grep_like_distinct_matches_preserved() -> None:
    """The exact shape the old pass targeted — many grep hits sharing
    `src/module/file_N.py:` — is now preserved, because each match is a
    distinct result, not redundant repetition."""
    grep_like = "\n".join(f"src/module/file_{i}.py: match found" for i in range(20))
    out, stats = juice(
        grep_like,
        enable_html=False,
        enable_url=False,
        enable_array=False,
        enable_cap=False,
    )
    for i in range(20):
        assert f"file_{i}.py:" in out, f"grep hit file_{i} dropped: {out!r}"
    assert "dedup" not in stats.passes


def test_dedup_still_collapses_exact_duplicate_lines() -> None:
    """Exact-duplicate runs (≥4 identical lines) are still collapsed —
    that's lossless and remains the dedup pass's job."""
    raw = "start\n" + "warning: deprecated\n" * 9 + "end"
    out, stats = juice(
        raw,
        enable_html=False,
        enable_url=False,
        enable_array=False,
        enable_cap=False,
    )
    assert "× 9 times" in out, out
    assert "start" in out and "end" in out
    assert "dedup" in stats.passes


def test_array_trim_collapses_long_lists() -> None:
    body = ", ".join(f'{{"id": {i}, "v": "x"}}' for i in range(30))
    raw = f"prefix [{body}] suffix"
    out, stats = juice(
        raw, enable_html=False, enable_url=False, enable_dedup=False, enable_cap=False
    )
    assert "more items omitted" in out
    assert "prefix" in out and "suffix" in out
    assert "array" in stats.passes


def test_hard_cap_keeps_head_and_tail() -> None:
    raw = "HEAD" + "x" * 10000 + "TAIL"
    out, stats = juice(
        raw,
        max_chars=500,
        enable_html=False,
        enable_url=False,
        enable_dedup=False,
        enable_array=False,
    )
    assert "HEAD" in out
    assert "TAIL" in out
    assert "已压缩中段" in out
    assert len(out) < len(raw)
    assert "cap" in stats.passes


def test_protected_sentinel_tool_failure_survives_cap() -> None:
    """If hard cap would eat the tail (containing `(工具失败)` sentinel)
    we revert to original. The model sees more tokens, but the loop's
    retry/error semantics stay correct."""
    raw = "HEAD" + "x" * 10000 + "(工具失败) status=timeout"
    out, _stats = juice(raw, max_chars=200)
    # Original returned because sentinel was in tail beyond cap.
    assert "(工具失败) status=timeout" in out


def test_protected_parallel_batch_header_survives() -> None:
    """[1/3 read_file] style headers must reach the model so it
    knows which observation belongs to which call."""
    raw = (
        "[1/3 read_file]\n"
        + ("a" * 50 + "\n") * 6
        + "[2/3 read_file]\n"
        + ("b" * 50 + "\n") * 6
        + "[3/3 read_file]\nresult"
    )
    out, _stats = juice(raw, max_chars=400)
    assert "[1/3 read_file]" in out
    assert "[2/3 read_file]" in out
    assert "[3/3 read_file]" in out
    assert len(out) < len(raw)


def test_parallel_success_receipts_are_capped_per_file() -> None:
    raw = "\n\n".join(
        f"[{index}/3 read_file]\n(real tool execution succeeded) read_file\n"
        + marker * 1800
        + f"\nTAIL-{index}"
        for index, marker in enumerate(("a", "b", "c"), start=1)
    )

    out, stats = juice(raw, max_chars=2400)

    assert "parallel-cap" in stats.passes
    assert len(out) < len(raw)
    for index in range(1, 4):
        assert f"[{index}/3 read_file]" in out
        assert f"TAIL-{index}" in out
    assert out.count("(real tool execution succeeded)") == 3


def test_combined_passes_compose() -> None:
    """Realistic scrape output: HTML body + duplicate warning lines +
    a long URL. All three passes should fire and stats reflect both
    before and after."""
    raw = (
        "<html><body>"
        + "<p>Article title</p>"
        + "<p>Body paragraph.</p>"
        + "</body></html>\n"
        + "warning: deprecated\n" * 6
        + "see https://very.long.example.com/path/"
        + "y" * 200
    )
    out, stats = juice(raw)
    assert "Article title" in out
    assert "Body paragraph." in out
    assert "× 6 times" in out
    assert "<very.long.example.com/" in out
    assert set(stats.passes) >= {"html", "dedup", "url"}


def test_is_enabled_defaults_on_and_respects_opt_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TokenJuice is ON by default — compression is validated to reduce
    token usage without losing sentinel patterns. Opt out via
    `OCTOPUS_TOKEN_JUICE=0|false|no|off`; any other value (including
    unset) keeps compression on."""
    monkeypatch.delenv("OCTOPUS_TOKEN_JUICE", raising=False)
    assert is_enabled() is True  # default ON
    monkeypatch.setenv("OCTOPUS_TOKEN_JUICE", "1")
    assert is_enabled() is True
    monkeypatch.setenv("OCTOPUS_TOKEN_JUICE", "true")
    assert is_enabled() is True
    monkeypatch.setenv("OCTOPUS_TOKEN_JUICE", "on")
    assert is_enabled() is True
    monkeypatch.setenv("OCTOPUS_TOKEN_JUICE", "0")
    assert is_enabled() is False
    monkeypatch.setenv("OCTOPUS_TOKEN_JUICE", "false")
    assert is_enabled() is False
    monkeypatch.setenv("OCTOPUS_TOKEN_JUICE", "off")
    assert is_enabled() is False
    monkeypatch.setenv("OCTOPUS_TOKEN_JUICE", "no")
    assert is_enabled() is False
    # Unrecognized values keep compression ON (default-on policy).
    monkeypatch.setenv("OCTOPUS_TOKEN_JUICE", "maybe")
    assert is_enabled() is True


def test_cjk_text_preserved() -> None:
    """Never strip CJK / emoji grapheme-by-grapheme.
    Verify that compression on text containing only CJK doesn't mangle it."""
    raw = "今天天气真好" * 200
    out, _stats = juice(raw, max_chars=400)
    # Either kept whole (if under cap after passes) or head+tail
    # form — both must remain valid CJK without partial decoding.
    assert "今天天气真好" in out
    out.encode("utf-8")  # would raise on broken surrogate pair


def test_react_loop_compresses_observation_when_flag_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Wiring proof: when OCTOPUS_TOKEN_JUICE is on, the observation
    that actually reaches the next LLM round through messages.append is
    the compressed version, not the raw one. Default-on path is
    covered by the existing 110 react_loop tests staying green (their
    short observations don't trigger any compression pass)."""
    from typing import Any

    from runtime.core.cerebrum.react_loop import stream_react_loop

    # Build a verbose HTML observation by giving the model an action
    # that returns one. We reuse the test harness's existing fakes.
    from tests.test_react_loop import (
        _build_stack_with_executor,
        _CapturingRouter,
        _intent,
    )

    monkeypatch.setenv("OCTOPUS_TOKEN_JUICE", "1")

    # Two-iter scripted router: first iter runs an exec_shell that
    # the test fixture handles; second iter gives Final Answer. We
    # patch the executor to return a long HTML observation so juicer
    # has something to compress.
    class _HtmlExecutor:
        """Stand-in executor that returns an HTML-heavy observation."""

        def __init__(self) -> None:
            from runtime.execution.suckers import Skill, SkillRegistry
            from runtime.execution.tool_engine import ToolExecutor
            from runtime.safety.auth import TrustEngine

            reg = SkillRegistry()
            reg.register(
                Skill(
                    name="fetch_html",
                    description="Returns a verbose HTML page.",
                    trusted_source="builtin://fetch_html",
                    handler=lambda url="x": {
                        "url": url,
                        "html": (
                            "<html><body>"
                            + "<p>Useful sentence.</p>"
                            + "<script>tracking()</script>" * 30
                            + "</body></html>"
                        ),
                    },
                ),
                verify_tests=False,
            )
            self.real = ToolExecutor(
                registry=reg,
                immunity=TrustEngine(
                    trusted_sources=["builtin://*"],
                    unknown_policy="allow",
                ),
            )
            self.registry = self.real.registry
            self.journal = self.real.journal

        def execute_step(self, *args: Any, **kwargs: Any) -> Any:
            return self.real.execute_step(*args, **kwargs)

    router = _CapturingRouter(
        [
            'Thought: fetch the page\nAction: fetch_html({"url": "x"})\n',
            "Final Answer: 已完成",
        ]
    )
    stack = _build_stack_with_executor(router)
    stack.executor = _HtmlExecutor()

    intent = _intent("compress test")
    intent.user_context["auto_approve"] = True

    # Drain the loop. After Iter 1, the next router request will
    # contain the compressed observation in its messages.
    gen = stream_react_loop(stack, intent, agent=None, max_iterations=3)
    list(gen)  # exhaust

    # The router captured the message stream of the second call;
    # check the user message containing "Observation:".
    second_request_messages = router.requests[1].messages
    obs_messages = [
        m
        for m in second_request_messages
        if isinstance(m.content, str) and m.content.startswith("Observation:")
    ]
    assert obs_messages, "no Observation: message reached the second LLM call"
    obs_text = obs_messages[0].content
    # Compressed: <script> blocks are gone, but the useful sentence
    # survives.
    assert "tracking()" not in obs_text, "<script> body leaked into prompt — juicer didn't engage"
    assert "Useful sentence." in obs_text


# ── code pass · AST-aware body elision ──


def _many_functions(count: int, body_lines: int = 8) -> str:
    return "\n".join(
        f"def f{i}(a, b):\n    '''compute f{i}.'''\n"
        + "\n".join(f"    x{k} = a + {k}" for k in range(body_lines))
        + "\n    return x0\n"
        for i in range(count)
    )


def test_code_pass_keeps_every_signature() -> None:
    """Signatures carry the structure a model reasons about; bodies don't."""
    out, stats = juice(_many_functions(60), max_chars=6000)

    assert "code" in stats.passes
    assert out.count("def f") == 60
    assert stats.after < stats.before


def test_code_pass_output_still_parses() -> None:
    """The whole point: the byte-offset cap sliced mid-function and handed
    the model source that no longer parses. Structural elision must not."""
    import ast

    out, _ = juice(_many_functions(60), max_chars=6000)
    ast.parse(out)  # raises SyntaxError on regression


def test_code_pass_beats_the_hard_cap() -> None:
    """Guards against the pass silently degrading back to a plain cap."""
    text = _many_functions(60)
    with_code, code_stats = juice(text, max_chars=6000)
    cap_only, cap_stats = juice(text, max_chars=6000, enable_code=False)

    assert "code" in code_stats.passes
    assert "code" not in cap_stats.passes
    # The cap keeps head+tail, so it retains far fewer signatures.
    assert with_code.count("def f") > cap_only.count("def f")


def test_code_pass_preserves_docstrings() -> None:
    out, _ = juice(_many_functions(60), max_chars=6000)
    assert out.count("compute f0.") == 1


def test_code_pass_handles_decorated_definitions() -> None:
    """A decorated def must be elided together with its decorators.

    Eliding from the ``def`` line alone leaves the decorators stranded
    above an elision marker, which is a syntax error.
    """
    import ast

    text = "class C:\n" + "".join(
        f"    @property\n    def m{i}(self):\n"
        + "\n".join(f"        q{k} = 1" for k in range(10))
        + "\n"
        for i in range(60)
    )
    out, stats = juice(text, max_chars=6000)

    assert "code" in stats.passes
    ast.parse(out)
    assert out.count("def m") == 60


def test_code_pass_handles_async_definitions() -> None:
    import ast

    text = "\n".join(
        f"async def g{i}(x):\n" + "\n".join(f"    v{k} = x + {k}" for k in range(10)) + "\n"
        for i in range(60)
    )
    out, stats = juice(text, max_chars=6000)

    assert "code" in stats.passes
    ast.parse(out)


def test_unparseable_python_falls_back_to_cap() -> None:
    """Never raise on malformed source — degrade to the existing cap."""
    out, stats = juice("def f(:\n  ???\n" * 900, max_chars=6000)

    assert "code" not in stats.passes
    assert len(out) <= 6100


def test_prose_mentioning_keywords_is_not_treated_as_code() -> None:
    prose = "import means bringing in.\nclass of problems.\ndef not what you think.\n" * 3
    out, stats = juice(prose, max_chars=6000)

    assert out == prose
    assert "code" not in stats.passes


def test_small_code_is_byte_identical() -> None:
    """Prompt-cache prefixes must not shift for outputs under budget."""
    src = "def f():\n    return 1\n"
    out, stats = juice(src, max_chars=6000)

    assert out == src
    assert stats.passes == ()


def test_code_pass_can_be_disabled() -> None:
    _, stats = juice(_many_functions(60), max_chars=6000, enable_code=False)
    assert "code" not in stats.passes


def test_code_pass_respects_protected_sentinels() -> None:
    text = "(工具失败)\n" + _many_functions(60)
    out, _ = juice(text, max_chars=6000)
    assert "(工具失败)" in out
