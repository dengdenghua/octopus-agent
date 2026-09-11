"""CLI Codex request construction with local protocol notifications."""

import json
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from runtime.cli import main
from runtime.execution.codex_backend import role_runner
from runtime.execution.codex_backend.model_profile import CodexModelPreference
from runtime.execution.codex_backend.types import Notification


@pytest.mark.parametrize(
    "mode,failed",
    [("default", False), ("plan", False), ("bypassPermissions", False), ("default", True)],
)
def test_cli_codex_request_and_resume(tmp_path, monkeypatch, capsys, mode, failed):
    monkeypatch.setenv("OCTOPUS_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(
        "runtime.cli_core._build_stack", Mock(side_effect=AssertionError("native stack"))
    )
    monkeypatch.setattr(role_runner, "require_codex_backend_enabled", lambda: None)
    monkeypatch.setattr(role_runner, "deployment_mode", lambda: "local")
    monkeypatch.setattr(
        role_runner, "state_root_for_workspace", lambda workspace: tmp_path / "state"
    )
    monkeypatch.setattr(
        role_runner, "codex_app_server_command", lambda agent: ("codex", "app-server")
    )
    monkeypatch.setattr(role_runner, "resolve_codex_execution_auth_home", lambda **kwargs: None)
    monkeypatch.setattr(
        role_runner.CodexModelPreferenceStore,
        "read",
        lambda self, scope: CodexModelPreference(mode="chatgpt"),
    )
    requests = []

    @asynccontextmanager
    async def lifecycle(stack, request, **kwargs):
        requests.append(request)
        assert not hasattr(stack, "planner")
        assert request.execution.task.execution_engine == "codex"
        assert request.model == "gpt-5.4"
        assert (
            request.sandbox_mode
            == {
                "default": "workspace-write",
                "plan": "read-only",
                "bypassPermissions": "danger-full-access",
            }[mode]
        )
        assert request.approval_policy == ("never" if mode == "bypassPermissions" else "on-request")
        assert request.dynamic_tools
        assert request.execution.task.resources.remaining_seconds() > 0
        if failed:
            raise RuntimeError("Codex fixture unavailable")
        notifications = iter(
            [
                Notification(
                    method="item/agentMessage/delta",
                    params={"delta": "Codex answer", "itemId": "m"},
                ),
                Notification(method="turn/completed", params={"turn": {"status": "completed"}}),
            ]
        )

        async def start():
            pass

        async def next_notification(**kwargs):
            return next(notifications)

        yield SimpleNamespace(
            session=SimpleNamespace(start=start, next_notification=next_notification)
        )

    monkeypatch.setattr(role_runner, "codex_execution_lifecycle", lifecycle)
    options = ["--cwd", str(tmp_path), "--permission-mode", mode, "--output-format", "json"]
    assert main(["code", "hello", "--engine", "codex", "--model", "gpt-5.4", *options]) == (
        1 if failed else 0
    )
    first = json.loads(capsys.readouterr().out)
    assert first["execution_engine"] == "codex"
    if failed:
        saved = json.loads(Path(first["session_path"]).read_text(encoding="utf-8"))
        assert saved["last_result"] == {
            "success": False,
            "terminated_reason": "Codex fixture unavailable",
        }
        assert len(requests) == 1
        return
    assert first["final_answer"] == "Codex answer"
    assert main(["code", "continue discussion", "--resume", first["session_id"], *options]) == 0
    saved = json.loads(Path(first["session_path"]).read_text(encoding="utf-8"))
    assert saved["model"] == "gpt-5.4"
    assert saved["last_result"]["success"] is True
    assert "Codex answer" in requests[1].prompt
    assert requests[1].execution.task.authorization_intent == "continue discussion"
