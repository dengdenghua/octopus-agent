"""Group fan-out: a team message goes to every member in parallel (冒泡)."""

from __future__ import annotations

from runtime.execution.agents.group_fanout import (
    arbitrate_group_fanout,
    build_fanout_prompt,
    run_group_fanout,
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
    assert (
        out["arbitration"]["recommended_next_action"]
        == "use_primary_and_retry_failed_members"
    )


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
