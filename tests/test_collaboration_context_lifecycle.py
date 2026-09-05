from __future__ import annotations

import hashlib
import json

import pytest

from runtime.memory.cowork.collaboration_store import CollaborationStore
from runtime.memory.cowork.context_steward import plan_group_context


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _receipt() -> dict:
    plan = plan_group_context(
        "复核发布方案",
        [
            {"name": "coder", "description": "实现发布代码"},
            {"name": "reviewer", "description": "检查发布风险"},
        ],
        [
            {"role": "user", "content": "决定：蓝绿发布必须支持快速回滚"},
            {"role": "assistant", "content": "风险：旧版本数据库结构不可逆"},
        ],
    )
    return plan.lifecycle_receipt()


def test_context_lifecycle_is_persistent_idempotent_and_body_free(tmp_path) -> None:
    store = CollaborationStore(base_dir=tmp_path)
    receipt = _receipt()
    admitted = store.admit_context_turn(
        session_id="thread-1",
        turn_id="turn-1",
        run_id="run-1",
        message="复核发布方案 SECRET-BODY",
        receipt=receipt,
    )

    assert admitted["status"] == "admitted"
    assert admitted["expected_members"] == 2
    assert admitted["committed_members"] == 0
    assert admitted["message_sha256"] == _digest("复核发布方案 SECRET-BODY")
    encoded = json.dumps(admitted, ensure_ascii=False)
    assert "SECRET-BODY" not in encoded
    assert "蓝绿发布" not in encoded

    replay = store.admit_context_turn(
        session_id="thread-1",
        turn_id="turn-1",
        run_id="run-1",
        message="复核发布方案 SECRET-BODY",
        receipt=receipt,
    )
    assert replay == admitted
    with pytest.raises(ValueError, match="conflicts"):
        store.admit_context_turn(
            session_id="thread-1",
            turn_id="turn-1",
            run_id="run-1",
            message="篡改后的请求",
            receipt=receipt,
        )

    partial = store.settle_context_turn(
        "thread-1",
        "turn-1",
        [
            {
                "agent_id": "coder",
                "status": "committed",
                "result_sha256": _digest("coder accepted output"),
            }
        ],
    )
    assert partial["status"] == "admitted"
    assert partial["committed_members"] == 1

    settled = store.settle_context_turn(
        "thread-1",
        "turn-1",
        [
            {
                "agent_id": "reviewer",
                "status": "aborted",
                "result_sha256": _digest("reviewer failure"),
            }
        ],
    )
    assert settled["status"] == "partial"
    assert settled["committed_members"] == 1
    assert settled["aborted_members"] == 1

    restarted = CollaborationStore(base_dir=tmp_path)
    assert restarted.context_turn("thread-1", "turn-1") == settled
    assert (
        restarted.settle_context_turn(
            "thread-1",
            "turn-1",
            [
                {
                    "agent_id": "reviewer",
                    "status": "aborted",
                    "result_sha256": _digest("reviewer failure"),
                }
            ],
        )
        == settled
    )
    with pytest.raises(ValueError, match="conflicts"):
        restarted.settle_context_turn(
            "thread-1",
            "turn-1",
            [
                {
                    "agent_id": "reviewer",
                    "status": "committed",
                    "result_sha256": _digest("late conflicting output"),
                }
            ],
        )


def test_context_admission_rollback_is_safe_and_final(tmp_path) -> None:
    store = CollaborationStore(base_dir=tmp_path)
    receipt = _receipt()
    store.admit_context_turn(
        session_id="thread-rollback",
        turn_id="turn-rollback",
        message="do not persist me",
        receipt=receipt,
    )

    rolled_back = store.rollback_context_turn("thread-rollback", "turn-rollback")
    assert rolled_back["status"] == "rolled_back"
    assert rolled_back["aborted_members"] == 2
    assert store.rollback_context_turn("thread-rollback", "turn-rollback") == rolled_back
    with pytest.raises(ValueError, match="cannot advance"):
        store.settle_context_turn(
            "thread-rollback",
            "turn-rollback",
            [
                {
                    "agent_id": "coder",
                    "status": "committed",
                    "result_sha256": _digest("late output"),
                }
            ],
        )


def test_committed_context_cannot_be_rolled_back_or_widened(tmp_path) -> None:
    store = CollaborationStore(base_dir=tmp_path)
    receipt = _receipt()
    coder_only = {**receipt, "members": [receipt["members"][0]]}
    store.admit_context_turn(
        session_id="thread-final",
        turn_id="turn-final",
        message="ship",
        receipt=coder_only,
    )
    committed = store.settle_context_turn(
        "thread-final",
        "turn-final",
        [
            {
                "agent_id": "coder",
                "status": "committed",
                "result_sha256": _digest("accepted"),
            }
        ],
    )
    assert committed["status"] == "committed"
    with pytest.raises(ValueError, match="cannot be rolled back"):
        store.rollback_context_turn("thread-final", "turn-final")
    with pytest.raises(ValueError, match="was not admitted"):
        store.settle_context_turn(
            "thread-final",
            "turn-final",
            [
                {
                    "agent_id": "intruder",
                    "status": "committed",
                    "result_sha256": _digest("forbidden"),
                }
            ],
        )
