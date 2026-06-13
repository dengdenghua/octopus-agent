"""Regression: dated-layout thread file resolution must pick the LATEST month.

When a thread has files in several dated dirs (touched across months), the
resolver must return the newest — the old ``hits[0]`` returned whatever
``rglob`` yielded first (filesystem-arbitrary), which could be a stale month for
both reads and appends.
"""

from __future__ import annotations

from runtime.memory.threads.store import ThreadStateStore


def test_resolve_thread_file_picks_latest_dated_month(tmp_path):
    store = ThreadStateStore(per_agent_base=tmp_path / "base", dated_layout=True)
    sess_root = tmp_path / "sess"
    # Create out of order on purpose; correctness must not depend on order.
    for ym in ("2026/05", "2026/04", "2026/06"):
        d = sess_root / ym
        d.mkdir(parents=True)
        (d / "t.jsonl").write_text("{}\n", encoding="utf-8")

    chosen = store._resolve_thread_file(sess_root, "t")
    assert chosen == sess_root / "2026" / "06" / "t.jsonl"


def test_resolve_thread_file_flat_still_wins(tmp_path):
    # An existing flat file short-circuits (upgrade flat→dated never orphans it).
    store = ThreadStateStore(per_agent_base=tmp_path / "base", dated_layout=True)
    sess_root = tmp_path / "sess"
    sess_root.mkdir(parents=True)
    (sess_root / "t.jsonl").write_text("{}\n", encoding="utf-8")
    (sess_root / "2026" / "06").mkdir(parents=True)
    (sess_root / "2026" / "06" / "t.jsonl").write_text("{}\n", encoding="utf-8")

    assert store._resolve_thread_file(sess_root, "t") == sess_root / "t.jsonl"
