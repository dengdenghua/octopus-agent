"""Tests for the background-task heartbeat feature in react_loop.

Covers:
  1. ``_background_task_info_from_observation`` parses a rendered
     observation that wraps a JSON snapshot with ``task_id`` +
     ``running=True`` (or ``status="running"``).
  2. The same helper returns ``None`` for missing ``task_id`` and
     for terminal statuses (``completed`` / ``failed``).
  3. Integration-light: a fake step list drives the registry +
     heartbeat formatter and we verify the heartbeat string gets
     produced after 5 iterations.
"""

from __future__ import annotations

import json

from runtime.core.cerebrum.react_loop import (
    _background_task_info_from_observation,
    _format_background_task_heartbeat,
)

# ─── 1. Helper parses a running background_exec observation ─────


def test_background_task_info_parses_running_payload() -> None:
    payload = {
        "task_id": "abc",
        "status": "running",
        "running": True,
        "argv": ["sleep", "30"],
        "stdout": "",
        "stderr": "",
    }
    obs = "(real tool execution succeeded) background_exec\n" + json.dumps(payload)

    info = _background_task_info_from_observation(obs)

    assert info is not None
    assert info["task_id"] == "abc"
    assert info["running"] is True
    assert info["status"] == "running"


def test_background_task_info_parses_running_via_status_only() -> None:
    # Some renderers might omit the ``running`` boolean and only set
    # status — the helper should still treat it as a live task.
    payload = {"task_id": "xyz", "status": "running", "stdout": ""}
    obs = "header line\n" + json.dumps(payload)

    info = _background_task_info_from_observation(obs)

    assert info is not None
    assert info["task_id"] == "xyz"


# ─── 2. Helper rejects bogus / terminal payloads ───────────────


def test_background_task_info_returns_none_when_no_task_id() -> None:
    obs = "header\n" + json.dumps({"status": "running", "running": True})
    assert _background_task_info_from_observation(obs) is None


def test_background_task_info_returns_none_for_completed_status() -> None:
    payload = {
        "task_id": "done-1",
        "status": "completed",
        "running": False,
        "exit_code": 0,
    }
    obs = "header\n" + json.dumps(payload)
    assert _background_task_info_from_observation(obs) is None


def test_background_task_info_returns_none_for_failed_status() -> None:
    payload = {
        "task_id": "failed-1",
        "status": "failed",
        "running": False,
        "exit_code": 1,
    }
    obs = "header\n" + json.dumps(payload)
    assert _background_task_info_from_observation(obs) is None


def test_background_task_info_returns_none_on_non_json_payload() -> None:
    assert _background_task_info_from_observation("just plain text") is None
    assert _background_task_info_from_observation("") is None
    assert _background_task_info_from_observation(None) is None


# ─── 3. Integration-light: simulate the loop's bookkeeping ─────


def _simulate_loop_with_observations(
    observations: list[str],
) -> list[tuple[int, str | None]]:
    """Mini reproduction of the heartbeat slice of stream_react_loop.

    Returns a list of ``(iteration_index, nudge_or_none)`` so the
    test can assert when the heartbeat fires and what it says. No
    LLM, no tools, no executor — just the registry + period check
    that lives inside the real loop.
    """
    known: dict[str, dict] = {}
    fired: list[tuple[int, str | None]] = []

    for i, obs in enumerate(observations):
        info = _background_task_info_from_observation(obs)
        if info is not None:
            tid = info.get("task_id")
            if isinstance(tid, str) and tid:
                known[tid] = info

        nudge: str | None = None
        if i > 0 and i % 5 == 0 and known:
            nudge = _format_background_task_heartbeat(list(known.keys()))
        fired.append((i, nudge))

    return fired


def test_heartbeat_injected_after_five_iterations() -> None:
    running_obs = "header\n" + json.dumps(
        {"task_id": "bg_abc123", "status": "running", "running": True},
    )
    quiet_obs = "header\n" + json.dumps({"unrelated": "ok"})

    # Register the bg task at iteration 0, then quiet steps.
    observations = [running_obs] + [quiet_obs] * 9

    fired = _simulate_loop_with_observations(observations)

    # Iter 0: registers but doesn't fire (i > 0 guard)
    assert fired[0][1] is None
    # Iters 1..4: nothing
    for idx in range(1, 5):
        assert fired[idx][1] is None, f"unexpected nudge at iter {idx}"
    # Iter 5: heartbeat fires
    nudge_5 = fired[5][1]
    assert nudge_5 is not None
    assert "[background-task-tracker]" in nudge_5
    assert "bg_abc123" in nudge_5
    assert "read_shell_output" in nudge_5
    assert "kill_shell" in nudge_5


def test_heartbeat_does_not_fire_without_registered_tasks() -> None:
    quiet_obs = "header\n" + json.dumps({"unrelated": "ok"})
    fired = _simulate_loop_with_observations([quiet_obs] * 8)

    # No task ever registered, so no heartbeat at iter 5 either.
    for idx, nudge in fired:
        assert nudge is None, f"unexpected nudge at iter {idx}: {nudge!r}"


def test_heartbeat_lists_multiple_task_ids() -> None:
    obs_a = "header\n" + json.dumps(
        {"task_id": "bg_a", "status": "running", "running": True},
    )
    obs_b = "header\n" + json.dumps(
        {"task_id": "bg_b", "status": "running", "running": True},
    )
    quiet = "header\n" + json.dumps({"unrelated": "ok"})

    observations = [obs_a, obs_b] + [quiet] * 5  # iter 5 should fire
    fired = _simulate_loop_with_observations(observations)

    nudge_5 = fired[5][1]
    assert nudge_5 is not None
    assert "bg_a" in nudge_5
    assert "bg_b" in nudge_5


def test_format_heartbeat_string_shape() -> None:
    rendered = _format_background_task_heartbeat(["bg_1", "bg_2"])
    # Header tag is the first thing the model sees — keep it stable.
    assert rendered.startswith("[background-task-tracker]\n")
    assert "Background processes still registered: bg_1, bg_2." in rendered
    assert "read_shell_output(task_id)" in rendered
    assert "kill_shell(task_id)" in rendered
    assert "finalised the task without checking" in rendered
