from __future__ import annotations

from runtime.safety.approval.approval_policy_store import load_policy
from runtime.safety.evolution.policy_review_rules import (
    build_policy_review_rule_drafts,
    install_policy_review_rule_draft,
    verify_policy_review_rule_draft,
)
from runtime.safety.evolution.proposal_ledger import ProposalLedger


def test_policy_review_rule_draft_is_signed_from_replay_backed_proposal(
    tmp_path,
) -> None:
    ledger = ProposalLedger(tmp_path / "proposal_ledger.jsonl")
    proposal = ledger.propose(
        kind="review_queue_policy_review",
        description="Review repeated denials for exec_shell",
        metadata={
            "review_queue_item_id": "rq_1",
            "item": {
                "title": "Review repeated denials for exec_shell",
                "text": "Tool exec_shell was denied repeatedly.",
                "metadata": {
                    "tool_name": "exec_shell",
                    "latest_denial": {
                        "tool_name": "exec_shell",
                        "reason": "no destructive shell",
                    },
                },
            },
            "evidence": {
                "schema": "octopus.policy_review_promotion_evidence.v1",
                "replay": {
                    "case_id": "task-run:abc123",
                    "fingerprint": "abc123",
                    "replayable": True,
                },
                "replay_gate": {"passed": True},
            },
        },
    )

    report = build_policy_review_rule_drafts(ledger_path=tmp_path / "proposal_ledger.jsonl")
    draft = report["drafts"][0]

    assert report["schema"] == "octopus.policy_review_rule_drafts.v1"
    assert report["total"] == 1
    assert draft["draft_id"].startswith("prd_")
    payload = draft["signed_payload"]
    assert payload["proposal_id"] == proposal.proposal_id
    assert payload["rule"] == {
        "effect": "deny",
        "tool": "exec_shell",
        "args_contains": "",
        "reason": "no destructive shell",
    }
    assert payload["evidence"]["replay"]["case_id"] == "task-run:abc123"
    assert verify_policy_review_rule_draft(draft)["ok"] is True


def test_policy_review_rule_draft_signature_detects_tampering(tmp_path) -> None:
    ledger = ProposalLedger(tmp_path / "proposal_ledger.jsonl")
    ledger.propose(
        kind="review_queue_policy_review",
        description="Review repeated denials for exec_shell",
        metadata={
            "review_queue_item_id": "rq_1",
            "item": {
                "title": "Review repeated denials for exec_shell",
                "text": "Tool exec_shell was denied repeatedly.",
            },
            "evidence": {"replay_gate": {"passed": True}},
        },
    )
    draft = build_policy_review_rule_drafts(
        ledger_path=tmp_path / "proposal_ledger.jsonl",
    )["drafts"][0]
    draft["signed_payload"]["rule"]["tool"] = "read_file"

    check = verify_policy_review_rule_draft(draft)

    assert check["ok"] is False
    assert check["reason"] == "signature mismatch"


def test_install_policy_review_rule_draft_requires_confirmation(tmp_path) -> None:
    ledger = ProposalLedger(tmp_path / "proposal_ledger.jsonl")
    ledger.propose(
        kind="review_queue_policy_review",
        description="Review repeated denials for exec_shell",
        metadata={
            "review_queue_item_id": "rq_1",
            "item": {
                "title": "Review repeated denials for exec_shell",
                "text": "Tool exec_shell was denied repeatedly.",
            },
            "evidence": {"replay_gate": {"passed": True}},
        },
    )
    draft = build_policy_review_rule_drafts(
        ledger_path=tmp_path / "proposal_ledger.jsonl",
    )["drafts"][0]

    try:
        install_policy_review_rule_draft(
            draft,
            policy_path=tmp_path / "permissions.json",
            confirm_install=False,
        )
    except ValueError as exc:
        assert str(exc) == "confirm_install=true is required"
    else:
        raise AssertionError("expected confirmation failure")

    assert load_policy(tmp_path / "permissions.json").rules == ()


def test_install_policy_review_rule_draft_appends_deny_rule(tmp_path) -> None:
    ledger = ProposalLedger(tmp_path / "proposal_ledger.jsonl")
    ledger.propose(
        kind="review_queue_policy_review",
        description="Review repeated denials for exec_shell",
        metadata={
            "review_queue_item_id": "rq_1",
            "item": {
                "title": "Review repeated denials for exec_shell",
                "text": "Tool exec_shell was denied repeatedly.",
                "metadata": {
                    "tool_name": "exec_shell",
                    "latest_denial": {
                        "tool_name": "exec_shell",
                        "reason": "no destructive shell",
                    },
                },
            },
            "evidence": {"replay_gate": {"passed": True}},
        },
    )
    draft = build_policy_review_rule_drafts(
        ledger_path=tmp_path / "proposal_ledger.jsonl",
    )["drafts"][0]

    result = install_policy_review_rule_draft(
        draft,
        policy_path=tmp_path / "permissions.json",
        confirm_install=True,
    )
    policy = load_policy(tmp_path / "permissions.json")

    assert result["installed"] is True
    assert result["policy_rule_count"] == 1
    assert len(policy.rules) == 1
    assert policy.rules[0].effect == "deny"
    assert policy.rules[0].tool == "exec_shell"
    assert policy.rules[0].reason == "no destructive shell"
