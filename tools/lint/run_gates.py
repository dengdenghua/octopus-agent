"""Single entry point for the nine mechanical gates.

Runs each gate exactly the way CI runs it, aggregates results into one
table plus an optional JSON report, and exits non-zero if any gate fails.

Usage:
    python tools/lint/run_gates.py                    # all nine gates
    python tools/lint/run_gates.py --only god_file_check,root_hygiene
    python tools/lint/run_gates.py --json report.json

Why: CI carries one step per gate with individual names and comments; a
local contributor had to remember nine invocations. This runner keeps a
single source of truth for the gate list so the reusable workflow
(.github/workflows/mech-gates.yml) and local runs cannot drift apart.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

PY = sys.executable or "python"


@dataclass(frozen=True)
class Gate:
    """One mechanical gate and the exact command CI uses to run it."""

    name: str
    args: tuple[str, ...]


# Keep in sync with .github/workflows/ci.yml (lint-and-test job). Order
# mirrors the CI steps so local failures read the same as CI failures.
GATES: tuple[Gate, ...] = (
    Gate("untracked_source_check", (PY, "-m", "tools.lint.untracked_source_check")),
    Gate("god_file_check", (PY, "tools/lint/god_file_check.py", "--strict")),
    Gate("import_direction_check", (PY, "tools/lint/import_direction_check.py", "--strict")),
    Gate("orphan_module_check", (PY, "tools/lint/orphan_module_check.py", "--strict")),
    Gate(
        "feature_flag_consumption_check",
        (PY, "tools/lint/feature_flag_consumption_check.py", "--strict"),
    ),
    Gate("async_lock_check", (PY, "tools/lint/async_lock_check.py", "--strict")),
    Gate("async_blocking_check", (PY, "tools/lint/async_blocking_check.py", "--strict")),
    Gate("root_hygiene", (PY, "tools/lint/root_hygiene.py", "--strict")),
    Gate("repo_url_check", (PY, "tools/lint/repo_url_check.py", "--strict")),
)


@dataclass(frozen=True)
class GateResult:
    """Outcome of one gate run. exit_code 124 marks our own timeout."""

    name: str
    exit_code: int
    duration_s: float
    output_tail: str


def select_gates(only: str | None, skip: str | None) -> tuple[Gate, ...]:
    """Filter the gate list by comma-separated names; unknown names raise."""
    known = {g.name for g in GATES}
    selected = GATES
    if only:
        names = {n.strip() for n in only.split(",") if n.strip()}
        unknown = names - known
        if unknown:
            raise SystemExit(
                f"unknown gate(s): {', '.join(sorted(unknown))}; known: {', '.join(sorted(known))}"
            )
        selected = tuple(g for g in GATES if g.name in names)
    if skip:
        names = {n.strip() for n in skip.split(",") if n.strip()}
        unknown = names - known
        if unknown:
            raise SystemExit(
                f"unknown gate(s): {', '.join(sorted(unknown))}; known: {', '.join(sorted(known))}"
            )
        selected = tuple(g for g in selected if g.name not in names)
    if not selected:
        raise SystemExit("no gates selected")
    return selected


def run_one(gate: Gate, timeout_s: float, cwd: Path) -> GateResult:
    """Run one gate; never raises. Tail of output is kept for the table."""
    started = time.monotonic()
    try:
        proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
            list(gate.args),
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_s,
        )
        exit_code = proc.returncode
        output = (proc.stdout or "") + (proc.stderr or "")
    except subprocess.TimeoutExpired:
        exit_code = 124
        output = f"TIMEOUT after {timeout_s:.0f}s"
    duration = time.monotonic() - started
    tail = "\n".join(output.strip().splitlines()[-6:])
    return GateResult(gate.name, exit_code, round(duration, 1), tail)


def render_table(results: list[GateResult]) -> str:
    """Human-readable table. Kept dependency-free for CI portability."""
    width = max(len(r.name) for r in results) if results else 4
    lines = []
    for r in results:
        status = "PASS" if r.exit_code == 0 else f"FAIL({r.exit_code})"
        lines.append(f"{status:>9}  {r.name:<{width}}  {r.duration_s:>6.1f}s")
    failed = sum(1 for r in results if r.exit_code != 0)
    lines.append(f"\n{len(results) - failed}/{len(results)} gates passed")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--only", default=None, help="comma-separated gate names to run")
    parser.add_argument("--skip", default=None, help="comma-separated gate names to skip")
    parser.add_argument("--timeout", type=float, default=600.0, help="per-gate timeout seconds")
    parser.add_argument("--json", default=None, help="write a JSON report to this path")
    args = parser.parse_args()

    gates = select_gates(args.only, args.skip)
    results = [run_one(g, args.timeout, REPO_ROOT) for g in gates]

    print(render_table(results))
    if args.json:
        report = {
            "gates": [
                {
                    "name": r.name,
                    "exit_code": r.exit_code,
                    "passed": r.exit_code == 0,
                    "duration_s": r.duration_s,
                    "output_tail": r.output_tail,
                }
                for r in results
            ],
            "all_passed": all(r.exit_code == 0 for r in results),
        }
        Path(args.json).write_text(
            json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"wrote JSON report to {args.json}")

    return 0 if all(r.exit_code == 0 for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
