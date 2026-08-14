"""Subagent multi-provider backend tests — dsh provider vocabulary port."""

from __future__ import annotations

from pathlib import Path

import pytest

from runtime.execution.subagents import bridge
from runtime.execution.subagents.registry import (
    SubagentDefinition,
    SubagentRegistry,
    load_subagent_file,
)


def _definition(**overrides: object) -> SubagentDefinition:
    base: dict[str, object] = {
        "name": "code_reviewer",
        "description": "reviews code",
        "system_prompt": "You review code.",
    }
    base.update(overrides)
    return SubagentDefinition(**base)  # type: ignore[arg-type]


def test_frontmatter_backend_parsed(tmp_path: Path) -> None:
    path = tmp_path / "reviewer.md"
    path.write_text(
        "---\nname: reviewer\ndescription: reviews code\nbackend: codex-cli\n---\nBody",
        encoding="utf-8",
    )
    definition = load_subagent_file(path, scope="project")
    assert definition.backend == "codex-cli"
    assert definition.to_wire()["backend"] == "codex-cli"


def test_frontmatter_backend_absent() -> None:
    definition = _definition()
    assert definition.backend is None
    assert definition.to_wire()["backend"] is None


def test_dispatch_partner_success(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []

    def _which(commands: list[str]) -> tuple[str | None, str | None]:
        return "codex", "/usr/bin/codex"

    def _run(**kw: object) -> object:
        calls.append(kw)

        class Result:
            ok = True
            output = "partner answer"
            error = ""
            raw_error = ""
            unsupported = False
            failure_kind = None
            timed_out = False

        return Result()

    monkeypatch.setattr("runtime.execution.agents.local_partner_discovery.which_command", _which)
    monkeypatch.setattr("runtime.execution.agents.local_partner_bridge.run_local_partner", _run)
    result = bridge._dispatch_partner(_definition(backend="codex-cli"), "do it", 120)
    assert result is not None
    assert result["success"] is True
    assert result["output"] == "partner answer"
    assert result["backend"] == "codex-cli"
    assert result["command"] == "codex"
    assert calls[0]["partner_id"] == "codex-cli"
    assert calls[0]["timeout"] == 120.0


def test_dispatch_partner_agent_id_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    def _which(commands: list[str]) -> tuple[str | None, str | None]:
        return "claude", "/usr/bin/claude"

    def _run(**kw: object) -> object:
        class Result:
            ok = True
            output = "x"
            error = ""
            raw_error = ""
            unsupported = False
            failure_kind = None
            timed_out = False

        return Result()

    monkeypatch.setattr("runtime.execution.agents.local_partner_discovery.which_command", _which)
    monkeypatch.setattr("runtime.execution.agents.local_partner_bridge.run_local_partner", _run)
    result = bridge._dispatch_partner(_definition(backend="local_claude_code"), "do it", 60)
    assert result is not None
    assert result["backend"] == "claude-code"


def test_dispatch_partner_failure_mapping(monkeypatch: pytest.MonkeyPatch) -> None:
    def _which(commands: list[str]) -> tuple[str | None, str | None]:
        return "codex", "/usr/bin/codex"

    def _run(**kw: object) -> object:
        class Result:
            ok = False
            output = "partial"
            error = "exit 1"
            raw_error = "boom"
            unsupported = False
            failure_kind = "non_zero_exit"
            timed_out = False

        return Result()

    monkeypatch.setattr("runtime.execution.agents.local_partner_discovery.which_command", _which)
    monkeypatch.setattr("runtime.execution.agents.local_partner_bridge.run_local_partner", _run)
    result = bridge._dispatch_partner(_definition(backend="codex-cli"), "do it", 60)
    assert result is not None
    assert result["success"] is False
    assert result["error"] == "exit 1"
    assert result["failure_kind"] == "non_zero_exit"
    assert result["output"] == "partial"


def test_dispatch_partner_unsupported_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    def _which(commands: list[str]) -> tuple[str | None, str | None]:
        return "kimi", "/usr/bin/kimi"

    def _run(**kw: object) -> object:
        class Result:
            ok = False
            output = ""
            error = "no headless"
            raw_error = ""
            unsupported = True
            failure_kind = None
            timed_out = False

        return Result()

    monkeypatch.setattr("runtime.execution.agents.local_partner_discovery.which_command", _which)
    monkeypatch.setattr("runtime.execution.agents.local_partner_bridge.run_local_partner", _run)
    assert bridge._dispatch_partner(_definition(backend="kimi-cli"), "do it", 60) is None


def test_dispatch_partner_unknown_backend() -> None:
    result = bridge._dispatch_partner(_definition(backend="nope-cli"), "do it", 60)
    assert result is not None
    assert result["success"] is False
    assert "unknown subagent backend" in result["error"]


def test_dispatch_partner_missing_executable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "runtime.execution.agents.local_partner_discovery.which_command",
        lambda commands: (None, None),
    )
    result = bridge._dispatch_partner(_definition(backend="codex-cli"), "do it", 60)
    assert result is not None
    assert result["success"] is False
    assert "executable not found" in result["error"]


def test_call_subagent_routes_to_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "runtime.execution.agents.local_partner_discovery.which_command",
        lambda commands: ("codex", "/usr/bin/codex"),
    )

    def _run(**kw: object) -> object:
        class Result:
            ok = True
            output = "from codex"
            error = ""
            raw_error = ""
            unsupported = False
            failure_kind = None
            timed_out = False

        return Result()

    monkeypatch.setattr("runtime.execution.agents.local_partner_bridge.run_local_partner", _run)
    previous = bridge.get_subagent_registry()
    try:
        bridge.set_subagent_registry(SubagentRegistry([_definition(backend="codex-cli")]))
        result = bridge.call_subagent(agent_id="code_reviewer", prompt="check it")
    finally:
        bridge.set_subagent_registry(previous)
    assert result["success"] is True
    assert result["output"] == "from codex"
    assert result["backend"] == "codex-cli"


def test_call_subagent_unsupported_backend_falls_back_in_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from runtime.execution.suckers.ephemeral_agents import (
        get_ephemeral_role_runner,
        set_ephemeral_role_runner,
    )

    def _which(commands: list[str]) -> tuple[str | None, str | None]:
        return "kimi", "/usr/bin/kimi"

    def _run(**kw: object) -> object:
        class Result:
            ok = False
            output = ""
            error = "no headless"
            raw_error = ""
            unsupported = True
            failure_kind = None
            timed_out = False

        return Result()

    monkeypatch.setattr("runtime.execution.agents.local_partner_discovery.which_command", _which)
    monkeypatch.setattr("runtime.execution.agents.local_partner_bridge.run_local_partner", _run)
    seen: list[str] = []

    def runner(call: object) -> str:
        seen.append("in-process")
        return "fallback answer"

    previous_runner = get_ephemeral_role_runner()
    previous_registry = bridge.get_subagent_registry()
    try:
        set_ephemeral_role_runner(runner)
        bridge.set_subagent_registry(SubagentRegistry([_definition(backend="kimi-cli")]))
        result = bridge.call_subagent(agent_id="code_reviewer", prompt="do it")
    finally:
        set_ephemeral_role_runner(previous_runner)
        bridge.set_subagent_registry(previous_registry)
    assert seen == ["in-process"]
    assert result["success"] is True
    assert result["output"] == "fallback answer"
