from __future__ import annotations

import json
import subprocess

from benchmarks import codex_cli_runner


def test_codex_cli_runner_uses_ephemeral_json_without_shell(monkeypatch, tmp_path) -> None:
    captured: dict[str, object] = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured.update(kwargs)
        stdout = "\n".join(
            [
                json.dumps(
                    {
                        "type": "item.completed",
                        "item": {"type": "agent_message", "text": "done"},
                    }
                ),
                json.dumps(
                    {
                        "type": "item.started",
                        "item": {"type": "command_execution", "command": "pwd"},
                    }
                ),
            ]
        )
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(codex_cli_runner.subprocess, "run", fake_run)
    runner = codex_cli_runner.CodexCliTrialRunner(
        executable="/opt/codex",
        workspace=tmp_path,
        model="gpt-test",
        ignore_user_config=True,
    )

    events = list(runner("do work"))

    command = captured["command"]
    assert isinstance(command, list)
    assert command[:2] == ["/opt/codex", "exec"]
    assert "--json" in command
    assert "--ephemeral" in command
    assert "--ignore-user-config" in command
    assert command[-1] == "-"
    assert captured["input"] == "do work"
    assert "shell" not in captured
    assert {"kind": "text_delta", "delta": "done"} in events
    assert any(event["kind"] == "tool_start" for event in events)


def test_codex_cli_runner_records_nonzero_exit(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        codex_cli_runner.subprocess,
        "run",
        lambda command, **kwargs: subprocess.CompletedProcess(
            command,
            7,
            stdout="",
            stderr="provider failed",
        ),
    )

    events = list(
        codex_cli_runner.CodexCliTrialRunner(
            executable="codex",
            workspace=tmp_path,
        )("work")
    )

    assert events == [
        {
            "kind": "error",
            "error": {"returncode": 7, "stderr": "provider failed"},
        }
    ]
