"""LocalPartner execution bridge — argv mapping + total, injectable runner."""

from __future__ import annotations

import subprocess

from runtime.execution.agents.local_partner_bridge import (
    build_partner_argv,
    partner_identity,
    run_local_partner,
)

# ── partner_identity: read drivable caps off an agent profile ────────


def test_partner_identity_prefers_executable_path() -> None:
    caps = {
        "local_partner": True,
        "local_partner_id": "claude-code",
        "local_partner_command": "claude",
        "local_partner_executable": "/usr/local/bin/claude",
    }
    assert partner_identity(caps) == ("claude-code", "/usr/local/bin/claude")


def test_partner_identity_falls_back_to_command() -> None:
    caps = {
        "local_partner": True,
        "local_partner_id": "codex-cli",
        "local_partner_command": "codex",
    }
    assert partner_identity(caps) == ("codex-cli", "codex")


def test_partner_identity_rejects_non_partner_or_incomplete() -> None:
    assert partner_identity(None) is None
    assert partner_identity({}) is None
    assert partner_identity({"local_partner": False, "local_partner_id": "x"}) is None
    # flagged but no command → not drivable
    assert partner_identity({"local_partner": True, "local_partner_id": "claude-code"}) is None
    # flagged + command but no id → not drivable
    assert partner_identity({"local_partner": True, "local_partner_command": "claude"}) is None


# ── build_partner_argv: per-CLI non-interactive invocation ───────────


def test_argv_for_known_clis() -> None:
    assert build_partner_argv("claude-code", "claude", "fix the bug") == [
        "claude",
        "-p",
        "fix the bug",
    ]
    assert build_partner_argv("codex-cli", "codex", "add a test") == [
        "codex",
        "exec",
        "--skip-git-repo-check",
        "add a test",
    ]


def test_argv_model_override_passes_through_m() -> None:
    # A CLI-valid model name is threaded to the tool's own model flag.
    assert build_partner_argv("codex-cli", "codex", "go", model="o3") == [
        "codex",
        "exec",
        "-m",
        "o3",
        "--skip-git-repo-check",
        "go",
    ]
    assert build_partner_argv("claude-code", "claude", "go", model="claude-x") == [
        "claude",
        "-p",
        "--model",
        "claude-x",
        "go",
    ]


def test_argv_empty_or_auto_model_keeps_cli_default() -> None:
    # No model / "auto" → omit the flag so the CLI uses its configured default.
    for m in (None, "", "  ", "auto", "AUTO"):
        assert build_partner_argv("codex-cli", "codex", "go", model=m) == [
            "codex",
            "exec",
            "--skip-git-repo-check",
            "go",
        ]


def test_prompt_is_a_separate_argv_element_not_a_shell_string() -> None:
    # A prompt full of shell metacharacters stays ONE argv element — proof the
    # text never gets concatenated into a shell command.
    nasty = "ship it; rm -rf / && echo $(whoami) `id`"
    argv = build_partner_argv("claude-code", "claude", nasty)
    assert argv == ["claude", "-p", nasty]
    assert argv[-1] == nasty  # untouched, single token


def test_argv_none_for_unknown_or_empty() -> None:
    assert build_partner_argv("openclaw", "openclaw", "do a thing") is None
    assert build_partner_argv("mystery-cli", "x", "hi") is None
    assert build_partner_argv("claude-code", "claude", "   ") is None
    assert build_partner_argv("claude-code", "", "hi") is None


# ── run_local_partner: total over every outcome, no real spawn ───────


def _runner(returns):
    """A fake runner: records the call, then returns/raises ``returns``."""
    seen: dict = {}

    def run(argv, cwd, timeout):
        seen["argv"] = argv
        seen["cwd"] = cwd
        seen["timeout"] = timeout
        if isinstance(returns, Exception):
            raise returns
        return returns

    return run, seen


def test_run_ok_returns_output() -> None:
    run, seen = _runner((0, "done: edited 3 files\n", ""))
    res = run_local_partner(
        partner_id="claude-code", command="claude", prompt="go", cwd="/repo", runner=run
    )
    assert res.ok is True
    assert res.output == "done: edited 3 files"
    assert res.exit_code == 0
    assert seen["argv"] == ["claude", "-p", "go"]
    assert seen["cwd"] == "/repo"


def test_run_unsupported_partner_short_circuits() -> None:
    # openclaw has no headless form → unsupported, runner never invoked.
    called = {"n": 0}

    def run(argv, cwd, timeout):
        called["n"] += 1
        return (0, "x", "")

    res = run_local_partner(partner_id="openclaw", command="openclaw", prompt="go", runner=run)
    assert res.unsupported is True
    assert res.ok is False
    assert called["n"] == 0


def test_run_nonzero_exit_is_failure_with_stderr() -> None:
    run, _ = _runner((1, "", "Error: not logged in\n"))
    res = run_local_partner(partner_id="codex-cli", command="codex", prompt="go", runner=run)
    assert res.ok is False
    assert res.exit_code == 1
    assert "not logged in" in res.error


def test_run_exit0_but_empty_output_is_failure() -> None:
    run, _ = _runner((0, "   \n", ""))
    res = run_local_partner(partner_id="claude-code", command="claude", prompt="go", runner=run)
    assert res.ok is False  # exit 0 but nothing to show


def test_run_timeout_flagged() -> None:
    run, _ = _runner(subprocess.TimeoutExpired(cmd="claude", timeout=240))
    res = run_local_partner(
        partner_id="claude-code", command="claude", prompt="go", timeout=240, runner=run
    )
    assert res.ok is False
    assert res.timed_out is True
    assert "240s" in res.error


def test_run_missing_binary_reported() -> None:
    run, _ = _runner(FileNotFoundError())
    res = run_local_partner(partner_id="codex-cli", command="codex", prompt="go", runner=run)
    assert res.ok is False
    assert "not installed" in res.error


def test_run_truncates_runaway_output() -> None:
    run, _ = _runner((0, "x" * 50_000, ""))
    res = run_local_partner(partner_id="claude-code", command="claude", prompt="go", runner=run)
    assert res.ok is True
    assert "…(truncated)" in res.output
    assert len(res.output) < 21_000


# ── shared-blackboard envelope + env pass-through ────────────────────


def test_run_layers_env_over_inherited(monkeypatch) -> None:
    from runtime.execution.agents import local_partner_bridge as b

    captured: dict = {}

    class _CP:
        returncode = 0
        stdout = "done"
        stderr = ""

    def fake_run(argv, **kw):
        captured["env"] = kw.get("env")
        return _CP()

    monkeypatch.setattr(b.subprocess, "run", fake_run)
    monkeypatch.setenv("PATH", "/usr/bin")
    res = b.run_local_partner(
        partner_id="claude-code",
        command="claude",
        prompt="go",
        env={"OCTOPUS_TURN_ID": "t1"},
    )
    assert res.ok is True
    assert captured["env"]["OCTOPUS_TURN_ID"] == "t1"  # extra layered in
    assert "PATH" in captured["env"]  # inherited env not dropped


def test_brief_empty_without_turn_or_board() -> None:
    from runtime.execution.agents import local_partner_bridge as b

    assert b.blackboard_brief("") == ""
    assert b.blackboard_brief(None) == ""


def test_brief_and_harvest_round_trip() -> None:
    from runtime.execution.agents import local_partner_bridge as b
    from runtime.memory.runtime_state.blackboard import get_blackboard

    tid = "test-turn-envelope-1"
    board = get_blackboard(tid)
    assert board is not None
    board.write("finding.1", "auth uses JWT", writer="agentA")

    brief = b.blackboard_brief(tid)
    assert "finding.1" in brief and "auth uses JWT" in brief

    b.harvest_to_blackboard(tid, "agentB", "I rewired the login flow")
    assert "rewired the login flow" in str(get_blackboard(tid).read("partner.agentB.output"))


def test_harvest_noop_without_turn_or_output() -> None:
    from runtime.execution.agents import local_partner_bridge as b

    b.harvest_to_blackboard("", "a", "x")  # no turn → no-op, no raise
    b.harvest_to_blackboard("tid", "a", "   ")  # blank output → no-op, no raise
