"""Host-owned inspection and transaction semantics for isolated patches."""

from __future__ import annotations

from pathlib import Path

import pytest

from runtime.execution.artifact_contracts import HandoffRecorder
from runtime.execution.misc.file_write_leases import file_write_lease_snapshot
from runtime.execution.subagents.bridge import call_subagent
from runtime.execution.subagents.candidate_patch import (
    apply_candidate_patch,
    inspect_candidate_patch,
    reconcile_candidate_patch,
)
from runtime.platform.process.session import current_session
from tests.test_artifact_handoff import _events
from tests.test_isolated_subagent import _host


def _candidate(tmp_path, *, declared: bool = True):
    repo, parent, log = _host(tmp_path)

    def runner(*_args, **_kwargs):
        workspace = Path(current_session().metadata["workspace_path"])
        (workspace / "README.md").write_text("candidate\n", encoding="utf-8")
        (workspace / "new.bin").write_bytes(b"\x00candidate\xff")
        return "done"

    result = call_subagent(
        "coder",
        "implement candidate",
        session=parent,
        isolate=True,
        runner=runner,
        output_files=["README.md", "new.bin"] if declared else ["README.md"],
        timeout_seconds=15,
    )
    return repo, parent, log, result


def test_inspected_candidate_applies_once_with_durable_receipts(tmp_path):
    repo, parent, log, candidate = _candidate(tmp_path)
    assert candidate["success"], candidate
    digest = candidate["worktree"]["patch"]["sha256"]

    inspected = inspect_candidate_patch(digest, session=parent)
    assert inspected["ok"], inspected
    assert inspected["contract_valid"] is True
    assert set(inspected["files"]) == {"README.md", "new.bin"}
    assert (repo / "README.md").read_text(encoding="utf-8") == "base\n"
    assert not (repo / "new.bin").exists()

    applied = apply_candidate_patch(inspected["inspection_id"], session=parent)
    assert applied["ok"] and applied["status"] == "applied", applied
    assert (repo / "README.md").read_text(encoding="utf-8") == "candidate\n"
    assert (repo / "new.bin").read_bytes() == b"\x00candidate\xff"
    leases = file_write_lease_snapshot(parent.metadata)["leases"]
    assert {row["owner"] for row in leases} == {"parent-turn"}

    repeated = apply_candidate_patch(inspected["inspection_id"], session=parent)
    assert repeated["ok"] and repeated["status"] == "already_applied"
    phases = [row["phase"] for row in _events(log)]
    assert phases == [
        "worktree_assigned",
        "worktree_exported",
        "patch_inspected",
        "patch_apply_started",
        "patch_applied",
    ]


def test_unknown_candidate_and_inspection_coordinates_are_rejected(tmp_path):
    _repo, parent, _log, _candidate_result = _candidate(tmp_path)
    inspected = inspect_candidate_patch("0" * 64, session=parent)
    assert not inspected["ok"] and inspected["status"] == "rejected"
    applied = apply_candidate_patch("inspection-" + "0" * 32, session=parent)
    assert not applied["ok"] and applied["status"] == "rejected"
    reconciled = reconcile_candidate_patch("patch-" + "0" * 32, session=parent)
    assert not reconciled["ok"] and reconciled["status"] == "rejected"


def test_project_drift_after_inspection_blocks_all_apply_effects(tmp_path):
    repo, parent, log, candidate = _candidate(tmp_path)
    digest = candidate["worktree"]["patch"]["sha256"]
    inspected = inspect_candidate_patch(digest, session=parent)
    assert inspected["ok"], inspected

    (repo / "README.md").write_text("external edit\n", encoding="utf-8")
    applied = apply_candidate_patch(inspected["inspection_id"], session=parent)
    assert not applied["ok"] and applied["status"] == "rejected"
    assert "changed since candidate snapshot" in applied["error"]
    assert (repo / "README.md").read_text(encoding="utf-8") == "external edit\n"
    assert not (repo / "new.bin").exists()
    assert "patch_apply_started" not in [row["phase"] for row in _events(log)]


def test_invalid_artifact_contract_requires_explicit_diff_acknowledgement(tmp_path):
    repo, parent, log, candidate = _candidate(tmp_path, declared=False)
    assert not candidate["success"] and not candidate["worktree"]["contract_valid"]
    digest = candidate["worktree"]["patch"]["sha256"]
    inspected = inspect_candidate_patch(digest, session=parent)
    assert inspected["ok"] and inspected["requires_invalid_contract_ack"] is True

    blocked = apply_candidate_patch(inspected["inspection_id"], session=parent)
    assert not blocked["ok"] and blocked["status"] == "rejected"
    assert "allow_invalid_contract=true" in blocked["error"]
    assert (repo / "README.md").read_text(encoding="utf-8") == "base\n"

    accepted = apply_candidate_patch(
        inspected["inspection_id"],
        allow_invalid_contract=True,
        session=parent,
    )
    assert accepted["ok"] and accepted["status"] == "applied", accepted
    assert (repo / "new.bin").read_bytes() == b"\x00candidate\xff"
    started = [row for row in _events(log) if row["phase"] == "patch_apply_started"]
    assert len(started) == 1 and started[0]["allow_invalid_contract"] is True


def test_sensitive_candidate_path_is_rejected_during_inspection(tmp_path):
    repo, parent, _log = _host(tmp_path)

    def runner(*_args, **_kwargs):
        workspace = Path(current_session().metadata["workspace_path"])
        (workspace / ".env").write_text("SECRET=engine-output\n", encoding="utf-8")
        return "done"

    candidate = call_subagent(
        "coder",
        "write environment file",
        session=parent,
        isolate=True,
        runner=runner,
        output_files=[".env"],
        timeout_seconds=15,
    )
    digest = candidate["worktree"]["patch"]["sha256"]
    inspected = inspect_candidate_patch(digest, session=parent)
    assert not inspected["ok"] and inspected["status"] == "rejected"
    assert "blocked" in inspected["error"]
    assert not (repo / ".env").exists()


def test_task_file_allowlist_is_enforced_for_the_whole_candidate(tmp_path):
    repo, parent, _log, candidate = _candidate(tmp_path)
    parent.metadata["allowed_write_paths"] = ["README.md"]
    digest = candidate["worktree"]["patch"]["sha256"]
    inspected = inspect_candidate_patch(digest, session=parent)
    assert not inspected["ok"] and "write allowlist" in inspected["error"]
    assert (repo / "README.md").read_text(encoding="utf-8") == "base\n"


def test_patch_bytes_must_still_match_the_export_receipt(tmp_path):
    repo, parent, _log, candidate = _candidate(tmp_path)
    patch = Path(candidate["worktree"]["patch"]["path"])
    patch.write_bytes(patch.read_bytes() + b"\n# tampered\n")
    inspected = inspect_candidate_patch(
        candidate["worktree"]["patch"]["sha256"],
        session=parent,
    )
    assert not inspected["ok"] and "no longer match" in inspected["error"]
    assert (repo / "README.md").read_text(encoding="utf-8") == "base\n"


def test_failed_start_journal_prevents_project_effects(tmp_path):
    repo, parent, log, candidate = _candidate(tmp_path)
    inspected = inspect_candidate_patch(candidate["worktree"]["patch"]["sha256"], session=parent)
    original = parent.metadata["_execution_handoff_recorder"]

    def fail_start(receipt):
        if receipt.get("phase") == "patch_apply_started":
            raise OSError("journal unavailable")
        original.write(receipt)

    parent.metadata["_execution_handoff_recorder"] = HandoffRecorder(
        fail_start,
        original.read,
    )
    applied = apply_candidate_patch(inspected["inspection_id"], session=parent)
    assert not applied["ok"] and applied["status"] == "rejected"
    assert "journal unavailable" in applied["error"]
    assert (repo / "README.md").read_text(encoding="utf-8") == "base\n"
    assert not (repo / "new.bin").exists()
    assert file_write_lease_snapshot(parent.metadata)["leases"] == []
    assert "patch_apply_started" not in [row["phase"] for row in _events(log)]


def test_failed_commit_receipt_restores_exact_original_bytes(tmp_path):
    repo, parent, log, candidate = _candidate(tmp_path)
    inspected = inspect_candidate_patch(candidate["worktree"]["patch"]["sha256"], session=parent)
    original_bytes = (repo / "README.md").read_bytes()
    original = parent.metadata["_execution_handoff_recorder"]

    def fail_commit(receipt):
        if receipt.get("phase") == "patch_applied":
            raise OSError("commit journal unavailable")
        original.write(receipt)

    parent.metadata["_execution_handoff_recorder"] = HandoffRecorder(
        fail_commit,
        original.read,
    )
    applied = apply_candidate_patch(inspected["inspection_id"], session=parent)
    assert not applied["ok"] and applied["status"] == "rolled_back", applied
    assert (repo / "README.md").read_bytes() == original_bytes
    assert not (repo / "new.bin").exists()
    leases = file_write_lease_snapshot(parent.metadata)["leases"]
    assert {row["owner"] for row in leases} == {"parent-turn"}
    phases = [row["phase"] for row in _events(log)]
    assert phases[-2:] == ["patch_apply_started", "patch_apply_rolled_back"]


def test_interrupted_commit_can_be_reconciled_from_durable_coordinates(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
):
    from runtime.execution.subagents import candidate_patch as transaction

    repo, parent, log, candidate = _candidate(tmp_path)
    inspected = inspect_candidate_patch(candidate["worktree"]["patch"]["sha256"], session=parent)
    original_settle = transaction._settle

    with monkeypatch.context() as patcher:
        patcher.setattr(
            transaction,
            "_settle",
            lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("process stopped")),
        )
        patcher.setattr(
            transaction,
            "_rollback",
            lambda *args, **kwargs: {
                "ok": False,
                "status": "reconciliation_required",
                "operation_id": kwargs["operation_id"],
                "error": "process stopped",
            },
        )
        pending = apply_candidate_patch(inspected["inspection_id"], session=parent)

    assert original_settle is transaction._settle
    assert pending["status"] == "reconciliation_required"
    assert (repo / "README.md").read_text(encoding="utf-8") == "candidate\n"
    assert [row["phase"] for row in _events(log)][-1] == "patch_apply_started"

    repeated = apply_candidate_patch(inspected["inspection_id"], session=parent)
    assert repeated["status"] == "reconciliation_required"
    assert repeated["operation_id"] == pending["operation_id"]
    reconciled = reconcile_candidate_patch(pending["operation_id"], session=parent)
    assert reconciled["ok"] and reconciled["status"] == "applied", reconciled
    assert reconcile_candidate_patch(pending["operation_id"], session=parent)["status"] == (
        "already_applied"
    )


def test_reconciliation_preserves_external_edits_and_rolls_back_known_files(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
):
    from runtime.execution.subagents import candidate_patch as transaction

    repo, parent, _log, candidate = _candidate(tmp_path)
    inspected = inspect_candidate_patch(candidate["worktree"]["patch"]["sha256"], session=parent)
    with monkeypatch.context() as patcher:
        patcher.setattr(
            transaction,
            "_settle",
            lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("process stopped")),
        )
        patcher.setattr(
            transaction,
            "_rollback",
            lambda *args, **kwargs: {
                "ok": False,
                "status": "reconciliation_required",
                "operation_id": kwargs["operation_id"],
                "error": "process stopped",
            },
        )
        pending = apply_candidate_patch(inspected["inspection_id"], session=parent)

    (repo / "README.md").write_text("human edit after interruption\n", encoding="utf-8")
    reconciled = reconcile_candidate_patch(pending["operation_id"], session=parent)
    assert not reconciled["ok"] and reconciled["status"] == "reconciliation_required"
    assert reconciled["states"] == {"README.md": "unknown", "new.bin": "old"}
    assert (repo / "README.md").read_text(encoding="utf-8") == ("human edit after interruption\n")
    assert not (repo / "new.bin").exists()
    owners = {row["owner"] for row in file_write_lease_snapshot(parent.metadata)["leases"]}
    assert owners == {pending["operation_id"]}
