"""Group fan-out: a team message goes to every member in parallel (冒泡)."""

from __future__ import annotations

from runtime.execution.agents.group_fanout import (
    arbitrate_group_fanout,
    build_fanout_prompt,
    run_group_fanout,
    synthesize_group_fanout,
)

_MEMBERS = [
    {"name": "aoi", "display_name": "Aoi"},
    {"name": "coder", "display_name": "Coder"},
    {"name": "market_researcher", "display_name": "Market Researcher"},
]


def _caller_ok(*, agent_id, prompt, **_kw):
    return {"success": True, "output": f"{agent_id} 冒泡:这事我来", "error": None}


def test_every_member_replies_in_parallel() -> None:
    out = run_group_fanout(
        "新项目启动，大家说说",
        _MEMBERS,
        agent_caller=_caller_ok,
        turn_id="turn-1",
    )
    assert out["ok"] is True
    assert out["count"] == 3 and out["spoke"] == 3
    # roster order preserved
    assert [r["agent_id"] for r in out["replies"]] == ["aoi", "coder", "market_researcher"]
    assert all(r["ok"] and r["reply"] for r in out["replies"])
    assert out["replies"][0]["display_name"] == "Aoi"
    assert out["arbitration"]["schema"] == "octopus.group_fanout_arbitration.v1"
    assert out["arbitration"]["primary_agent_id"] == "aoi"
    assert out["arbitration"]["recommended_next_action"] == "use_primary_response"
    assert out["arbitration"]["ranking"][0]["response_id"].startswith("turn-1:resp:0:")
    assert out["synthesis"]["schema"] == "octopus.group_fanout_synthesis.v1"
    assert out["synthesis"]["ready"] is True
    assert out["synthesis"]["primary_agent_id"] == "aoi"
    assert out["synthesis"]["supporting_agent_ids"] == ["coder", "market_researcher"]


def test_one_member_failure_is_isolated() -> None:
    def caller(*, agent_id, prompt, **_kw):
        if agent_id == "coder":
            return {"success": False, "output": "", "error": "boom"}
        return {"success": True, "output": "ok", "error": None}

    out = run_group_fanout("hi", _MEMBERS, agent_caller=caller)
    by = {r["agent_id"]: r for r in out["replies"]}
    assert by["coder"]["ok"] is False and by["coder"]["error"] == "boom"
    assert by["aoi"]["ok"] is True
    assert out["spoke"] == 2 and out["ok"] is True  # group ok if anyone spoke
    assert out["arbitration"]["primary_agent_id"] == "aoi"
    assert out["arbitration"]["failed_agent_ids"] == ["coder"]
    assert out["arbitration"]["recommended_next_action"] == "use_primary_and_retry_failed_members"
    assert out["synthesis"]["retry_agent_ids"] == ["coder"]


def test_caller_exception_does_not_break_others() -> None:
    def caller(*, agent_id, prompt, **_kw):
        if agent_id == "aoi":
            raise RuntimeError("network")
        return {"success": True, "output": "ok", "error": None}

    out = run_group_fanout("hi", _MEMBERS, agent_caller=caller)
    by = {r["agent_id"]: r for r in out["replies"]}
    assert by["aoi"]["ok"] is False and "network" in by["aoi"]["error"]
    assert out["spoke"] == 2
    assert out["arbitration"]["failed_agent_ids"] == ["aoi"]


def test_caps_member_count() -> None:
    many = [{"name": f"a{i}", "display_name": f"A{i}"} for i in range(20)]
    out = run_group_fanout("hi", many, agent_caller=_caller_ok, max_members=4)
    assert out["count"] == 4
    assert out["dropped"] == 16
    assert out["capacity"] == {
        "schema": "octopus.group_fanout_capacity.v1",
        "requested_members": 20,
        "dispatched_members": 4,
        "dropped_members": 16,
        "max_members": 4,
        "max_concurrency": 4,
        "concurrency": 4,
        "scale_mode": "safe",
        "capacity_tier": "room_scale",
    }


def test_capacity_marks_kimi_scale_rosters_without_hiding_dispatch_limit() -> None:
    many = [{"name": f"a{i}", "display_name": f"A{i}"} for i in range(300)]
    called: list[str] = []

    def caller(*, agent_id, prompt, **_kw):
        called.append(agent_id)
        return {"success": True, "output": f"{agent_id} ok", "error": None}

    out = run_group_fanout("hi", many, agent_caller=caller, max_members=32)

    assert out["count"] == 32
    assert len(called) == 32
    assert called == [f"a{i}" for i in range(32)]
    assert out["dropped"] == 268
    assert out["capacity"]["schema"] == "octopus.group_fanout_capacity.v1"
    assert out["capacity"]["requested_members"] == 300
    assert out["capacity"]["dispatched_members"] == 32
    assert out["capacity"]["dropped_members"] == 268
    assert out["capacity"]["scale_mode"] == "safe"
    assert out["capacity"]["capacity_tier"] == "kimi_scale"


def test_full_scale_mode_dispatches_kimi_scale_roster_with_bounded_workers() -> None:
    many = [{"name": f"a{i}", "display_name": f"A{i}"} for i in range(320)]
    called: list[str] = []

    def caller(*, agent_id, prompt, **_kw):
        called.append(agent_id)
        return {"success": True, "output": f"{agent_id} ok", "error": None}

    out = run_group_fanout(
        "hi",
        many,
        agent_caller=caller,
        max_members=320,
        max_concurrency=32,
        scale_mode="full",
    )

    assert out["ok"] is True
    assert out["count"] == 320
    assert out["spoke"] == 320
    assert len(called) == 320
    assert called[0] == "a0"
    assert called[-1] == "a319"
    assert out["dropped"] == 0
    assert out["capacity"] == {
        "schema": "octopus.group_fanout_capacity.v1",
        "requested_members": 320,
        "dispatched_members": 320,
        "dropped_members": 0,
        "max_members": 320,
        "max_concurrency": 32,
        "concurrency": 32,
        "scale_mode": "full",
        "capacity_tier": "kimi_scale",
    }
    assert out["synthesis"]["answered_count"] == 320
    assert out["synthesis"]["total_count"] == 320


def test_guards() -> None:
    assert run_group_fanout("", _MEMBERS, agent_caller=_caller_ok)["ok"] is False  # no msg
    assert run_group_fanout("hi", [], agent_caller=_caller_ok)["ok"] is False  # no members


def test_prompt_is_persona_and_brief() -> None:
    p = build_fanout_prompt("上线新功能", "Aoi", ["Aoi", "Coder"])
    assert "上线新功能" in p
    assert "Aoi" in p and "Coder" in p
    assert "第一人称" in p and "冒泡" in p  # persona + group-chat framing


def test_arbitration_handles_all_failed_members() -> None:
    replies = [
        {
            "agent_id": "aoi",
            "display_name": "Aoi",
            "ok": False,
            "reply": "",
            "error": "timeout",
        },
        {
            "agent_id": "coder",
            "display_name": "Coder",
            "ok": False,
            "reply": "",
            "error": "quota",
        },
    ]

    out = arbitrate_group_fanout(replies, turn_id="turn-fail")

    assert out["primary_agent_id"] is None
    assert out["failed_agent_ids"] == ["aoi", "coder"]
    assert out["recommended_next_action"] == "retry_or_fallback_to_single_agent"
    assert [row["rank"] for row in out["ranking"]] == [1, 2]


def test_arbitration_handles_empty_successes() -> None:
    out = arbitrate_group_fanout(
        [
            {
                "agent_id": "aoi",
                "display_name": "Aoi",
                "ok": True,
                "reply": "",
                "error": None,
            }
        ],
        turn_id="turn-empty",
    )

    assert out["primary_agent_id"] is None
    assert out["empty_agent_ids"] == ["aoi"]
    assert out["recommended_next_action"] == "ask_members_to_expand"


def test_synthesis_is_structured_without_extra_model_call() -> None:
    replies = [
        {
            "agent_id": "aoi",
            "display_name": "Aoi",
            "ok": True,
            "reply": "主答案",
            "error": None,
        },
        {
            "agent_id": "coder",
            "display_name": "Coder",
            "ok": False,
            "reply": "",
            "error": "timeout",
        },
    ]
    arbitration = arbitrate_group_fanout(replies, turn_id="turn-synthesis")

    synthesis = synthesize_group_fanout(replies, arbitration)

    assert synthesis == {
        "schema": "octopus.group_fanout_synthesis.v1",
        "primary_agent_id": "aoi",
        "primary_reply": "主答案",
        "supporting_agent_ids": [],
        "retry_agent_ids": ["coder"],
        "answered_count": 1,
        "total_count": 2,
        "recommended_next_action": "use_primary_and_retry_failed_members",
        "ready": True,
    }
