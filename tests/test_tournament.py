"""Tournament selection — pure best-of-N picker + the wired skill handler."""

from __future__ import annotations

import hashlib
import threading
from dataclasses import replace
from pathlib import Path

import pytest

from runtime.execution.artifact_contracts import HandoffRecorder
from runtime.execution.request import current_execution_request
from runtime.execution.subagents import bridge
from runtime.execution.subagents.tournament import Candidate, select_winner
from runtime.execution.suckers import delegation_skills as ds
from runtime.execution.suckers import ephemeral_agents
from runtime.execution.suckers.delegation_budget import orchestration_budget_scope
from runtime.platform.process.scope import resolve_execution_scope
from runtime.platform.process.session import current_session
from runtime.safety.approval.cancellation import CancellationSource, scoped_cancellation
from tests.test_artifact_handoff import _events
from tests.test_isolated_subagent import _git, _host
from tests.test_worktree_loop import _worktree_count

# ── pure primitive: select_winner ───────────────────────────────────


def _c(cid, output, ok=True):
    return Candidate(id=cid, output=output, ok=ok, meta={"files": [f"{cid}.py"]})


def test_no_viable_candidate_returns_none() -> None:
    res = select_winner([_c("a", "", ok=True), _c("b", "x", ok=False)], judge=lambda v: "a")
    assert res.winner is None
    assert res.decided_by == "none"
    assert res.viable_count == 0


def test_single_viable_wins_unjudged() -> None:
    called = {"n": 0}

    def judge(_v):
        called["n"] += 1
        return "a"

    res = select_winner([_c("a", "diff", ok=True), _c("b", "", ok=False)], judge=judge)
    assert res.winner.id == "a"
    assert res.decided_by == "only_candidate"
    assert called["n"] == 0  # judge not consulted for a single viable candidate


def test_judge_picks_winner_and_runners_up() -> None:
    cands = [_c("a", "dA"), _c("b", "dB"), _c("c", "dC")]
    res = select_winner(cands, judge=lambda v: "b")
    assert res.winner.id == "b"
    assert res.decided_by == "judge"
    assert [c.id for c in res.runners_up] == ["a", "c"]


def test_judge_abstain_or_junk_falls_back_to_first_viable() -> None:
    cands = [_c("a", "dA"), _c("b", "dB")]
    assert select_winner(cands, judge=lambda v: None).winner.id == "a"
    res = select_winner(cands, judge=lambda v: "nonexistent")
    assert res.winner.id == "a"
    assert res.decided_by == "judge_abstained"


# ── wired skill handler ──────────────────────────────────────────────


@pytest.fixture
def host(tmp_path, monkeypatch):
    monkeypatch.setattr(bridge, "_REGISTRY", None)
    monkeypatch.setattr(
        ds, "_allowed_agent_ids", lambda: {"coder", "reviewer", "debugger", "researcher"}
    )
    return _host(tmp_path)


def test_handler_missing_goal_errors() -> None:
    r = ds._run_tournament(goal="")
    assert r["ok"] is False
    assert "required" in r["error"]


def test_handler_requires_host_scope(monkeypatch) -> None:
    monkeypatch.setattr(ds, "_call_agent_parallel", lambda **kw: pytest.fail("unexpected spawn"))
    result = ds._run_tournament(goal="implement", session={"workspace_path": "/repo"})
    assert not result["ok"] and "host-scoped task" in result["error"]


def test_handler_cannot_redirect_project(host, monkeypatch):
    repo, parent, log = host
    monkeypatch.setattr(ds, "_call_agent_parallel", lambda **kw: pytest.fail("unexpected spawn"))
    result = ds._run_tournament(goal="implement", session=parent, repo_root=str(repo.parent))
    assert not result["ok"] and "must match" in result["error"]
    assert not log.path.exists()


def test_handler_runs_real_scoped_candidates_and_readonly_judges(host, monkeypatch):
    repo, parent, log = host
    (repo / "README.md").write_text("staged\n")
    _git(repo, "add", "README.md")
    (repo / "README.md").write_text("working input\n")
    before_index = (repo / ".git" / "index").read_bytes()
    before_head = _git(repo, "rev-parse", "HEAD")
    task = parent.metadata["_execution_task"]
    candidates, judges = [], []
    lock = threading.Lock()

    def runner(prompt, **_kw):
        request = current_execution_request()
        session = current_session()
        workspace = Path(session.metadata["workspace_path"])
        assert request.task.resources is task.resources
        assert request.task.parent_task_id == task.task_id
        assert request.task.actor_id == task.actor_id
        if not request.task.permissions.writable_roots:
            assert workspace == repo
            assert not resolve_execution_scope(session).allows_write(repo / "README.md")
            assert request.task.permissions.allows_read(
                Path(parent.metadata["_artifact_output_root"])
            )
            assert "Full patch:" in prompt and "SHA-256:" in prompt
            judges.append(request.task.task_id)
            return '{"verdict":"candidate_2","reason":"consistent implementation"}'
        with lock:
            candidates.append((workspace, request.task.task_id))
        assert workspace != repo and not request.task.permissions.allows_write(repo)
        assert (workspace / "README.md").read_text() == "working input\n"
        assert request.task.artifacts.inputs[0].path == workspace / "README.md"
        (workspace / "README.md").write_text(f"implemented {request.task.task_id}\n")
        (workspace / "asset.bin").write_bytes(b"\x00\xffbinary")
        return "implemented"

    monkeypatch.setattr(bridge, "_RUNNER", runner)
    monkeypatch.setattr(ephemeral_agents, "_EPHEMERAL_RUNNER", lambda call: runner(call.user_prompt))
    result = ds._run_tournament(
        goal="implement X",
        n=3,
        judge_n=2,
        agent_id="coder",
        session=parent,
        input_files=["README.md"],
        output_files=["README.md", "asset.bin"],
        timeout_s=30,
    )
    assert result["ok"], result
    assert result.get("judgment", {}).get("ok"), result.get("judgment")
    assert result["decided_by"] == "judge" and result["winner"]["id"] == "candidate_2", result
    assert len(candidates) == 3 and len(judges) == 2 and result["spawns_used"] == 5
    assert len({child for _, child in candidates} | set(judges)) == 5
    assert all(not workspace.exists() for workspace, _ in candidates)
    assert _worktree_count(repo) == 1
    assert (repo / "README.md").read_text() == "working input\n"
    assert not (repo / "asset.bin").exists()
    assert (repo / ".git" / "index").read_bytes() == before_index
    assert _git(repo, "rev-parse", "HEAD") == before_head
    patch_ref = result["winner"]["worktree"]["patch"]
    patch = Path(patch_ref["path"])
    assert hashlib.sha256(patch.read_bytes()).hexdigest() == patch_ref["sha256"]
    _git(repo, "apply", "--check", str(patch))
    selected = _events(log)[-1]
    assert selected["phase"] == "worktree_selected" and selected["applied"] is False
    assert selected["selection_id"] == result["selection_id"]
    assert selected["worktree"] == result["winner"]["worktree"]
    assert result["retry_allowed"] is False


def test_failed_contracts_keep_patches_and_are_not_candidates(host, monkeypatch):
    repo, parent, log = host

    def runner(*_args, **_kw):
        workspace = Path(current_session().metadata["workspace_path"])
        (workspace / "unexpected.txt").write_text("partial implementation")
        return "done"

    monkeypatch.setattr(bridge, "_RUNNER", runner)
    monkeypatch.setattr(ds, "_call_agent_vote", lambda **kw: pytest.fail("unexpected judge"))
    result = ds._run_tournament(
        goal="implement",
        n=2,
        agent_id="coder",
        session=parent,
        output_files=["README.md"],
        timeout_s=30,
    )
    assert not result["ok"] and result["winner"] is None and result["viable_count"] == 0
    assert len(result["candidates"]) == 2 and result["spawns_used"] == 2
    for candidate in result["candidates"]:
        assert not candidate["worktree"]["contract_valid"]
        assert "undeclared" in candidate["error"]
        assert Path(candidate["worktree"]["patch"]["path"]).is_file()
    assert _worktree_count(repo) == 1 and _events(log)[-1]["winner"] is None


@pytest.mark.parametrize("failure", ["tamper", "cancel", "journal"])
def test_selection_failure_preserves_candidates_and_does_not_name_winner(
    host, monkeypatch, failure
):
    _repo, parent, log = host
    source = CancellationSource()
    before_write = parent.metadata["_execution_handoff_recorder"].write

    def record(receipt):
        if failure == "journal" and receipt["phase"] == "worktree_selected":
            raise OSError("selection journal full")
        before_write(receipt)

    parent.metadata["_execution_handoff_recorder"] = HandoffRecorder(record)

    def runner(*_args, **_kw):
        (Path(current_session().metadata["workspace_path"]) / "README.md").write_text("candidate\n")
        return "done"

    def judge(**_kw):
        if failure == "cancel":
            source.cancel(reason="user stopped tournament")
        elif failure == "tamper":
            exported = next(r for r in _events(log) if r["phase"] == "worktree_exported")
            Path(exported["patch"]["path"]).write_text("substituted patch")
        return {"ok": True, "verdict": "candidate_1"}

    monkeypatch.setattr(bridge, "_RUNNER", runner)
    monkeypatch.setattr(ds, "_call_agent_vote", judge)
    with scoped_cancellation(source.token):
        result = ds._run_tournament(
            goal="implement", n=2, agent_id="coder", session=parent, max_workers=1, timeout_s=30
        )
    assert not result["ok"] and result["winner"] is None, result
    assert result["status"] == "selection_failed" and result["retry_allowed"] is False
    assert len(result["candidates"]) == 2
    assert all(Path(c["worktree"]["patch"]["path"]).exists() for c in result["candidates"])
    assert all(row["phase"] != "worktree_selected" for row in _events(log))


def test_tournament_respects_enclosing_spawn_budget(host, monkeypatch):
    _repo, parent, _log = host
    seen = []

    def runner(*_args, **_kw):
        seen.append(current_execution_request().task.task_id)
        (Path(current_session().metadata["workspace_path"]) / "README.md").write_text("candidate\n")
        return "done"

    monkeypatch.setattr(bridge, "_RUNNER", runner)
    monkeypatch.setattr(ds, "_call_agent_vote", lambda **kw: pytest.fail("unexpected judge"))
    with orchestration_budget_scope(1) as budget:
        result = ds._run_tournament(
            goal="implement", n=3, agent_id="coder", session=parent, max_workers=1, timeout_s=30
        )
        assert budget.used == 1
    assert result["ok"] and result["decided_by"] == "only_candidate", result
    assert result["spawns_used"] == 1 and len(seen) == 1
    assert result["candidate_count"] == 3 and result["viable_count"] == 1


def test_expired_or_cancelled_tournament_does_not_spawn(host, monkeypatch):
    _repo, parent, log = host
    task = parent.metadata["_execution_task"]
    parent.metadata["_execution_task"] = replace(
        task, resources=replace(task.resources, deadline=0)
    )
    monkeypatch.setattr(ds, "_call_agent_parallel", lambda **kw: pytest.fail("unexpected spawn"))
    result = ds._run_tournament(goal="implement", session=parent)
    assert not result["ok"] and result["status"] == "preflight_failed"
    parent.metadata["_execution_task"] = task
    source = CancellationSource()
    source.cancel(reason="already stopped")
    with scoped_cancellation(source.token):
        result = ds._run_tournament(goal="implement", session=parent)
    assert not result["ok"] and "already stopped" in result["error"]
    assert not log.path.exists()
