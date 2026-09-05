"""Persistent macOS development stack manager.

The ordinary Vite/backend commands inherit the terminal's process group.  In
Codex and other short-lived terminals that means both services disappear when
the terminal is reclaimed.  This tool registers per-user launchd jobs instead,
so the services survive terminal/chat lifetimes and are restarted after an
unexpected exit.
"""

from __future__ import annotations

import argparse
import os
import plistlib
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

BACKEND_LABEL = "com.echoage.octopus.dev.backend"
FRONTEND_LABEL = "com.echoage.octopus.dev.frontend"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _state_dir() -> Path:
    override = os.environ.get("OCTOPUS_DEV_STACK_STATE", "").strip()
    return (
        Path(override).expanduser()
        if override
        else Path.home() / ".local" / "state" / "octopus-agent-dev"
    )


def _launch_domain() -> str:
    return f"gui/{os.getuid()}"


def _pnpm_path() -> str:
    path = shutil.which("pnpm")
    if not path:
        raise RuntimeError("pnpm not found; install frontend dependencies first")
    return str(Path(path).resolve())


def build_job_specs(root: Path, state: Path) -> dict[str, dict[str, Any]]:
    """Build launchd job dictionaries without writing or registering them."""

    python = root / ".venv" / "bin" / "python"
    if not python.is_file():
        raise RuntimeError(f"project Python not found: {python}")
    if not (root / "config.local.yaml").is_file():
        raise RuntimeError("config.local.yaml not found")
    frontend = root / "frontend"
    if not frontend.is_dir():
        raise RuntimeError(f"frontend directory not found: {frontend}")

    base_env = {
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "PYTHONUNBUFFERED": "1",
    }
    common: dict[str, Any] = {
        "RunAtLoad": True,
        "KeepAlive": {"SuccessfulExit": False},
        "ProcessType": "Interactive",
        "ThrottleInterval": 2,
    }
    return {
        "backend": {
            **common,
            "Label": BACKEND_LABEL,
            "ProgramArguments": [
                # Keep the venv entry path intact. Resolving this symlink to
                # the uv-managed base interpreter discards pyvenv.cfg and the
                # service starts without project dependencies.
                str(python),
                "-m",
                "runtime",
                "serve",
                "--config",
                "config.local.yaml",
                "--port",
                "8888",
            ],
            "WorkingDirectory": str(root),
            "EnvironmentVariables": base_env,
            "StandardOutPath": str(state / "backend.log"),
            "StandardErrorPath": str(state / "backend.log"),
        },
        "frontend": {
            **common,
            "Label": FRONTEND_LABEL,
            "ProgramArguments": [_pnpm_path(), "dev", "--host", "127.0.0.1"],
            "WorkingDirectory": str(frontend),
            "EnvironmentVariables": {
                **base_env,
                "FRONTEND_PORT": "3888",
                "GATEWAY_PORT": "8888",
            },
            "StandardOutPath": str(state / "frontend.log"),
            "StandardErrorPath": str(state / "frontend.log"),
        },
    }


def _plist_paths(state: Path) -> dict[str, Path]:
    return {"backend": state / "backend.plist", "frontend": state / "frontend.plist"}


def _run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, check=check, text=True, capture_output=True)


def _bootout(label: str) -> None:
    _run("launchctl", "bootout", f"{_launch_domain()}/{label}", check=False)
    # launchd tears jobs down asynchronously. Re-registering the same label in
    # the small window after bootout returns produces Bootstrap error 5.
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        probe = _run("launchctl", "print", f"{_launch_domain()}/{label}", check=False)
        if probe.returncode != 0:
            return
        time.sleep(0.1)


def _port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.4)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def start() -> int:
    if sys.platform != "darwin":
        raise RuntimeError("persistent dev-stack management currently requires macOS launchd")
    root = _repo_root()
    state = _state_dir()
    state.mkdir(parents=True, exist_ok=True)
    specs = build_job_specs(root, state)
    paths = _plist_paths(state)

    for name, spec in specs.items():
        path = paths[name]
        with path.open("wb") as handle:
            plistlib.dump(spec, handle, sort_keys=True)
        _bootout(str(spec["Label"]))
        result = _run("launchctl", "bootstrap", _launch_domain(), str(path), check=False)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            raise RuntimeError(f"failed to start {name}: {detail}")

    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if _port_open(8888) and _port_open(3888):
            print("dev stack ready: frontend http://127.0.0.1:3888 · backend http://127.0.0.1:8888")
            return 0
        time.sleep(0.25)
    raise RuntimeError(f"services did not become ready; inspect logs in {state}")


def stop() -> int:
    for label in (FRONTEND_LABEL, BACKEND_LABEL):
        _bootout(label)
    print("dev stack stopped")
    return 0


def status() -> int:
    services = (("frontend", 3888, FRONTEND_LABEL), ("backend", 8888, BACKEND_LABEL))
    all_ready = True
    for name, port, label in services:
        loaded = _run("launchctl", "print", f"{_launch_domain()}/{label}", check=False)
        ready = loaded.returncode == 0 and _port_open(port)
        all_ready = all_ready and ready
        print(f"{name}: {'ready' if ready else 'stopped'} · 127.0.0.1:{port}")
    return 0 if all_ready else 1


def logs(lines: int) -> int:
    state = _state_dir()
    for name in ("backend", "frontend"):
        path = state / f"{name}.log"
        print(f"\n== {name} ==")
        if not path.is_file():
            print("no log yet")
            continue
        content = path.read_text(encoding="utf-8", errors="replace").splitlines()
        print("\n".join(content[-max(1, lines) :]))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage the persistent local dev stack")
    parser.add_argument("action", choices=("start", "stop", "restart", "status", "logs"))
    parser.add_argument("--lines", type=int, default=60)
    args = parser.parse_args()
    try:
        if args.action == "start":
            return start()
        if args.action == "stop":
            return stop()
        if args.action == "restart":
            stop()
            return start()
        if args.action == "logs":
            return logs(args.lines)
        return status()
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
