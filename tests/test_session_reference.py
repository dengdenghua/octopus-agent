"""Session-reference resolver tests — dsh ``@dsh-session-reference`` port."""

from __future__ import annotations

from pathlib import Path

import pytest

from runtime.execution.subagents.sessions import SubagentSessionStore
from runtime.execution.tool_engine.session_reference import (
    MAX_REFERENCES,
    SessionReferenceError,
    SessionReferenceInput,
    SessionReferenceRecord,
    SessionReferenceResolver,
    candidate_rank,
    normalize_references,
    render_reference_prompt,
)


def _surface(session_id: str, body: str = "") -> list[dict]:
    return [
        {
            "type": "user/message",
            "data": {
                "source": {"kind": "user"},
                "content": [{"type": "text", "text": body or f"prompt-{session_id}"}],
            },
        },
        {
            "type": "assistant/message",
            "data": {
                "message": {"content": [{"type": "text", "text": f"answer-{session_id}"}]},
            },
        },
    ]


def _records() -> list[SessionReferenceRecord]:
    return [
        SessionReferenceRecord(session_id="abc123", label="Researcher", cwd="/repo"),
        SessionReferenceRecord(session_id="def456", label="Writer", cwd="/other"),
        SessionReferenceRecord(session_id="ghi789", label="Researcher two", cwd="/repo"),
        SessionReferenceRecord(session_id="target-id", label="Self", cwd="/repo"),
    ]


# ─── candidate ranking ─────────────────────────────────────────────────────


def test_candidate_rank_order() -> None:
    assert candidate_rank("/repo", "/repo") == 0
    assert candidate_rank(None, "/repo") == 1
    assert candidate_rank("/other", "/repo") == 2


def test_list_candidates_excludes_self_and_ranks_by_cwd() -> None:
    resolver = SessionReferenceResolver()
    out = resolver.list_candidates(target_id="target-id", sessions=_records(), target_cwd="/repo")
    ids = [c.session_id for c in out]
    # Same-cwd sessions rank before the different-cwd one; self excluded.
    assert "target-id" not in ids
    assert ids[0] == "abc123"
    assert ids[1] == "ghi789"
    assert ids[2] == "def456"


def test_list_candidates_query_filters() -> None:
    resolver = SessionReferenceResolver()
    out = resolver.list_candidates(
        target_id="target-id",
        sessions=_records(),
        query="writer",
    )
    assert [c.session_id for c in out] == ["def456"]


def test_list_candidates_query_matches_cwd() -> None:
    resolver = SessionReferenceResolver()
    out = resolver.list_candidates(
        target_id="target-id",
        sessions=_records(),
        query="repo",
    )
    ids = [c.session_id for c in out]
    assert "abc123" in ids
    assert "def456" not in ids


def test_list_candidates_limit() -> None:
    resolver = SessionReferenceResolver()
    out = resolver.list_candidates(target_id="x", sessions=_records(), limit=2)
    assert len(out) == 2


def test_list_candidates_invalid_limit() -> None:
    resolver = SessionReferenceResolver()
    with pytest.raises(SessionReferenceError):
        resolver.list_candidates(target_id="x", sessions=_records(), limit=0)


# ─── normalize_references ──────────────────────────────────────────────────


def test_normalize_references_dedupes_and_caps() -> None:
    refs = [
        {"session_id": "a", "label": "A"},
        {"session_id": "b"},
        {"session_id": "a"},  # dup collapses
    ]
    out = normalize_references("self", refs, max_references=3)
    assert [r.session_id for r in out] == ["a", "b"]


def test_normalize_references_rejects_self() -> None:
    with pytest.raises(SessionReferenceError) as exc:
        normalize_references("self", [{"session_id": "self"}], max_references=3)
    assert exc.value.code == "SESSION_REFERENCE_SELF_REFERENCE"


def test_normalize_references_too_many() -> None:
    refs = [{"session_id": f"s{i}"} for i in range(4)]
    with pytest.raises(SessionReferenceError) as exc:
        normalize_references("self", refs, max_references=3)
    assert exc.value.code == "SESSION_REFERENCE_TOO_MANY"


def test_normalize_references_invalid() -> None:
    with pytest.raises(SessionReferenceError):
        normalize_references("self", [{"label": "no id"}], max_references=3)
    with pytest.raises(SessionReferenceError):
        normalize_references("self", ["not-an-object"], max_references=3)


# ─── prepare ───────────────────────────────────────────────────────────────


def test_prepare_no_references_returns_content_only() -> None:
    resolver = SessionReferenceResolver()
    result = resolver.prepare(
        target_id="t",
        content=[{"type": "text", "text": "hi"}],
        references=[],
        read_surface=lambda sid: _surface(sid),
    )
    assert result.additional_context is None


def test_prepare_renders_referenced_frame() -> None:
    resolver = SessionReferenceResolver()
    result = resolver.prepare(
        target_id="t",
        content=[{"type": "text", "text": "hi"}],
        references=[SessionReferenceInput(session_id="s1", label="Patents")],
        read_surface=lambda sid: _surface(sid),
    )
    assert result.content == [{"type": "text", "text": "hi"}]
    ctx = result.additional_context
    assert ctx is not None
    assert ctx["source"]["kind"] == "session-reference"
    assert ctx["source"]["form"] == "recall"
    assert ctx["source"]["version"] == 1
    assert ctx["source"]["references"][0]["sessionId"] == "s1"
    assert ctx["source"]["references"][0]["label"] == "Patents"
    text = ctx["content"][0]["text"]
    assert "## Referenced sessions" in text
    assert "<referenced-sessions>" in text
    assert "</referenced-sessions>" in text
    assert "answer-s1" in text


def test_prepare_escapes_tag_characters() -> None:
    resolver = SessionReferenceResolver()
    result = resolver.prepare(
        target_id="t",
        content=[],
        references=[SessionReferenceInput(session_id="s1")],
        read_surface=lambda sid: [
            {
                "type": "user/message",
                "data": {
                    "source": {"kind": "user"},
                    "content": [{"type": "text", "text": "<script>alert(1)</script>"}],
                },
            }
        ],
    )
    text = result.additional_context["content"][0]["text"]
    # No literal '<' survives in the serialized JSON (tag-safe).
    assert "<script>" not in text


def test_prepare_self_reference_rejected() -> None:
    resolver = SessionReferenceResolver()
    with pytest.raises(SessionReferenceError) as exc:
        resolver.prepare(
            target_id="me",
            content=[],
            references=[SessionReferenceInput(session_id="me")],
            read_surface=lambda sid: _surface(sid),
        )
    assert exc.value.code == "SESSION_REFERENCE_SELF_REFERENCE"


def test_prepare_budget_exceeded() -> None:
    resolver = SessionReferenceResolver(max_reference_bytes=16)
    with pytest.raises(SessionReferenceError) as exc:
        resolver.prepare(
            target_id="t",
            content=[],
            references=[SessionReferenceInput(session_id="s1")],
            read_surface=lambda sid: _surface(sid),
        )
    assert exc.value.code == "SESSION_REFERENCE_BUDGET_EXCEEDED"


def test_prepare_read_failure() -> None:
    resolver = SessionReferenceResolver()

    def _boom(sid: str) -> list[dict]:
        raise RuntimeError("store down")

    with pytest.raises(SessionReferenceError) as exc:
        resolver.prepare(
            target_id="t",
            content=[],
            references=[SessionReferenceInput(session_id="s1")],
            read_surface=_boom,
        )
    assert exc.value.code == "SESSION_REFERENCE_READ_FAILED"


def test_invalid_config_rejected() -> None:
    with pytest.raises(SessionReferenceError):
        SessionReferenceResolver(max_references=0)
    with pytest.raises(SessionReferenceError):
        SessionReferenceResolver(max_references=MAX_REFERENCES + 1)
    with pytest.raises(SessionReferenceError):
        SessionReferenceResolver(candidate_limit=-1)


def test_render_reference_prompt_shape() -> None:
    from runtime.execution.tool_engine.session_projection import ReferencedSessionData

    data = ReferencedSessionData(
        session_id="s1",
        label="L",
        cwd=None,
        captured_through_seq=None,
        conversation=[{"role": "user", "text": "x"}],
    )
    text = render_reference_prompt([data])
    assert text.startswith("## Referenced sessions")
    assert text.endswith("</referenced-sessions>")


# ─── subagent store adapter ────────────────────────────────────────────────


def test_store_surface_events_and_candidates(tmp_path: Path) -> None:
    store = SubagentSessionStore(base_dir=tmp_path / "sessions")
    s1 = store.create(agent_id="researcher", thread_id="t1")
    s2 = store.create(agent_id="writer", thread_id="t2")
    store.append_turn(s1.session_id, prompt="p1", output="o1", success=True)

    events = store.surface_events(s1.session_id)
    assert events and events[0]["type"] == "user/message"
    assert events[1]["type"] == "assistant/message"
    assert store.surface_events("missing") == []

    candidates = store.list_reference_candidates(target_id=s1.session_id)
    ids = [c["sessionId"] for c in candidates]
    assert s2.session_id in ids
    assert s1.session_id not in ids
