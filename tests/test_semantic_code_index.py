"""Read-only semantic search over the persisted KB index (reuse, not rebuild)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from runtime.memory.hemolymph import semantic_code_index as sci


def test_returns_none_when_disabled(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("OCTOPUS_CODEBASE_SEMANTIC", "0")
    assert sci.search_persisted("anything", db_path=tmp_path / "x.db") is None


def test_returns_none_without_db(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("OCTOPUS_CODEBASE_SEMANTIC", raising=False)
    assert sci.search_persisted("q", db_path=tmp_path / "missing.db") is None


def test_returns_none_for_empty_query(tmp_path: Path) -> None:
    assert sci.search_persisted("   ", db_path=tmp_path / "x.db") is None


def _write_db(path: Path, rows: list[tuple[str, str, list[float]]]) -> None:
    import numpy as np

    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE code_chunks (path TEXT, chunk TEXT, embedding BLOB)")
    for p, c, vec in rows:
        conn.execute(
            "INSERT INTO code_chunks VALUES (?,?,?)",
            (p, c, np.asarray(vec, dtype=np.float32).tobytes()),
        )
    conn.commit()
    conn.close()


def test_ranks_by_cosine_against_persisted_vectors(monkeypatch, tmp_path: Path) -> None:
    np = pytest.importorskip("numpy")
    db = tmp_path / "code_index.db"
    _write_db(
        db,
        [
            ("auth.py", "# auth.py\ndef login(): ...", [1.0, 0.0, 0.0]),
            ("math.py", "# math.py\ndef add(): ...", [0.0, 1.0, 0.0]),
        ],
    )

    class _Emb:
        def encode(self, xs):  # query embeds onto the auth axis → auth.py wins
            return [np.asarray([1.0, 0.0, 0.0], dtype=np.float32) for _ in xs]

    monkeypatch.setattr(sci, "_get_embedder", lambda: _Emb())
    monkeypatch.delenv("OCTOPUS_CODEBASE_SEMANTIC", raising=False)

    res = sci.search_persisted("how does sign-in work", top_k=2, db_path=db)
    assert res is not None
    assert res[0]["path"] == "auth.py"  # semantic match despite no shared token
    assert res[0]["score"] >= res[1]["score"]


def test_returns_none_without_embedder(monkeypatch, tmp_path: Path) -> None:
    pytest.importorskip("numpy")
    db = tmp_path / "code_index.db"
    _write_db(db, [("a.py", "x", [1.0, 0.0])])
    monkeypatch.setattr(sci, "_get_embedder", lambda: None)
    monkeypatch.delenv("OCTOPUS_CODEBASE_SEMANTIC", raising=False)
    assert sci.search_persisted("q", db_path=db) is None
