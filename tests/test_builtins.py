"""Implementation note."""

from __future__ import annotations

from pathlib import Path

from runtime.execution.suckers import SkillRegistry
from runtime.execution.suckers.builtins import (
    BUILTIN_NAMES,
    _count_words,
    _file_stats,
    _hash_text,
    _list_cwd,
    _read_file,
    _use_chatgpt_connector,
    register_builtins,
)
from runtime.platform.process.session import Session


class TestRegistration:
    def test_register_all_returns_registry(self):
        r = SkillRegistry()
        register_builtins(r)
        for name in BUILTIN_NAMES:
            assert r.has(name), f"missing: {name}"

    def test_all_trusted_sources_are_skill_public(self):
        r = SkillRegistry()
        register_builtins(r)
        for name in BUILTIN_NAMES:
            assert r.get(name).trusted_source.startswith("skill://public/")


class TestChatGPTConnectorBridge:
    def test_requires_an_execution_stack(self):
        result = _use_chatgpt_connector(
            "google_drive",
            "List recent files",
            session=Session(actor="alice"),
        )
        assert result == {
            "error": "ChatGPT connector bridge is unavailable on this execution surface"
        }

    def test_delegates_with_principal_session_and_exact_app(
        self,
        monkeypatch,
    ):
        from runtime.execution.codex_backend import role_runner

        seen = {}

        def _run(stack, agent, goal, *, context):
            seen.update(stack=stack, agent=agent, goal=goal, context=context)
            return type(
                "Result",
                (),
                {"success": True, "status": "completed", "output": "Three files"},
            )()

        monkeypatch.setattr(role_runner, "run_agent_role_sync", _run)
        stack = object()
        agent = type("Agent", (), {"agent_id": "researcher"})()
        session = Session(
            actor="alice",
            agent=agent,
            metadata={"_execution_stack": stack},
        )

        result = _use_chatgpt_connector(
            "google_drive",
            "List recent files",
            session=session,
        )

        assert result == {
            "app_id": "google_drive",
            "success": True,
            "status": "completed",
            "content": "Three files",
        }
        assert seen["stack"] is stack
        assert seen["agent"] is agent
        assert seen["goal"] == "List recent files"
        assert seen["context"]["caller_session"] is session
        assert seen["context"]["_codex_app_id"] == "google_drive"


class TestListCwd:
    def test_lists_files(self, tmp_path: Path):
        (tmp_path / "a.txt").write_text("A")
        (tmp_path / "sub").mkdir()
        result = _list_cwd(path=str(tmp_path))
        assert result["count"] == 2
        names = {item["name"] for item in result["items"]}
        assert {"a.txt", "sub"} <= names

    def test_missing_path_returns_error(self):
        result = _list_cwd(path="/nonexistent/xxx/zzz")
        assert "error" in result

    def test_hidden_files_excluded(self, tmp_path: Path):
        (tmp_path / "visible.txt").write_text("ok")
        (tmp_path / ".hidden").write_text("no")
        result = _list_cwd(path=str(tmp_path))
        names = {item["name"] for item in result["items"]}
        assert "visible.txt" in names
        assert ".hidden" not in names


class TestReadFile:
    def test_reads_utf8(self, tmp_path: Path):
        path = tmp_path / "a.txt"
        # Implementation note.
        path.write_bytes(b"hello\nworld\n")
        r = _read_file(path=str(path))
        assert r["content"] == "hello\nworld\n"
        assert r["size"] == 12
        assert r["truncated"] is False

    def test_reads_requested_range(self, tmp_path: Path):
        path = tmp_path / "range.txt"
        path.write_bytes(b"line0\nline1\nline2\nline3\n")
        r = _read_file(path=str(path), offset=2, limit=2)
        assert r["content"] == "line2\nline3\n"
        assert r["truncated"] is False

    def test_truncates_large(self, tmp_path: Path):
        path = tmp_path / "big.txt"
        path.write_text("x" * 200_000, encoding="utf-8")
        r = _read_file(path=str(path), max_bytes=1000)
        assert r["truncated"] is True
        assert len(r["content"]) == 1000

    def test_ignores_tail_only_when_range_is_set(self, tmp_path: Path):
        path = tmp_path / "tail.txt"
        path.write_bytes(b"a\nb\nc\nd\n")
        r = _read_file(path=str(path), offset=1, limit=1, max_bytes=2)
        assert r["content"] == "b\n"
        assert r["lines_read"] == 1

    def test_clamps_requested_range_to_reader_line_cap(self, tmp_path: Path):
        path = tmp_path / "many-lines.txt"
        path.write_text("x\n" * 2_500, encoding="utf-8")

        r = _read_file(path=str(path), offset=0, limit=5_000)

        assert r["lines_read"] == 2_000
        assert r["limit"] == 2_000
        assert r["requested_limit"] == 5_000
        assert r["limit_clamped"] is True
        assert r["truncated"] is True

    def test_unbounded_large_line_count_returns_first_page(self, tmp_path: Path):
        path = tmp_path / "many-short-lines.txt"
        path.write_text("x\n" * 2_500, encoding="utf-8")

        r = _read_file(path=str(path))

        assert "error" not in r
        assert r["auto_bounded"] is True
        assert r["lines_read"] == 400
        assert r["limit"] == 400
        assert r["truncated"] is True
        assert r["total_lines_at_least"] == 2_001
        assert "offset=400" in r["pagination_hint"]

    def test_missing_file(self):
        r = _read_file(path="/nope/nope/nope")
        assert "error" in r


class TestCountWords:
    def test_basic(self):
        r = _count_words(text="hello world\nfoo bar baz")
        assert r["chars"] == 23
        assert r["words"] == 5
        assert r["lines"] == 2

    def test_empty(self):
        r = _count_words(text="")
        assert r == {"chars": 0, "words": 0, "lines": 0}


class TestHashText:
    def test_blake2b_default(self):
        r = _hash_text(text="abc")
        assert r["algorithm"] == "blake2b"
        assert len(r["hash"]) == 32  # digest_size=16 → 32 hex chars

    def test_sha256(self):
        r = _hash_text(text="abc", algorithm="sha256")
        assert r["algorithm"] == "sha256"
        assert len(r["hash"]) == 64

    def test_unknown_algo(self):
        r = _hash_text(text="x", algorithm="md42")
        assert "error" in r


class TestFileStats:
    def test_file(self, tmp_path: Path):
        p = tmp_path / "x.txt"
        p.write_text("hello")
        r = _file_stats(path=str(p))
        assert r["size"] == 5
        assert r["is_file"] is True
        assert r["is_dir"] is False

    def test_missing(self):
        r = _file_stats(path="/missing")
        assert "error" in r
