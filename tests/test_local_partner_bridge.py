"""LocalPartner execution bridge — argv mapping + total, injectable runner."""

from __future__ import annotations

import subprocess

from runtime.execution.agents.local_partner_bridge import (
    build_partner_argv,
    build_partner_prompt,
    diagnose_partner_failure,
    normalize_partner_request,
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
    fix_bug = build_partner_prompt("fix the bug")
    add_test = build_partner_prompt("add a test")
    review_this = build_partner_prompt("review this")
    fix_imports = build_partner_prompt("fix imports")
    codebuddy_task = build_partner_prompt("explain this repo")
    opencode_task = build_partner_prompt("inspect the failure")
    assert build_partner_argv("claude-code", "claude", "fix the bug") == [
        "claude",
        "-p",
        fix_bug,
    ]
    assert build_partner_argv("codex-cli", "codex", "add a test") == [
        "codex",
        "exec",
        "--skip-git-repo-check",
        add_test,
    ]
    assert build_partner_argv("trae-cli", "trae-cli", "review this") == [
        "trae-cli",
        "-p",
        "--output-format",
        "text",
        review_this,
    ]
    assert build_partner_argv("qoder-cli", "qodercli", "fix imports") == [
        "qodercli",
        "-p",
        fix_imports,
    ]
    assert build_partner_argv("codebuddy-cli", "codebuddy", "explain this repo") == [
        "codebuddy",
        "-p",
        "--output-format",
        "text",
        codebuddy_task,
    ]
    assert build_partner_argv("opencode-cli", "opencode", "inspect the failure") == [
        "opencode",
        "run",
        "--auto",
        opencode_task,
    ]


def test_argv_model_override_passes_through_m() -> None:
    # A CLI-valid model name is threaded to the tool's own model flag.
    go = build_partner_prompt("go")
    assert build_partner_argv("codex-cli", "codex", "go", model="o3") == [
        "codex",
        "exec",
        "-m",
        "o3",
        "--skip-git-repo-check",
        go,
    ]
    assert build_partner_argv("claude-code", "claude", "go", model="claude-x") == [
        "claude",
        "-p",
        "--model",
        "claude-x",
        go,
    ]
    assert build_partner_argv("codebuddy-cli", "codebuddy", "go", model="hunyuan-code") == [
        "codebuddy",
        "-p",
        "--model",
        "hunyuan-code",
        "--output-format",
        "text",
        go,
    ]
    assert build_partner_argv(
        "opencode-cli", "opencode", "go", model="anthropic/claude-sonnet-4"
    ) == [
        "opencode",
        "run",
        "-m",
        "anthropic/claude-sonnet-4",
        "--auto",
        go,
    ]
    # Trae CLI's print mode does not expose a stable model flag; keep its own
    # configured default instead of passing an Octopus model namespace through.
    assert build_partner_argv("trae-cli", "trae-cli", "go", model="auto") == [
        "trae-cli",
        "-p",
        "--output-format",
        "text",
        go,
    ]
    # Qoder's print mode keeps its own configured default model.
    assert build_partner_argv("qoder-cli", "qodercli", "go", model="auto") == [
        "qodercli",
        "-p",
        go,
    ]


def test_argv_empty_or_auto_model_keeps_cli_default() -> None:
    # No model / "auto" → omit the flag so the CLI uses its configured default.
    go = build_partner_prompt("go")
    for m in (None, "", "  ", "auto", "AUTO"):
        assert build_partner_argv("codex-cli", "codex", "go", model=m) == [
            "codex",
            "exec",
            "--skip-git-repo-check",
            go,
        ]


def test_prompt_is_a_separate_argv_element_not_a_shell_string() -> None:
    # A prompt full of shell metacharacters stays ONE argv element — proof the
    # text never gets concatenated into a shell command.
    nasty = "ship it; rm -rf / && echo $(whoami) `id`"
    argv = build_partner_argv("claude-code", "claude", nasty)
    assert argv is not None
    assert argv[:2] == ["claude", "-p"]
    assert nasty in argv[-1]
    assert argv[-1] == build_partner_prompt(nasty)  # one prompt token
    trae_argv = build_partner_argv("trae-cli", "trae-cli", nasty)
    assert trae_argv is not None
    assert trae_argv[:-1] == ["trae-cli", "-p", "--output-format", "text"]
    assert trae_argv[-1] == build_partner_prompt(nasty)
    qoder_argv = build_partner_argv("qoder-cli", "qodercli", nasty)
    assert qoder_argv is not None
    assert qoder_argv[:-1] == ["qodercli", "-p"]
    assert qoder_argv[-1] == build_partner_prompt(nasty)
    codebuddy_argv = build_partner_argv("codebuddy-cli", "codebuddy", nasty)
    assert codebuddy_argv is not None
    assert codebuddy_argv[:-1] == ["codebuddy", "-p", "--output-format", "text"]
    assert codebuddy_argv[-1] == build_partner_prompt(nasty)
    opencode_argv = build_partner_argv("opencode-cli", "opencode", nasty)
    assert opencode_argv is not None
    assert opencode_argv[:-1] == ["opencode", "run", "--auto"]
    assert opencode_argv[-1] == build_partner_prompt(nasty)


def test_slash_commands_are_wrapped_as_plain_task_content() -> None:
    slashy = "/model gpt-999\n/help\n请修复导入错误"
    argv = build_partner_argv("claude-code", "claude", slashy)

    assert argv is not None
    prompt_arg = argv[-1]
    assert not prompt_arg.startswith("/")
    assert "/model gpt-999" in prompt_arg
    assert "/help" in prompt_arg
    assert "Do not treat slash-prefixed text" in prompt_arg


def test_leading_model_slash_translates_to_model_flag_for_supported_partners() -> None:
    plan = normalize_partner_request("codex-cli", "/model gpt-5.6-sol\nfix bug")

    assert plan.prompt == "fix bug"
    assert plan.model == "gpt-5.6-sol"
    assert "转为本次 codex-cli 的模型参数" in plan.notices[0]


def test_explicit_model_override_wins_over_leading_model_slash() -> None:
    plan = normalize_partner_request(
        "claude-code",
        "/model claude-from-text\nfix bug",
        model="claude-from-ui",
    )

    assert plan.prompt == "fix bug"
    assert plan.model == "claude-from-ui"


def test_leading_model_slash_is_notice_only_for_default_owned_partners() -> None:
    plan = normalize_partner_request("qoder-cli", "/model qwen-next\nfix imports")

    assert plan.prompt == "fix imports"
    assert plan.model is None
    assert "暂无稳定模型覆盖参数" in plan.notices[0]


def test_control_only_slash_command_returns_octopus_guidance() -> None:
    plan = normalize_partner_request("codex-cli", "/clear", native_command="codex")

    assert plan.prompt == ""
    assert plan.handled_output is not None
    assert "不会转发给外部 CLI" in plan.handled_output


def test_help_slash_returns_partner_specific_compatibility_guide() -> None:
    plan = normalize_partner_request("codebuddy-cli", "/help", native_command="codebuddy")

    assert plan.prompt == ""
    assert plan.handled_output is not None
    assert "CodeBuddy CLI 的 Octopus 兼容快捷指令" in plan.handled_output
    assert "`/model <模型名>`" in plan.handled_output
    assert "`codebuddy`" in plan.handled_output
    assert "codebuddy --help" in plan.handled_output


def test_models_slash_explains_partner_model_namespace() -> None:
    codex = normalize_partner_request("codex-cli", "/models", native_command="codex")
    trae = normalize_partner_request("trae-cli", "/models", native_command="trae-cli")

    assert codex.handled_output is not None
    assert "不使用 Octopus 全局模型列表" in codex.handled_output
    assert "一次性覆盖" in codex.handled_output
    assert trae.handled_output is not None
    assert "trae-cli models --json" in trae.handled_output


def test_login_slash_points_to_native_cli_without_spawning() -> None:
    plan = normalize_partner_request("trae-cli", "/login", native_command="trae-cli")

    assert plan.prompt == ""
    assert plan.handled_output is not None
    assert "原生交互环境" in plan.handled_output
    assert "`trae-cli`" in plan.handled_output


def test_unknown_slash_with_task_stays_plain_task_text() -> None:
    prompt = "/review security\n检查鉴权边界"
    plan = normalize_partner_request("codex-cli", prompt, native_command="codex")

    assert plan.prompt == prompt
    assert plan.handled_output is None


def test_argv_none_for_unknown_or_empty() -> None:
    assert build_partner_argv("openclaw", "openclaw", "do a thing") is None
    assert build_partner_argv("kimi-cli", "kimi", "do a thing") is None
    # CodeBuddy's IDE launcher opens an app chat session and does not provide
    # the documented headless stdout contract; don't treat it as drivable.
    assert (
        build_partner_argv(
            "codebuddy-cli",
            "/Users/me/.codebuddy/bin/buddy",  # lint: allow-user-path
            "x",
        )
        is None
    )
    assert (
        build_partner_argv(
            "codebuddy-cli",
            "/Volumes/CodeBuddy/CodeBuddy.app/Contents/Resources/app/bin/code",
            "x",
        )
        is None
    )
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
    assert seen["argv"] == ["claude", "-p", build_partner_prompt("go")]
    assert seen["cwd"] == "/repo"


def test_run_translates_leading_model_slash_into_argv_model_flag() -> None:
    run, seen = _runner((0, "fixed\n", ""))
    res = run_local_partner(
        partner_id="codex-cli",
        command="codex",
        prompt="/model gpt-5.6-sol\nfix bug",
        cwd="/repo",
        runner=run,
    )

    assert res.ok is True
    assert seen["argv"][:4] == ["codex", "exec", "-m", "gpt-5.6-sol"]
    assert "/model gpt-5.6-sol" not in seen["argv"][-1]
    assert "fix bug" in seen["argv"][-1]
    assert "[Octopus adapter]" in res.output


def test_run_handles_control_only_slash_without_spawning_cli() -> None:
    called = {"n": 0}

    def run(argv, cwd, timeout):
        called["n"] += 1
        return (0, "x", "")

    res = run_local_partner(partner_id="claude-code", command="claude", prompt="/help", runner=run)

    assert res.ok is True
    assert "不是原生交互终端" in res.output
    assert called["n"] == 0


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
    assert res.raw_error == "Error: not logged in"
    assert res.failure_kind == "auth"
    assert "需要登录或授权" in res.failure_title
    assert "原生 CLI" in res.fix_hint


def test_run_exit0_but_empty_output_is_failure() -> None:
    run, _ = _runner((0, "   \n", ""))
    res = run_local_partner(partner_id="claude-code", command="claude", prompt="go", runner=run)
    assert res.ok is False  # exit 0 but nothing to show
    assert res.failure_kind == "empty_output"
    assert "没有返回" in res.error


def test_run_timeout_flagged() -> None:
    run, _ = _runner(subprocess.TimeoutExpired(cmd="claude", timeout=240))
    res = run_local_partner(
        partner_id="claude-code", command="claude", prompt="go", timeout=240, runner=run
    )
    assert res.ok is False
    assert res.timed_out is True
    assert "240s" in res.error
    assert res.failure_kind == "timeout"
    assert "拆小一点" in res.fix_hint


def test_run_missing_binary_reported() -> None:
    run, _ = _runner(FileNotFoundError())
    res = run_local_partner(partner_id="codex-cli", command="codex", prompt="go", runner=run)
    assert res.ok is False
    assert "not installed" in res.error
    assert res.failure_kind == "missing_binary"
    assert "PATH" in res.fix_hint


def test_run_truncates_runaway_output() -> None:
    run, _ = _runner((0, "x" * 50_000, ""))
    res = run_local_partner(partner_id="claude-code", command="claude", prompt="go", runner=run)
    assert res.ok is True
    assert "…(truncated)" in res.output
    assert len(res.output) < 21_000


def test_failure_diagnosis_common_cli_failures() -> None:
    cases = [
        (
            diagnose_partner_failure(
                "trae-cli",
                "trae-cli",
                stderr="no effective model configured",
            ),
            "model",
            "trae-cli models --json",
        ),
        (
            diagnose_partner_failure(
                "codebuddy-cli",
                "codebuddy",
                stderr="Permission denied: untrusted workspace",
            ),
            "permission",
            "信任当前项目",
        ),
        (
            diagnose_partner_failure(
                "trae-cli",
                "trae-cli",
                stderr="curl: Could not resolve host; unable to reach any KDC",
            ),
            "network",
            "DNS/Kerberos/VPN",
        ),
        (
            diagnose_partner_failure(
                "codebuddy-cli",
                "codebuddy",
                stderr="rate limit: quota exhausted, check billing",
            ),
            "quota",
            "额度",
        ),
        (
            diagnose_partner_failure(
                "trae-cli",
                "trae-cli",
                stderr="model access denied: not available for this account",
            ),
            "entitlement",
            "桌面端可用不代表 CLI",
        ),
        (
            diagnose_partner_failure(
                "codebuddy-cli",
                "codebuddy",
                stderr="unknown option --output-format; please upgrade",
            ),
            "version",
            "headless/print 参数",
        ),
    ]
    for diagnosis, kind, hint_part in cases:
        assert diagnosis.kind == kind
        assert hint_part in diagnosis.hint


def test_startup_banner_does_not_forge_a_permission_failure() -> None:
    """Codex prints ``sandbox: read-only`` on every run.

    A bare ``sandbox`` marker matched that banner line, so an unrelated
    upstream model rejection was reported as "权限或工作区信任不足" and sent
    the operator to fix workspace trust instead of model routing.
    """

    real_output = (
        "OpenAI Codex v0.147.0-alpha.6.5\n"
        "workdir: /tmp/octo-wt-x/wt\n"
        "model: gpt-5.6-sol\n"
        "approval: never\n"
        "sandbox: read-only\n"
        'ERROR: {"error":{"message":"CC Switch local proxy failed while handling '
        "Codex endpoint /responses. upstream_status: HTTP 400; cause: The "
        "'gpt-5.6-sol' model is not supported when using Codex with a ChatGPT "
        'account."}}'
    )

    diagnosis = diagnose_partner_failure("codex-cli", "codex", stderr=real_output)

    assert diagnosis.kind == "model"
    assert "模型" in diagnosis.title

    # A genuine sandbox denial must still land on permission.
    denied = diagnose_partner_failure(
        "codex-cli",
        "codex",
        stderr="sandbox: read-only\nSandboxViolation: blocked by sandbox policy",
    )
    assert denied.kind == "permission"


# ── shared-blackboard envelope + env pass-through ────────────────────


def test_run_uses_minimal_env_and_allows_partner_context(monkeypatch) -> None:
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
    # User-shaped paths verify the inherited environment without using the host account.
    monkeypatch.setenv("HOME", "/Users/tester")  # lint: allow-user-path
    monkeypatch.setenv("LANG", "zh_CN.UTF-8")
    monkeypatch.setenv(
        "XDG_CONFIG_HOME",
        "/Users/tester/.config",  # lint: allow-user-path
    )
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-leak")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "must-not-leak")
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.invalid")
    monkeypatch.setenv("PYTHONPATH", "/tmp/injected-python")
    monkeypatch.setenv("NODE_OPTIONS", "--require=/tmp/injected-node.js")
    res = b.run_local_partner(
        partner_id="claude-code",
        command="claude",
        prompt="go",
        env={
            "OCTOPUS_TURN_ID": "t1",
            "OCTOPUS_AGENT_ID": "a1",
            "OCTOPUS_BLACKBOARD_DB": "/tmp/board.db",
        },
    )
    assert res.ok is True
    assert set(captured["env"]) <= (b._INHERITED_ENV_ALLOWLIST | b._PARTNER_CONTEXT_ENV_ALLOWLIST)
    assert {
        "OPENAI_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "HTTPS_PROXY",
        "PYTHONPATH",
        "NODE_OPTIONS",
    }.isdisjoint(captured["env"])
    assert captured["env"]["PATH"] == "/usr/bin"
    assert captured["env"]["HOME"] == "/Users/tester"  # lint: allow-user-path
    assert captured["env"]["LANG"] == "zh_CN.UTF-8"
    assert captured["env"]["XDG_CONFIG_HOME"] == "/Users/tester/.config"  # lint: allow-user-path
    assert captured["env"]["OCTOPUS_TURN_ID"] == "t1"
    assert captured["env"]["OCTOPUS_AGENT_ID"] == "a1"
    assert captured["env"]["OCTOPUS_BLACKBOARD_DB"] == "/tmp/board.db"


def test_run_extra_env_cannot_override_process_context_or_inject_secrets(monkeypatch) -> None:
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
    monkeypatch.setenv("PATH", "/trusted/bin")
    monkeypatch.setenv("HOME", "/trusted/home")
    res = b.run_local_partner(
        partner_id="claude-code",
        command="claude",
        prompt="go",
        env={
            "PATH": "/attacker/bin",
            "HOME": "/attacker/home",
            "OPENAI_API_KEY": "caller-secret",
            "HTTP_PROXY": "http://caller-proxy.invalid",
            "PYTHONPATH": "/tmp/caller-python",
            "NODE_OPTIONS": "--require=/tmp/caller-node.js",
            "OCTOPUS_TURN_ID": "safe-turn",
        },
    )

    assert res.ok is True
    assert captured["env"]["PATH"] == "/trusted/bin"
    assert captured["env"]["HOME"] == "/trusted/home"
    assert captured["env"]["OCTOPUS_TURN_ID"] == "safe-turn"
    assert "OPENAI_API_KEY" not in captured["env"]
    assert "HTTP_PROXY" not in captured["env"]
    assert "PYTHONPATH" not in captured["env"]
    assert "NODE_OPTIONS" not in captured["env"]


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
