"""Tests for the atomic storage helpers in intelligence_router.

These exercise only the private ``_read_store`` / ``_write_store``
functions — not the HTTP surface — to confirm the migration to
``runtime.platform.io.atomic_write_json`` / ``read_json_with_backup``
preserves the contract and gains crash-safety (``.bak`` rollover).
"""

from __future__ import annotations

from pathlib import Path

from runtime.sensing.gateway.intelligence_router import (
    _empty_store,
    _read_store,
    _write_store,
)


def _sample_store() -> dict:
    return {
        "subscriptions": [
            {
                "id": "sub_1",
                "topic": "AI safety",
                "keywords": ["alignment", "eval"],
                "enabled": True,
            }
        ],
        "reports": [
            {
                "id": "rpt_1",
                "subscription_id": "sub_1",
                "title": "Weekly recap",
                "summary": "一些情报",
                "items": [],
            }
        ],
    }


def test_write_read_roundtrip(tmp_path: Path) -> None:
    """Round-trip: writing a payload and reading it back yields the
    same subscriptions + reports (with the normalised shape).
    """
    path = tmp_path / "intelligence.json"
    payload = _sample_store()

    _write_store(path, payload)
    loaded = _read_store(path)

    assert loaded["subscriptions"] == payload["subscriptions"]
    assert loaded["reports"] == payload["reports"]


def test_second_write_creates_backup(tmp_path: Path) -> None:
    """After two sequential writes the ``.bak`` sibling should exist
    (``atomic_write_json`` rotates the previous version on replace).
    """
    path = tmp_path / "intelligence.json"
    bak = path.with_suffix(path.suffix + ".bak")

    first = _sample_store()
    _write_store(path, first)
    assert path.exists()
    assert not bak.exists()

    second = _sample_store()
    second["subscriptions"][0]["keywords"].append("policy")
    _write_store(path, second)

    assert path.exists()
    assert bak.exists(), "expected .bak file alongside the primary"

    # The primary reflects the second write; the .bak holds the first.
    primary = _read_store(path)
    assert "policy" in primary["subscriptions"][0]["keywords"]


def test_corrupt_primary_falls_back_to_backup(tmp_path: Path) -> None:
    """If the primary file is corrupted, ``_read_store`` (backed by
    ``read_json_with_backup``) recovers from ``.bak``.
    """
    path = tmp_path / "intelligence.json"
    bak = path.with_suffix(path.suffix + ".bak")

    first = _sample_store()
    _write_store(path, first)

    second = _sample_store()
    second["reports"].append(
        {"id": "rpt_2", "title": "Second", "summary": "", "items": []},
    )
    _write_store(path, second)
    assert bak.exists()

    # Corrupt the primary mid-session.
    path.write_text("{not valid json", encoding="utf-8")

    recovered = _read_store(path)
    # .bak holds the FIRST write, so we should see only one report.
    assert len(recovered["reports"]) == 1
    assert recovered["reports"][0]["id"] == "rpt_1"
    assert recovered["subscriptions"] == first["subscriptions"]


def test_missing_primary_returns_empty_stub(tmp_path: Path) -> None:
    """Reading a non-existent file yields the canonical empty stub,
    preserving the pre-migration contract.
    """
    path = tmp_path / "does_not_exist.json"
    assert not path.exists()

    loaded = _read_store(path)
    assert loaded == _empty_store()
    assert loaded == {"subscriptions": [], "reports": []}
