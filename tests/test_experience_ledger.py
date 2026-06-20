from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from runtime.memory.learning.experience_ledger import ExperienceLedger


def _review(task_id: str = "turn-1") -> dict:
    return {
        "schema": "octopus.task_run_review.v1",
        "task_id": task_id,
        "thread_id": "thread-1",
        "turn_id": task_id,
        "agent_id": "agent-a",
        "status": "failed",
        "learning_candidates": [
            {
                "kind": "failure_pattern",
                "priority": "P0",
                "memory_bucket": "experience",
                "title": "Tool failure pattern: exec_shell",
                "text": "Add preflight validation before retrying exec_shell.",
            }
        ],
        "backlog_candidates": [
            {
                "priority": "P0",
                "experiment": "Create deterministic replay case",
                "hypothesis": "A replay case prevents repeating this failure.",
                "minimal_implementation": "Convert replay.steps into a fixture.",
                "validation_metric": "Replay passes before prompt changes land.",
            }
        ],
    }


def _learning_review(
    *,
    task_id: str,
    title: str,
    text: str,
    priority: str = "P1",
    extra: dict | None = None,
) -> dict:
    item = {
        "kind": "success_pattern",
        "priority": priority,
        "memory_bucket": "experience",
        "title": title,
        "text": text,
    }
    if extra:
        item.update(extra)
    return {
        "schema": "octopus.task_run_review.v1",
        "task_id": task_id,
        "thread_id": "thread-1",
        "turn_id": task_id,
        "agent_id": "agent-a",
        "status": "completed",
        "learning_candidates": [item],
        "backlog_candidates": [],
    }


def test_experience_ledger_commits_review_candidates(tmp_path: Path) -> None:
    ledger = ExperienceLedger(tmp_path / "experience.json")

    result = ledger.add_from_task_run_review(
        _review(),
        now=datetime(2026, 6, 7, 1, 0, tzinfo=UTC),
    )
    rows = ledger.records()

    assert result["created"] == 2
    assert result["updated"] == 0
    assert rows["total"] == 2
    assert {row["memory_bucket"] for row in rows["records"]} == {
        "experience",
        "experiment_backlog",
    }
    assert rows["records"][0]["priority"] == "P0"
    assert rows["records"][0]["source_task_ids"] == ["turn-1"]


def test_experience_ledger_deduplicates_without_overwriting(
    tmp_path: Path,
) -> None:
    ledger = ExperienceLedger(tmp_path / "experience.json")

    ledger.add_from_task_run_review(
        _review("turn-1"),
        now=datetime(2026, 6, 7, 1, 0, tzinfo=UTC),
    )
    result = ledger.add_from_task_run_review(
        _review("turn-2"),
        now=datetime(2026, 6, 8, 1, 0, tzinfo=UTC),
    )
    rows = ledger.records()["records"]

    assert result["created"] == 0
    assert result["updated"] == 2
    assert len(rows) == 2
    assert all(row["occurrences"] == 2 for row in rows)
    assert all(row["created_at"].startswith("2026-06-07") for row in rows)
    assert all(row["last_seen_at"].startswith("2026-06-08") for row in rows)
    assert all(row["source_task_ids"] == ["turn-1", "turn-2"] for row in rows)


def test_experience_ledger_weekly_summary_groups_current_week(
    tmp_path: Path,
) -> None:
    ledger = ExperienceLedger(tmp_path / "experience.json")

    ledger.add_from_task_run_review(
        _review("turn-old"),
        now=datetime(2026, 5, 31, 23, 0, tzinfo=UTC),
    )
    ledger.add_from_task_run_review(
        _review("turn-current"),
        now=datetime(2026, 6, 7, 1, 0, tzinfo=UTC),
    )

    current = ledger.weekly_summary(week_start="2026-06-01")
    next_week = ledger.weekly_summary(week_start="2026-06-08")

    assert current["schema"] == "octopus.experience_weekly_summary.v1"
    assert current["week_start"] == "2026-06-01"
    assert current["record_count"] == 2
    assert current["by_priority"] == {"P0": 2}
    assert current["next_actions"]
    assert next_week["record_count"] == 0


def test_experience_ledger_filters_records(tmp_path: Path) -> None:
    ledger = ExperienceLedger(tmp_path / "experience.json")
    ledger.add_from_task_run_review(
        _review(),
        now=datetime(2026, 6, 7, 1, 0, tzinfo=UTC),
    )

    backlog = ledger.records(bucket="experiment_backlog")
    failures = ledger.records(kind="failure_pattern")

    assert backlog["total"] == 1
    assert backlog["records"][0]["kind"] == "backlog_candidate"
    assert failures["total"] == 1
    assert failures["records"][0]["memory_bucket"] == "experience"


def test_experience_ledger_marks_stale_memory_quality(tmp_path: Path) -> None:
    ledger = ExperienceLedger(tmp_path / "experience.json")
    ledger.add_from_task_run_review(
        _learning_review(
            task_id="turn-fresh",
            title="Prefer targeted tests",
            text="Run the narrowest related test before broader suites.",
            priority="P1",
        ),
        now=datetime(2026, 6, 7, 1, 0, tzinfo=UTC),
    )

    fresh = ledger.records(
        now=datetime(2026, 6, 10, 1, 0, tzinfo=UTC),
    )["records"][0]
    stale = ledger.records(
        now=datetime(2027, 1, 7, 1, 0, tzinfo=UTC),
        include_contradicted=True,
    )["records"][0]

    assert fresh["memory_quality"]["schema"] == "octopus.experience_memory_quality.v1"
    assert fresh["memory_quality"]["freshness"] == 1.0
    assert fresh["memory_quality"]["reliability"] > stale["memory_quality"]["reliability"]
    assert stale["memory_quality"]["age_days"] >= 180


def test_experience_ledger_filters_contradicted_records_by_default(
    tmp_path: Path,
) -> None:
    ledger = ExperienceLedger(tmp_path / "experience.json")
    ledger.add_from_task_run_review(
        _learning_review(
            task_id="turn-old",
            title="Use broad suite first",
            text="Always run the full suite before any narrow test.",
            priority="P0",
        ),
        now=datetime(2026, 6, 7, 1, 0, tzinfo=UTC),
    )
    old_id = ledger.records(include_contradicted=True)["records"][0]["id"]

    ledger.add_from_task_run_review(
        _learning_review(
            task_id="turn-new",
            title="Use targeted tests first",
            text="Run targeted tests first, then broaden only after they pass.",
            priority="P0",
            extra={
                "contradicts_record_ids": [old_id],
                "contradiction_reason": "targeted verification is cheaper and less noisy",
            },
        ),
        now=datetime(2026, 6, 8, 1, 0, tzinfo=UTC),
    )

    visible = ledger.records()["records"]
    all_rows = ledger.records(include_contradicted=True)["records"]
    contradicted = next(row for row in all_rows if row["id"] == old_id)
    superseding = next(row for row in all_rows if row["id"] != old_id)

    assert [row["title"] for row in visible] == ["Use targeted tests first"]
    assert contradicted["memory_quality"]["contradiction_status"] == "contradicted"
    assert contradicted["metadata"]["contradiction"]["by_record_id"] == superseding["id"]
    assert superseding["memory_quality"]["contradiction_status"] == "supersedes"
    assert superseding["metadata"]["contradiction"]["contradicts_record_ids"] == [old_id]


def test_experience_ledger_records_for_task_excludes_contradicted(
    tmp_path: Path,
) -> None:
    ledger = ExperienceLedger(tmp_path / "experience.json")
    ledger.add_from_task_run_review(
        _learning_review(
            task_id="turn-old",
            title="Use broad suite first",
            text="Always run the full suite before any narrow test.",
            priority="P0",
        ),
        now=datetime(2026, 6, 7, 1, 0, tzinfo=UTC),
    )
    old_id = ledger.records(include_contradicted=True)["records"][0]["id"]

    ledger.add_from_task_run_review(
        _learning_review(
            task_id="turn-new",
            title="Use targeted tests first",
            text="Run targeted tests first, then broaden only after they pass.",
            priority="P0",
            extra={
                "contradicts_record_ids": [old_id],
                "contradiction_reason": "targeted verification is cheaper and less noisy",
            },
        ),
        now=datetime(2026, 6, 8, 1, 0, tzinfo=UTC),
    )

    rows = ledger.records_for_task("turn-old")

    assert rows == []


def test_experience_ledger_quality_summary_counts_risks(tmp_path: Path) -> None:
    ledger = ExperienceLedger(tmp_path / "experience.json")
    ledger.add_from_task_run_review(
        _learning_review(
            task_id="turn-old",
            title="Use broad suite first",
            text="Always run the full suite before any narrow test.",
            priority="P0",
        ),
        now=datetime(2026, 1, 1, 1, 0, tzinfo=UTC),
    )
    old_id = ledger.records(include_contradicted=True)["records"][0]["id"]
    ledger.add_from_task_run_review(
        _learning_review(
            task_id="turn-new",
            title="Use targeted tests first",
            text="Run targeted tests first, then broaden only after they pass.",
            priority="P0",
            extra={"contradicts_record_ids": [old_id]},
        ),
        now=datetime(2026, 6, 8, 1, 0, tzinfo=UTC),
    )
    ledger.add_from_task_run_review(
        _learning_review(
            task_id="turn-stale",
            title="Prefer old lint shortcut",
            text="Use the historical lint shortcut without checking current config.",
            priority="P2",
        ),
        now=datetime(2026, 1, 2, 1, 0, tzinfo=UTC),
    )

    summary = ledger.quality_summary(now=datetime(2026, 8, 1, 1, 0, tzinfo=UTC))

    assert summary["schema"] == "octopus.experience_memory_quality_summary.v1"
    assert summary["total"] == 3
    assert summary["active_count"] == 2
    assert summary["contradicted_count"] == 1
    assert summary["stale_count"] == 1
    assert summary["low_reliability_count"] >= 1
    assert summary["top_risks"][0]["quality"]["contradiction_status"] == "contradicted"
    assert summary["next_actions"]
