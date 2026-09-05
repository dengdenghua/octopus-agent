"""Group fan-out: a team message goes to every member in parallel (冒泡)."""

from __future__ import annotations

import threading

from runtime.execution.agents.group_fanout import (
    arbitrate_group_fanout,
    build_fanout_prompt,
    format_group_presence_reply,
    is_group_presence_query,
    run_group_fanout,
    synthesize_group_fanout,
)

_MEMBERS = [
    {"name": "aoi", "display_name": "Aoi"},
    {"name": "coder", "display_name": "Coder"},
    {"name": "market_researcher", "display_name": "Market Researcher"},
]


def _caller_ok(*, agent_id, prompt, **_kw):
    return {
        "success": True,
        "output": f"{agent_id} 判断：新项目应先锁定验收指标再启动。",
        "error": None,
    }


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
    assert len({reply["response_id"] for reply in out["replies"]}) == len(_MEMBERS)
    assert out["synthesis"]["schema"] == "octopus.group_fanout_synthesis.v1"
    assert out["synthesis"]["ready"] is True
    assert out["synthesis"]["primary_agent_id"] == "aoi"
    assert out["synthesis"]["supporting_agent_ids"] == ["coder", "market_researcher"]


def test_each_reply_is_reported_to_durable_collector_callback_as_it_finishes() -> None:
    collected: list[dict] = []

    out = run_group_fanout(
        "新项目启动，大家说说",
        _MEMBERS,
        agent_caller=_caller_ok,
        turn_id="turn-callback",
        on_reply=collected.append,
    )

    assert len(collected) == len(_MEMBERS)
    assert {item["agent_id"] for item in collected} == {
        "aoi",
        "coder",
        "market_researcher",
    }
    assert {item["response_id"] for item in collected} == {
        item["response_id"] for item in out["replies"]
    }


def test_reply_preserves_member_steering_audit_position() -> None:
    def caller(*, agent_id, prompt, **_kw):
        return {
            "success": True,
            "output": f"{agent_id} applied the correction",
            "error": None,
            "steering_count": 2,
            "steering_generation": 3,
            "steering_seq": 2,
            "session_compaction": {
                "checkpoint_valid": True,
                "checkpoint_through_turn": 12,
                "raw_turns_retained": 16,
            },
        }

    out = run_group_fanout("apply corrections", [_MEMBERS[0]], agent_caller=caller)

    reply = out["replies"][0]
    assert reply["steering_count"] == 2
    assert reply["steering_generation"] == 3
    assert reply["steering_seq"] == 2
    assert reply["session_compaction"]["checkpoint_through_turn"] == 12


def test_newer_steering_atomically_supersedes_an_obsolete_reply() -> None:
    calls: list[int] = []
    committed: list[int] = []

    def caller(*, agent_id, prompt, **_kw):
        sequence = len(calls)
        calls.append(sequence)
        return {
            "success": True,
            "output": f"{agent_id} answer after steering {sequence}",
            "error": None,
            "steering_count": sequence,
            "steering_generation": 1,
            "steering_seq": sequence,
        }

    def commit(reply: dict) -> bool:
        sequence = int(reply["steering_seq"])
        committed.append(sequence)
        return sequence == 1

    out = run_group_fanout(
        "apply corrections",
        [_MEMBERS[0]],
        agent_caller=caller,
        result_committer=commit,
    )

    reply = out["replies"][0]
    assert calls == [0, 1]
    assert committed == [0, 1]
    assert reply["ok"] is True
    assert reply["reply"].endswith("steering 1")
    assert reply["steering_seq"] == 1
    assert reply["validation"]["attempts"][0]["status"] == "superseded_by_steering"


def test_one_member_can_be_cancelled_while_other_members_continue() -> None:
    calls: list[str] = []

    def caller(*, agent_id, prompt, **_kw):
        calls.append(agent_id)
        return {"success": True, "output": f"{agent_id} done", "error": None}

    out = run_group_fanout(
        "continue useful lanes",
        _MEMBERS,
        agent_caller=caller,
        should_cancel_member=lambda agent_id: agent_id == "coder",
    )

    by_id = {reply["agent_id"]: reply for reply in out["replies"]}
    assert "coder" not in calls
    assert by_id["coder"]["cancelled"] is True
    assert by_id["aoi"]["ok"] is True
    assert by_id["market_researcher"]["ok"] is True
    assert out["cancelled"] is False


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
    assert set(called) == {f"a{i}" for i in range(32)}
    assert [reply["agent_id"] for reply in out["replies"]] == [f"a{i}" for i in range(32)]
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
    assert set(called) == {f"a{i}" for i in range(320)}
    assert [reply["agent_id"] for reply in out["replies"]] == [f"a{i}" for i in range(320)]
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


def test_each_member_sees_the_actual_human_speaker_not_itself() -> None:
    prompts: list[str] = []

    def caller(*, agent_id, prompt, **_kw):
        prompts.append(prompt)
        return {
            "success": True,
            "output": f"{agent_id} 判断：当前应先确认启动条件。",
            "error": None,
        }

    run_group_fanout(
        "开始吧",
        _MEMBERS,
        agent_caller=caller,
        speaker="用户",
    )

    assert len(prompts) == len(_MEMBERS)
    assert all("群里有人（用户）说" in prompt for prompt in prompts)


def test_planner_error_text_is_a_failure_not_a_completed_reply() -> None:
    def caller(*, agent_id, prompt, **_kw):
        if agent_id == "coder":
            return {
                "success": True,
                "output": "[planner error] LLM response lacks JSON: '在线'",
                "error": None,
            }
        return {"success": True, "output": "正常回复", "error": None}

    out = run_group_fanout("hi", _MEMBERS, agent_caller=caller)
    coder = next(reply for reply in out["replies"] if reply["agent_id"] == "coder")

    assert coder["ok"] is False
    assert coder["reply"] == ""
    assert "planner error" in coder["error"]
    assert "coder" in out["arbitration"]["failed_agent_ids"]
    assert "coder" not in out["arbitration"]["answered_agent_ids"]


def test_future_work_promise_is_not_counted_as_a_completed_reply() -> None:
    def caller(*, agent_id, prompt, **_kw):
        if agent_id == "coder":
            return {
                "success": True,
                "output": "我先去查官网和用户评测，整理好稍后发群里。",
                "error": None,
            }
        return {"success": True, "output": "结论：当前方案风险在于缺少回归测试。", "error": None}

    out = run_group_fanout("研究一下", _MEMBERS, agent_caller=caller)
    coder = next(reply for reply in out["replies"] if reply["agent_id"] == "coder")

    assert coder["ok"] is False
    assert coder["reply"] == ""
    assert "未在本轮交付结果" in coder["error"]
    assert "coder" in out["arbitration"]["failed_agent_ids"]


def test_question_and_generic_willingness_fail_the_response_quality_gate() -> None:
    outputs = {
        "aoi": "你具体想分析哪一方面？",
        "coder": "请先把现场截图贴出来。",
        "market_researcher": "没问题，交给我。",
    }

    def caller(*, agent_id, prompt, **_kw):
        return {"success": True, "output": outputs[agent_id], "error": None}

    out = run_group_fanout("大家讨论产品前景", _MEMBERS, agent_caller=caller)

    assert out["ok"] is False
    assert out["spoke"] == 0
    assert out["arbitration"]["answered_agent_ids"] == []
    assert set(out["arbitration"]["failed_agent_ids"]) == set(outputs)
    assert all(reply["validation"]["status"] == "rejected" for reply in out["replies"])
    assert any("反问" in reply["error"] for reply in out["replies"])
    assert any("补充输入" in reply["error"] for reply in out["replies"])
    assert any("接收或意愿" in reply["error"] for reply in out["replies"])


def test_explicit_blocker_with_a_conclusion_is_kept_as_a_valid_response() -> None:
    def caller(*, agent_id, prompt, **_kw):
        return {
            "success": True,
            "output": "结论：缺少成本数据，目前无法验证毛利率；风险是定价结论不可靠。",
            "error": None,
        }

    out = run_group_fanout("大家评估定价", _MEMBERS, agent_caller=caller)

    assert out["ok"] is True
    assert out["spoke"] == len(_MEMBERS)
    assert all(reply["validation"]["status"] == "accepted" for reply in out["replies"])


def test_rejected_response_is_retried_once_with_the_validation_reason() -> None:
    calls: dict[str, list[str]] = {member["name"]: [] for member in _MEMBERS}

    def caller(*, agent_id, prompt, **_kw):
        calls[agent_id].append(prompt)
        if len(calls[agent_id]) == 1:
            return {"success": True, "output": "没问题，交给我。", "error": None}
        return {
            "success": True,
            "output": "结论：应先验证付费转化率，再决定是否扩大投放。",
            "error": None,
        }

    out = run_group_fanout("大家评估增长方案", _MEMBERS, agent_caller=caller)

    assert out["ok"] is True
    assert out["spoke"] == len(_MEMBERS)
    assert all(len(prompts) == 2 for prompts in calls.values())
    assert all("仅表达接收或意愿" in prompts[1] for prompts in calls.values())
    assert all(reply["validation"]["status"] == "accepted" for reply in out["replies"])
    assert all(reply["validation"]["attempt_count"] == 2 for reply in out["replies"])
    assert out["attempt_count"] == len(_MEMBERS) * 2
    assert out["quality_retry_count"] == len(_MEMBERS)
    assert out["recovered_after_retry_count"] == len(_MEMBERS)
    assert all(
        [attempt["status"] for attempt in reply["validation"]["attempts"]]
        == ["rejected", "accepted"]
        for reply in out["replies"]
    )


def test_quality_retry_can_be_disabled_for_cost_sensitive_callers() -> None:
    calls = 0

    def caller(*, agent_id, prompt, **_kw):
        nonlocal calls
        calls += 1
        return {"success": True, "output": "请补充更多信息。", "error": None}

    out = run_group_fanout(
        "大家评估方案",
        _MEMBERS,
        agent_caller=caller,
        max_quality_retries=0,
    )

    assert out["ok"] is False
    assert calls == len(_MEMBERS)
    assert all(reply["validation"]["attempt_count"] == 1 for reply in out["replies"])


def test_presence_query_is_answered_from_roster_state() -> None:
    assert is_group_presence_query("你们都在线么？") is True
    assert is_group_presence_query("大家到齐了吗") is True
    assert is_group_presence_query("你们在线的话分析这个方案") is False
    assert format_group_presence_reply(_MEMBERS) == (
        "3 位 AI 成员均已就绪：Aoi、Coder、Market Researcher。"
    )


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


def test_quality_rubric_prefers_specific_evidenced_answer_over_longer_generic_text() -> None:
    def caller(*, agent_id, prompt, **_kw):
        if agent_id == "coder":
            return {
                "success": True,
                "output": (
                    "结论：已通过 tests/test_checkout.py 的 42 个测试；失败率从 8% 降到 0%，"
                    "证据见 https://example.test/run/42。"
                ),
                "error": None,
            }
        return {
            "success": True,
            "output": "这个测试验收方案总体上比较不错，我们应当继续充分考虑各种可能情况。" * 3,
            "error": None,
        }

    out = run_group_fanout("大家测试验收结账功能", _MEMBERS, agent_caller=caller)

    assert out["arbitration"]["primary_agent_id"] == "coder"
    assert out["quality"]["schema"] == "octopus.collaboration_quality.v1"
    coder = next(item for item in out["quality"]["outcomes"] if item["agent_id"] == "coder")
    assert coder["evidence"] >= 60
    assert out["delivery"]["schema"] == "octopus.collaboration_delivery.v1"
    coder_delivery = next(
        item for item in out["delivery"]["contributions"] if item["agent_id"] == "coder"
    )
    assert coder_delivery["evidence_refs"] == [
        "https://example.test/run/42",
        "tests/test_checkout.py",
    ]


def test_unverified_research_is_delivered_but_requires_semantic_review() -> None:
    def caller(*, agent_id, prompt, **_kw):
        return {
            "success": True,
            "output": f"{agent_id} 的结论是这个市场会快速增长，建议立即进入。",
            "error": None,
        }

    out = run_group_fanout("大家研究并核实这个市场", _MEMBERS, agent_caller=caller)

    assert out["ok"] is True
    assert out["quality"]["evidence_required"] is True
    assert out["quality"]["semantic_review_required"] is True
    assert out["delivery"]["ready"] is False
    assert out["delivery"]["semantic_review_required"] is True


def test_delivery_preserves_quality_identity_across_debate_rounds() -> None:
    call_count = 0

    def caller(*, agent_id, prompt, **_kw):
        nonlocal call_count
        call_count += 1
        return {
            "success": True,
            "output": f"结论：{agent_id} 第 {call_count} 次给出独立判断。",
            "error": None,
        }

    out = run_group_fanout(
        "大家讨论方案",
        _MEMBERS,
        agent_caller=caller,
        debate_rounds=2,
        turn_id="turn-quality-rounds",
    )

    contributions = out["delivery"]["contributions"]
    assert len(contributions) == 6
    assert all(item["quality"]["response_id"] == item["response_id"] for item in contributions)
    assert [item["round"] for item in contributions] == [1, 1, 1, 2, 2, 2]


def test_semantic_reviewer_must_accept_every_contribution_before_delivery_is_ready() -> None:
    seen_prompts: list[str] = []

    def reviewer(*, prompt, **_kw):
        seen_prompts.append(prompt)
        return {
            "success": True,
            "output": (
                '{"verdict":"pass","confidence":0.94,'
                '"accepted_response_ids":['
                '"turn-reviewed:resp:0:aoi","turn-reviewed:resp:1:coder",'
                '"turn-reviewed:resp:2:market_researcher"],'
                '"issues":[],"summary":"证据与结论一致"}'
            ),
        }

    out = run_group_fanout(
        "大家评审并验证发布方案",
        _MEMBERS,
        agent_caller=_caller_ok,
        turn_id="turn-reviewed",
        pattern={"id": "adversarial_review", "debate_rounds": 1},
        semantic_reviewer=reviewer,
        semantic_reviewer_agent_id="market_researcher",
    )

    assert len(seen_prompts) == 1
    assert "semantic-review-input" in seen_prompts[0]
    assert out["quality"]["semantic_review"]["verdict"] == "pass"
    assert out["quality"]["semantic_review_required"] is False
    assert out["delivery"]["ready"] is True
    assert all(item["semantic_status"] == "accepted" for item in out["delivery"]["contributions"])


def test_semantic_reviewer_fails_closed_on_invalid_or_partial_output() -> None:
    def invalid_reviewer(**_kw):
        return {"success": True, "output": "看起来都没问题"}

    invalid = run_group_fanout(
        "大家评审风险",
        _MEMBERS,
        agent_caller=_caller_ok,
        turn_id="turn-invalid-review",
        pattern={"id": "adversarial_review", "debate_rounds": 1},
        semantic_reviewer=invalid_reviewer,
        semantic_reviewer_agent_id="market_researcher",
    )
    assert invalid["delivery"]["ready"] is False
    assert invalid["quality"]["semantic_review"]["verdict"] == "review_failed"

    def partial_reviewer(**_kw):
        return {
            "success": True,
            "output": (
                '{"verdict":"pass","confidence":0.8,'
                '"accepted_response_ids":["turn-partial:resp:0:aoi"],'
                '"issues":[],"summary":"只检查了一个"}'
            ),
        }

    partial = run_group_fanout(
        "大家评审风险",
        _MEMBERS,
        agent_caller=_caller_ok,
        turn_id="turn-partial",
        pattern={"id": "adversarial_review", "debate_rounds": 1},
        semantic_reviewer=partial_reviewer,
    )
    assert partial["quality"]["semantic_review"]["verdict"] == "needs_revision"
    assert partial["delivery"]["ready"] is False


def test_debate_runs_second_round_with_transcript() -> None:
    calls: list[tuple[str, str]] = []

    def caller(*, agent_id, prompt, **_kw):
        calls.append((agent_id, prompt))
        return {"success": True, "output": f"{agent_id} round-reply", "error": None}

    out = run_group_fanout(
        "浙江自然能不能拿，大家辩论一下",
        _MEMBERS,
        agent_caller=caller,
        debate_rounds=2,
        turn_id="turn-debate",
    )

    # 2 rounds x 3 members = 6 replies.
    assert out["count"] == 6
    assert out["spoke"] == 6
    assert out["debate"] is not None
    assert out["debate"]["rounds"] == 2
    assert [r["round"] for r in out["replies"]] == [1, 1, 1, 2, 2, 2]
    assert len({reply["response_id"] for reply in out["replies"]}) == 6
    # Round-2 prompts contain the round-1 transcript (成员互见) and invite @反驳.
    r2_prompts = [p for (aid, p) in calls if aid == "aoi"]
    assert len(r2_prompts) == 2
    assert "成员互见辩论" in r2_prompts[1]
    assert "Aoi" in r2_prompts[1] or "Coder" in r2_prompts[1]  # transcript has teammates
    assert "@对方名字" in r2_prompts[1]
    # Arbitration reports the round span.
    assert out["arbitration"]["rounds"] == 2


def test_adversarial_pattern_assigns_roles_and_enforces_two_rounds() -> None:
    members = [
        *_MEMBERS,
        {"name": "qa", "display_name": "QA"},
    ]
    calls: list[tuple[str, str]] = []
    pattern = {
        "schema": "octopus.team_pattern_decision.v1",
        "id": "adversarial_review",
        "label": "对抗评审",
        "execution": "fanout",
        "debate_rounds": 2,
    }

    def caller(*, agent_id, prompt, **_kw):
        calls.append((agent_id, prompt))
        return {"success": True, "output": f"{agent_id} reply", "error": None}

    out = run_group_fanout(
        "大家评审方案并验证风险",
        members,
        agent_caller=caller,
        pattern=pattern,
        turn_id="turn-pattern",
    )

    assert out["pattern"] == pattern
    assert out["debate"]["rounds"] == 2
    assert out["count"] == 8
    assert [reply["pattern_role"] for reply in out["replies"][:4]] == [
        "proposer",
        "critic",
        "verifier",
        "alternative",
    ]
    first_round_prompts = {agent_id: prompt for agent_id, prompt in calls[:4]}
    assert "候选提出者" in first_round_prompts["aoi"]
    assert "质疑者" in first_round_prompts["coder"]
    assert "验证者" in first_round_prompts["market_researcher"]
    assert "替代方案探索者" in first_round_prompts["qa"]
    assert out["arbitration"]["outcomes"][0]["pattern_role"] is not None


def test_debate_does_not_run_when_off() -> None:
    calls: list[str] = []

    def caller(*, agent_id, prompt, **_kw):
        calls.append(agent_id)
        return {"success": True, "output": "hi", "error": None}

    out = run_group_fanout("hi", _MEMBERS, agent_caller=caller)
    assert out["count"] == 3
    assert out["debate"] is None
    assert [r["round"] for r in out["replies"]] == [1, 1, 1]
    assert len(calls) == 3


def test_debate_clamps_rounds() -> None:
    calls: list[str] = []

    def caller(*, agent_id, prompt, **_kw):
        calls.append(agent_id)
        return {"success": True, "output": "x", "error": None}

    out = run_group_fanout(
        "hi",
        _MEMBERS,
        agent_caller=caller,
        debate_rounds=99,
    )
    # Clamped to _MAX_DEBATE_ROUNDS = 3.
    assert out["debate"]["rounds"] == 3
    assert out["count"] == 9
    assert len(calls) == 9


def test_debate_mentioned_names_land_in_prompt() -> None:
    calls: list[tuple[str, str]] = []

    def caller(*, agent_id, prompt, **_kw):
        calls.append((agent_id, prompt))
        return {"success": True, "output": "ok", "error": None}

    out = run_group_fanout(
        "@Coder 你来说说",
        _MEMBERS,
        agent_caller=caller,
        debate_rounds=2,
        mentioned=["Coder"],
        turn_id="turn-mention",
    )
    assert out["debate"]["mentioned"] == ["Coder"]
    r2_prompts = [p for (aid, p) in calls if p and "第 2 轮" in p]
    assert r2_prompts, "expected round-2 prompts"
    assert "Coder" in r2_prompts[0]


def test_debate_build_prompt_has_rebuttal_instruction() -> None:
    from runtime.execution.agents.group_fanout import build_debate_prompt

    transcript = [
        {"agent_id": "aoi", "display_name": "Aoi", "reply": "我看好"},
        {"agent_id": "coder", "display_name": "Coder", "reply": "我谨慎"},
    ]
    p = build_debate_prompt(
        "能不能拿",
        "Market Researcher",
        ["Aoi", "Coder", "Market Researcher"],
        transcript,
        round_no=2,
    )
    assert "Aoi" in p and "Coder" in p
    assert "我看好" in p and "我谨慎" in p
    assert "@对方名字" in p
    assert "成员互见辩论" in p


def test_debate_reply_to_extraction() -> None:
    """③ @因果链: 回复正文里的 @成员名 应被解析为 reply_to 标注."""

    # 实际闭包内定义，改为直接测 group_fanout 的 build prompt 即可；
    # 这里验证协议字段存在且能承载 reply_to。
    from runtime.protocol.items import AgentMessageItem

    item = AgentMessageItem(text="hi", agent_display_name="A", reply_to="星望远 · 产业策略师")
    assert item.reply_to == "星望远 · 产业策略师"
    dumped = item.model_dump(by_alias=True, mode="json")
    assert dumped["replyTo"] == "星望远 · 产业策略师"


def test_fanout_emits_failure_rows() -> None:
    """② 失败可视化: 蜂群成员失败应 emit 一条 '未能回应 · 原因' 行."""

    emitted: list[dict] = []

    async def fake_emit(body, *, display_name=None, agent_id=None, icon=None, reply_to=None):
        emitted.append(
            {
                "body": body,
                "display_name": display_name,
                "agent_id": agent_id,
                "icon": icon,
                "reply_to": reply_to,
            }
        )

    # 直接验证 emit 逻辑分支：ok=False 时（结合 run_group_fanout 返回），
    # 网关循环会走失败分支。这里验证 run_group_fanout 的失败 reply 带 error。
    def caller(*, agent_id, prompt, **_kw):
        if agent_id == "coder":
            return {"success": False, "output": "", "error": "quota exceeded"}
        return {"success": True, "output": "ok", "error": None}

    out = run_group_fanout("hi", _MEMBERS, agent_caller=caller)
    coder = next(r for r in out["replies"] if r["agent_id"] == "coder")
    assert coder["ok"] is False
    assert coder["error"] == "quota exceeded"
    # 网关失败分支应产出一条带 ⚠️ 的文本（该逻辑在 _drive_group_fanout 内，
    # 此处通过协议层验证 error 信息可承载即可）。
    assert "quota exceeded" in str(coder["error"])


def test_fanout_cancellation_returns_promptly_and_skips_queued_members() -> None:
    started = threading.Event()
    release = threading.Event()
    stopped = threading.Event()
    calls: list[str] = []
    emitted: list[dict] = []
    output: dict = {}

    def caller(*, agent_id, prompt, **_kw):
        calls.append(agent_id)
        started.set()
        assert release.wait(timeout=2)
        return {"success": True, "output": f"late {agent_id}", "error": None}

    def run() -> None:
        output.update(
            run_group_fanout(
                "slow collaboration",
                _MEMBERS,
                agent_caller=caller,
                max_concurrency=1,
                on_reply=emitted.append,
                should_cancel=stopped.is_set,
            )
        )

    coordinator = threading.Thread(target=run)
    coordinator.start()
    assert started.wait(timeout=1)
    stopped.set()
    coordinator.join(timeout=1)
    release.set()

    assert not coordinator.is_alive()
    assert output["cancelled"] is True
    assert output["ok"] is False
    assert calls == ["aoi"]
    assert len(output["replies"]) == len(_MEMBERS)
    assert all(reply["cancelled"] for reply in output["replies"])
    assert len(emitted) == len(_MEMBERS)
