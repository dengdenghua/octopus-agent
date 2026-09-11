"""防篡改封签：署名与审核记录必须可事后审计、不可静默改写。

哈希链不保密、也不证明「谁封的」；它证明的是「自链首以来序列完整」——
改内容、删中间行、重排、插行都会在 verify 时定位到断点。
"""

from __future__ import annotations

import sqlite3

import pytest

from runtime.memory.cowork.room_messages import RoomMessageStore
from runtime.platform.integrity.chain import GENESIS, seal_step, verify_chain
from runtime.projectos.model import Project
from runtime.projectos.store import ProjectStore

# ── 链原语 ──────────────────────────────────────────


def _rows(n, start=1):
    rows, prev = [], GENESIS
    for i in range(start, start + n):
        seal = seal_step(
            prev, scope="s", seq=i, record_id=f"r{i}", payload=f"p{i}", ts=f"t{i}"
        )
        rows.append(
            {
                "seq": i,
                "record_id": f"r{i}",
                "payload": f"p{i}",
                "ts": f"t{i}",
                "prev_seal": prev,
                "seal": seal,
            }
        )
        prev = seal
    return rows


def test_verify_accepts_an_intact_chain():
    assert verify_chain(_rows(5), scope="s")["ok"] is True


def test_verify_detects_content_mutation():
    rows = _rows(5)
    rows[2]["payload"] = "篡改后的内容"
    result = verify_chain(rows, scope="s")
    assert result["ok"] is False
    assert result["broken_seq"] == 3
    assert "mutated" in result["reason"]


def test_verify_detects_deleted_middle_row():
    rows = _rows(5)
    del rows[2]  # 删掉 seq=3，4 的 prev_seal 不再衔接
    result = verify_chain(rows, scope="s")
    assert result["ok"] is False
    assert result["broken_seq"] == 4


def test_verify_anchors_at_the_first_sealed_row():
    """老库中途开始封签：首行 prev=GENESIS，seq 不必是 1。"""
    rows = _rows(3, start=42)  # 迁移后 seq 从 42 起
    assert verify_chain(rows, scope="s")["ok"] is True


def test_seal_step_rejects_a_malformed_prev():
    with pytest.raises(ValueError):
        seal_step("short", scope="s", seq=1, record_id="r", payload="p", ts="t")


# ── 项目事件链 ──────────────────────────────────────


def _tamper_event_payload(db_path: str, project_id: str) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE project_events SET payload = '{\"evil\": true}' "
            "WHERE project_id = ? AND kind = 'project.note'",
            (project_id,),
        )


def _fresh_project(store):
    project = Project(id="P-seal", name="p", goal="测试项目")
    store.save_project(project)
    return project


def test_project_event_chain_verifies_after_writes(tmp_path):
    store = ProjectStore(base_dir=tmp_path)
    project = _fresh_project(store)
    for i in range(3):
        store.append_event(
            project.id, kind="project.note", payload={"i": i, "note": f"第{i}条"}
        )
    result = store.verify_event_chain(project.id)
    assert result["ok"] is True
    assert result["sealed_rows"] == 3


def test_project_event_chain_detects_retroactive_edit(tmp_path):
    store = ProjectStore(base_dir=tmp_path)
    project = _fresh_project(store)
    for i in range(3):
        store.append_event(project.id, kind="project.note", payload={"i": i})
    db = str(tmp_path / "projectos.db")
    _tamper_event_payload(db, project.id)
    result = store.verify_event_chain(project.id)
    assert result["ok"] is False
    assert result["reason"] == "content mutated after sealing"


def test_project_event_chain_reports_unsealed_history_honestly(tmp_path):
    """迁移场景：把既有行抹成未封签 → 链从其后开始，前缀如实上报。"""
    store = ProjectStore(base_dir=tmp_path)
    project = _fresh_project(store)
    store.append_event(project.id, kind="project.note", payload={"old": 1})
    db = str(tmp_path / "projectos.db")
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE project_events SET seal_prev = '', seal = ''")
    for i in range(2):
        store.append_event(project.id, kind="project.note", payload={"new": i})
    result = store.verify_event_chain(project.id)
    assert result["ok"] is True
    assert result["unsealed_prefix"] == 1
    assert result["sealed_rows"] == 2


def test_new_events_survive_a_legacy_database(tmp_path):
    """老库迁移后继续写入，事件读取契约（含新增封签字段）不受影响。"""
    store = ProjectStore(base_dir=tmp_path)
    project = _fresh_project(store)
    store.append_event(project.id, kind="project.note", payload={"after": "migration"})
    events = store.events_for_project(project.id)
    assert len(events) == 1
    assert events[0]["seal"]  # 新事件都带封签
    assert store.verify_event_chain(project.id)["ok"] is True


# ── 房间消息链 ──────────────────────────────────────


def test_room_message_chain_verifies_and_detects_edits(tmp_path):
    store = RoomMessageStore(base_dir=tmp_path)
    store.append("room-1", text="第一条", participant_id="u1", sender_kind="human")
    store.append(
        "room-1",
        text="第二条",
        participant_id="A1",
        sender_kind="role",
        sender_driver="ai",
    )
    assert store.verify_chain("room-1")["ok"] is True

    with sqlite3.connect(str(tmp_path / "room_messages.db")) as conn:
        conn.execute(
            "UPDATE room_messages SET text = 'AI 冒充真人改写' WHERE seq = 1"
        )
    result = store.verify_chain("room-1")
    assert result["ok"] is False
    assert result["broken_seq"] == 1


def test_room_message_chain_detects_deleted_row(tmp_path):
    store = RoomMessageStore(base_dir=tmp_path)
    for i in range(3):
        store.append("room-1", text=f"消息{i}")
    with sqlite3.connect(str(tmp_path / "room_messages.db")) as conn:
        conn.execute("DELETE FROM room_messages WHERE seq = 2")
    result = store.verify_chain("room-1")
    assert result["ok"] is False
    assert result["broken_seq"] == 3


def test_room_message_chain_is_per_room(tmp_path):
    store = RoomMessageStore(base_dir=tmp_path)
    store.append("room-a", text="A")
    store.append("room-b", text="B")
    assert store.verify_chain("room-a")["ok"] is True
    assert store.verify_chain("room-b")["ok"] is True
