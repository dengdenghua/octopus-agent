"""Spawn-level content-hash resume for ``call_agent_graph``.

The identity of a spawn is what it was asked to do - ``(agent_id, resolved
prompt, model tier, context digest)`` - hashed so an unchanged node replays
its recorded result instead of respawning.

Two rules the tests pin hardest:

* **Only completed, non-empty results are ever stored.** A failure, an empty
  output, or a never-finished spawn is exactly the work a resume exists to
  redo; caching any of them would pin one bad run onto every future resume.
* **Downstream identity is inherited through the resolved prompt.** A node's
  prompt embeds its upstream outputs, so a changed upstream shifts every
  dependent's key - the diamond below asserts the propagation explicitly.
"""

from __future__ import annotations

from typing import Any

import pytest

from runtime.execution.suckers import delegation_skills as ds
from runtime.execution.suckers.delegation_result_cache import (
    SpawnResultCache,
    compute_spawn_cache_key,
    reset_spawn_cache_store,
)

_DIAMOND = [
    {"id": "l", "prompt": "left facts"},
    {"id": "r", "prompt": "right facts"},
    {
        "id": "fold",
        "prompt": "reconcile L with R: {l.output} || {r.output}",
        "depends_on": ["l", "r"],
    },
]


class _FakeParallel:
    """Counts spawns; returns one success per spec, output derived from prompt.

    Fail-on-demand: ``fail_ids`` / ``empty_ids`` match on bb_key (node id).
    """

    def __init__(self) -> None:
        self.spawned: list[dict[str, Any]] = []
        self.fail_ids: set[str] = set()
        self.empty_ids: set[str] = set()

    def __call__(self, specs: Any = None, **_kw: Any) -> dict[str, Any]:
        successes: list[dict[str, Any]] = []
        failures: list[dict[str, Any]] = []
        for i, s in enumerate(list(specs or [])):
            key = str(s.get("bb_key") or "")
            if key in self.fail_ids:
                failures.append(
                    {
                        "bb_key": key,
                        "spec_index": i,
                        "agent_id": s.get("agent_id"),
                        "output": "",
                        "success": False,
                        "error": "boom",
                    }
                )
                continue
            out = "" if key in self.empty_ids else f"OUT[{s['prompt']}]"
            successes.append(
                {
                    "bb_key": key,
                    "spec_index": i,
                    "agent_id": s.get("agent_id"),
                    "output": out,
                    "success": True,
                }
            )
            self.spawned.append(s)
        return {"ok": bool(successes), "successes": successes, "failures": failures}


@pytest.fixture(autouse=True)
def _clean_store():
    reset_spawn_cache_store()
    yield
    reset_spawn_cache_store()


# ── the headline acceptance: replay, exact-respawn, redo ───────────


def test_same_graph_and_token_respawns_nothing(monkeypatch: Any) -> None:
    fake = _FakeParallel()
    monkeypatch.setattr(ds, "_call_agent_parallel", fake)

    first = ds._run_agent_graph(nodes=_DIAMOND)
    token = first["resume_token"]
    assert token
    assert len(fake.spawned) == 3

    second = ds._run_agent_graph(nodes=_DIAMOND, resume_token=token)
    assert len(fake.spawned) == 3, "resume must not spawn for unchanged nodes"
    assert sorted(second["replayed"]) == ["fold", "l", "r"]
    assert second["nodes"]["fold"]["output"] == first["nodes"]["fold"]["output"]
    assert second["nodes"]["l"]["replayed"] is True


def test_changing_only_the_last_node_respawns_exactly_one(monkeypatch: Any) -> None:
    fake = _FakeParallel()
    monkeypatch.setattr(ds, "_call_agent_parallel", fake)

    token = ds._run_agent_graph(nodes=_DIAMOND)["resume_token"]
    changed = [dict(n) for n in _DIAMOND]
    changed[-1]["prompt"] = "reconcile differently: {l.output} || {r.output}"
    fake.spawned.clear()

    second = ds._run_agent_graph(nodes=changed, resume_token=token)
    assert len(fake.spawned) == 1, "only the changed node should respawn"
    assert second["replayed"] == ["l", "r"]
    assert "differently" in fake.spawned[-1]["prompt"]


def test_changed_upstream_forces_the_downstream_to_respawn(monkeypatch: Any) -> None:
    fake = _FakeParallel()
    monkeypatch.setattr(ds, "_call_agent_parallel", fake)

    token = ds._run_agent_graph(nodes=_DIAMOND)["resume_token"]
    changed = [dict(n) for n in _DIAMOND]
    changed[0]["prompt"] = "left facts, revised"
    fake.spawned.clear()

    second = ds._run_agent_graph(nodes=changed, resume_token=token)
    # l changed -> its key moves; fold embeds {l.output} -> its resolved prompt
    # moves too. Only r replays.
    assert sorted(second["replayed"]) == ["r"]
    assert len(fake.spawned) == 2


def test_replayed_outputs_feed_downstream_resolution(monkeypatch: Any) -> None:
    """Resume is not just bookkeeping: a replayed upstream's recorded output is
    what the respawned downstream's prompt is resolved against.
    """
    fake = _FakeParallel()
    monkeypatch.setattr(ds, "_call_agent_parallel", fake)

    first = ds._run_agent_graph(nodes=_DIAMOND)
    token = first["resume_token"]
    left_output = first["nodes"]["l"]["output"]
    changed = [dict(n) for n in _DIAMOND]
    changed[-1]["prompt"] = "fold v2: {l.output} || {r.output}"

    ds._run_agent_graph(nodes=changed, resume_token=token)
    assert left_output in fake.spawned[-1]["prompt"]


# ── nothing incomplete ever enters the store ───────────────────────


def test_failed_node_is_not_cached_and_reruns(monkeypatch: Any) -> None:
    fake = _FakeParallel()
    fake.fail_ids = {"l"}
    monkeypatch.setattr(ds, "_call_agent_parallel", fake)

    first = ds._run_agent_graph(nodes=_DIAMOND)
    assert first["nodes"]["l"]["ok"] is False
    token = first["resume_token"]

    fake.fail_ids.clear()
    fake.spawned.clear()
    second = ds._run_agent_graph(nodes=_DIAMOND, resume_token=token)
    # l failed before -> re-runs; r succeeded -> replays; fold was skipped
    # upstream-failure -> re-runs.
    assert sorted(second["replayed"]) == ["r"]
    assert {s["bb_key"] for s in fake.spawned} == {"fold", "l"}


def test_empty_success_is_not_cached_and_reruns(monkeypatch: Any) -> None:
    fake = _FakeParallel()
    fake.empty_ids = {"l"}
    monkeypatch.setattr(ds, "_call_agent_parallel", fake)

    token = ds._run_agent_graph(nodes=_DIAMOND)["resume_token"]
    fake.empty_ids.clear()
    fake.spawned.clear()

    second = ds._run_agent_graph(nodes=_DIAMOND, resume_token=token)
    assert "l" not in second["replayed"]
    assert any(s["bb_key"] == "l" for s in fake.spawned)


def test_put_refuses_failures_and_empty_output() -> None:
    cache = SpawnResultCache(token="t")
    assert cache.put("k", {"success": False, "output": "text"}) is False
    assert cache.put("k", {"success": True, "output": ""}) is False
    assert cache.put("k", {"success": True, "output": "  \n"}) is False
    assert cache.get("k") is None
    assert cache.put("k", {"success": True, "output": "real", "parsed": {"a": 1}}) is True
    hit = cache.get("k")
    assert hit is not None and hit["output"] == "real" and hit["parsed"] == {"a": 1}


# ── token lifecycle ────────────────────────────────────────────────


def test_unknown_token_fails_loud_before_spawning(monkeypatch: Any) -> None:
    fake = _FakeParallel()
    monkeypatch.setattr(ds, "_call_agent_parallel", fake)
    out = ds._run_agent_graph(nodes=_DIAMOND, resume_token="typo-token")
    assert out["ok"] is False
    assert "resume_token" in (out.get("error") or "")
    assert fake.spawned == []


def test_two_tokens_do_not_share_entries(monkeypatch: Any) -> None:
    fake = _FakeParallel()
    monkeypatch.setattr(ds, "_call_agent_parallel", fake)

    ds._run_agent_graph(nodes=_DIAMOND)
    cold = ds._run_agent_graph(nodes=_DIAMOND)  # fresh token: cold run
    assert len(fake.spawned) == 6
    assert cold["replayed"] == []


# ── key hygiene ────────────────────────────────────────────────────


def test_key_is_stable_across_volatile_context_noise() -> None:
    base = {"model_name": "m1", "system_addendum": "focus"}
    noisy = {
        **base,
        "event_emitter": lambda _e: None,
        "react_stack": object(),
        "subagent_route_decision": {"action": "allow", "when": "now"},
    }
    assert compute_spawn_cache_key(
        agent_id="r", prompt="p", context=base
    ) == compute_spawn_cache_key(agent_id="r", prompt="p", context=noisy)


def test_key_moves_on_any_identity_bearing_input() -> None:
    k = compute_spawn_cache_key(agent_id="r", prompt="p", context={"model_name": "m"})
    assert k != compute_spawn_cache_key(agent_id="o", prompt="p", context={"model_name": "m"})
    assert k != compute_spawn_cache_key(agent_id="r", prompt="q", context={"model_name": "m"})
    assert k != compute_spawn_cache_key(agent_id="r", prompt="p", context={"model_name": "m2"})
    assert k != compute_spawn_cache_key(
        agent_id="r", prompt="p", cheap=True, context={"model_name": "m"}
    )
    assert k != compute_spawn_cache_key(
        agent_id="r", prompt="p", context={"model_name": "m"}, extra={"output_schema": {"a": 1}}
    )


def test_isolated_nodes_never_replay(monkeypatch: Any) -> None:
    """An isolated node's product is a diff against a worktree that is deleted
    on exit - replaying it would hand back a diff with no branch behind it.
    """
    fake = _FakeParallel()
    monkeypatch.setattr(ds, "_call_agent_parallel", fake)

    graph = [dict(n) for n in _DIAMOND]
    graph[0]["isolate"] = True
    token = ds._run_agent_graph(nodes=graph)["resume_token"]
    fake.spawned.clear()

    second = ds._run_agent_graph(nodes=graph, resume_token=token)
    assert "l" not in second["replayed"]
    assert any(s["bb_key"] == "l" for s in fake.spawned)
