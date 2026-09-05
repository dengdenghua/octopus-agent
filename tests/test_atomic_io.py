"""Tests for runtime.platform.io.atomic."""

from __future__ import annotations

import json
import multiprocessing
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from runtime.platform.io.atomic import (
    AtomicWriteError,
    atomic_write_bytes,
    atomic_write_json,
    atomic_write_text,
    debounced_json_writer,
    read_json_with_backup,
)
from runtime.platform.io.transactional import JsonMutation, mutate_json_file


def _transaction_process_worker(path: str, key: str, barrier) -> None:
    for _index in range(12):
        barrier.wait(timeout=5)

        def increment(state):
            value = int(state.get(key, 0)) + 1
            # Widen the stale-read window.  A missing OS lock deterministically
            # lets both workers replace a snapshot that lacks the peer update.
            time.sleep(0.002)
            state[key] = value
            return JsonMutation(None)

        mutate_json_file(
            path,
            default_factory=dict,
            validate=lambda state: None,
            mutate=increment,
        )


# ─── atomic_write_bytes / text / json ───────────────────────


def test_write_bytes_creates_file(tmp_path: Path) -> None:
    target = tmp_path / "out.bin"
    atomic_write_bytes(target, b"hello")
    assert target.read_bytes() == b"hello"


@pytest.mark.skipif(
    __import__("os").name == "nt", reason="POSIX file-mode bits not meaningful on Windows"
)
def test_mode_creates_restrictive_secret_file(tmp_path: Path) -> None:
    # A secret file (token store) must be created 0600 from the start —
    # no brief 0644 window that a chmod-after-write would leave.
    import os
    import stat

    old = os.umask(0o022)
    try:
        target = tmp_path / "secret.json"
        atomic_write_json(target, {"access_token": "sk-secret"}, mode=0o600)
        assert stat.S_IMODE(target.stat().st_mode) == 0o600
        # An overwrite keeps it locked down too.
        atomic_write_json(target, {"access_token": "sk-secret-2"}, mode=0o600)
        assert stat.S_IMODE(target.stat().st_mode) == 0o600
        # Without mode, the default (0644 minus umask) is unchanged.
        plain = tmp_path / "plain.json"
        atomic_write_json(plain, {"x": 1})
        assert stat.S_IMODE(plain.stat().st_mode) == 0o644
    finally:
        os.umask(old)


def test_write_text_appends_trailing_newline(tmp_path: Path) -> None:
    target = tmp_path / "out.txt"
    atomic_write_text(target, "line")
    assert target.read_text(encoding="utf-8") == "line\n"


def test_write_text_respects_existing_newline(tmp_path: Path) -> None:
    target = tmp_path / "out.txt"
    atomic_write_text(target, "line\n")
    assert target.read_text(encoding="utf-8") == "line\n"


def test_write_text_no_newline_mode(tmp_path: Path) -> None:
    target = tmp_path / "out.txt"
    atomic_write_text(target, "line", newline=None)
    assert target.read_text(encoding="utf-8") == "line"


def test_write_json_round_trip(tmp_path: Path) -> None:
    target = tmp_path / "out.json"
    payload = {"a": 1, "b": ["x", "y"], "中文": True}
    atomic_write_json(target, payload)
    assert json.loads(target.read_text(encoding="utf-8")) == payload


def test_write_json_creates_parent_dirs(tmp_path: Path) -> None:
    target = tmp_path / "deep" / "nested" / "x.json"
    atomic_write_json(target, {"ok": True})
    assert json.loads(target.read_text(encoding="utf-8")) == {"ok": True}


# ─── Backup rotation ────────────────────────────────────────


def test_bak_created_on_overwrite(tmp_path: Path) -> None:
    target = tmp_path / "out.json"
    atomic_write_json(target, {"v": 1})
    atomic_write_json(target, {"v": 2})
    bak = target.with_suffix(target.suffix + ".bak")
    assert bak.exists()
    assert json.loads(bak.read_text(encoding="utf-8")) == {"v": 1}
    assert json.loads(target.read_text(encoding="utf-8")) == {"v": 2}


def test_bak_disabled(tmp_path: Path) -> None:
    target = tmp_path / "out.json"
    atomic_write_json(target, {"v": 1})
    atomic_write_json(target, {"v": 2}, keep_backup=False)
    bak = target.with_suffix(target.suffix + ".bak")
    assert not bak.exists()


def test_bak_overwrites_on_third_write(tmp_path: Path) -> None:
    target = tmp_path / "out.json"
    atomic_write_json(target, {"v": 1})
    atomic_write_json(target, {"v": 2})
    atomic_write_json(target, {"v": 3})
    bak = target.with_suffix(target.suffix + ".bak")
    # .bak always holds the immediately-previous version, not v1.
    assert json.loads(bak.read_text(encoding="utf-8")) == {"v": 2}
    assert json.loads(target.read_text(encoding="utf-8")) == {"v": 3}


# ─── Crash safety ───────────────────────────────────────────


def test_failed_write_leaves_original_intact(tmp_path: Path) -> None:
    target = tmp_path / "out.json"
    atomic_write_json(target, {"v": 1})

    # Simulate failure: os.replace raises partway through.
    with (
        patch(
            "runtime.platform.io.atomic.os.replace",
            side_effect=OSError("simulated"),
        ),
        pytest.raises(AtomicWriteError),
    ):
        atomic_write_json(target, {"v": 2})

    # Original file still contains v1.
    assert json.loads(target.read_text(encoding="utf-8")) == {"v": 1}


def test_failed_write_cleans_up_tmp(tmp_path: Path) -> None:
    target = tmp_path / "out.json"
    with (
        patch(
            "runtime.platform.io.atomic.os.replace",
            side_effect=OSError("simulated"),
        ),
        pytest.raises(AtomicWriteError),
    ):
        atomic_write_json(target, {"v": 1})
    # No temp files left behind.
    leftovers = [p for p in tmp_path.iterdir() if p.name.startswith(".")]
    assert leftovers == [], f"temp files not cleaned up: {leftovers}"


# ─── read_json_with_backup ──────────────────────────────────


def test_read_returns_primary_when_valid(tmp_path: Path) -> None:
    target = tmp_path / "out.json"
    atomic_write_json(target, {"v": 1})
    atomic_write_json(target, {"v": 2})
    assert read_json_with_backup(target) == {"v": 2}


def test_read_falls_back_to_bak_when_primary_corrupt(
    tmp_path: Path,
) -> None:
    target = tmp_path / "out.json"
    atomic_write_json(target, {"v": 1})
    atomic_write_json(target, {"v": 2})
    # Corrupt primary.
    target.write_text("{not valid json", encoding="utf-8")
    assert read_json_with_backup(target) == {"v": 1}


def test_read_returns_default_when_both_missing(tmp_path: Path) -> None:
    target = tmp_path / "missing.json"
    assert read_json_with_backup(target, default={"fallback": True}) == {"fallback": True}


def test_read_returns_default_when_both_corrupt(tmp_path: Path) -> None:
    target = tmp_path / "out.json"
    bak = target.with_suffix(target.suffix + ".bak")
    target.write_text("garbage", encoding="utf-8")
    bak.write_text("garbage too", encoding="utf-8")
    assert read_json_with_backup(target, default=[]) == []


# ─── Concurrent writes ──────────────────────────────────────


def test_concurrent_writers_never_leave_corruption(tmp_path: Path) -> None:
    """With many threads racing, the target must always be
    parseable JSON — it's always one writer's payload, never a mix.
    """
    target = tmp_path / "race.json"
    atomic_write_json(target, {"initial": True})

    errors: list[Exception] = []

    def writer(n: int) -> None:
        try:
            for i in range(20):
                atomic_write_json(
                    target,
                    {"writer": n, "i": i},
                    fsync=False,
                )
        except Exception as e:  # pragma: no cover
            errors.append(e)

    threads = [threading.Thread(target=writer, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    # Final file is always parseable.
    data = json.loads(target.read_text(encoding="utf-8"))
    assert "writer" in data and "i" in data


def test_transactional_json_serializes_read_modify_write_across_processes(
    tmp_path: Path,
) -> None:
    target = tmp_path / "shared-state.json"
    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(2)
    workers = [
        context.Process(
            target=_transaction_process_worker,
            args=(str(target), key, barrier),
        )
        for key in ("worker-a", "worker-b")
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=15)
        assert worker.exitcode == 0

    assert json.loads(target.read_text(encoding="utf-8")) == {
        "worker-a": 12,
        "worker-b": 12,
    }


# ─── debounced_json_writer ──────────────────────────────────


def test_debounced_writes_coalesce(tmp_path: Path) -> None:
    target = tmp_path / "state.json"
    writer = debounced_json_writer(target, interval_s=0.1)
    try:
        for i in range(50):
            writer.queue({"tick": i})
        writer.flush()
        assert json.loads(target.read_text(encoding="utf-8")) == {"tick": 49}
    finally:
        writer.close()


def test_debounced_close_flushes(tmp_path: Path) -> None:
    target = tmp_path / "state.json"
    writer = debounced_json_writer(target, interval_s=5.0)
    writer.queue({"final": "value"})
    writer.close()
    assert json.loads(target.read_text(encoding="utf-8")) == {"final": "value"}


def test_debounced_noop_when_empty(tmp_path: Path) -> None:
    target = tmp_path / "state.json"
    writer = debounced_json_writer(target, interval_s=0.1)
    writer.flush()  # nothing queued
    writer.close()
    assert not target.exists()
