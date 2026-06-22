"""Phones as remote team members — registry + dispatch/result round-trip."""

from __future__ import annotations

import threading

from runtime.execution.agents.mobile_device import (
    MobileDeviceRegistry,
    mobile_members_from_assignees,
)


def test_register_and_list_marks_online() -> None:
    reg = MobileDeviceRegistry()
    entry = reg.register("dev-1", "我的红米", "Redmi K70", now=1000.0)
    assert entry["agent_id"] == "mobile_dev-1"
    assert entry["name"] == "我的红米"
    devices = reg.list_devices(now=1010.0)
    assert len(devices) == 1 and devices[0]["online"] is True
    # stale heartbeat → offline
    assert reg.list_devices(now=2000.0)[0]["online"] is False


def test_dispatch_queues_and_phone_pulls_in_order() -> None:
    reg = MobileDeviceRegistry()
    reg.register("dev-1", "phone", "model")
    assert reg.dispatch("dev-1", "t1", "打开微信") is True
    assert reg.dispatch("dev-1", "t2", "发消息") is True
    assert reg.next_task("dev-1")["task_id"] == "t1"  # FIFO
    assert reg.next_task("dev-1")["task_id"] == "t2"
    assert reg.next_task("dev-1") is None  # drained


def test_dispatch_unknown_device_fails() -> None:
    reg = MobileDeviceRegistry()
    assert reg.dispatch("ghost", "t1", "x") is False


def test_await_result_round_trip() -> None:
    reg = MobileDeviceRegistry()
    reg.register("dev-1", "phone", "model")
    reg.dispatch("dev-1", "t1", "截图")

    def phone_side() -> None:
        task = reg.next_task("dev-1")
        assert task["goal"] == "截图"
        reg.post_result("dev-1", task["task_id"], ok=True, output="已截图 1 张")

    t = threading.Thread(target=phone_side)
    t.start()
    result = reg.await_result("t1", timeout=5.0)
    t.join()
    assert result is not None
    assert result["ok"] is True and "已截图" in result["output"]


def test_await_result_times_out() -> None:
    reg = MobileDeviceRegistry()
    reg.register("dev-1", "phone", "model")
    reg.dispatch("dev-1", "t1", "x")
    assert reg.await_result("t1", timeout=0.2) is None  # phone never replied


def test_members_from_assignees_filters_to_registered() -> None:
    reg = MobileDeviceRegistry()
    reg.register("dev-1", "phone-1", "m")
    reg.register("dev-2", "phone-2", "m")
    got = mobile_members_from_assignees(
        ["mobile_dev-1", "coder", "ghost"], registry=reg
    )
    assert [m["agent_id"] for m in got] == ["mobile_dev-1"]
    assert mobile_members_from_assignees([], registry=reg) == []


def test_team_task_mobile_helpers(monkeypatch) -> None:
    import runtime.execution.agents.mobile_device as md
    from runtime.sensing.gateway import team_tasks_router as ttr
    from runtime.sensing.gateway.team_tasks_router import TeamTaskWire

    reg = MobileDeviceRegistry()
    reg.register("dev-1", "我的手机", "Pixel")
    monkeypatch.setattr(md, "_REGISTRY", reg)

    task = TeamTaskWire(
        id="task-m",
        room_id="team-alpha",
        title="打开设置",
        created_at="2026-06-07T00:00:00+00:00",
        updated_at="2026-06-07T00:00:00+00:00",
        assignees=[
            {"kind": "agent", "ref": "mobile_dev-1"},
            {"kind": "agent", "ref": "coder"},  # normal agent, ignored
        ],
    )
    members = ttr._mobile_members(task)
    assert [m["agent_id"] for m in members] == ["mobile_dev-1"]

    arts = ttr._mobile_artifacts(
        [
            {"agent_id": "mobile_dev-1", "name": "我的手机", "device_id": "dev-1", "ok": True, "output": "已打开设置"},
            {"agent_id": "mobile_dev-2", "name": "平板", "device_id": "dev-2", "ok": False, "error": "离线"},
        ]
    )
    assert len(arts) == 2
    by = {a["agent_id"]: a for a in arts}
    assert by["mobile_dev-1"]["type"] == "mobile_run"
    assert by["mobile_dev-1"]["content"] == "已打开设置"
    assert by["mobile_dev-2"]["content"] == "离线"  # falls back to error
    assert by["mobile_dev-2"]["ok"] is False


def test_router_exposes_routes() -> None:
    from runtime.sensing.gateway.mobile_devices_router import create_mobile_devices_router

    router = create_mobile_devices_router()
    paths = {getattr(r, "path", None) for r in router.routes}
    assert "/api/mobile/register" in paths
    assert "/api/mobile/devices" in paths
    assert "/api/mobile/next" in paths
    assert "/api/mobile/result" in paths
    assert "/api/mobile/dispatch" in paths
