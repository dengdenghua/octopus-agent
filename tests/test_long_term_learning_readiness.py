from __future__ import annotations

from runtime.safety.evolution.long_term_learning_readiness import (
    SCHEMA,
    compute_long_term_learning_readiness,
)


def test_long_term_learning_readiness_proves_journal_recovery() -> None:
    report = compute_long_term_learning_readiness()

    assert report["schema"] == SCHEMA
    assert report["ready"] is True
    assert report["score"] == 1.0
    assert report["verdict"] == "pass"
    assert report["requirements"] == {
        "corrupt_line_isolated": True,
        "subsequent_events_recovered": True,
        "partial_tail_preserved": True,
        "diagnostics_exposed": True,
        "health_warns_on_recovered_corruption": True,
    }
    assert report["probe"]["ok"] is True
    assert report["probe"]["diagnostics"]["first"]["skipped_total"] == 1
    assert report["probe"]["health"]["status"] == "warn"
