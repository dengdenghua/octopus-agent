from __future__ import annotations

from collections.abc import Callable

from runtime.execution.loops.models import VerifierFinding, VerifierResult


def _summarize_failed_findings(findings: list[VerifierFinding]) -> str:
    failed = [finding for finding in findings if not finding.passed]
    if not failed:
        return "all checks passed"
    names = ", ".join(finding.name for finding in failed[:5])
    return f"failed checks: {names}"


class LoopVerifierRegistry:
    def __init__(self) -> None:
        self._handlers: dict[str, Callable[[str], VerifierResult]] = {}

    def register(
        self,
        profile: str,
        handler: Callable[[str], VerifierResult],
    ) -> None:
        self._handlers[str(profile).strip()] = handler

    def run(self, profile: str, workspace_path: str) -> VerifierResult:
        key = str(profile or "").strip()
        handler = self._handlers.get(key)
        if handler is None:
            raise KeyError(key or "<empty>")
        return handler(workspace_path)


def _run_python_repo_patch_verifier(workspace_path: str) -> VerifierResult:
    from runtime.execution.suckers.verify_skills import detect_project, run_checks

    profile = detect_project(workspace_path)
    results = run_checks(profile, timeout_per_check=60)
    findings = [
        VerifierFinding(
            name=result.name,
            command=result.command,
            passed=result.passed,
            exit_code=result.exit_code,
            stdout=result.stdout,
            stderr=result.stderr,
            duration_ms=result.duration_ms,
        )
        for result in results
    ]
    passed = all(finding.passed for finding in findings)
    return VerifierResult(
        profile="python_repo_patch",
        kind=profile.kind,
        passed=passed,
        findings=findings,
        summary=_summarize_failed_findings(findings),
    )


def build_default_loop_verifier_registry() -> LoopVerifierRegistry:
    registry = LoopVerifierRegistry()
    registry.register("python_repo_patch", _run_python_repo_patch_verifier)
    return registry
