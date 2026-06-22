"""Group fan-out: a team message goes to every member in parallel (冒泡)."""

from __future__ import annotations

from runtime.execution.agents.group_fanout import build_fanout_prompt, run_group_fanout

_MEMBERS = [
    {"name": "aoi", "display_name": "Aoi"},
    {"name": "coder", "display_name": "Coder"},
    {"name": "market_researcher", "display_name": "Market Researcher"},
]


def _caller_ok(*, agent_id, prompt, **_kw):
    return {"success": True, "output": f"{agent_id} 冒泡:这事我来", "error": None}


def test_every_member_replies_in_parallel() -> None:
    out = run_group_fanout("新项目启动，大家说说", _MEMBERS, agent_caller=_caller_ok)
    assert out["ok"] is True
    assert out["count"] == 3 and out["spoke"] == 3
    # roster order preserved
    assert [r["agent_id"] for r in out["replies"]] == ["aoi", "coder", "market_researcher"]
    assert all(r["ok"] and r["reply"] for r in out["replies"])
    assert out["replies"][0]["display_name"] == "Aoi"


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


def test_caller_exception_does_not_break_others() -> None:
    def caller(*, agent_id, prompt, **_kw):
        if agent_id == "aoi":
            raise RuntimeError("network")
        return {"success": True, "output": "ok", "error": None}

    out = run_group_fanout("hi", _MEMBERS, agent_caller=caller)
    by = {r["agent_id"]: r for r in out["replies"]}
    assert by["aoi"]["ok"] is False and "network" in by["aoi"]["error"]
    assert out["spoke"] == 2


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
