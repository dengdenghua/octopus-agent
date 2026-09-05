"""Offline deterministic simulation for Tentacle procedures."""

from __future__ import annotations

import copy
import time
from dataclasses import dataclass, field
from typing import Any

from .contract import DeviceManifest
from .procedure import Procedure


@dataclass(frozen=True, slots=True)
class SimulationStepResult:
    step_id: str
    action: str
    success: bool
    before: dict[str, Any]
    after: dict[str, Any]
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "action": self.action,
            "success": self.success,
            "before": self.before,
            "after": self.after,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True, slots=True)
class SimulationReport:
    procedure_id: str
    device_id: str
    contract_version: str
    driver_version: str
    success: bool
    initial_state: dict[str, Any]
    final_state: dict[str, Any]
    steps: tuple[SimulationStepResult, ...]
    started_at: float
    finished_at: float
    errors: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "procedure_id": self.procedure_id,
            "device_id": self.device_id,
            "contract_version": self.contract_version,
            "driver_version": self.driver_version,
            "success": self.success,
            "initial_state": self.initial_state,
            "final_state": self.final_state,
            "steps": [step.to_dict() for step in self.steps],
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "errors": list(self.errors),
        }


@dataclass(slots=True)
class SimulationScenario:
    initial_state: dict[str, Any] = field(default_factory=dict)
    """Faults keyed by step_id. Values are human-readable injected failures."""
    injected_faults: dict[str, str] = field(default_factory=dict)


class ProcedureSimulator:
    """Evaluates a procedure without acquiring a lease or calling hardware."""

    def simulate(
        self,
        procedure: Procedure,
        manifest: DeviceManifest,
        scenario: SimulationScenario | None = None,
    ) -> SimulationReport:
        if procedure.device_id != manifest.device_id:
            raise ValueError("procedure and manifest target different devices")
        scenario = scenario or SimulationScenario()
        started_at = time.time()
        state = copy.deepcopy(scenario.initial_state)
        initial_state = copy.deepcopy(state)
        results: list[SimulationStepResult] = []
        version_errors: list[str] = []
        if (
            procedure.expected_contract_version is not None
            and procedure.expected_contract_version != manifest.contract_version
        ):
            version_errors.append("device contract version changed")
        if (
            procedure.expected_driver_version is not None
            and procedure.expected_driver_version != manifest.driver_version
        ):
            version_errors.append("device driver version changed")
        if version_errors:
            return SimulationReport(
                procedure.procedure_id,
                procedure.device_id,
                manifest.contract_version,
                manifest.driver_version,
                False,
                initial_state,
                copy.deepcopy(state),
                (),
                started_at,
                time.time(),
                tuple(version_errors),
            )

        for step in procedure.steps:
            before = copy.deepcopy(state)
            errors = manifest.validate_action(step.action, step.arguments)
            warnings: list[str] = []
            action = manifest.action(step.action)
            if action is not None:
                for condition in action.preconditions:
                    try:
                        satisfied = condition.evaluate(state)
                    except ValueError as exc:
                        errors.append(f"invalid precondition: {exc}")
                        continue
                    if not satisfied:
                        errors.append(
                            f"precondition failed: {condition.key} {condition.operator} {condition.value!r}"
                        )
            injected = scenario.injected_faults.get(step.step_id)
            if injected:
                errors.append(f"injected fault: {injected}")

            if not errors and action is not None:
                if not action.effects:
                    warnings.append("action declares no simulated state effects")
                for effect in action.effects:
                    try:
                        effect.apply(state)
                    except (TypeError, ValueError) as exc:
                        errors.append(f"state transition failed: {exc}")
                        state = before
                        break

            results.append(
                SimulationStepResult(
                    step.step_id,
                    step.action,
                    not errors,
                    before,
                    copy.deepcopy(state),
                    tuple(errors),
                    tuple(warnings),
                )
            )
            if errors:
                break

        finished_at = time.time()
        return SimulationReport(
            procedure.procedure_id,
            procedure.device_id,
            manifest.contract_version,
            manifest.driver_version,
            bool(results)
            and all(result.success for result in results)
            and len(results) == len(procedure.steps),
            initial_state,
            copy.deepcopy(state),
            tuple(results),
            started_at,
            finished_at,
        )
