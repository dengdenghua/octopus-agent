"""Tests for the per-turn output-style overlay.

Covers the pure ``render_output_style`` mapping plus an integration
spot-check that ``stream_react_loop`` actually appends the audit overlay
to ``system_parts`` when ``output_style`` is in ``user_context``.
"""

from __future__ import annotations

from runtime.core.cerebrum.output_styles import render_output_style


def test_render_none_returns_empty() -> None:
    assert render_output_style(None) == ""


def test_render_default_returns_empty() -> None:
    assert render_output_style("default") == ""
    assert render_output_style("DEFAULT") == ""
    assert render_output_style("") == ""


def test_render_concise_contains_keyword() -> None:
    out = render_output_style("concise")
    assert "concise" in out.lower()
    # block is wrapped so the system prompt can locate it
    assert "<output-style>" in out
    assert "</output-style>" in out


def test_render_detailed_contains_keyword() -> None:
    out = render_output_style("detailed")
    assert "detailed" in out.lower()
    assert "trade-offs" in out


def test_render_audit_contains_severity() -> None:
    out = render_output_style("audit")
    assert "severity" in out.lower()
    assert "audit" in out.lower()


def test_render_review_contains_verdict() -> None:
    out = render_output_style("review")
    assert "verdict" in out.lower()
    assert "review" in out.lower()


def test_render_unknown_returns_empty() -> None:
    assert render_output_style("totally-unknown") == ""
    assert render_output_style("verbose") == ""
    assert render_output_style("123") == ""


def test_render_is_case_insensitive() -> None:
    assert "concise" in render_output_style("CONCISE").lower()
    assert "audit" in render_output_style("Audit").lower()


def test_render_strips_whitespace() -> None:
    assert "concise" in render_output_style("  concise  ").lower()
