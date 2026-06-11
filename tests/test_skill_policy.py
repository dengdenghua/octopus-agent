from types import SimpleNamespace


def test_agent_skill_policy_tracks_sources():
    from runtime.execution.misc.skill_policy import resolve_agent_skill_policy

    agent = SimpleNamespace(
        arms=[
            SimpleNamespace(
                arm_id="web_arm",
                allowed_skills=["web_search", "fetch_url"],
            ),
            SimpleNamespace(
                arm_id="writer_arm",
                allowed_skills=["write_text_file"],
            ),
        ],
        extra_skills=["custom_private_skill"],
    )

    policy = resolve_agent_skill_policy(agent)

    assert "read_file" in policy.allowed
    assert "web_search" in policy.allowed
    assert "write_text_file" in policy.allowed
    assert "custom_private_skill" in policy.allowed
    assert policy.reasons_for("read_file") == ("atomic",)
    assert policy.reasons_for("web_search") == ("arm:web_arm",)
    assert policy.reasons_for("custom_private_skill") == ("agent:extra",)


def test_agent_skill_policy_all_marker_wins():
    from runtime.execution.misc.skill_policy import resolve_agent_skill_policy

    agent = SimpleNamespace(
        arms=[SimpleNamespace(arm_id="admin_arm", allowed_skills=["*"])],
        extra_skills=[],
    )

    policy = resolve_agent_skill_policy(agent)

    assert policy.allow_all is True
    assert policy.as_list() == ["*"]
    assert policy.allows("anything")


def test_context_tool_policy_preserves_role_then_dynamic_order():
    from runtime.execution.misc.skill_policy import resolve_context_tool_policy

    policy = resolve_context_tool_policy(
        role_allowlist=("fetch_url", "web_search"),
        context={
            "extra_tool_allowlist": ["read_file", "bb_write"],
            "extra_skills": ["query_skill"],
        },
    )

    assert policy.as_list() == [
        "fetch_url",
        "web_search",
        "read_file",
        "bb_write",
        "query_skill",
    ]
    assert policy.reasons_for("fetch_url") == ("role",)
    assert policy.reasons_for("read_file") == ("dynamic",)
    assert policy.reasons_for("query_skill") == ("extra_skills",)
