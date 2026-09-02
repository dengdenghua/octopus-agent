from __future__ import annotations

from pathlib import Path

import tools.dev_stack as dev_stack


def test_job_specs_pin_standard_ports_and_restart_policy(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "repo"
    (root / ".venv" / "bin").mkdir(parents=True)
    (root / ".venv" / "bin" / "python").write_text("", encoding="utf-8")
    (root / "config.local.yaml").write_text("planner: llm", encoding="utf-8")
    (root / "frontend").mkdir()
    monkeypatch.setattr(dev_stack, "_pnpm_path", lambda: "/mock/pnpm")

    specs = dev_stack.build_job_specs(root, tmp_path / "state")

    backend = specs["backend"]
    frontend = specs["frontend"]
    assert backend["ProgramArguments"][0] == str(root / ".venv" / "bin" / "python")
    assert backend["ProgramArguments"][-2:] == ["--port", "8888"]
    assert frontend["EnvironmentVariables"]["FRONTEND_PORT"] == "3888"
    assert frontend["EnvironmentVariables"]["GATEWAY_PORT"] == "8888"
    assert backend["KeepAlive"] == {"SuccessfulExit": False}
    assert frontend["KeepAlive"] == {"SuccessfulExit": False}
    assert backend["WorkingDirectory"] == str(root)
    assert frontend["WorkingDirectory"] == str(root / "frontend")


def test_status_requires_launchd_registration_and_open_port(monkeypatch) -> None:
    class Result:
        returncode = 0

    monkeypatch.setattr(dev_stack, "_run", lambda *args, **kwargs: Result())
    monkeypatch.setattr(dev_stack, "_port_open", lambda port: port == 3888)

    assert dev_stack.status() == 1
