"""Run the complete fixed behavioral suite for one comparison system."""

from __future__ import annotations

import argparse
import ast
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from benchmarks.codex_cli_runner import CodexCliTrialRunner, codex_cli_version
from benchmarks.eval_harness import run_suite_by_case, write_behavioral_system_evidence
from benchmarks.fixed_suite_fixtures import prepare_fixture_suite
from benchmarks.multiphase_runner import MultiPhaseTrialRunner
from benchmarks.realtime_runner import RealtimeTrialRunner

REPO_ROOT = Path(__file__).resolve().parents[1]


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
        "--codex-executable",
        default="/Applications/ChatGPT.app/Contents/Resources/codex",
    )
    parser.add_argument("--codex-ignore-user-config", action="store_true")
    parser.add_argument("--timeout", type=float, default=900.0)
    parser.add_argument("--preserve-runs", action="store_true")
    args = parser.parse_args(argv)
    if args.k < 1:
        parser.error("--k must be at least 1")
    selected = set(args.case_ids) if args.case_ids else None
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
            return RealtimeTrialRunner(
                url=args.octopus_url,
                token=os.environ.get(args.octopus_token_env) or None,
                model=args.model,
                topology_id="research_swarm_v1" if multi_agent else None,
                workspace=lambda: prepared.workspace(case.id),
                context_overrides=_context_overrides(case.metadata["domain"]),
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

    report = run_suite_by_case(prepared.cases, runner_factory=runner_factory, k=args.k)
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
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(report.summary())
    print(f"system evidence: {args.output}")
    return 0 if report.aggregate_pass_pow_k == 1.0 else 1


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


def _progress_observer(case_id: str):
    """Print content-free live progress without leaking prompts or tool output."""

    visible_kinds = {"approval_request", "error", "tool_start", "tool_end", "turn_result"}

    def observe(event: dict[str, object]) -> None:
        kind = str(event.get("kind") or "event")
        if kind not in visible_kinds:
            return
        tool = f" {event.get('tool_name')}" if event.get("tool_name") else ""
        print(f"[{case_id}] {kind}{tool}", file=sys.stderr, flush=True)

    return observe


if __name__ == "__main__":
    raise SystemExit(main())
