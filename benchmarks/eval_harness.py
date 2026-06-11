"""Agent eval harness — pass@k / pass^k driver.

Implements Anthropic's recommended methodology from
"Demystifying evals for AI agents" (Mar 2026):
  * Run each task ``k`` times with isolated state.
  * Report both ``pass@k`` (any-success probability) and ``pass^k``
    (all-success probability).
  * Grade outcomes, not paths — verdicts come from a pluggable grader.
  * Capture full trajectories so failures are debuggable.

Usage::

    from benchmarks.eval_harness import EvalCase, run_suite

    cases = [
        EvalCase(
            id="echo-hello",
            prompt="Reply with exactly: hello",
            grader=lambda traj: "hello" in traj.last_text(),
        ),
    ]
    report = run_suite(cases, k=3, runner=my_runner)
    print(report.summary())
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

# ── Trajectory ───────────────────────────────────────────────


@dataclass
class TrajectoryStep:
    """One observable event in a trial. Mirrors the ReAct event shape."""

    kind: str              # "text_delta" / "tool_start" / "tool_end" / ...
    payload: dict[str, Any] = field(default_factory=dict)
    ts: float = field(default_factory=time.time)


@dataclass
class Trajectory:
    """Complete record of one trial run.

    The grader inspects this; the runner builds it event-by-event.
    """

    trial_id: str
    case_id: str
    steps: list[TrajectoryStep] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)
    ended_at: float | None = None
    error: str | None = None

    def append(self, kind: str, **payload: Any) -> None:
        self.steps.append(TrajectoryStep(kind=kind, payload=payload))

    def last_text(self) -> str:
        """All ``text_delta`` payloads concatenated. Convenient for graders
        that only care about the final answer.
        """
        out: list[str] = []
        for s in self.steps:
            if s.kind == "text_delta":
                out.append(str(s.payload.get("delta", "")))
        return "".join(out)

    def tool_names(self) -> list[str]:
        """Every ``tool_start`` name in order. Useful for "did agent call X?" graders."""
        return [
            str(s.payload.get("tool_name", ""))
            for s in self.steps
            if s.kind == "tool_start"
        ]

    def runtime_ms(self) -> float:
        end = self.ended_at or time.time()
        return (end - self.started_at) * 1000.0


# ── Grader ───────────────────────────────────────────────────


@dataclass(frozen=True)
class Verdict:
    passed: bool
    score: float = 0.0       # 0..1 partial-credit score
    reason: str = ""
    rubric: dict[str, Any] = field(default_factory=dict)


# A grader is a callable taking the trajectory and returning a verdict.
# Keep it dead simple: no class hierarchy required — just a function.
Grader = Callable[[Trajectory], Verdict | bool]


def _coerce_verdict(raw: Verdict | bool) -> Verdict:
    if isinstance(raw, Verdict):
        return raw
    return Verdict(passed=bool(raw), score=1.0 if raw else 0.0)


# ── Case + Runner ────────────────────────────────────────────


@dataclass
class EvalCase:
    """One concrete evaluation task."""

    id: str
    prompt: str
    grader: Grader
    setup: Callable[[], None] | None = None
    teardown: Callable[[], None] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class TrialRunner(Protocol):
    """A function that runs one trial and yields ReAct-shaped events."""

    def __call__(self, prompt: str) -> Any: ...


# ── Suite report ─────────────────────────────────────────────


@dataclass
class CaseResult:
    case_id: str
    k: int
    passes: int
    trajectories: list[Trajectory] = field(default_factory=list)
    verdicts: list[Verdict] = field(default_factory=list)

    @property
    def pass_at_k(self) -> float:
        """Probability of *at least one* success across the k trials."""
        return 1.0 if self.passes >= 1 else 0.0

    @property
    def pass_pow_k(self) -> float:
        """Probability of *all k* trials succeeding."""
        return 1.0 if self.passes == self.k else 0.0

    @property
    def avg_score(self) -> float:
        if not self.verdicts:
            return 0.0
        return sum(v.score for v in self.verdicts) / len(self.verdicts)

    @property
    def avg_runtime_ms(self) -> float:
        if not self.trajectories:
            return 0.0
        return sum(t.runtime_ms() for t in self.trajectories) / len(self.trajectories)


@dataclass
class SuiteReport:
    cases: list[CaseResult] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)
    ended_at: float | None = None

    def add(self, result: CaseResult) -> None:
        self.cases.append(result)

    @property
    def aggregate_pass_at_k(self) -> float:
        if not self.cases:
            return 0.0
        return sum(c.pass_at_k for c in self.cases) / len(self.cases)

    @property
    def aggregate_pass_pow_k(self) -> float:
        if not self.cases:
            return 0.0
        return sum(c.pass_pow_k for c in self.cases) / len(self.cases)

    def summary(self) -> str:
        lines = [
            f"Eval suite · {len(self.cases)} cases · k={self.cases[0].k if self.cases else 0}",
            f"  pass@k  = {self.aggregate_pass_at_k:.2%}  (any-success)",
            f"  pass^k  = {self.aggregate_pass_pow_k:.2%}  (all-success)",
            "",
        ]
        for c in self.cases:
            mark = "✓" if c.pass_pow_k == 1.0 else (
                "~" if c.pass_at_k == 1.0 else "✗"
            )
            lines.append(
                f"  {mark} {c.case_id:30s} "
                f"{c.passes}/{c.k} · score={c.avg_score:.2f} · "
                f"avg={c.avg_runtime_ms:.0f}ms",
            )
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "aggregate_pass_at_k": self.aggregate_pass_at_k,
            "aggregate_pass_pow_k": self.aggregate_pass_pow_k,
            "cases": [
                {
                    "case_id": c.case_id,
                    "k": c.k,
                    "passes": c.passes,
                    "pass_at_k": c.pass_at_k,
                    "pass_pow_k": c.pass_pow_k,
                    "avg_score": c.avg_score,
                    "avg_runtime_ms": c.avg_runtime_ms,
                    "verdicts": [
                        {"passed": v.passed, "score": v.score, "reason": v.reason}
                        for v in c.verdicts
                    ],
                }
                for c in self.cases
            ],
        }

    def write_json(self, path: Path | str) -> None:
        Path(path).write_text(
            json.dumps(self.to_dict(), indent=2),
            encoding="utf-8",
        )


# ── Runner core ──────────────────────────────────────────────


def run_case(
    case: EvalCase,
    *,
    runner: TrialRunner,
    k: int = 3,
) -> CaseResult:
    """Execute one case ``k`` times under the supplied runner."""
    result = CaseResult(case_id=case.id, k=k, passes=0)
    for trial_idx in range(k):
        trial_id = f"{case.id}.{trial_idx}.{uuid.uuid4().hex[:6]}"
        traj = Trajectory(trial_id=trial_id, case_id=case.id)

        if case.setup:
            try:
                case.setup()
            except Exception as exc:
                traj.error = f"setup failed: {exc}"
                traj.ended_at = time.time()
                result.trajectories.append(traj)
                result.verdicts.append(Verdict(passed=False, reason=traj.error))
                continue

        try:
            for raw in runner(case.prompt):
                if isinstance(raw, dict):
                    kind = raw.get("kind") or raw.get("type") or "event"
                    payload = {k_: v for k_, v in raw.items() if k_ not in ("kind", "type")}
                    traj.steps.append(TrajectoryStep(kind=kind, payload=payload))
        except Exception as exc:
            traj.error = f"runner raised: {exc}"
        finally:
            traj.ended_at = time.time()
            if case.teardown:
                try:
                    case.teardown()
                except Exception as exc:
                    traj.append("teardown_error", message=str(exc))

        verdict = _coerce_verdict(case.grader(traj))
        if verdict.passed:
            result.passes += 1
        result.trajectories.append(traj)
        result.verdicts.append(verdict)

    return result


def run_suite(
    cases: Sequence[EvalCase],
    *,
    runner: TrialRunner,
    k: int = 3,
) -> SuiteReport:
    """Run every case ``k`` times and return an aggregated report."""
    report = SuiteReport()
    for case in cases:
        report.add(run_case(case, runner=runner, k=k))
    report.ended_at = time.time()
    return report


__all__ = [
    "CaseResult",
    "EvalCase",
    "Grader",
    "SuiteReport",
    "Trajectory",
    "TrajectoryStep",
    "TrialRunner",
    "Verdict",
    "run_case",
    "run_suite",
]
