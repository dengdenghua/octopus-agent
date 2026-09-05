"""Run or record the two-engine unified-runtime acceptance scenarios.

The live mode sends one coding task to Codex and one document task to native
Octopus through the production realtime gateway.  A reuse mode turns retained
event logs into the same compact, reviewable evidence without repeating paid
model calls.
"""

from __future__ import annotations

import argparse
import ast
import asyncio
import hashlib
import json
import os
import subprocess
import sys
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import httpx

from benchmarks.realtime_runner import RealtimeTrialRunner, probe_realtime_endpoint

SCHEMA = "octopus.unified_runtime_acceptance.v1"
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / "benchmarks" / "results" / "unified-runtime-acceptance.json"
DEFAULT_RUNS_ROOT = REPO_ROOT / "benchmarks" / "results" / "unified-runtime-runs"
CALCULATOR_NAME = "calculator.py"
DOCUMENT_NAME = "acceptance.docx"
DOCUMENT_TITLE = "Unified Runtime Acceptance"
DOCUMENT_BODY = "Native engine plugin execution verified."
PluginState = Literal["loaded", "unloaded", "unknown"]


@dataclass(frozen=True, slots=True)
class AcceptanceInputs:
    codex_events: Path
    codex_workspace: Path
    native_events: Path
    native_workspace: Path
    plugin_before: dict[str, Any]
    plugin_after: dict[str, Any]
    source: str


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    reused = [
        args.reuse_codex_events,
        args.reuse_codex_workspace,
        args.reuse_native_events,
        args.reuse_native_workspace,
    ]
    if any(reused) and not all(reused):
        raise SystemExit("all four --reuse-* paths are required together")

    inputs = _reuse_inputs(args) if all(reused) else asyncio.run(_run_live(args))
    report = _build_report(inputs)
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "schema": report["schema"],
                "passed": report["passed"],
                "output": str(output),
                "codex_seconds": report["scenarios"]["codex_coding"]["duration_seconds"],
                "native_seconds": report["scenarios"]["native_document"]["duration_seconds"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report["passed"] else 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--ws-url", default=None)
    parser.add_argument("--local-username", default="local")
    parser.add_argument("--token-env", default="OCTOPUS_TOKEN")
    parser.add_argument("--native-model", default="chatgpt/gpt-5.6-sol")
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument("--runs-root", type=Path, default=DEFAULT_RUNS_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--reuse-codex-events", type=Path)
    parser.add_argument("--reuse-codex-workspace", type=Path)
    parser.add_argument("--reuse-native-events", type=Path)
    parser.add_argument("--reuse-native-workspace", type=Path)
    parser.add_argument(
        "--plugin-before",
        choices=("loaded", "unloaded", "unknown"),
        default="unknown",
        help="documents plugin state observed before an imported native trajectory",
    )
    parser.add_argument(
        "--plugin-after",
        choices=("loaded", "unloaded", "unknown"),
        default="unknown",
        help="documents plugin state observed after an imported native trajectory",
    )
    return parser


def _reuse_inputs(args: argparse.Namespace) -> AcceptanceInputs:
    return AcceptanceInputs(
        codex_events=args.reuse_codex_events.resolve(),
        codex_workspace=args.reuse_codex_workspace.resolve(),
        native_events=args.reuse_native_events.resolve(),
        native_workspace=args.reuse_native_workspace.resolve(),
        plugin_before=_imported_plugin_state(args.plugin_before),
        plugin_after=_imported_plugin_state(args.plugin_after),
        source="retained_live_trajectories",
    )


async def _run_live(args: argparse.Namespace) -> AcceptanceInputs:
    base_url = args.base_url.rstrip("/")
    ws_url = args.ws_url or _realtime_url(base_url)
    token = os.environ.get(args.token_env) or _local_token(base_url, args.local_username)
    await probe_realtime_endpoint(ws_url, token=token, timeout_seconds=min(args.timeout, 10.0))

    run_root = (args.runs_root / f"acceptance-{uuid.uuid4().hex}").resolve()
    codex_workspace = run_root / "codex"
    native_workspace = run_root / "native"
    codex_workspace.mkdir(parents=True)
    native_workspace.mkdir(parents=True)
    _write_broken_calculator(codex_workspace / CALCULATOR_NAME)

    plugin_before = _plugin_state(base_url, token, "documents")
    codex_events = await _run_codex(ws_url, token, codex_workspace, args.timeout)
    native_events = await _run_native(
        ws_url,
        token,
        native_workspace,
        args.native_model,
        args.timeout,
    )
    plugin_after = _plugin_state(base_url, token, "documents")

    codex_events_path = run_root / "codex-events.json"
    native_events_path = run_root / "native-events.json"
    _write_events(codex_events_path, codex_events)
    _write_events(native_events_path, native_events)
    return AcceptanceInputs(
        codex_events=codex_events_path,
        codex_workspace=codex_workspace,
        native_events=native_events_path,
        native_workspace=native_workspace,
        plugin_before=plugin_before,
        plugin_after=plugin_after,
        source="live_gateway_run",
    )


async def _run_codex(
    ws_url: str,
    token: str,
    workspace: Path,
    timeout: float,
) -> list[dict[str, Any]]:
    target = (workspace / CALCULATOR_NAME).resolve()
    runner = RealtimeTrialRunner(
        url=ws_url,
        token=token,
        agent_id="coder",
        execution_engine="codex",
        workspace=workspace,
        context_overrides={"allowed_write_paths": [CALCULATOR_NAME]},
        sandbox_policy={"type": "workspaceWrite", "networkAccess": False},
        approval_policy="on-request",
        approval_responder=_codex_approval_responder(workspace, target),
        timeout_seconds=timeout,
    )
    return await runner.run(
        "In this isolated workspace, fix the bug in calculator.py so clamp(value, low, high) "
        "returns low below the range, high above it, and the original value inside it. Preserve "
        "the public signature and ValueError behavior. Modify only calculator.py, use no network, "
        "and verify the implementation."
    )


async def _run_native(
    ws_url: str,
    token: str,
    workspace: Path,
    model: str,
    timeout: float,
) -> list[dict[str, Any]]:
    target = (workspace / DOCUMENT_NAME).resolve()
    runner = RealtimeTrialRunner(
        url=ws_url,
        token=token,
        agent_id="general",
        execution_engine="octopus",
        model=model,
        workspace=workspace,
        context_overrides={
            "mode": "code",
            "capability_mode": "general",
            "allowed_write_paths": [DOCUMENT_NAME],
        },
        sandbox_policy={"type": "workspaceWrite", "networkAccess": False},
        approval_policy="on-request",
        approval_responder=_native_approval_responder(workspace, target),
        timeout_seconds=timeout,
    )
    return await runner.run(
        "Use @plugin:documents and call documents.create_docx to create acceptance.docx "
        "in the current workspace. The document title must be 'Unified Runtime Acceptance' "
        "and it must contain a paragraph with the exact text "
        "'Native engine plugin execution verified.'. Do not use shell or Python tools, do not "
        "write any other file, and finish only after the document tool succeeds."
    )


def _build_report(inputs: AcceptanceInputs) -> dict[str, Any]:
    codex = _scenario_report(
        name="codex_coding",
        event_path=inputs.codex_events,
        workspace=inputs.codex_workspace,
        expected_engine="codex",
        expected_driver="codex_app_server",
        artifact_validator=_validate_calculator,
        approval_responder=_codex_approval_responder(
            inputs.codex_workspace,
            (inputs.codex_workspace / CALCULATOR_NAME).resolve(),
        ),
    )
    native = _scenario_report(
        name="native_document",
        event_path=inputs.native_events,
        workspace=inputs.native_workspace,
        expected_engine="octopus",
        expected_driver="react",
        artifact_validator=_validate_document,
        approval_responder=_native_approval_responder(
            inputs.native_workspace,
            (inputs.native_workspace / DOCUMENT_NAME).resolve(),
        ),
    )
    plugin_transition = {
        "before": inputs.plugin_before,
        "after": inputs.plugin_after,
        "passed": (
            inputs.plugin_before.get("loaded") is False
            and inputs.plugin_before.get("started") is False
            and inputs.plugin_after.get("loaded") is True
            and inputs.plugin_after.get("started") is True
        ),
    }
    checks = {
        "codex_task_passed": codex["passed"],
        "native_task_passed": native["passed"],
        "optional_plugin_loaded_on_demand": plugin_transition["passed"],
        "one_host_receipt_per_task": (
            codex["checks"]["single_engine_binding"] and native["checks"]["single_engine_binding"]
        ),
        "no_cross_engine_transfer_after_start": (
            codex["checks"]["no_cross_engine_transfer"]
            and native["checks"]["no_cross_engine_transfer"]
        ),
    }
    return {
        "schema": SCHEMA,
        "generated_at": datetime.now(UTC).isoformat(),
        "source": inputs.source,
        "repository": _repository_state(),
        "passed": all(checks.values()),
        "checks": checks,
        "plugin_transition": plugin_transition,
        "scenarios": {"codex_coding": codex, "native_document": native},
        "measurement_notes": {
            "cost_usd": None,
            "cost_source": "not_reported",
            "native_token_usage": (
                "The native provider emitted character throughput telemetry but no token count."
            ),
            "human_intervention": (
                "Approval counts are policy decisions replayed from captured approval requests."
            ),
        },
    }


def _scenario_report(
    *,
    name: str,
    event_path: Path,
    workspace: Path,
    expected_engine: str,
    expected_driver: str,
    artifact_validator: Callable[[Path], dict[str, Any]],
    approval_responder: Callable[[str, dict[str, Any]], dict[str, str]],
) -> dict[str, Any]:
    events = _read_events(event_path)
    turn = next(
        (event.get("turn") for event in reversed(events) if event.get("kind") == "turn_result"),
        None,
    )
    if not isinstance(turn, dict):
        raise ValueError(f"{name}: no final turn_result in {event_path}")
    raw_receipt = turn.get("execution")
    receipt: dict[str, Any] = raw_receipt if isinstance(raw_receipt, dict) else {}
    protocol_receipts = [
        event.get("params", {}).get("execution")
        for event in events
        if event.get("kind") == "protocol_event"
        and event.get("method") == "turn/execution/updated"
        and isinstance(event.get("params"), dict)
    ]
    engines = {
        str(row.get("engine"))
        for row in [receipt, *protocol_receipts]
        if isinstance(row, dict) and row.get("engine")
    }
    unique_commands = _unique_command_items(turn)
    approvals = [event for event in events if event.get("kind") == "approval_request"]
    decisions = [
        approval_responder(str(event.get("method") or ""), event.get("params") or {}).get(
            "action",
            "decline",
        )
        for event in approvals
    ]
    artifact = artifact_validator(workspace)
    checks = {
        "turn_completed": turn.get("status") == "completed" and not turn.get("error"),
        "expected_engine": receipt.get("engine") == expected_engine,
        "expected_driver": receipt.get("driver") == expected_driver,
        "single_engine_binding": len(protocol_receipts) == 1,
        "no_cross_engine_transfer": engines == {expected_engine},
        "artifact_verified": artifact["passed"],
    }
    usage_updates = [
        event.get("usage") or {} for event in events if event.get("kind") == "token_usage"
    ]
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "execution": receipt,
        "duration_seconds": _duration_seconds(turn),
        "event_count": len(events),
        "approval_requests": len(approvals),
        "approval_decisions": {
            "accepted": decisions.count("accept"),
            "declined": decisions.count("decline"),
        },
        "tool_calls": unique_commands,
        "usage": {
            "updates": len(usage_updates),
            "last": usage_updates[-1] if usage_updates else None,
        },
        "cost_usd": None,
        "cost_source": "not_reported",
        "artifact": artifact,
        "trajectory": {
            "path": _display_path(event_path),
            "sha256": _sha256(event_path),
        },
    }


def _validate_calculator(workspace: Path) -> dict[str, Any]:
    target = workspace / CALCULATOR_NAME
    files = _workspace_files(workspace)
    verifier = (
        "import json,runpy,sys; ns=runpy.run_path(sys.argv[1]); f=ns['clamp']; "
        "values=[f(-1,0,10),f(0,0,10),f(5,0,10),f(10,0,10),f(11,0,10)]; "
        "error=False; "
        "\ntry: f(1,2,1)\nexcept ValueError: error=True\n"
        "print(json.dumps({'values':values,'value_error':error}))"
    )
    completed = subprocess.run(
        [sys.executable, "-I", "-c", verifier, str(target)],
        cwd=workspace,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    observed: dict[str, Any] | None = None
    if completed.returncode == 0:
        try:
            value = json.loads(completed.stdout)
            observed = value if isinstance(value, dict) else None
        except json.JSONDecodeError:
            observed = None
    passed = (
        target.is_file()
        and files == [CALCULATOR_NAME]
        and observed == {"values": [0, 0, 5, 10, 10], "value_error": True}
    )
    return {
        "passed": passed,
        "path": _display_path(target),
        "sha256": _sha256(target) if target.is_file() else None,
        "size_bytes": target.stat().st_size if target.is_file() else None,
        "workspace_files": files,
        "verifier": observed,
        "verifier_stderr": completed.stderr.strip() or None,
    }


def _validate_document(workspace: Path) -> dict[str, Any]:
    from docx import Document

    target = workspace / DOCUMENT_NAME
    files = _workspace_files(workspace)
    paragraphs: list[str] = []
    error: str | None = None
    if target.is_file():
        try:
            paragraphs = [paragraph.text for paragraph in Document(str(target)).paragraphs]
        except Exception as exc:  # noqa: BLE001 - preserved as acceptance evidence
            error = f"{type(exc).__name__}: {exc}"
    passed = (
        files == [DOCUMENT_NAME]
        and paragraphs[:2] == [DOCUMENT_TITLE, DOCUMENT_BODY]
        and error is None
    )
    return {
        "passed": passed,
        "path": _display_path(target),
        "sha256": _sha256(target) if target.is_file() else None,
        "size_bytes": target.stat().st_size if target.is_file() else None,
        "workspace_files": files,
        "paragraphs": paragraphs,
        "open_error": error,
    }


def _codex_approval_responder(
    workspace: Path,
    target: Path,
) -> Callable[[str, dict[str, Any]], dict[str, str]]:
    def respond(method: str, params: dict[str, Any]) -> dict[str, str]:
        if "requestApproval" not in method:
            return {"action": "decline"}
        tool = str(params.get("tool") or "")
        preview = _parse_preview(params.get("argsPreview"))
        if tool in {"edit_text_file", "write_text_file", "read_file"}:
            supplied = _resolve_supplied_path(workspace, preview.get("path"))
            return {"action": "accept" if supplied == target else "decline"}
        if tool == "exec_shell":
            actions = preview.get("actions")
            if not isinstance(actions, list) or not actions:
                return {"action": "decline"}
            allowed = all(
                isinstance(action, dict)
                and action.get("type") == "read"
                and _resolve_supplied_path(workspace, action.get("path")) == target
                for action in actions
            )
            return {"action": "accept" if allowed else "decline"}
        return {"action": "decline"}

    return respond


def _native_approval_responder(
    workspace: Path,
    target: Path,
) -> Callable[[str, dict[str, Any]], dict[str, str]]:
    def respond(method: str, params: dict[str, Any]) -> dict[str, str]:
        if "requestApproval" not in method or params.get("tool") != "documents.create_docx":
            return {"action": "decline"}
        preview = _parse_preview(params.get("argsPreview"))
        supplied = _resolve_supplied_path(workspace, preview.get("path"))
        return {"action": "accept" if supplied == target else "decline"}

    return respond


def _parse_preview(value: Any) -> dict[str, Any]:
    raw = str(value or "{}")
    for loader in (json.loads, ast.literal_eval):
        try:
            parsed = loader(raw)
        except (json.JSONDecodeError, SyntaxError, ValueError):
            continue
        if isinstance(parsed, dict):
            return parsed
    return {}


def _resolve_supplied_path(workspace: Path, value: Any) -> Path | None:
    if not isinstance(value, str) or not value:
        return None
    supplied = Path(value)
    try:
        return supplied.resolve() if supplied.is_absolute() else (workspace / supplied).resolve()
    except (OSError, RuntimeError):
        return None


def _plugin_state(base_url: str, token: str, plugin_id: str) -> dict[str, Any]:
    with httpx.Client(base_url=base_url, timeout=30) as client:
        response = client.get(
            "/api/plugin-hub/plugins",
            headers={"Authorization": f"Bearer {token}"},
        )
        response.raise_for_status()
        payload = response.json()
    rows = payload if isinstance(payload, list) else payload.get("plugins", [])
    plugin = next(row for row in rows if row.get("id") == plugin_id)
    return {
        "activation": plugin.get("activation"),
        "loaded": plugin.get("loaded"),
        "started": plugin.get("started"),
    }


def _imported_plugin_state(state: PluginState) -> dict[str, Any]:
    loaded = {"loaded": True, "unloaded": False, "unknown": None}[state]
    return {"activation": "on_demand", "loaded": loaded, "started": loaded}


def _local_token(base_url: str, username: str) -> str:
    with httpx.Client(base_url=base_url, timeout=30) as client:
        response = client.post("/api/auth/local/login", json={"username": username})
        response.raise_for_status()
        payload = response.json()
    token = payload.get("access_token")
    if not isinstance(token, str) or not token:
        raise RuntimeError("local login returned no access token")
    return token


def _realtime_url(base_url: str) -> str:
    if base_url.startswith("https://"):
        return "wss://" + base_url.removeprefix("https://") + "/api/realtime"
    if base_url.startswith("http://"):
        return "ws://" + base_url.removeprefix("http://") + "/api/realtime"
    raise ValueError("--base-url must start with http:// or https://")


def _duration_seconds(turn: dict[str, Any]) -> float | None:
    try:
        started = datetime.fromisoformat(str(turn["startedAt"]).replace("Z", "+00:00"))
        completed = datetime.fromisoformat(str(turn["completedAt"]).replace("Z", "+00:00"))
    except (KeyError, TypeError, ValueError):
        return None
    return round((completed - started).total_seconds(), 3)


def _unique_command_items(turn: dict[str, Any]) -> list[dict[str, Any]]:
    commands: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(turn.get("items") or []):
        if isinstance(item, dict) and item.get("type") == "commandExecution":
            item_id = str(item.get("id") or index)
            commands[item_id] = {
                "command": item.get("command"),
                "status": item.get("status"),
                "network_access": item.get("networkAccess"),
            }
    return list(commands.values())


def _write_broken_calculator(path: Path) -> None:
    path.write_text(
        "def clamp(value: float, low: float, high: float) -> float:\n"
        "    if low > high:\n"
        "        raise ValueError('low must not exceed high')\n"
        "    return min(low, max(high, value))\n",
        encoding="utf-8",
    )


def _read_events(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not all(isinstance(row, dict) for row in payload):
        raise ValueError(f"event log must be a list of objects: {path}")
    return payload


def _write_events(path: Path, events: list[dict[str, Any]]) -> None:
    path.write_text(json.dumps(events, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _workspace_files(workspace: Path) -> list[str]:
    return sorted(
        path.relative_to(workspace).as_posix() for path in workspace.rglob("*") if path.is_file()
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _display_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(resolved)


def _repository_state() -> dict[str, Any]:
    def git(*args: str) -> str:
        completed = subprocess.run(
            ["git", *args],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        return completed.stdout.strip()

    try:
        revision = git("rev-parse", "HEAD")
        branch = git("branch", "--show-current")
        dirty = bool(git("status", "--porcelain"))
    except (OSError, subprocess.SubprocessError):
        revision, branch, dirty = None, None, None
    return {"revision": revision, "branch": branch, "working_tree_dirty": dirty}


if __name__ == "__main__":
    raise SystemExit(main())
