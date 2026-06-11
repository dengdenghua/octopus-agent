from __future__ import annotations

from runtime.execution.suckers import Skill, SkillRegistry
from runtime.sensing.gateway.tool_bridge import build_anthropic_tool_specs


def test_native_tool_catalog_preserves_parallel_delegation_after_cap():
    reg = SkillRegistry()
    for idx in range(12):
        reg.register(
            Skill(
                name=f"dummy_{idx}",
                description="Dummy skill.",
                trusted_source=f"skill://public/dummy_{idx}",
                handler=lambda **_kwargs: {"ok": True},
            ),
            verify_tests=False,
        )
    for name in ("call_agent_parallel", "bb_keys", "bb_read", "bb_write"):
        reg.register(
            Skill(
                name=name,
                description=f"{name} should survive catalog clipping.",
                trusted_source=f"skill://public/{name}",
                handler=lambda **_kwargs: {"ok": True},
            ),
            verify_tests=False,
        )

    specs = build_anthropic_tool_specs(reg, max_skills=3)
    names = {spec.name for spec in specs}

    assert "call_agent_parallel" in names
    assert "bb_keys" in names
    assert "bb_read" in names
