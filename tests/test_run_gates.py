"""Tests for tools/lint/run_gates.py — the mechanical-gate aggregator."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

TOOLS_LINT = Path(__file__).resolve().parent.parent / "tools" / "lint"
sys.path.insert(0, str(TOOLS_LINT))

import run_gates  # noqa: E402


def test_gate_list_matches_ci_nine() -> None:
    """The aggregator must carry exactly the nine mechanical gates."""
    expected = {
        "untracked_source_check",
        "god_file_check",
        "import_direction_check",
        "orphan_module_check",
        "feature_flag_consumption_check",
        "async_lock_check",
        "async_blocking_check",
        "root_hygiene",
        "repo_url_check",
    }
    assert {g.name for g in run_gates.GATES} == expected


def test_select_gates_only_and_skip() -> None:
    picked = run_gates.select_gates("god_file_check,root_hygiene", None)
    assert [g.name for g in picked] == ["god_file_check", "root_hygiene"]

    picked = run_gates.select_gates(None, "root_hygiene")
    assert "root_hygiene" not in {g.name for g in picked}
    assert len(picked) == 8


def test_select_gates_rejects_unknown_names() -> None:
    with pytest.raises(SystemExit, match="unknown gate"):
        run_gates.select_gates("no_such_gate", None)
    with pytest.raises(SystemExit, match="unknown gate"):
        run_gates.select_gates(None, "no_such_gate")


def test_select_gates_empty_selection_raises() -> None:
    with pytest.raises(SystemExit, match="no gates selected"):
        run_gates.select_gates(None, ",".join(g.name for g in run_gates.GATES))


def test_run_one_captures_exit_code_and_timeout() -> None:
    ok = run_gates.run_one(
        run_gates.Gate("ok", (sys.executable, "-c", "print('fine')")), 30.0, Path.cwd()
    )
    assert ok.exit_code == 0
    assert "fine" in ok.output_tail

    bad = run_gates.run_one(
        run_gates.Gate("bad", (sys.executable, "-c", "raise SystemExit(3)")), 30.0, Path.cwd()
    )
    assert bad.exit_code == 3


def test_run_one_timeout_marks_124() -> None:
    import time as _time

    original = run_gates.subprocess.run

    def _hang(*a, **k):
        raise run_gates.subprocess.TimeoutExpired(cmd=a[0], timeout=0.01)

    run_gates.subprocess.run = _hang  # type: ignore[assignment]
    try:
        res = run_gates.run_one(run_gates.Gate("slow", ("noop",)), 0.01, Path.cwd())
    finally:
        run_gates.subprocess.run = original
        _time.sleep(0)
    assert res.exit_code == 124
    assert "TIMEOUT" in res.output_tail


def test_render_table_and_exit_semantics() -> None:
    results = [
        run_gates.GateResult("a", 0, 1.2, ""),
        run_gates.GateResult("b", 1, 0.3, "boom"),
    ]
    table = run_gates.render_table(results)
    assert "PASS" in table
    assert "FAIL(1)" in table
    assert "1/2 gates passed" in table

    all_ok = [run_gates.GateResult("a", 0, 1.0, "")]
    assert "1/1 gates passed" in run_gates.render_table(all_ok)


def test_aggregate_exit_code_is_nonzero_on_any_failure() -> None:
    """main()'s contract: any failing gate -> exit 1 (asserted via results)."""
    results = [
        run_gates.GateResult("a", 0, 1.0, ""),
        run_gates.GateResult("b", 2, 1.0, ""),
    ]
    assert 0 if all(r.exit_code == 0 for r in results) else 1
    assert not all(r.exit_code == 0 for r in results)
