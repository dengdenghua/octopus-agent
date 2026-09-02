"""Tests for the session-sharded thread store and session_index."""

from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from pathlib import Path

from runtime.memory.threads import SessionIndex, ThreadStateStore
from runtime.memory.threads.session_index import IndexEntry


def _records(path: Path) -> list[dict]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def _write_thread_copy(
    root: Path,
    *,
    thread_id: str,
    agent: str,
    created_at: str,
    updated_at: str,
    messages: list[dict],
) -> Path:
    path = root / "agents" / agent / "sessions" / f"{thread_id}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    thread = {
        "thread_id": thread_id,
        "status": "idle",
        "created_at": created_at,
        "updated_at": updated_at,
        "metadata": {"agent": agent},
        "values": {"title": "hello", "messages": messages, "artifacts": []},
    }
    state = {
        "values": thread["values"],
        "next": [],
        "metadata": thread["metadata"],
        "checkpoint": {"id": agent, "checkpoint_id": agent, "ts": updated_at},
        "checkpoint_id": agent,
        "tasks": [],
    }
    path.write_text(
        json.dumps({"type": "session_meta", "payload": {"id": thread_id, "agent": agent}})
        + "\n"
        + json.dumps(
            {
                "op": "upsert",
                "thread_id": thread_id,
                "thread": thread,
                "state": state,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return path


# ─── session_meta header ────────────────────────────────────


def test_per_thread_jsonl_starts_with_session_meta(tmp_path: Path) -> None:
    store = ThreadStateStore(per_agent_base=tmp_path)
    store.ensure_thread(
        "thread-a",
        metadata={"agent": "coder"},
    )
    target = tmp_path / "agents" / "coder" / "sessions" / "thread-a.jsonl"
    records = _records(target)
    assert records[0] == {
        "type": "session_meta",
        "payload": {
            "id": "thread-a",
            "timestamp": records[0]["payload"]["timestamp"],
            "originator": "octopus",
            "agent": "coder",
            "team_id": None,
        },
    }
    assert records[1]["op"] == "upsert"


def test_session_meta_ignored_on_reload(tmp_path: Path) -> None:
    store = ThreadStateStore(per_agent_base=tmp_path)
    store.ensure_thread("thread-b", metadata={"agent": "general"})
    store.update_state("thread-b", values={"title": "Hello"})

    reloaded = ThreadStateStore(per_agent_base=tmp_path)
    thread = reloaded.get("thread-b")
    assert thread is not None
    assert thread["values"]["title"] == "Hello"


def test_existing_thread_cannot_move_to_another_agent_shard(tmp_path: Path) -> None:
    store = ThreadStateStore(per_agent_base=tmp_path)
    store.ensure_thread("owned-thread", metadata={"agent": "installed_researcher"})

    store.update_state(
        "owned-thread",
        values={"title": "Still OpenCode"},
        metadata={"agent": "general", "agent_name": "general"},
    )

    thread = store.get("owned-thread")
    assert thread is not None
    assert thread["metadata"]["agent"] == "installed_researcher"
    assert (
        tmp_path / "agents" / "installed_researcher" / "sessions" / "owned-thread.jsonl"
    ).exists()
    assert not (tmp_path / "agents" / "general" / "sessions" / "owned-thread.jsonl").exists()


def test_reload_repairs_conflicting_role_copies_to_original_owner(tmp_path: Path) -> None:
    first_messages = [{"type": "human", "content": "hello"}]
    latest_messages = [
        *first_messages,
        {"type": "ai", "content": "from opencode"},
        {"type": "human", "content": "which model"},
        {"type": "ai", "content": "wrong role response"},
    ]
    owner_path = _write_thread_copy(
        tmp_path,
        thread_id="mixed-thread",
        agent="installed_researcher",
        created_at="2026-08-13T15:05:58.000000Z",
        updated_at="2026-08-13T15:05:59.000000Z",
        messages=first_messages,
    )
    stale_path = _write_thread_copy(
        tmp_path,
        thread_id="mixed-thread",
        agent="general",
        created_at="2026-08-13T15:05:58.100000Z",
        updated_at="2026-08-13T15:06:36.000000Z",
        messages=latest_messages,
    )

    store = ThreadStateStore(per_agent_base=tmp_path)

    repaired = store.get("mixed-thread")
    assert repaired is not None
    assert repaired["metadata"]["agent"] == "installed_researcher"
    assert repaired["values"]["messages"] == latest_messages
    assert owner_path.exists()
    assert not stale_path.exists()


def test_startup_role_repair_waits_for_live_update_and_refreshes_latest(
    tmp_path: Path, monkeypatch
) -> None:
    """A constructor must not overwrite a newer cross-process mutation."""
    from runtime.memory.threads import store as store_module

    live = ThreadStateStore(per_agent_base=tmp_path)
    live.ensure_thread("shared", metadata={"agent": "alpha"})
    stale_path = _write_thread_copy(
        tmp_path,
        thread_id="shared",
        agent="beta",
        created_at="2026-08-13T15:05:59.000000Z",
        updated_at="2026-08-13T15:06:00.000000Z",
        messages=[],
    )

    original_lock = store_module.thread_mutation_lock
    repair_waiting = threading.Event()
    allow_repair = threading.Event()

    @contextmanager
    def _gated_lock(**kwargs):
        if threading.current_thread().name == "repair-loader":
            repair_waiting.set()
            assert allow_repair.wait(timeout=3)
        with original_lock(**kwargs):
            yield

    monkeypatch.setattr(store_module, "thread_mutation_lock", _gated_lock)
    loaded: dict[str, ThreadStateStore] = {}
    errors: list[BaseException] = []

    def _load() -> None:
        try:
            loaded["store"] = ThreadStateStore(per_agent_base=tmp_path)
        except BaseException as exc:  # pragma: no cover - surfaced below
            errors.append(exc)

    worker = threading.Thread(target=_load, name="repair-loader")
    worker.start()
    assert repair_waiting.wait(timeout=3)
    try:
        live.update_state(
            "shared",
            values={
                "title": "LIVE",
                "messages": [{"type": "human", "content": "must survive"}],
            },
        )
    finally:
        allow_repair.set()
    worker.join(timeout=3)

    assert not worker.is_alive()
    assert not errors
    assert not stale_path.exists()
    for store in (loaded["store"], ThreadStateStore(per_agent_base=tmp_path)):
        thread = store.get("shared")
        assert thread is not None
        assert thread["values"]["title"] == "LIVE"
        assert thread["values"]["messages"] == [{"type": "human", "content": "must survive"}]


def test_custom_session_origin_is_respected(tmp_path: Path) -> None:
    store = ThreadStateStore(per_agent_base=tmp_path, session_origin="octopus-desktop")
    store.ensure_thread("thread-c", metadata={"agent": "coder"})
    target = tmp_path / "agents" / "coder" / "sessions" / "thread-c.jsonl"
    meta = _records(target)[0]
    assert meta["payload"]["originator"] == "octopus-desktop"


# ─── dated layout ───────────────────────────────────────────


def test_dated_layout_puts_new_threads_under_year_month(tmp_path: Path) -> None:
    store = ThreadStateStore(per_agent_base=tmp_path, dated_layout=True)
    store.ensure_thread("dated-thread", metadata={"agent": "coder"})

    sess_root = tmp_path / "agents" / "coder" / "sessions"
    flat = sess_root / "dated-thread.jsonl"
    assert not flat.exists(), "flat path should not be used under dated_layout"

    hits = list(sess_root.rglob("dated-thread.jsonl"))
    assert len(hits) == 1
    rel = hits[0].relative_to(sess_root)
    # e.g. 2026/05/dated-thread.jsonl
    assert len(rel.parts) == 3
    assert rel.parts[0].isdigit() and len(rel.parts[0]) == 4
    assert rel.parts[1].isdigit() and len(rel.parts[1]) == 2


def test_dated_layout_reads_pre_existing_flat_file(tmp_path: Path) -> None:
    # Pre-create a flat file as if it were written before the dated
    # layout was enabled. Subsequent writes should CONTINUE to go
    # there, not fork into a new dated file.
    sess_root = tmp_path / "agents" / "coder" / "sessions"
    sess_root.mkdir(parents=True)
    flat = sess_root / "legacy.jsonl"
    flat.write_text(
        json.dumps({"type": "session_meta", "payload": {"id": "legacy"}})
        + "\n"
        + json.dumps(
            {
                "op": "upsert",
                "thread_id": "legacy",
                "thread": {
                    "thread_id": "legacy",
                    "status": "idle",
                    "created_at": "2026-04-01T00:00:00Z",
                    "updated_at": "2026-04-01T00:00:00Z",
                    "metadata": {"agent": "coder"},
                    "values": {"title": "Old", "messages": [], "artifacts": []},
                },
                "state": {
                    "values": {"title": "Old", "messages": [], "artifacts": []},
                    "next": [],
                    "metadata": {"agent": "coder"},
                    "checkpoint": {"id": "x", "checkpoint_id": "x", "ts": "t"},
                    "checkpoint_id": "x",
                    "tasks": [],
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    store = ThreadStateStore(per_agent_base=tmp_path, dated_layout=True)
    store.update_state("legacy", values={"title": "Updated"})

    # No new dated file; the flat one grew.
    dated = list(sess_root.rglob("legacy.jsonl"))
    assert dated == [flat]
    records = _records(flat)
    assert records[-1]["thread"]["values"]["title"] == "Updated"


# ─── session_index ──────────────────────────────────────────


def test_session_index_is_written_alongside_threads(tmp_path: Path) -> None:
    store = ThreadStateStore(per_agent_base=tmp_path)
    store.ensure_thread("t1", metadata={"agent": "coder"})
    store.update_state("t1", values={"title": "Greeting"})
    store.ensure_thread("t2", metadata={"agent": "general"})

    idx_path = tmp_path / "data" / "sessions" / "session_index.jsonl"
    assert idx_path.exists()

    lines = [
        json.loads(line)
        for line in idx_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    # Three writes: ensure t1, update t1, ensure t2
    assert len(lines) >= 3
    thread_ids = {line["thread_id"] for line in lines if line.get("op") == "upsert"}
    assert thread_ids == {"t1", "t2"}


def test_session_index_deduplicates_no_op_upserts(tmp_path: Path) -> None:
    idx = SessionIndex(tmp_path / "idx.jsonl")
    entry = IndexEntry(
        thread_id="abc",
        title="Hi",
        status="idle",
        agent_id="coder",
        team_id=None,
        created_at="2026-05-01T00:00:00Z",
        updated_at="2026-05-01T00:00:00Z",
        file="agents/coder/sessions/abc.jsonl",
    )
    idx.upsert(entry)
    idx.upsert(entry)  # identical → should not re-append
    idx.upsert(entry)

    lines = (tmp_path / "idx.jsonl").read_text(encoding="utf-8").splitlines()
    assert len([line for line in lines if line.strip()]) == 1


def test_session_index_reload_applies_tombstones(tmp_path: Path) -> None:
    idx = SessionIndex(tmp_path / "idx.jsonl")
    idx.upsert(
        IndexEntry(
            thread_id="gone",
            title="Bye",
            status="idle",
            agent_id=None,
            team_id=None,
            created_at="t",
            updated_at="t",
            file="x",
        )
    )
    idx.delete("gone")

    reloaded = SessionIndex(tmp_path / "idx.jsonl")
    assert "gone" not in reloaded
    assert len(reloaded) == 0


def test_session_index_compact_collapses_history(tmp_path: Path) -> None:
    path = tmp_path / "idx.jsonl"
    idx = SessionIndex(path, compaction_threshold=0)  # disable auto

    base = IndexEntry(
        thread_id="t",
        title="v1",
        status="idle",
        agent_id=None,
        team_id=None,
        created_at="t",
        updated_at="t",
        file="x",
    )
    for v in ("v1", "v2", "v3", "v4"):
        idx.upsert(IndexEntry(**{**base.__dict__, "title": v, "updated_at": v}))
    # Four distinct upserts → four lines.
    raw = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(raw) == 4

    idx.compact()
    compacted = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(compacted) == 1
    # And reload sees the latest version.
    assert SessionIndex(path).get("t").title == "v4"


def test_session_index_reindexes_legacy_threads_on_first_boot(tmp_path: Path) -> None:
    # Simulate an upgrade: per-thread files already exist, but no
    # session_index.jsonl does yet. First boot should reindex them.
    sess_root = tmp_path / "agents" / "coder" / "sessions"
    sess_root.mkdir(parents=True)
    (sess_root / "legacy.jsonl").write_text(
        json.dumps(
            {
                "op": "upsert",
                "thread_id": "legacy",
                "thread": {
                    "thread_id": "legacy",
                    "status": "idle",
                    "created_at": "2026-01-01T00:00:00Z",
                    "updated_at": "2026-01-01T00:00:00Z",
                    "metadata": {"agent": "coder"},
                    "values": {"title": "Hi", "messages": [], "artifacts": []},
                },
                "state": {
                    "values": {"title": "Hi", "messages": [], "artifacts": []},
                    "next": [],
                    "metadata": {"agent": "coder"},
                    "checkpoint": {"id": "x", "checkpoint_id": "x", "ts": "t"},
                    "checkpoint_id": "x",
                    "tasks": [],
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    store = ThreadStateStore(per_agent_base=tmp_path)

    idx_path = tmp_path / "data" / "sessions" / "session_index.jsonl"
    assert idx_path.exists()
    idx = SessionIndex(idx_path)
    assert "legacy" in idx
    assert idx.get("legacy").title == "Hi"
    assert idx.get("legacy").file.endswith("legacy.jsonl")
    assert store.get("legacy") is not None


# ─── index disabled / path mode ─────────────────────────────


def test_index_disabled_does_not_create_file(tmp_path: Path) -> None:
    store = ThreadStateStore(per_agent_base=tmp_path, index_enabled=False)
    store.ensure_thread("t", metadata={"agent": "coder"})
    idx_path = tmp_path / "data" / "sessions" / "session_index.jsonl"
    assert not idx_path.exists()


def test_legacy_single_file_mode_still_supported(tmp_path: Path) -> None:
    path = tmp_path / "threads.jsonl"
    store = ThreadStateStore(path=path)
    store.ensure_thread("solo", values={"title": "Hi"})
    store.update_state("solo", values={"title": "Hi there"})
    assert path.exists()
    reloaded = ThreadStateStore(path=path)
    thread = reloaded.get("solo")
    assert thread is not None
    assert thread["values"]["title"] == "Hi there"


# ─── _append_locked · cross-process lock offsets ────────────


def test_append_locked_windows_lock_and_unlock_use_same_byte_offset(
    tmp_path: Path, monkeypatch
) -> None:
    """``msvcrt.locking`` locks 1 byte at the CURRENT file position, not
    a fixed byte — mode "a" starts a writer at EOF-at-open, a size that
    differs per writer. Locking and unlocking must target the same
    offset (else the unlock raises and the lock byte stays held, and
    two writers that opened at different sizes never actually
    contend). Fake the ``nt``/``msvcrt`` branch to pin the exact
    offsets used for LK_LOCK vs LK_UNLCK without needing real Windows.

    Builds the store/target path on the real (Posix) filesystem first,
    then only fakes ``os.name``/``msvcrt`` around the raw
    ``_append_locked`` calls — ``pathlib.Path`` dispatches to
    ``WindowsPath`` off ``os.name`` at construction time, so patching
    it globally before any Path is built would crash on this OS.
    """
    import sys
    import types

    store = ThreadStateStore(per_agent_base=tmp_path)
    target = tmp_path / "events.jsonl"

    positions: list[tuple[str, int]] = []

    fake_msvcrt = types.SimpleNamespace(LK_LOCK=1, LK_UNLCK=0)

    def _fake_locking(fd, mode, nbytes):
        # Record the file position at the moment locking/unlocking is
        # requested — this is the byte msvcrt would actually target.
        import os as _os

        pos = _os.lseek(fd, 0, 1)  # SEEK_CUR, no-op seek to read position
        positions.append(("lock" if mode == fake_msvcrt.LK_LOCK else "unlock", pos))

    fake_msvcrt.locking = _fake_locking
    monkeypatch.setitem(sys.modules, "msvcrt", fake_msvcrt)
    monkeypatch.setattr("os.name", "nt")

    store._append_locked(target, "first\n", header_line="header\n")
    store._append_locked(target, "second\n")

    assert len(positions) == 4
    lock_positions = [p for kind, p in positions if kind == "lock"]
    unlock_positions = [p for kind, p in positions if kind == "unlock"]
    assert len(lock_positions) == len(unlock_positions) == 2
    for lock_pos, unlock_pos in zip(lock_positions, unlock_positions, strict=True):
        assert lock_pos == unlock_pos == 0
    assert target.read_text(encoding="utf-8") == "header\nfirst\nsecond\n"
