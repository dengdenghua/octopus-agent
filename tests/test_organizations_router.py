"""Smoke tests for /api/organizations/* REST endpoints."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from runtime.safety.evolution.subagent_policy import SubagentPolicyStore  # noqa: E402
from runtime.safety.organization import (  # noqa: E402
    AgentSpec,
    CoordinationProtocol,
    Role,
    TeamTopology,
)
from runtime.safety.organization.forge import save_registry  # noqa: E402
from runtime.sensing.gateway.organizations_router import (  # noqa: E402
    create_organizations_router,
)


@pytest.fixture
def app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir(exist_ok=True)
    a = FastAPI()
    a.include_router(create_organizations_router())
    return a


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def test_list_topologies_empty(client: TestClient) -> None:
    """A fresh data_dir auto-seeds the four built-in topologies."""
    r = client.get("/api/organizations/topologies")
    assert r.status_code == 200
    body = r.json()
    # Built-ins are seeded on first boot so multi-agent dispatch works
    # out of the box. The count is the four shipped recipes.
    assert body["count"] == 4
    names = {t["name"] for t in body["topologies"]}
    assert {
        "research_swarm_v1",
        "code_review_team_v1",
        "refactor_pair_v1",
        "debug_team_v1",
    } == names


def test_list_topologies_after_save(client: TestClient, tmp_path: Path) -> None:
    t = TeamTopology(
        name="t",
        protocol=CoordinationProtocol.SEQUENTIAL,
        agents={Role.GENERATOR: AgentSpec(agent_id="g")},
        task_bucket="b",
    )
    save_registry({t.fingerprint: t})
    r = client.get("/api/organizations/topologies")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 1
    assert body["topologies"][0]["fingerprint"] == t.fingerprint
    assert body["topologies"][0]["subagent_policy"]["status"] == "clear"


def test_list_topologies_marks_operator_retired_agent(
    client: TestClient,
    tmp_path: Path,
) -> None:
    t = TeamTopology(
        name="blocked-team",
        protocol=CoordinationProtocol.SEQUENTIAL,
        agents={Role.GENERATOR: AgentSpec(agent_id="g")},
        task_bucket="b",
    )
    save_registry({t.fingerprint: t})
    SubagentPolicyStore(tmp_path / "data" / "subagent_policy.json").decide(
        "g",
        action="retire",
        reason="operator retired g",
        evidence_item_ids=["route-1"],
        actor="operator-test",
    )

    r = client.get("/api/organizations/topologies")

    assert r.status_code == 200
    policy = r.json()["topologies"][0]["subagent_policy"]
    assert policy["status"] == "blocked"
    assert policy["blocked"] is True
    assert policy["retired"][0]["role"] == "generator"
    assert policy["retired"][0]["agent_id"] == "g"


def test_get_topology_404(client: TestClient) -> None:
    r = client.get("/api/organizations/topologies/nope")
    assert r.status_code == 404


def test_list_proposals_empty(client: TestClient) -> None:
    r = client.get("/api/organizations/topology-proposals")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 0
    assert body["proposals"] == []
    assert body["persisted_count"] == 0
    assert body["subagent_promotion_count"] == 0


def test_list_proposals_returns_persisted_payload(
    client: TestClient, tmp_path: Path,
) -> None:
    payload = {
        "ts": 0,
        "proposals": [
            {
                "kind": "swap_agent",
                "base_topology": "abc",
                "bucket": "b",
                "detail": {"role": "generator", "new_agent": "bob"},
                "confidence": 0.7,
                "rationale": "test",
            },
        ],
    }
    (tmp_path / "data" / "topology_proposals.json").write_text(
        json.dumps(payload), encoding="utf-8",
    )
    r = client.get("/api/organizations/topology-proposals")
    body = r.json()
    assert body["count"] == 1
    assert body["proposals"][0]["kind"] == "swap_agent"
    assert body["persisted_count"] == 1


def test_list_proposals_includes_strong_subagent_promotion(
    client: TestClient,
    tmp_path: Path,
) -> None:
    from runtime.memory.learning.review_queue import ReviewQueue

    base = TeamTopology(
        name="orig",
        protocol=CoordinationProtocol.SEQUENTIAL,
        agents={Role.GENERATOR: AgentSpec(agent_id="legacy-generator")},
        task_bucket="code",
    )
    save_registry({base.fingerprint: base})
    queue = ReviewQueue(tmp_path / "data" / "review_queue.json")
    for idx in range(3):
        added = queue.add_from_task_run_review({
            "status": "completed",
            "task_id": f"task-{idx}",
            "thread_id": "thread-1",
            "turn_id": f"turn-{idx}",
            "agent_id": "generator",
            "learning_candidates": [
                {
                    "kind": "subagent_output",
                    "priority": "P1",
                    "memory_bucket": "experience",
                    "title": f"generator sample {idx}",
                    "text": f"generator output {idx}",
                    "subagent": {
                        "role": "generator",
                        "agent_id": "generator",
                        "files_touched": ["runtime/example.py"],
                    },
                }
            ],
        })
        queue.decide(added["items"][0]["id"], action="promoted", reason="good")

    response = client.get("/api/organizations/topology-proposals")
    body = response.json()

    assert response.status_code == 200
    assert body["subagent_promotion_count"] == 1
    assert body["proposals"][0]["detail"]["source"] == "subagent_fitness"
    assert body["proposals"][0]["detail"]["new_agent"] == "generator"
    assert body["proposals"][0]["rank_score"] >= body["proposals"][0]["confidence"]


def test_promote_strong_subagent_live_proposal(
    client: TestClient,
    tmp_path: Path,
) -> None:
    from runtime.memory.learning.review_queue import ReviewQueue

    base = TeamTopology(
        name="orig",
        protocol=CoordinationProtocol.SEQUENTIAL,
        agents={Role.GENERATOR: AgentSpec(agent_id="legacy-generator")},
        task_bucket="code",
    )
    save_registry({base.fingerprint: base})
    queue = ReviewQueue(tmp_path / "data" / "review_queue.json")
    for idx in range(3):
        added = queue.add_from_task_run_review({
            "status": "completed",
            "task_id": f"task-{idx}",
            "thread_id": "thread-1",
            "turn_id": f"turn-{idx}",
            "agent_id": "generator",
            "learning_candidates": [
                {
                    "kind": "subagent_output",
                    "priority": "P1",
                    "memory_bucket": "experience",
                    "title": f"generator sample {idx}",
                    "text": f"generator output {idx}",
                    "subagent": {
                        "role": "generator",
                        "agent_id": "generator",
                        "files_touched": ["runtime/example.py"],
                    },
                }
            ],
        })
        queue.decide(added["items"][0]["id"], action="promoted", reason="good")

    response = client.post("/api/organizations/topology-proposals/0/promote")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["accepted"] is True
    assert body["new_topology"]["agents"]["generator"]["agent_id"] == "generator"
    assert body["new_topology"]["metadata"]["promotion_source"] == "subagent_fitness"


def test_topology_promotion_lift_endpoint(
    client: TestClient,
    tmp_path: Path,
) -> None:
    base = TeamTopology(
        name="orig",
        protocol=CoordinationProtocol.SEQUENTIAL,
        agents={Role.GENERATOR: AgentSpec(agent_id="legacy-generator")},
        task_bucket="code",
    )
    promoted = TeamTopology(
        name="orig+swap(generator:generator)",
        protocol=CoordinationProtocol.SEQUENTIAL,
        agents={Role.GENERATOR: AgentSpec(agent_id="generator")},
        task_bucket="code",
        metadata={
            "derived_from": base.fingerprint,
            "mutation": "swap_agent",
            "promotion_source": "subagent_fitness",
        },
    )
    save_registry({
        base.fingerprint: base,
        promoted.fingerprint: promoted,
    })
    rows = [
        {"fingerprint": base.fingerprint, "success": False, "quality_score": 0.4},
        {"fingerprint": promoted.fingerprint, "success": True, "quality_score": 0.9},
    ]
    (tmp_path / "data" / "topology_performance.jsonl").write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )

    response = client.get("/api/organizations/topology-promotion-lift")
    body = response.json()

    assert response.status_code == 200
    assert body["schema"] == "octopus.topology_promotion_lift.v1"
    assert body["reports"][0]["promotion_source"] == "subagent_fitness"
    assert body["reports"][0]["verdict"] == "improved"


def test_promote_proposal_invalid_index(client: TestClient) -> None:
    r = client.post("/api/organizations/topology-proposals/99/promote")
    assert r.status_code == 404


def test_promote_proposal_against_real_registry(
    client: TestClient, tmp_path: Path,
) -> None:
    base = TeamTopology(
        name="orig",
        protocol=CoordinationProtocol.SEQUENTIAL,
        agents={Role.GENERATOR: AgentSpec(agent_id="alice")},
        task_bucket="b",
    )
    save_registry({base.fingerprint: base})
    proposals = {
        "ts": 0,
        "proposals": [{
            "kind": "swap_agent",
            "base_topology": base.fingerprint,
            "bucket": "b",
            "detail": {"role": "generator", "old_agent": "alice", "new_agent": "bob"},
            "confidence": 0.8,
            "rationale": "smoke",
        }],
    }
    (tmp_path / "data" / "topology_proposals.json").write_text(
        json.dumps(proposals), encoding="utf-8",
    )
    r = client.post("/api/organizations/topology-proposals/0/promote")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["accepted"] is True
    assert body["new_topology"]["agents"]["generator"]["agent_id"] == "bob"
    assert body["new_topology"]["subagent_policy"]["status"] == "clear"


def test_promote_proposal_rejects_operator_retired_agent(
    client: TestClient,
    tmp_path: Path,
) -> None:
    base = TeamTopology(
        name="orig",
        protocol=CoordinationProtocol.SEQUENTIAL,
        agents={Role.GENERATOR: AgentSpec(agent_id="alice")},
        task_bucket="b",
    )
    save_registry({base.fingerprint: base})
    SubagentPolicyStore(tmp_path / "data" / "subagent_policy.json").decide(
        "bob",
        action="retire",
        reason="operator retired bob",
        actor="operator-test",
    )
    proposals = {
        "ts": 0,
        "proposals": [{
            "kind": "swap_agent",
            "base_topology": base.fingerprint,
            "bucket": "b",
            "detail": {"role": "generator", "old_agent": "alice", "new_agent": "bob"},
            "confidence": 0.8,
            "rationale": "smoke",
        }],
    }
    (tmp_path / "data" / "topology_proposals.json").write_text(
        json.dumps(proposals), encoding="utf-8",
    )

    r = client.post("/api/organizations/topology-proposals/0/promote")

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["accepted"] is False
    assert "retired agents in operator policy" in body["reason"]
    assert body["new_topology"] is None


def test_topology_performance_empty(client: TestClient) -> None:
    r = client.get("/api/organizations/topology-performance")
    assert r.status_code == 200
    assert r.json() == {"count": 0, "runs": []}


def test_retire_topology_removes_entry(
    client: TestClient, tmp_path: Path,
) -> None:
    t = TeamTopology(
        name="doomed",
        protocol=CoordinationProtocol.SEQUENTIAL,
        agents={Role.GENERATOR: AgentSpec(agent_id="g")},
    )
    save_registry({t.fingerprint: t})
    r = client.post(f"/api/organizations/topologies/{t.fingerprint}/retire")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["retired"] == t.fingerprint
    assert body["remaining"] == 0


def test_retire_topology_404(client: TestClient) -> None:
    r = client.post("/api/organizations/topologies/nonexistent/retire")
    assert r.status_code == 404
