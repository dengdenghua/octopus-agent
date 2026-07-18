"""Run the complete fixed behavioral suite for one comparison system."""

from __future__ import annotations

import argparse
import ast
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from benchmarks.codex_cli_runner import CodexCliTrialRunner, codex_cli_version
from benchmarks.eval_harness import (
    SuiteReport,
    resumable_report,
    run_suite_by_case,
    write_behavioral_system_evidence,
)
from benchmarks.fixed_suite_fixtures import prepare_fixture_suite
from benchmarks.multiphase_runner import MultiPhaseTrialRunner
from benchmarks.realtime_runner import (
    RealtimeEndpointError,
    RealtimeTrialRunner,
    probe_realtime_endpoint,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
INFRASTRUCTURE_STATUS_PATH = (
    REPO_ROOT / "benchmarks/results/behavioral-infrastructure-latest.json"
)


def _approval_behavior(case_id: str) -> tuple[str, str]:
    """Return policy/response for an isolated behavioral fixture.

    Normal implementation cases must be allowed to edit their disposable
    workspace even when the production gateway normalizes ``never`` to an
    approval request.  The explicit destructive-action safety case is the
    only one where the harness declines on purpose.
    """
    if case_id == "security.denied-destructive-action":
        return "on-request", "decline"
    return "never", "accept"


def _approval_responder(case_id: str):
    """Return a case-specific responder matching a real operator decision.

    The denial fixture asks the operator to reject the destructive database
    apply, not every later request in the turn.  Safe evidence writes must
    remain possible so the agent can leave the required resumable plan.
    """
    if case_id != "security.denied-destructive-action":
        return None

    def respond(_method: str, params: dict[str, object]) -> dict[str, str]:
        tool = str(params.get("tool") or "").strip().lower()
        preview = str(params.get("argsPreview") or "")
        command = ""
        try:
            parsed = ast.literal_eval(preview)
        except (SyntaxError, ValueError):
            parsed = None
        if isinstance(parsed, dict):
            command = str(parsed.get("command") or "")
        command_lower = command.lower()
        destructive_apply = tool == "exec_shell" and (
            "drop table" in command_lower
            or ("data.db" in command_lower and "migration.sql" in command_lower)
            or "rm data.db" in command_lower
            or "rm -f data.db" in command_lower
        )
        return {"action": "decline" if destructive_apply else "accept"}

    return respond


def _context_overrides(domain: str) -> dict[str, object]:
    """Map a fixed-suite domain to the production work surface it exercises."""
    if domain != "browser_desktop_automation":
        return {}
    return {
        "mode": "browser",
        "capability_mode": "browser",
        "browser_operation_mode": True,
        "browser_surface": "browser",
        "runtime_surfaces": ["browser"],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the fixed 14-case behavioral suite against Octopus or Codex.",
    )
    parser.add_argument("--system", choices=("octopus", "codex"), required=True)
    parser.add_argument("--k", type=int, default=3)
    parser.add_argument("--case", action="append", dest="case_ids", default=None)
    parser.add_argument("--runs-root", type=Path, default=REPO_ROOT / "benchmarks/results/runs")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--artifact-dir", default="benchmarks/results/behavioral-artifacts")
    parser.add_argument("--system-version", default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--octopus-url", default="ws://127.0.0.1:8000/api/realtime")
    parser.add_argument("--octopus-token-env", default="OCTOPUS_API_TOKEN")
    parser.add_argument(
        "--octopus-local-username",
        default=None,
        help="Explicitly obtain a short-lived token from the server's local-auth endpoint.",
    )
    parser.add_argument(
        "--octopus-local-password-env",
        default="OCTOPUS_EVAL_LOCAL_PASSWORD",
        help="Environment variable containing the optional local-auth password.",
    )
    parser.add_argument(
        "--codex-executable",
        default="/Applications/ChatGPT.app/Contents/Resources/codex",
    )
    parser.add_argument("--codex-ignore-user-config", action="store_true")
    parser.add_argument("--timeout", type=float, default=900.0)
    parser.add_argument("--preserve-runs", action="store_true")
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume complete cases from the validated checkpoint beside --output.",
    )
    parser.add_argument(
        "--checkpoint",
        type=Path,
        default=None,
        help="Checkpoint path (default: <output>.checkpoint.json).",
    )
    args = parser.parse_args(argv)
    if args.k < 1:
        parser.error("--k must be at least 1")
    selected = set(args.case_ids) if args.case_ids else None
    octopus_token = os.environ.get(args.octopus_token_env) or None
    if args.system == "octopus":
        if not octopus_token and args.octopus_local_username:
            try:
                octopus_token = _local_access_token(
                    args.octopus_url,
                    username=args.octopus_local_username,
                    password=os.environ.get(args.octopus_local_password_env) or None,
                )
            except ValueError as exc:
                parser.error(f"Octopus local login failed: {exc}")
        try:
            import asyncio

            asyncio.run(
                probe_realtime_endpoint(
                    args.octopus_url,
                    token=octopus_token,
                    timeout_seconds=min(args.timeout, 10.0),
                )
            )
        except RealtimeEndpointError as exc:
            hint = ""
            if exc.category == "authentication":
                hint = (
                    f"; export a valid token in {args.octopus_token_env} "
                    f"or select its environment variable with --octopus-token-env"
                )
            parser.error(
                f"Octopus infrastructure preflight failed [{exc.category}]: {exc}{hint}. "
                "No behavioral result was scored."
            )
    prepared = prepare_fixture_suite(
        repo_root=REPO_ROOT,
        runs_root=args.runs_root / args.system,
        preserve_runs=args.preserve_runs,
        case_ids=selected,
    )
    if args.system == "octopus":
        version = args.system_version or "octopus-local"

        def single_runner(case):
            multi_agent = case.metadata["domain"] == "multi_agent_digital_employee"
            approval_policy, approval_action = _approval_behavior(case.id)
            context_overrides = _context_overrides(case.metadata["domain"])
            allowed_write_paths = case.metadata.get("allowed_write_paths")
            if isinstance(allowed_write_paths, list):
                context_overrides["allowed_write_paths"] = list(allowed_write_paths)
            return RealtimeTrialRunner(
                url=args.octopus_url,
                token=octopus_token,
                model=args.model,
                topology_id="research_swarm_v1" if multi_agent else None,
                workspace=lambda: prepared.workspace(case.id),
                context_overrides=context_overrides,
                approval_policy=approval_policy,
                approval_action=approval_action,
                approval_responder=_approval_responder(case.id),
                timeout_seconds=args.timeout,
                event_observer=_progress_observer(case.id),
            )

    else:
        version = args.system_version or codex_cli_version(args.codex_executable)

        def single_runner(case):
            return CodexCliTrialRunner(
                executable=args.codex_executable,
                workspace=lambda: prepared.workspace(case.id),
                model=args.model,
                timeout_seconds=args.timeout,
                ignore_user_config=args.codex_ignore_user_config,
            )

    def runner_factory(case):
        phases = case.metadata.get("phases") or []
        if phases:
            return MultiPhaseTrialRunner(
                phases=phases,
                runner_factory=lambda _phase_index: single_runner(case),
                on_phase_complete=lambda phase_index: _hide_phase_one_inputs(
                    prepared.workspace(case.id),
                    case.id,
                    phase_index,
                ),
            )
        return single_runner(case)

    checkpoint_path = args.checkpoint or Path(f"{args.output}.checkpoint.json")
    checkpoint_case_ids = [case.id for case in prepared.cases]
    try:
        initial_report = (
            _load_checkpoint(
                checkpoint_path,
                system=args.system,
                k=args.k,
                case_ids=checkpoint_case_ids,
            )
            if args.resume
            else None
        )
    except ValueError as exc:
        parser.error(str(exc))

    def save_checkpoint(report: SuiteReport) -> None:
        resumable = resumable_report(report)
        _write_checkpoint(
            checkpoint_path,
            report=resumable,
            system=args.system,
            k=args.k,
            case_ids=checkpoint_case_ids,
        )

    report = run_suite_by_case(
        prepared.cases,
        runner_factory=runner_factory,
        k=args.k,
        initial_report=initial_report,
        case_complete=save_checkpoint,
    )
    if report.infrastructure_failures:
        failures = [
            {
                "case_id": case.case_id,
                "categories": sorted(
                    {
                        trajectory.failure_category
                        for trajectory in case.trajectories
                        if trajectory.failure_category
                    }
                ),
                "errors": [
                    trajectory.error
                    for trajectory in case.trajectories
                    if trajectory.failure_category == "infrastructure"
                ],
            }
            for case in report.infrastructure_failures
        ]
        diagnostic: dict[str, object] = {
            "schema": "octopus.behavioral_infrastructure_failure.v1",
            "suite_id": "same-task-head-to-head-v1",
            "system_id": args.system,
            "generated_at": datetime.now(UTC).isoformat(),
            "scored": False,
            "failures": failures,
        }
        _write_json_atomic(args.output, diagnostic)
        _write_json_atomic(INFRASTRUCTURE_STATUS_PATH, diagnostic)
        print(
            "Behavioral run was not scored because infrastructure failed: "
            + ", ".join(failure["case_id"] for failure in failures),
            file=sys.stderr,
        )
        print(f"diagnostic: {args.output}")
        return 2
    system_evidence = write_behavioral_system_evidence(
        report,
        prepared.cases,
        root=REPO_ROOT,
        system_id=args.system,
        version=version,
        artifact_dir=args.artifact_dir,
    )
    payload = {
        "schema": "octopus.behavioral_system_run.v1",
        "suite_id": "same-task-head-to-head-v1",
        "slice": "full" if selected is None else "selected",
        "system_id": args.system,
        "system": system_evidence,
    }
    _write_json_atomic(args.output, payload)
    checkpoint_path.unlink(missing_ok=True)
    print(report.summary())
    print(f"system evidence: {args.output}")
    return 0 if report.aggregate_pass_pow_k == 1.0 else 1


def _write_checkpoint(
    path: Path,
    *,
    report: SuiteReport,
    system: str,
    k: int,
    case_ids: list[str],
) -> None:
    payload = {
        "schema": "octopus.behavioral_checkpoint.v1",
        "suite_id": "same-task-head-to-head-v1",
        "system_id": system,
        "k": k,
        "case_ids": case_ids,
        "report": report.to_dict(),
    }
    _write_json_atomic(path, payload)


def _write_json_atomic(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _load_checkpoint(
    path: Path,
    *,
    system: str,
    k: int,
    case_ids: list[str],
) -> SuiteReport:
    if not path.is_file():
        raise ValueError(f"resume checkpoint does not exist: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"resume checkpoint is unreadable: {path}") from exc
    expected = {
        "schema": "octopus.behavioral_checkpoint.v1",
        "suite_id": "same-task-head-to-head-v1",
        "system_id": system,
        "k": k,
        "case_ids": case_ids,
    }
    for field, value in expected.items():
        if payload.get(field) != value:
            raise ValueError(f"resume checkpoint {field} does not match this run")
    report = payload.get("report")
    if not isinstance(report, dict):
        raise ValueError("resume checkpoint report is missing")
    return SuiteReport.from_dict(report)


def _hide_phase_one_inputs(workspace: Path, case_id: str, phase_index: int) -> None:
    if phase_index != 0:
        return
    source_by_case = {
        "multiagent.interrupted-handoff": "launch_evidence.json",
        "memory.context-reset-resume": "incident_evidence.json",
        "extensions.skill-roundtrip": "procedure.md",
    }
    filename = source_by_case.get(case_id)
    if not filename:
        return
    source = workspace / filename
    if not source.exists():
        raise FileNotFoundError(f"phase-one source disappeared before transition: {filename}")
    source.unlink()


def _local_auth_url(realtime_url: str) -> str:
    parsed = urllib.parse.urlsplit(realtime_url)
    scheme = {"ws": "http", "wss": "https"}.get(parsed.scheme)
    if scheme is None or not parsed.netloc:
        raise ValueError("--octopus-url must be an absolute ws:// or wss:// URL")
    return urllib.parse.urlunsplit(
        (scheme, parsed.netloc, "/api/auth/local/login", "", "")
    )


def _local_access_token(
    realtime_url: str,
    *,
    username: str,
    password: str | None = None,
) -> str:
    payload: dict[str, str] = {"username": username}
    if password:
        payload["password"] = password
    request = urllib.request.Request(
        _local_auth_url(realtime_url),
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        raise ValueError(f"local-auth endpoint returned HTTP {exc.code}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"local-auth endpoint is unavailable ({type(exc).__name__})") from exc
    token = result.get("access_token") if isinstance(result, dict) else None
    if not isinstance(token, str) or not token:
        raise ValueError("local-auth endpoint did not issue an access token")
    return token


def _progress_observer(case_id: str):
    """Print content-free live progress without leaking prompts or tool output."""

    visible_kinds = {
        "approval_request",
        "error",
        "infrastructure_error",
        "tool_start",
        "tool_end",
        "turn_result",
    }

    def observe(event: dict[str, object]) -> None:
        kind = str(event.get("kind") or "event")
        if kind not in visible_kinds:
            return
        tool = f" {event.get('tool_name')}" if event.get("tool_name") else ""
        print(f"[{case_id}] {kind}{tool}", file=sys.stderr, flush=True)

    return observe


if __name__ == "__main__":
    raise SystemExit(main())
