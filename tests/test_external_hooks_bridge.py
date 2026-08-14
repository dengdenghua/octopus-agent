"""External hooks.json bridge tests (dsh hook-protocol + dialect bridges)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from runtime.safety.hooks.events import (
    PreToolUseEvent,
    UserPromptSubmitEvent,
)
from runtime.safety.hooks.external_bridge import (
    BLOCKING_EXIT_CODE,
    build_payload,
    discover_external_hook_paths,
    load_external_hooks,
    matcher_diagnostic,
    matches_matcher,
    parse_external_hooks,
    parse_hook_output,
    register_external_hooks,
    run_external_hook,
)
from runtime.safety.hooks.registry import HookRegistry, get_global_registry

# ─── matchers ──────────────────────────────────────────────────────────────


def test_matcher_diagnostic_and_matching() -> None:
    assert matcher_diagnostic(None, "codex") is None
    assert matcher_diagnostic("", "codex") is None
    assert matcher_diagnostic("*", "claude-code") is None
    assert matcher_diagnostic("(unclosed", "codex") is not None
    assert matcher_diagnostic("(unclosed", "claude-code") is not None

    # Match-all sentinels.
    assert matches_matcher(None, "exec_shell", "codex") is True
    assert matches_matcher("*", "exec_shell", "codex") is True
    # Codex: always an unanchored regex.
    assert matches_matcher("exec_shell|exec_python", "exec_python", "codex") is True
    assert matches_matcher("exec_", "exec_shell", "codex") is True
    # Claude: word/pipe patterns are literal alternatives.
    assert matches_matcher("exec_shell|exec_python", "exec_python", "claude-code") is True
    assert matches_matcher("exec_shell|exec_python", "exec_sh", "claude-code") is False
    assert matches_matcher("exec_", "exec_shell", "claude-code") is False
    # Invalid regex never matches.
    assert matches_matcher("(unclosed", "anything", "codex") is False


# ─── codec ─────────────────────────────────────────────────────────────────


def test_parse_hook_output_exit2_blocks_with_stderr() -> None:
    out = parse_hook_output(BLOCKING_EXIT_CODE, "", "forbidden by policy")
    assert out.decision == "block"
    assert out.reason == "forbidden by policy"


def test_parse_hook_output_nonzero_is_non_blocking() -> None:
    out = parse_hook_output(1, "", "script exploded")
    assert out.decision is None


def test_parse_hook_output_json_decision() -> None:
    out = parse_hook_output(0, json.dumps({"decision": "block", "reason": "nope"}), "")
    assert out.decision == "block"
    assert out.reason == "nope"


def test_parse_hook_output_permission_decision_overrides() -> None:
    out = parse_hook_output(
        0,
        json.dumps({"decision": "approve", "permissionDecision": "deny", "reason": "r"}),
        "",
    )
    assert out.decision == "deny"


def test_parse_hook_output_modified_fields() -> None:
    out = parse_hook_output(
        0,
        json.dumps(
            {
                "decision": "allow",
                "modifiedPrompt": "rewritten",
                "modifiedInput": {"cmd": "ls"},
                "additionalDirectives": "be careful",
            }
        ),
        "",
    )
    assert out.modified_prompt == "rewritten"
    assert out.modified_input == {"cmd": "ls"}
    assert out.additional_directives == "be careful"


def test_parse_hook_output_malformed_json_lenient() -> None:
    out = parse_hook_output(0, "not json at all", "")
    assert out.decision is None
    assert out.stdout == "not json at all"


# ─── config parsing ────────────────────────────────────────────────────────


def _config(hooks: dict) -> dict:
    return {"version": 1, "hooks": hooks}


def test_parse_external_hooks_claude_and_codex() -> None:
    raw = _config(
        {
            "PreToolUse": [
                {
                    "matcher": "exec_shell|exec_python",
                    "hooks": [{"type": "command", "command": "python3 check.py"}],
                }
            ],
            "UserPromptSubmit": [
                {"hooks": [{"type": "command", "command": "python3 prompt.py"}]}
            ],
        }
    )
    specs, skipped = parse_external_hooks(raw, "claude-code")
    assert skipped == []
    assert len(specs) == 2
    assert specs[0].event == "PreToolUse"
    assert specs[0].matcher == "exec_shell|exec_python"
    assert specs[1].event == "UserPromptSubmit"
    assert specs[1].matcher == ""

    specs, _ = parse_external_hooks(raw, "codex")
    assert len(specs) == 2


def test_parse_external_hooks_skips_bad_entries() -> None:
    raw = _config(
        {
            "PreToolUse": [
                {
                    "matcher": "(unclosed",
                    "hooks": [{"type": "command", "command": "x"}],
                },
                {
                    "hooks": [{"type": "mcp", "command": "x"}],
                },
                {"hooks": [{"type": "command", "command": ""}]},
            ],
            "PostCompact": [{"hooks": [{"type": "command", "command": "y"}]}],
        }
    )
    specs, skipped = parse_external_hooks(raw, "codex")
    assert specs == []
    assert any("invalid codex regex matcher" in s for s in skipped)
    assert any("non-command hook" in s for s in skipped)
    assert any("empty command" in s for s in skipped)
    assert any("unsupported event PostCompact" in s for s in skipped)


def test_load_external_hooks_missing_and_bad(tmp_path: Path) -> None:
    assert load_external_hooks(tmp_path / "nope.json", "codex") == ([], [])
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert load_external_hooks(bad, "codex") == ([], [])


# ─── payloads ──────────────────────────────────────────────────────────────


def test_build_payload_pre_tool() -> None:
    event = PreToolUseEvent(sucker_id="exec_shell", args={"cmd": "ls"}, caller="call-1")
    payload = build_payload(event, "PreToolUse")
    assert payload["hook_event_name"] == "PreToolUse"
    assert payload["tool_name"] == "exec_shell"
    assert payload["tool_input"] == {"cmd": "ls"}
    assert payload["tool_use_id"] == "call-1"


def test_build_payload_user_prompt() -> None:
    event = UserPromptSubmitEvent(prompt_text="hello", thread_id="t1")
    payload = build_payload(event, "UserPromptSubmit")
    assert payload["prompt"] == "hello"
    assert payload["thread_id"] == "t1"


# ─── end-to-end dispatch through the registry ──────────────────────────────


def _write_config(tmp_path: Path, hooks: dict, dialect: str = "codex") -> Path:
    path = tmp_path / (".codex" if dialect == "codex" else ".claude") / "hooks.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_config(hooks)), encoding="utf-8")
    return path


def _hook_cmd(script: str) -> str:
    return f"{sys.executable} -c {json.dumps(script)}"


def test_dispatch_user_prompt_block_via_global_registry(tmp_path: Path) -> None:
    script = (
        "import json,sys;"
        "p=json.load(sys.stdin);"
        "print(json.dumps({'decision':'block','reason':'policy: '+p['prompt']}))"
    )
    path = _write_config(
        tmp_path,
        {"UserPromptSubmit": [{"hooks": [{"type": "command", "command": _hook_cmd(script)}]}]},
    )
    from runtime.safety.hooks.runner import dispatch_user_prompt

    reg = get_global_registry()
    reg.clear()
    try:
        assert register_external_hooks(registry=reg, paths=[(path, "codex")]) == 1
        decision = dispatch_user_prompt(prompt_text="hello", thread_id="t1")
        assert decision.cancelled is True
        assert "policy: hello" in decision.reason
    finally:
        reg.clear()


def test_dispatch_user_prompt_modified_prompt(tmp_path: Path) -> None:
    script = (
        "import json,sys;"
        "print(json.dumps({'decision':'allow','modifiedPrompt':'rewritten'}))"
    )
    path = _write_config(
        tmp_path,
        {"UserPromptSubmit": [{"hooks": [{"type": "command", "command": _hook_cmd(script)}]}]},
    )
    from runtime.safety.hooks.runner import dispatch_user_prompt

    reg = get_global_registry()
    reg.clear()
    try:
        register_external_hooks(registry=reg, paths=[(path, "codex")])
        decision = dispatch_user_prompt(prompt_text="hello", thread_id="t1")
        assert decision.cancelled is False
        assert decision.modified_prompt == "rewritten"
    finally:
        reg.clear()


def test_dispatch_pre_tool_modified_input_and_matcher(tmp_path: Path) -> None:
    script = (
        "import json,sys;"
        "p=json.load(sys.stdin);"
        "print(json.dumps({'decision':'allow','modifiedInput':{'cmd':'echo patched'}}))"
    )
    path = _write_config(
        tmp_path,
        {
            "PreToolUse": [
                {
                    "matcher": "exec_shell",
                    "hooks": [{"type": "command", "command": _hook_cmd(script)}],
                }
            ]
        },
    )
    from runtime.safety.hooks.runner import dispatch_pre_tool

    reg = get_global_registry()
    reg.clear()
    try:
        register_external_hooks(registry=reg, paths=[(path, "codex")])
        decision = dispatch_pre_tool(sucker_id="exec_shell", args={"cmd": "rm -rf /"})
        assert decision.modified_args == {"cmd": "echo patched"}
        # Non-matching tool → hook never runs, no modification.
        decision = dispatch_pre_tool(sucker_id="read_file", args={"path": "x"})
        assert decision.modified_args is None
        assert decision.cancelled is False
    finally:
        reg.clear()


def test_dispatch_post_tool_exit2_blocks(tmp_path: Path) -> None:
    script = "import sys;sys.stderr.write('no writes today');sys.exit(2)"
    path = _write_config(
        tmp_path,
        {
            "PostToolUse": [
                {
                    "matcher": "*",
                    "hooks": [{"type": "command", "command": _hook_cmd(script)}],
                }
            ]
        },
    )
    from runtime.safety.hooks.runner import dispatch_post_tool

    reg = get_global_registry()
    reg.clear()
    try:
        register_external_hooks(registry=reg, paths=[(path, "codex")])
        decision = dispatch_post_tool(sucker_id="write_text_file", args={}, output="x")
        assert decision.cancelled is True
        assert "no writes today" in decision.reason
    finally:
        reg.clear()


def test_failing_hook_degrades_to_pass_through(tmp_path: Path) -> None:
    script = "import sys;sys.exit(1)"
    path = _write_config(
        tmp_path,
        {"UserPromptSubmit": [{"hooks": [{"type": "command", "command": _hook_cmd(script)}]}]},
    )
    from runtime.safety.hooks.runner import dispatch_user_prompt

    reg = get_global_registry()
    reg.clear()
    try:
        register_external_hooks(registry=reg, paths=[(path, "codex")])
        decision = dispatch_user_prompt(prompt_text="hello")
        assert decision.cancelled is False
        assert decision.modified_prompt is None
    finally:
        reg.clear()


# ─── execution details ─────────────────────────────────────────────────────


def test_run_external_hook_timeout_is_non_blocking() -> None:
    out = run_external_hook(
        f"{sys.executable} -c 'import time;time.sleep(30)'",
        {},
        timeout_s=0.1,
    )
    assert out.decision is None


def test_run_external_hook_claude_trailing_newline() -> None:
    script = (
        "import json,sys;"
        "raw=sys.stdin.read();"
        "ok='\\n' in raw;"
        "print(json.dumps({'decision':'block' if ok else 'allow','reason':'nl'}))"
    )
    out = run_external_hook(
        _hook_cmd(script),
        {"prompt": "x"},
        dialect="claude-code",
    )
    assert out.decision == "block"


def test_discovery_env_var(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = _write_config(
        tmp_path,
        {"UserPromptSubmit": [{"hooks": [{"type": "command", "command": "true"}]}]},
        dialect="codex",
    )
    monkeypatch.setenv("OCTOPUS_HOOKS_JSON", str(path))
    monkeypatch.chdir(tmp_path)
    discovered = discover_external_hook_paths()
    assert any(p == path for p, _dialect in discovered)
    reg = HookRegistry()
    assert register_external_hooks(registry=reg, paths=None) == 1
    assert reg.handlers_for(UserPromptSubmitEvent)
