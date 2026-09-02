from __future__ import annotations

from runtime.tentacle import (
    ActionSpec,
    DeviceManifest,
    Procedure,
    ProcedureSimulator,
    ProcedureStep,
    SimulationScenario,
    StateCondition,
    StateEffect,
    ValueConstraint,
)


def _manifest() -> DeviceManifest:
    return DeviceManifest(
        device_id="heater-1",
        kind="heater",
        platform="test",
        driver_version="driver-2",
        actions=(
            ActionSpec(
                name="heat",
                arguments=(ValueConstraint("target", required=True, minimum=10, maximum=60),),
                preconditions=(StateCondition("door_closed", "eq", True),),
                effects=(StateEffect("temperature", "set", 40),),
            ),
            ActionSpec(
                name="cool",
                effects=(StateEffect("temperature", "decrement", 10),),
            ),
        ),
    )


def _procedure() -> Procedure:
    return Procedure(
        "simulation-1",
        "heater-1",
        (
            ProcedureStep("heat-1", "heat", {"target": 40}),
            ProcedureStep("cool-1", "cool"),
        ),
    )


def test_simulation_applies_deterministic_state_transitions() -> None:
    report = ProcedureSimulator().simulate(
        _procedure(),
        _manifest(),
        SimulationScenario(initial_state={"door_closed": True, "temperature": 20}),
    )

    assert report.success
    assert report.final_state == {"door_closed": True, "temperature": 30}
    assert report.steps[0].before["temperature"] == 20
    assert report.steps[0].after["temperature"] == 40


def test_failed_precondition_stops_before_later_steps() -> None:
    report = ProcedureSimulator().simulate(
        _procedure(),
        _manifest(),
        SimulationScenario(initial_state={"door_closed": False, "temperature": 20}),
    )

    assert not report.success
    assert len(report.steps) == 1
    assert "precondition failed" in report.steps[0].errors[0]
    assert report.final_state["temperature"] == 20


def test_fault_injection_does_not_apply_action_effects() -> None:
    report = ProcedureSimulator().simulate(
        _procedure(),
        _manifest(),
        SimulationScenario(
            initial_state={"door_closed": True, "temperature": 20},
            injected_faults={"heat-1": "temperature sensor unavailable"},
        ),
    )

    assert not report.success
    assert report.final_state["temperature"] == 20
    assert report.steps[0].errors == ("injected fault: temperature sensor unavailable",)


def test_driver_version_drift_fails_before_simulating_steps() -> None:
    procedure = _procedure()
    procedure.expected_driver_version = "driver-1"

    report = ProcedureSimulator().simulate(procedure, _manifest())

    assert not report.success
    assert report.steps == ()
    assert report.errors == ("device driver version changed",)
