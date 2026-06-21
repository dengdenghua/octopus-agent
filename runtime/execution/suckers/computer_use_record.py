"""Record a successful computer-use loop as a journal Trajectory.

This closes the *record → skill* loop for desktop automation. A successful
vision-action run (``computer_use_loop``) is distilled into a
:class:`Trajectory` whose steps reference the **registered** GUI skills
(``mouse_click`` / ``keyboard_type`` / ``keyboard_press`` / ``mouse_move``),
then written to the journal. From there the existing :class:`SkillForge`
picks it up automatically: it clusters repeated runs of the same action
pattern and forges a composite "macro" skill — *without any new forge code*.

The safety story is deliberate. Every GUI primitive is
``is_dangerous_tool() == True`` (a click or keystroke can do anything), so
the forge's immune gate refuses to *auto-promote* a recorded macro to a
public skill. Rather than silently dropping it (the prior behaviour), the
forge now routes such a candidate to the governed quarantine / approval
queue — see ``SkillForge.run`` and ``SkillForgeResult.quarantined``. So the
closure is: record → forge → immune gate → human approval, never
record → silently-auto-grant.

The recorder is best-effort and side-channel: a failure here must never
break the live computer-use loop.
"""
from __future__ import annotations

from typing import Any

from runtime.platform.models.execution import (
    ExecutionResult,
    Step,
    ToolCall,
    Trajectory,
    TrajectoryOutcome,
)
from runtime.platform.models.primitives import ArmId, SkillId, TaskId, new_id

# Loop action ``kind`` → registered GUI skill name (``sucker_id``). These are
# the names registered by ``computer_api_skills``; SkillForge replays a forged
# macro by ``registry.get(name)``, so the mapping MUST hit real skills or the
# forged composite can't reconstruct. ``wait`` has no skill and is dropped:
# it is replay timing noise, not a reusable capability, and keeping it would
# pollute the pattern signature so repeated runs cluster less.
_ACTION_TO_SKILL: dict[str, str] = {
    "click": "mouse_click",
    "type": "keyboard_type",
    "key": "keyboard_press",
    "move": "mouse_move",
}

# Forge ignores trajectories with fewer than 2 steps (``propose`` skips
# ``step_count < 2``); recording a 1-action run would be dead weight.
_MIN_STEPS = 2


def loop_result_to_trajectory(loop_result: Any) -> Trajectory | None:
    """Convert a *successful* computer-use loop result into a Trajectory.

    Returns ``None`` when the run did not succeed, carried no replayable
    actions, or had fewer than ``_MIN_STEPS`` mappable steps.
    """
    if not isinstance(loop_result, dict) or loop_result.get("status") != "success":
        return None

    actions = loop_result.get("actions_taken") or []
    steps: list[Step] = []
    for action in actions:
        if not isinstance(action, dict):
            continue
        skill_name = _ACTION_TO_SKILL.get(action.get("action"))
        if skill_name is None:
            continue  # drop wait / unknown — not a reusable capability
        args = {k: v for k, v in action.items() if k != "action"}
        call = ToolCall(
            caller="computer_use_loop",
            sucker_id=SkillId(skill_name),
            args=args,
        )
        result = ExecutionResult(
            call_id=call.call_id,
            status="success",
            output="ok",
        )
        steps.append(
            Step(
                step_id=len(steps),
                node_id="computer_use_loop",
                action=call,
                result=result,
                immune_verdict="allow",
                args_template=dict(args),
            )
        )

    if len(steps) < _MIN_STEPS:
        return None

    return Trajectory(
        task_id=TaskId(new_id()),
        arm_id=ArmId(str(new_id())),
        strategy_id="computer_use",
        steps=steps,
        outcome=TrajectoryOutcome(success=True),
    )


def record_successful_loop(journal: Any, loop_result: Any) -> Trajectory | None:
    """Write a successful loop to the journal so SkillForge can distil it.

    Best-effort: any error (no journal, missing method, write failure) is
    swallowed so the live automation loop is never broken by recording.
    Returns the written Trajectory, or ``None`` if nothing was recorded.
    """
    traj = loop_result_to_trajectory(loop_result)
    if traj is None or journal is None:
        return None
    try:
        journal.write_trajectory(traj)
    except Exception:  # noqa: BLE001 — recording must never break the loop
        return None
    return traj
