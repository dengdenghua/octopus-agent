"""Pre-execution selection is deterministic, scoped and performs no model call."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from runtime.execution.codex_backend import readiness
from runtime.execution.codex_backend.model_profile import (
    CodexModelPreference,
    resolve_codex_execution_profile,
)
from runtime.execution.codex_backend.types import ConfigurationError
from runtime.execution.engines import EngineId, EngineSelectionError
from runtime.platform.models import ParsedIntent
from runtime.protocol import Turn
from runtime.protocol.items import TurnParams
from runtime.sensing.gateway.realtime_execution import (
    codex_readiness_for_turn,
    is_coding_task,
    select_turn_execution,
)


@pytest.fixture()
def configured_codex(monkeypatch):
    command = Mock(return_value=("codex", "app-server", "--listen", "stdio://"))
    monkeypatch.setattr(readiness, "resolution", lambda _name: (True, "env"))
    monkeypatch.setattr(readiness, "resolve_codex_app_server_command", command)
    monkeypatch.setattr(
        "runtime.execution.codex_backend.role_runner.require_codex_backend_enabled", lambda: None
    )
    return resolve_codex_execution_profile(preference=CodexModelPreference(mode="chatgpt")), command


def test_readiness_checks_configuration_without_starting_or_refreshing(configured_codex):
    profile, command = configured_codex
    auth = Mock(return_value=Path("managed-home"))
    assert readiness.inspect_codex_readiness(profile, auth_source=auth).available
    command.assert_called_once_with()
    auth.assert_called_once_with()


def test_proxy_profile_needs_no_codex_account(configured_codex):
    profile, _ = configured_codex
    auth = Mock(side_effect=AssertionError("proxy must not read account credentials"))
    assert readiness.inspect_codex_readiness(
        replace(profile, proxy_required=True), auth_source=auth
    ).available
    auth.assert_not_called()


def test_missing_shared_tools_prevents_account_access(configured_codex):
    profile, _ = configured_codex
    auth = Mock(side_effect=AssertionError("tools are unavailable"))
    result = readiness.inspect_codex_readiness(profile, auth_source=auth, tools_available=False)
    assert result.reason == "tools_unavailable"
    auth.assert_not_called()


@pytest.mark.parametrize(
    "problem",
    [
        "disabled",
        "executable_unavailable",
        "model_incompatible",
        "account_required",
        "account_unavailable",
    ],
)
def test_readiness_explains_unavailable_configuration(configured_codex, monkeypatch, problem):
    profile, command = configured_codex
    auth = Mock(return_value=Path("managed-home"))
    if problem == "disabled":
        monkeypatch.setattr(readiness, "resolution", lambda _name: (False, "env"))
    elif problem == "executable_unavailable":
        command.side_effect = ConfigurationError("missing executable")
    elif problem == "model_incompatible":
        profile = replace(profile, compatible=False)
    elif problem == "account_required":
        auth.return_value = None
    else:
        auth.side_effect = OSError("unreadable auth")
    result = readiness.inspect_codex_readiness(profile, auth_source=auth)
    assert not result.available
    assert result.reason == problem
    if problem not in {"account_required", "account_unavailable"}:
        auth.assert_not_called()


@pytest.mark.parametrize(
    ("context", "intent_type", "coding"),
    [
        ({}, "task", False),
        ({"mode": "code"}, "task", True),
        ({"capability_mode": "code"}, "task", True),
        ({"personal_mode": "build"}, "task", True),
        ({"mode": "code", "personal_mode": "general"}, "task", False),
        ({"capability_mode": "code", "personal_mode": "research"}, "task", False),
        ({"personal_mode": "general"}, "debug", True),
        ({}, "refactor", True),
    ],
)
def test_work_purpose_is_distinct_from_available_tools(context, intent_type, coding):
    intent = ParsedIntent(
        raw="task", normalized_goal="task", intent_type=intent_type, user_context=context
    )
    assert is_coding_task(intent) is coding


@pytest.mark.parametrize(
    ("preference", "role_codex", "ready", "engine", "reason"),
    [
        ("auto", False, True, "codex", "coding_task"),
        ("auto", False, False, "octopus", "codex_unavailable:account_required"),
        ("auto", True, False, None, "account_required"),
        ("codex", False, False, None, "account_required"),
        ("codex", False, True, "codex", "explicit_engine"),
        ("octopus", True, False, "octopus", "explicit_engine"),
    ],
)
def test_engine_selection_falls_back_only_before_effects_and_only_for_auto(
    monkeypatch, preference, role_codex, ready, engine, reason
):
    preflight = Mock(
        return_value=readiness.CodexReadiness(ready, None if ready else "account_required")
    )
    monkeypatch.setattr(
        "runtime.sensing.gateway.realtime_execution.codex_readiness_for_turn", preflight
    )
    turn = Turn(threadId="thread", params=TurnParams(threadId="thread", executionEngine=preference))
    intent = ParsedIntent(raw="task", normalized_goal="task", intent_type="debug")
    request = select_turn_execution(
        object(),
        turn,
        object(),
        intent,
        project_command=False,
        group_fanout=False,
        topology_id=None,
        codex_partner=role_codex,
        reflection_fast_path=False,
    )
    if engine is None:
        with pytest.raises(EngineSelectionError) as caught:
            asyncio.run(request)
        assert caught.value.reason == reason
    else:
        route = asyncio.run(request)
        assert route.engine == EngineId(engine)
        assert route.reason == reason
    assert turn.execution is None  # Selection is not an execution receipt.
    if preference == "octopus":
        preflight.assert_not_called()


def test_preflight_uses_trusted_workspace_and_principal(configured_codex, tmp_path, monkeypatch):
    from runtime.execution.codex_backend import role_runner

    profile, _ = configured_codex
    state_root = Mock(return_value=tmp_path / "state")
    auth = Mock(return_value=tmp_path / "managed")
    monkeypatch.setattr(role_runner, "state_root_for_workspace", state_root)
    monkeypatch.setattr(role_runner, "_execution_profile", lambda *_a, **_k: profile)
    monkeypatch.setattr(role_runner, "source_codex_home", lambda: None)
    monkeypatch.setattr(
        "runtime.execution.codex_backend.account.resolve_codex_execution_auth_home", auth
    )
    turn = Turn(
        threadId="thread",
        params=TurnParams(
            threadId="thread",
            owner_actor_id="alice",
            tenant_id="tenant-a",
            input=[
                {
                    "type": "text",
                    "text": "task",
                    "metadata": {
                        "context": {
                            "cwd": "attacker-path",
                            "owner_actor_id": "mallory",
                            "tenant_id": "tenant-b",
                        }
                    },
                }
            ],
        ),
    )
    host = SimpleNamespace(_stack=SimpleNamespace(executor=SimpleNamespace(registry=object())))
    assert codex_readiness_for_turn(host, turn, object()).reason == "workspace_required"
    state_root.assert_not_called()
    turn.execution_workspace_path = str(tmp_path)
    assert codex_readiness_for_turn(host, turn, object()).available
    state_root.assert_called_once_with(tmp_path)
    scope = auth.call_args.kwargs["scope"]
    assert (scope.actor_id, scope.tenant_id) == ("alice", "tenant-a")
    assert not (tmp_path / "state").exists()  # A status check must not provision state.
