"""Tests verifying cron_router._write_cron_jobs is atomic.

Migration: ``runtime/sensing/siphon/cron_router.py:_write_cron_jobs`` was a
naked ``path.write_text(json.dumps(...))`` and is now
``atomic_write_json(path, jobs)``. These tests pin round-trip and the
``.bak`` rollover on overwrite.
"""

from __future__ import annotations

import json
from pathlib import Path

from runtime.sensing.gateway import cron_router as cr


def _sample_jobs() -> list[dict]:
    return [
        {
            "name": "nightly",
            "command": "echo hi",
            "cron_expression": "0 3 * * *",
            "last_run": None,
            "last_status": "created",
        },
    ]


def test_write_cron_jobs_round_trip(tmp_path: Path) -> None:
    """_write_cron_jobs persists JSON readable by _read_cron_jobs."""
    path = tmp_path / "subdir" / "cron.json"
    jobs = _sample_jobs()

    cr._write_cron_jobs(path, jobs)

    assert path.exists()
    loaded = cr._read_cron_jobs(path)
    # _read_cron_jobs enriches each entry with newer optional fields
    # (e.g. ``creator_actor`` for ownership scoping). The round-trip
    # contract is "every field we wrote round-trips identically",
    # not "the loaded dict is exactly the input dict".
    assert len(loaded) == len(jobs)
    for written, read_back in zip(loaded, jobs, strict=True):
        for key, value in read_back.items():
            assert written[key] == value


def test_write_cron_jobs_creates_bak_on_overwrite(tmp_path: Path) -> None:
    """Second write rotates prior payload to .bak."""
    path = tmp_path / "cron.json"

    first = _sample_jobs()
    cr._write_cron_jobs(path, first)

    second = [{**first[0], "name": "morning", "cron_expression": "0 8 * * *"}]
    cr._write_cron_jobs(path, second)

    bak = path.with_suffix(".json.bak")
    assert path.exists()
    assert bak.exists(), "atomic_write_json should rotate prior file to .bak"

    assert json.loads(path.read_text(encoding="utf-8"))[0]["name"] == "morning"
    assert json.loads(bak.read_text(encoding="utf-8"))[0]["name"] == "nightly"


def test_write_cron_jobs_creates_parent_dir(tmp_path: Path) -> None:
    """Missing parent directories are created by the atomic helper."""
    path = tmp_path / "deep" / "nested" / "cron.json"

    cr._write_cron_jobs(path, _sample_jobs())

    assert path.exists()
    assert path.parent.is_dir()
