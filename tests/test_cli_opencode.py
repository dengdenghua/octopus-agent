"""CLI external execution uses the real host task and persisted conversation."""

import json
from asyncio import CancelledError
from pathlib import Path
from unittest.mock import Mock

import pytest

from runtime.cli import main


@pytest.fixture(autouse=True)
def no_startup_skill_download(monkeypatch):
    bootstrap = Mock(side_effect=AssertionError("CLI task attempted skill download"))
    monkeypatch.setattr("octopus_runtime.bootstrap_skills", bootstrap)
    yield
    bootstrap.assert_not_called()


@pytest.mark.parametrize("mode", ["default", "plan", "bypassPermissions"])
def test_cli_external_task_permissions_and_resume(tmp_path, monkeypatch, capsys, mode):
    monkeypatch.setenv("OCTOPUS_HOME", str(tmp_path / "home"))
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setattr(
        "runtime.cli_core._build_stack", Mock(side_effect=AssertionError("native stack"))
    )
    monkeypatch.setattr(
        "runtime.execution.opencode_backend.zen_catalog",
        lambda: {"opencode-zen": {"managed_by_plugin": "opencode-zen", "models": ["big-pickle"]}},
    )
    calls = []

    async def stream(stack, agent, **kwargs):
        assert not hasattr(stack, "planner")
        task = kwargs["request"].task
        assert task.execution_engine == "opencode"
        assert task.permissions.allows_read(workspace)
        assert task.permissions.allows_read(tmp_path / "outside") is (mode == "bypassPermissions")
        assert task.permissions.allows_write(workspace / "output.txt") is (mode != "plan")
        assert task.server_auto_approve is (mode == "bypassPermissions")
        assert task.permissions.approval_policy == (
            "never" if mode == "bypassPermissions" else "on-request"
        )
        assert task.authorization_intent == ("hello" if not calls else "continue discussion")
        assert kwargs["session"].metadata["_execution_task"] is task
        assert task.resources.remaining_seconds() > 0
        calls.append(kwargs)
        yield {"type": "text_delta", "delta": "External answer"}
        yield {"type": "react_completed", "success": True}

    monkeypatch.setattr("runtime.execution.opencode_roles.stream_role", stream)
    options = ["--cwd", str(workspace), "--permission-mode", mode, "--output-format", "json"]
    assert main(["code", "hello", *options]) == 0
    first = json.loads(capsys.readouterr().out)
    assert first["execution_engine"] == "opencode"
    assert first["final_answer"] == "External answer"
    assert main(["code", "continue discussion", "--resume", first["session_id"], *options]) == 0
    second = json.loads(capsys.readouterr().out)
    assert second["session_id"] == first["session_id"]
    assert "External answer" in calls[1]["text"]
    assert calls[0]["request"].task.task_id != calls[1]["request"].task.task_id
    saved = json.loads(
        (tmp_path / "home" / "sessions" / (first["session_id"] + ".json")).read_text()
    )
    assert saved["execution_engine"] == "opencode"
    assert saved["last_result"]["success"] is True


@pytest.mark.parametrize(
    "error,reason",
    [(RuntimeError("engine unavailable"), "engine unavailable"), (CancelledError(), "interrupted")],
)
def test_cli_external_failure_is_saved_without_native_fallback(
    tmp_path, monkeypatch, capsys, error, reason
):
    monkeypatch.setenv("OCTOPUS_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(
        "runtime.cli_core._build_stack", Mock(side_effect=AssertionError("native fallback"))
    )
    monkeypatch.setattr(
        "runtime.execution.opencode_backend.zen_catalog",
        lambda: {"opencode-zen": {"managed_by_plugin": "opencode-zen", "models": ["big-pickle"]}},
    )

    async def stream(*args, **kwargs):
        raise error
        yield  # pragma: no cover

    monkeypatch.setattr("runtime.execution.opencode_roles.stream_role", stream)
    assert main(["code", "hello", "--cwd", str(tmp_path), "--output-format", "json"]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["success"] is False
    saved = json.loads(Path(result["session_path"]).read_text(encoding="utf-8"))
    assert saved["last_result"]["terminated_reason"] == reason
