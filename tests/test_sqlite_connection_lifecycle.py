from __future__ import annotations

import ast
import sqlite3
from pathlib import Path

import pytest

from runtime.platform.io.sqlite import connect_closing

_RUNTIME = Path(__file__).resolve().parents[1] / "runtime"


def test_connection_context_commits_and_closes(tmp_path) -> None:
    path = tmp_path / "store.db"
    with connect_closing(path) as conn:
        conn.execute("CREATE TABLE records(value TEXT NOT NULL)")
        conn.execute("INSERT INTO records VALUES ('saved')")

    with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
        conn.execute("SELECT 1")

    with sqlite3.connect(path) as reader:
        assert reader.execute("SELECT value FROM records").fetchone() == ("saved",)


def test_connection_context_rolls_back_and_closes(tmp_path) -> None:
    path = tmp_path / "store.db"
    with sqlite3.connect(path) as setup:
        setup.execute("CREATE TABLE records(value TEXT NOT NULL)")

    with pytest.raises(RuntimeError, match="abort"), connect_closing(path) as conn:
        conn.execute("INSERT INTO records VALUES ('discarded')")
        raise RuntimeError("abort")

    with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
        conn.execute("SELECT 1")
    with sqlite3.connect(path) as reader:
        assert reader.execute("SELECT COUNT(*) FROM records").fetchone() == (0,)


def test_runtime_has_no_nonclosing_stdlib_sqlite_contexts() -> None:
    violations: list[str] = []
    for path in _RUNTIME.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.With, ast.AsyncWith)):
                continue
            for item in node.items:
                expression = ast.unparse(item.context_expr)
                if expression.startswith("sqlite3.connect("):
                    violations.append(f"{path.relative_to(_RUNTIME.parent)}:{node.lineno}")

    assert not violations, (
        "sqlite3.Connection.__exit__ does not close the database; use "
        "connect_closing(...) or closing(sqlite3.connect(...)): " + ", ".join(violations)
    )


@pytest.mark.parametrize(
    "module_name",
    (
        "runtime.memory.hemolymph.image_semantic_index",
        "runtime.memory.hemolymph.video_semantic_index",
    ),
)
def test_semantic_index_schema_failure_closes_connection(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    module_name: str,
) -> None:
    import importlib

    module = importlib.import_module(module_name)

    class BrokenConnection:
        closed = False

        def execute(self, _query: str) -> None:
            raise sqlite3.DatabaseError("broken schema")

        def close(self) -> None:
            self.closed = True

    connection = BrokenConnection()
    monkeypatch.setattr(module.sqlite3, "connect", lambda _path: connection)

    with pytest.raises(sqlite3.DatabaseError, match="broken schema"):
        module._open(tmp_path / "broken.db")

    assert connection.closed is True
