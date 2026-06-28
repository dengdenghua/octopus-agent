from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from runtime.memory.journal import JSONLJournal, TrajectoryEvent
from runtime.platform.models import Trajectory
from runtime.platform.observability.health import HealthRegistry, journal_check
from runtime.platform.process.paths import project_root as default_project_root

SCHEMA = "octopus.long_term_learning_readiness.v1"


def compute_long_term_learning_readiness(
    *,
    root: str | Path | None = None,
) -> dict[str, Any]:
    base = Path(root) if root is not None else default_project_root(Path(__file__))
    probe = _journal_recovery_probe(base)
    requirements = {
        "corrupt_line_isolated": probe.get("corrupt_line_isolated") is True,
        "subsequent_events_recovered": probe.get("subsequent_events_recovered") is True,
        "partial_tail_preserved": probe.get("partial_tail_preserved") is True,
        "diagnostics_exposed": probe.get("diagnostics_exposed") is True,
        "health_warns_on_recovered_corruption": (
            probe.get("health_warns_on_recovered_corruption") is True
        ),
    }
    passed = sum(1 for value in requirements.values() if value is True)
    total = len(requirements)
    score = round(passed / total, 3) if total else 0.0
    ready = score >= 1.0
    return {
        "schema": SCHEMA,
        "score": score,
        "ready": ready,
        "verdict": "pass" if ready else "review" if score >= 0.8 else "fail",
        "requirements": requirements,
        "probe": probe,
        "next_actions": (
            ["Long-term learning journal recovery is verified."]
            if ready
            else ["Make JSONL journal recovery preserve valid later events and expose diagnostics."]
        ),
        "policy": {
            "single_corrupt_jsonl_line_must_not_blind_later_memory": True,
            "partial_tail_line_must_not_be_consumed_until_complete": True,
            "health_checks_warn_when_corruption_was_recovered": True,
        },
    }


def _journal_recovery_probe(root: Path) -> dict[str, Any]:
    del root  # Kept for parity with other readiness probes.
    with tempfile.TemporaryDirectory(prefix="octopus-learning-journal-") as tmp:
        path = Path(tmp) / "journal.jsonl"
        writer = JSONLJournal(path)
        trajectory = Trajectory()
        writer.write_trajectory(trajectory)
        good_line = path.read_text(encoding="utf-8")
        path.write_text(
            good_line + "{bad json\n" + good_line + good_line.rstrip("\n"),
            encoding="utf-8",
        )

        reader = JSONLJournal(path)
        first_read = reader.read_all()
        first_diag = reader.diagnostics()

        with path.open("a", encoding="utf-8") as handle:
            handle.write("\n")

        second_read = reader.read_all()
        second_diag = reader.diagnostics()

        registry = HealthRegistry(parallel=False)
        registry.register(journal_check(reader))
        health = registry.probe()

    first_trajectory_count = sum(isinstance(event, TrajectoryEvent) for event in first_read)
    second_trajectory_count = sum(isinstance(event, TrajectoryEvent) for event in second_read)
    return {
        "schema": "octopus.long_term_learning_journal_recovery_probe.v1",
        "ok": (
            first_trajectory_count == 2
            and second_trajectory_count == 3
            and first_diag.get("skipped_total") == 1
            and second_diag.get("pending_tail_bytes") == 0
            and health.get("status") == "warn"
        ),
        "corrupt_line_isolated": first_diag.get("skipped_total") == 1,
        "subsequent_events_recovered": first_trajectory_count == 2,
        "partial_tail_preserved": (
            first_diag.get("pending_tail_bytes", 0) > 0
            and second_trajectory_count == 3
            and second_diag.get("pending_tail_bytes") == 0
        ),
        "diagnostics_exposed": (
            first_diag.get("schema") == "octopus.journal_diagnostics.v1"
            and bool(first_diag.get("skipped_lines"))
            and int(first_diag.get("skipped_lines", [{}])[0].get("line_number") or 0) == 2
        ),
        "health_warns_on_recovered_corruption": health.get("status") == "warn",
        "diagnostics": {
            "first": first_diag,
            "second": second_diag,
        },
        "health": health,
    }


__all__ = [
    "SCHEMA",
    "compute_long_term_learning_readiness",
]
