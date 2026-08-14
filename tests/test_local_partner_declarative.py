"""Test declarative args_template expansion for local CLI partners."""

from runtime.execution.agents.local_partner_bridge import (
    _expand_args_template,
    build_partner_argv,
)


def test_expand_args_template_simple():
    """Test simple template without conditionals."""
    template = ["{command}", "run", "{prompt}"]
    result = _expand_args_template(
        template,
        command="/usr/bin/opencode",
        prompt="Write hello world",
        model=None,
    )
    assert result == ["/usr/bin/opencode", "run", "Write hello world"]


def test_expand_args_template_with_model():
    """Test template with model conditional (model provided)."""
    template = [
        "{command}",
        "run",
        {"if": "model", "then": ["-m", "{model}"]},
        "{prompt}",
    ]
    result = _expand_args_template(
        template,
        command="/usr/bin/opencode",
        prompt="Write hello world",
        model="deepseek/flash",
    )
    assert result == ["/usr/bin/opencode", "run", "-m", "deepseek/flash", "Write hello world"]


def test_expand_args_template_without_model():
    """Test template with model conditional (model not provided)."""
    template = [
        "{command}",
        "run",
        {"if": "model", "then": ["-m", "{model}"]},
        "{prompt}",
    ]
    result = _expand_args_template(
        template,
        command="/usr/bin/opencode",
        prompt="Write hello world",
        model=None,
    )
    assert result == ["/usr/bin/opencode", "run", "Write hello world"]


def test_expand_args_template_with_else():
    """Test template with else branch."""
    template = [
        "{command}",
        {"if": "model", "then": ["-m", "{model}"], "else": ["--default-model"]},
        "{prompt}",
    ]
    # With model
    result = _expand_args_template(
        template,
        command="/usr/bin/cli",
        prompt="task",
        model="gpt-4",
    )
    assert result == ["/usr/bin/cli", "-m", "gpt-4", "task"]

    # Without model
    result = _expand_args_template(
        template,
        command="/usr/bin/cli",
        prompt="task",
        model=None,
    )
    assert result == ["/usr/bin/cli", "--default-model", "task"]


def test_expand_args_template_opencode():
    """Test OpenCode CLI template."""
    template = [
        "{command}",
        "run",
        {"if": "model", "then": ["-m", "{model}"]},
        "--auto",
        "{prompt}",
    ]
    result = _expand_args_template(
        template,
        command="opencode",
        prompt="test prompt",
        model="deepseek/flash",
    )
    assert result == ["opencode", "run", "-m", "deepseek/flash", "--auto", "test prompt"]


def test_expand_args_template_claude_code():
    """Test Claude Code CLI template."""
    template = [
        "{command}",
        "-p",
        {"if": "model", "then": ["--model", "{model}"]},
        "{prompt}",
    ]
    result = _expand_args_template(
        template,
        command="claude",
        prompt="test prompt",
        model="opus-4",
    )
    assert result == ["claude", "-p", "--model", "opus-4", "test prompt"]


def test_expand_args_template_codebuddy():
    """Test CodeBuddy CLI template with -y flag."""
    template = [
        "{command}",
        "-p",
        {"if": "model", "then": ["--model", "{model}"]},
        "--output-format",
        "text",
        "-y",
        "{prompt}",
    ]
    result = _expand_args_template(
        template,
        command="codebuddy",
        prompt="test prompt",
        model=None,
    )
    assert result == ["codebuddy", "-p", "--output-format", "text", "-y", "test prompt"]


def test_build_partner_argv_with_template():
    """Test that build_partner_argv uses template when capabilities provided."""
    capabilities = {
        "local_partner": True,
        "local_partner_id": "opencode-cli",
        "local_partner_invocation": {
            "args_template": [
                "{command}",
                "run",
                {"if": "model", "then": ["-m", "{model}"]},
                "--auto",
                "{prompt}",
            ],
        },
    }

    # The prompt gets wrapped by build_partner_prompt, so we test the structure
    result = build_partner_argv(
        partner_id="opencode-cli",
        command="opencode",
        prompt="hello",
        model="deepseek/flash",
        capabilities=capabilities,
    )

    assert result is not None
    assert result[0] == "opencode"
    assert result[1] == "run"
    assert result[2] == "-m"
    assert result[3] == "deepseek/flash"
    assert result[4] == "--auto"
    # result[5] is the wrapped prompt from build_partner_prompt


def test_build_partner_argv_fallback_to_hardcoded():
    """Test that build_partner_argv falls back to hardcoded when no template."""
    # No template in capabilities
    capabilities = {
        "local_partner": True,
        "local_partner_id": "opencode-cli",
    }

    result = build_partner_argv(
        partner_id="opencode-cli",
        command="opencode",
        prompt="hello",
        model="deepseek/flash",
        capabilities=capabilities,
    )

    # Should still work via hardcoded fallback
    assert result is not None
    assert result[0] == "opencode"
    assert result[1] == "run"
    assert "--auto" in result


def test_build_partner_argv_no_capabilities():
    """Test that build_partner_argv works without capabilities (backward compat)."""
    result = build_partner_argv(
        partner_id="opencode-cli",
        command="opencode",
        prompt="hello",
        model=None,
        capabilities=None,
    )

    # Should use hardcoded fallback
    assert result is not None
    assert result[0] == "opencode"
    assert result[1] == "run"
    assert "--auto" in result


def test_expand_args_template_empty():
    """Test that empty template returns None."""
    result = _expand_args_template(
        [],
        command="cmd",
        prompt="prompt",
        model=None,
    )
    assert result is None


def test_expand_args_template_malformed():
    """Test that malformed items are skipped gracefully."""
    template = [
        "{command}",
        123,  # Invalid: number
        {"unknown": "field"},  # Invalid: unknown conditional
        "{prompt}",
    ]
    result = _expand_args_template(
        template,
        command="cmd",
        prompt="prompt",
        model=None,
    )
    # Should skip invalid items but keep valid ones
    assert result == ["cmd", "prompt"]
