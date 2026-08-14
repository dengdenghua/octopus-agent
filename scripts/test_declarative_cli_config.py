#!/usr/bin/env python3
"""Test the declarative CLI partner configuration in action."""

import json
from pathlib import Path

from runtime.execution.agents.local_partner_bridge import build_partner_argv


def load_agent_capabilities(agent_id: str) -> dict:
    """Load capabilities from an agent's profile.jsonc."""
    profile_path = Path(f"agents/{agent_id}/profile.jsonc")
    if not profile_path.exists():
        raise FileNotFoundError(f"Agent profile not found: {profile_path}")

    # Strip comments and parse JSON
    content = profile_path.read_text()
    lines = [line for line in content.splitlines() if not line.strip().startswith("//")]
    data = json.loads("\n".join(lines))
    return data.get("capabilities", {})


def test_opencode_argv():
    """Test OpenCode argv building with declarative template."""
    print("\n=== Testing OpenCode argv building ===")

    capabilities = load_agent_capabilities("local_opencode_cli")
    print(f"Loaded capabilities: {json.dumps(capabilities.get('local_partner_invocation'), indent=2)}")

    # Test without model
    argv = build_partner_argv(
        partner_id="opencode-cli",
        command="opencode",
        prompt="test task",
        model=None,
        capabilities=capabilities,
    )
    print(f"\nWithout model: {argv[:4]}... (prompt wrapped)")
    assert argv[0] == "opencode"
    assert argv[1] == "run"
    assert argv[2] == "--auto"
    assert "test task" in argv[3]

    # Test with model
    argv = build_partner_argv(
        partner_id="opencode-cli",
        command="opencode",
        prompt="test task",
        model="deepseek/flash",
        capabilities=capabilities,
    )
    print(f"With model: {argv[:6]}... (prompt wrapped)")
    assert argv[0] == "opencode"
    assert argv[1] == "run"
    assert argv[2] == "-m"
    assert argv[3] == "deepseek/flash"
    assert argv[4] == "--auto"
    assert "test task" in argv[5]

    print("✅ OpenCode argv building works with declarative template")


def test_claude_code_argv():
    """Test Claude Code argv building with declarative template."""
    print("\n=== Testing Claude Code argv building ===")

    capabilities = load_agent_capabilities("local_claude_code")
    print(f"Loaded capabilities: {json.dumps(capabilities.get('local_partner_invocation'), indent=2)}")

    # Test without model
    argv = build_partner_argv(
        partner_id="claude-code",
        command="claude",
        prompt="test task",
        model=None,
        capabilities=capabilities,
    )
    print(f"\nWithout model: {argv[:3]}... (prompt wrapped)")
    assert argv[0] == "claude"
    assert argv[1] == "-p"
    assert "test task" in argv[2]

    # Test with model
    argv = build_partner_argv(
        partner_id="claude-code",
        command="claude",
        prompt="test task",
        model="opus-4",
        capabilities=capabilities,
    )
    print(f"With model: {argv[:5]}... (prompt wrapped)")
    assert argv[0] == "claude"
    assert argv[1] == "-p"
    assert argv[2] == "--model"
    assert argv[3] == "opus-4"
    assert "test task" in argv[4]

    print("✅ Claude Code argv building works with declarative template")


def test_codebuddy_argv():
    """Test CodeBuddy argv building with declarative template."""
    print("\n=== Testing CodeBuddy argv building ===")

    capabilities = load_agent_capabilities("local_codebuddy_cli")
    print(f"Loaded capabilities: {json.dumps(capabilities.get('local_partner_invocation'), indent=2)}")

    # Test without model
    argv = build_partner_argv(
        partner_id="codebuddy-cli",
        command="codebuddy",
        prompt="test task",
        model=None,
        capabilities=capabilities,
    )
    print(f"\nWithout model: {argv[:6]}... (prompt wrapped)")
    assert argv[0] == "codebuddy"
    assert argv[1] == "-p"
    assert argv[2] == "--output-format"
    assert argv[3] == "text"
    assert argv[4] == "-y"
    assert "test task" in argv[5]

    # Test with model
    argv = build_partner_argv(
        partner_id="codebuddy-cli",
        command="codebuddy",
        prompt="test task",
        model="hunyuan-code",
        capabilities=capabilities,
    )
    print(f"With model: {argv[:8]}... (prompt wrapped)")
    assert argv[0] == "codebuddy"
    assert argv[1] == "-p"
    assert argv[2] == "--model"
    assert argv[3] == "hunyuan-code"
    assert argv[4] == "--output-format"
    assert argv[5] == "text"
    assert argv[6] == "-y"
    assert "test task" in argv[7]

    print("✅ CodeBuddy argv building works with declarative template (now includes -y flag)")


def test_backward_compatibility():
    """Test that hardcoded fallback still works when no template provided."""
    print("\n=== Testing backward compatibility ===")

    # Simulate old agent without args_template
    old_capabilities = {
        "local_partner": True,
        "local_partner_id": "opencode-cli",
        # No local_partner_invocation
    }

    argv = build_partner_argv(
        partner_id="opencode-cli",
        command="opencode",
        prompt="test task",
        model=None,
        capabilities=old_capabilities,
    )

    print(f"Fallback argv: {argv[:4]}...")
    assert argv[0] == "opencode"
    assert argv[1] == "run"
    assert argv[2] == "--auto"

    print("✅ Backward compatibility maintained (hardcoded fallback works)")


if __name__ == "__main__":
    print("Testing declarative CLI partner configuration")
    print("=" * 60)

    test_opencode_argv()
    test_claude_code_argv()
    test_codebuddy_argv()
    test_backward_compatibility()

    print("\n" + "=" * 60)
    print("✅ All declarative configuration tests passed!")
    print("\n📝 Summary:")
    print("  • OpenCode: uses args_template with --auto flag")
    print("  • Claude Code: uses args_template with -p flag")
    print("  • CodeBuddy: uses args_template with -y flag (NEW FIX)")
    print("  • Backward compatibility: hardcoded fallback still works")
