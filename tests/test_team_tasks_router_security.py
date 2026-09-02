"""Security tests for team_tasks_router authorization + input validation.

Validates:
- Room membership enforcement (403 when actor not in room)
- sop_template path traversal rejection (400 on ../foo or /etc/passwd)
- Concurrency cap on /run endpoint (429 after limit)
- Broadcast signature adapter correctness
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from runtime.safety.auth.identity import Identity, IdentityStore  # noqa: E402
from runtime.safety.organization.team_runner import (  # noqa: E402
    RoleOutput,
    TeamRunResult,
)
from runtime.sensing.gateway.team_rooms_router import (  # noqa: E402
    create_team_rooms_router,
)
from runtime.sensing.gateway.team_tasks_router import (  # noqa: E402
    create_team_tasks_router,
)


class _SlowRunner:
    """Runner that blocks for 600ms — used to measure /run concurrency cap."""

    def __init__(
        self,
        *,
        timeout_seconds: int | None = None,
        event_emitter=None,
    ) -> None:
        pass

    def run(self, topology, task: str, *, context: dict[str, Any] | None = None):
        time.sleep(0.6)
        role, spec = next(iter(topology.agents.items()))
        return TeamRunResult(
            topology_name=topology.name,
            topology_fingerprint=topology.fingerprint,
            task_bucket=topology.task_bucket,
            success=True,
            final_output="slow done",
            role_outputs=[
                RoleOutput(
                    role=role,
                    agent_id=spec.agent_id,
                    output="slow output",
                    duration_ms=600.0,
                ),
            ],
        )


# Module-level event so the BlockingRunner factory below can share
# state with the test that releases it. Reset per-test by the fixture
# via _BlockingRunner.reset().
_BLOCKING_RUNNER_RELEASE = __import__("threading").Event()


class _BlockingRunner:
    """Runner that blocks until ``_BLOCKING_RUNNER_RELEASE`` is set.

    Replaces the sleep-based ``_SlowRunner`` for the concurrency-cap
    test. With sleep, the test was timing-sensitive: a worker thread
    could complete BEFORE the third /run was issued, freeing the cap
    and turning what should be a 429 into a 200. Using an Event lets
    the test deterministically hold workers until it has verified the
    cap has been hit.
    """

    @classmethod
    def reset(cls) -> None:
        _BLOCKING_RUNNER_RELEASE.clear()

    @classmethod
    def release(cls) -> None:
        _BLOCKING_RUNNER_RELEASE.set()

    def __init__(
        self,
        *,
        timeout_seconds: int | None = None,
        event_emitter=None,
    ) -> None:
        pass

    def run(self, topology, task: str, *, context: dict[str, Any] | None = None):
        # Block until the test releases. 5s safety bound so a buggy
        # test can't hang CI forever.
        _BLOCKING_RUNNER_RELEASE.wait(timeout=5.0)
        role, spec = next(iter(topology.agents.items()))
        return TeamRunResult(
            topology_name=topology.name,
            topology_fingerprint=topology.fingerprint,
            task_bucket=topology.task_bucket,
            success=True,
            final_output="blocking done",
            role_outputs=[
                RoleOutput(
                    role=role,
                    agent_id=spec.agent_id,
                    output="blocking output",
                    duration_ms=0.0,
                ),
            ],
        )


def _build_app(
    tmp_path: Path,
    runner_factory=None,
    max_concurrent_runs: int = 16,
) -> tuple[TestClient, IdentityStore, dict[str, str]]:
    """Build app with require_auth=True + 2 known identities (alice, bob).

    Returns the client, the identity store, and a {actor_id: api_key} map.
    """
    store = IdentityStore()
    keys: dict[str, str] = {}
    for actor in ("alice", "bob", "carol"):
        api_key = f"sk-test-{actor}"
        store.add(
            Identity(actor_id=actor, metadata={"tenant_id": "tenant-acme"}),
            api_key_plaintext=api_key,
        )
        keys[actor] = api_key

    app = FastAPI()
    rooms_router = create_team_rooms_router(
        state_path=tmp_path / "rooms.json",
        identity_store=store,
        require_auth=True,
    )
    app.include_router(rooms_router)

    async def _broadcaster(room_id: str, payload: dict[str, Any]) -> None:
        return None

    tasks_router = create_team_tasks_router(
        state_path=tmp_path / "tasks.json",
        identity_store=store,
        require_auth=True,
        runner_factory=runner_factory,
        team_event_broadcaster=_broadcaster,
        room_membership_resolver=rooms_router.list_room_members,
        room_participant_resolver=rooms_router.get_room_participant,
        max_concurrent_runs=max_concurrent_runs,
    )
    app.include_router(tasks_router)
    return TestClient(app), store, keys


def _auth_header(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"}


def _create_room(
    client: TestClient,
    keys: dict[str, str],
    room_id: str,
    owner: str,
) -> dict[str, Any]:
    """Create a team room owned by ``owner``. The actor_id is bound via
    members[].name field (which the router echoes into actor_id when
    a participant joins via member name)."""
    resp = client.post(
        "/api/teams",
        json={
            "id": room_id,
            "name": f"Room {room_id}",
            "members": [{"name": owner, "role": "owner"}],
        },
        headers=_auth_header(keys[owner]),
    )
    assert resp.status_code == 200, resp.json()
    return resp.json()


def _join_room(
    client: TestClient,
    keys: dict[str, str],
    room_id: str,
    actor: str,
    *,
    role: str,
) -> dict[str, Any]:
    invite = client.post(
        f"/api/teams/{room_id}/invites",
        json={"role": role, "expires_in_seconds": 3600},
        headers=_auth_header(keys["alice"]),
    )
    assert invite.status_code == 200, invite.json()
    joined = client.post(
        f"/api/team-invites/{invite.json()['invite_token']}/join",
        json={"display_name": actor},
        headers=_auth_header(keys[actor]),
    )
    assert joined.status_code == 200, joined.json()
    return joined.json()["participant"]


def test_membership_blocks_non_member_create(tmp_path: Path) -> None:
    """Non-member cannot create tasks in a room they don't belong to."""
    client, _, keys = _build_app(tmp_path)
    _create_room(client, keys, "room-alpha", owner="alice")

    resp = client.post(
        "/api/team-tasks",
        json={"room_id": "room-alpha", "title": "bob hijack"},
        headers=_auth_header(keys["bob"]),
    )

    assert resp.status_code == 403
    assert "not a member" in resp.json()["detail"]


def test_membership_blocks_non_member_get(tmp_path: Path) -> None:
    """Non-member cannot read tasks in a room they don't belong to."""
    client, _, keys = _build_app(tmp_path)
    _create_room(client, keys, "room-alpha", owner="alice")
    create = client.post(
        "/api/team-tasks",
        json={"room_id": "room-alpha", "title": "alice task"},
        headers=_auth_header(keys["alice"]),
    )
    assert create.status_code == 200, create.json()
    task_id = create.json()["id"]

    resp = client.get(
        f"/api/team-tasks/{task_id}",
        headers=_auth_header(keys["bob"]),
    )

    assert resp.status_code == 403


def test_membership_blocks_non_member_run(tmp_path: Path) -> None:
    """Non-member cannot trigger /run on a task in another room."""
    client, _, keys = _build_app(tmp_path, _SlowRunner)
    _create_room(client, keys, "room-alpha", owner="alice")
    create = client.post(
        "/api/team-tasks",
        json={"room_id": "room-alpha", "title": "alice task"},
        headers=_auth_header(keys["alice"]),
    )
    assert create.status_code == 200
    task_id = create.json()["id"]

    resp = client.post(
        f"/api/team-tasks/{task_id}/run",
        headers=_auth_header(keys["bob"]),
    )

    assert resp.status_code == 403


def test_membership_blocks_non_member_update(tmp_path: Path) -> None:
    client, _, keys = _build_app(tmp_path)
    _create_room(client, keys, "room-alpha", owner="alice")
    create = client.post(
        "/api/team-tasks",
        json={"room_id": "room-alpha", "title": "alice task"},
        headers=_auth_header(keys["alice"]),
    )
    task_id = create.json()["id"]

    resp = client.patch(
        f"/api/team-tasks/{task_id}",
        json={"title": "bob hijack"},
        headers=_auth_header(keys["bob"]),
    )

    assert resp.status_code == 403


def test_membership_blocks_non_member_delete(tmp_path: Path) -> None:
    client, _, keys = _build_app(tmp_path)
    _create_room(client, keys, "room-alpha", owner="alice")
    create = client.post(
        "/api/team-tasks",
        json={"room_id": "room-alpha", "title": "alice task"},
        headers=_auth_header(keys["alice"]),
    )
    task_id = create.json()["id"]

    resp = client.delete(
        f"/api/team-tasks/{task_id}",
        headers=_auth_header(keys["bob"]),
    )

    assert resp.status_code == 403


def test_viewer_reads_tasks_but_cannot_mutate_or_run(tmp_path: Path) -> None:
    client, _, keys = _build_app(tmp_path, _SlowRunner)
    _create_room(client, keys, "room-alpha", owner="alice")
    participant = _join_room(
        client,
        keys,
        "room-alpha",
        "carol",
        role="viewer",
    )
    created = client.post(
        "/api/team-tasks",
        json={"room_id": "room-alpha", "title": "owner task"},
        headers=_auth_header(keys["alice"]),
    )
    assert created.status_code == 200, created.json()
    task_id = created.json()["id"]

    assert (
        client.get(
            "/api/team-tasks?room_id=room-alpha",
            headers=_auth_header(keys["carol"]),
        ).status_code
        == 200
    )
    assert (
        client.get(
            f"/api/team-tasks/{task_id}",
            headers=_auth_header(keys["carol"]),
        ).status_code
        == 200
    )
    assert (
        client.get(
            f"/api/team-tasks/{task_id}/process-timeline",
            headers=_auth_header(keys["carol"]),
        ).status_code
        == 200
    )

    denied = [
        client.post(
            "/api/team-tasks",
            json={"room_id": "room-alpha", "title": "viewer task"},
            headers=_auth_header(keys["carol"]),
        ),
        client.post(
            f"/api/team-tasks/{task_id}/run",
            headers=_auth_header(keys["carol"]),
        ),
        client.patch(
            f"/api/team-tasks/{task_id}",
            json={"title": "viewer edit"},
            headers=_auth_header(keys["carol"]),
        ),
        client.delete(
            f"/api/team-tasks/{task_id}",
            headers=_auth_header(keys["carol"]),
        ),
    ]
    assert [response.status_code for response in denied] == [403, 403, 403, 403]
    assert all("viewers" in response.json()["detail"] for response in denied)

    # Presence changes are not membership changes: offline viewers still read.
    offline = client.patch(
        f"/api/teams/room-alpha/participants/{participant['id']}",
        json={"status": "offline"},
        headers=_auth_header(keys["alice"]),
    )
    assert offline.status_code == 200, offline.json()
    assert (
        client.get(
            f"/api/team-tasks/{task_id}",
            headers=_auth_header(keys["carol"]),
        ).status_code
        == 200
    )

    removed = client.patch(
        f"/api/teams/room-alpha/participants/{participant['id']}",
        json={"status": "removed"},
        headers=_auth_header(keys["alice"]),
    )
    assert removed.status_code == 200, removed.json()
    assert (
        client.get(
            f"/api/team-tasks/{task_id}",
            headers=_auth_header(keys["carol"]),
        ).status_code
        == 403
    )


def test_plain_member_can_create_and_update_tasks(tmp_path: Path) -> None:
    client, _, keys = _build_app(tmp_path)
    _create_room(client, keys, "room-alpha", owner="alice")
    _join_room(client, keys, "room-alpha", "bob", role="member")

    created = client.post(
        "/api/team-tasks",
        json={"room_id": "room-alpha", "title": "member task"},
        headers=_auth_header(keys["bob"]),
    )
    assert created.status_code == 200, created.json()
    updated = client.patch(
        f"/api/team-tasks/{created.json()['id']}",
        json={"title": "member update"},
        headers=_auth_header(keys["bob"]),
    )
    assert updated.status_code == 200, updated.json()
    assert updated.json()["title"] == "member update"


def test_viewer_cannot_use_run_endpoint_when_task_is_already_running(tmp_path: Path) -> None:
    _BlockingRunner.reset()
    try:
        client, _, keys = _build_app(tmp_path, _BlockingRunner)
        _create_room(client, keys, "room-alpha", owner="alice")
        _join_room(client, keys, "room-alpha", "carol", role="viewer")
        created = client.post(
            "/api/team-tasks",
            json={"room_id": "room-alpha", "title": "running task"},
            headers=_auth_header(keys["alice"]),
        )
        task_id = created.json()["id"]
        started = client.post(
            f"/api/team-tasks/{task_id}/run",
            headers=_auth_header(keys["alice"]),
        )
        assert started.status_code == 200, started.json()
        denied = client.post(
            f"/api/team-tasks/{task_id}/run",
            headers=_auth_header(keys["carol"]),
        )
        assert denied.status_code == 403
        assert "viewers" in denied.json()["detail"]
    finally:
        _BlockingRunner.release()


def test_sop_template_rejects_path_traversal(tmp_path: Path) -> None:
    """sop_template with ../, /, etc. is rejected as 400."""
    client, _, keys = _build_app(tmp_path)
    _create_room(client, keys, "room-alpha", owner="alice")

    for bad in ("../secrets", "../../etc/passwd", "/etc/passwd", "foo/bar"):
        resp = client.post(
            "/api/team-tasks",
            json={
                "room_id": "room-alpha",
                "title": "malicious",
                "sop_template": bad,
            },
            headers=_auth_header(keys["alice"]),
        )
        assert resp.status_code == 400, f"{bad!r} not rejected"
        assert "no slashes" in resp.json()["detail"]


def test_sop_template_accepts_valid_slugs(tmp_path: Path) -> None:
    client, _, keys = _build_app(tmp_path)
    _create_room(client, keys, "room-alpha", owner="alice")

    for slug in ("pitch-deck", "kyc_rules", "3-statement-model", "v1.2.3"):
        resp = client.post(
            "/api/team-tasks",
            json={
                "room_id": "room-alpha",
                "title": f"task {slug}",
                "sop_template": slug,
            },
            headers=_auth_header(keys["alice"]),
        )
        assert resp.status_code == 200, f"{slug!r} rejected: {resp.json()}"


def test_sop_template_update_rejects_path_traversal(tmp_path: Path) -> None:
    client, _, keys = _build_app(tmp_path)
    _create_room(client, keys, "room-alpha", owner="alice")
    create = client.post(
        "/api/team-tasks",
        json={"room_id": "room-alpha", "title": "task"},
        headers=_auth_header(keys["alice"]),
    )
    task_id = create.json()["id"]

    resp = client.patch(
        f"/api/team-tasks/{task_id}",
        json={"sop_template": "../evil"},
        headers=_auth_header(keys["alice"]),
    )

    assert resp.status_code == 400


def test_run_endpoint_concurrency_cap(tmp_path: Path) -> None:
    """POST /run returns 429 after max_concurrent_runs limit.

    Uses ``_BlockingRunner`` so workers stay parked until we explicitly
    release them — eliminates the timing flake that came from the old
    sleep-based runner finishing before the third /run was issued.
    """
    _BlockingRunner.reset()
    try:
        client, _, keys = _build_app(tmp_path, _BlockingRunner, max_concurrent_runs=2)
        _create_room(client, keys, "room-alpha", owner="alice")

        task_ids = []
        for i in range(3):
            create = client.post(
                "/api/team-tasks",
                json={"room_id": "room-alpha", "title": f"task-{i}"},
                headers=_auth_header(keys["alice"]),
            )
            assert create.status_code == 200
            task_ids.append(create.json()["id"])

        # Workers will block on the Event, occupying the cap.
        run1 = client.post(
            f"/api/team-tasks/{task_ids[0]}/run",
            headers=_auth_header(keys["alice"]),
        )
        assert run1.status_code == 200
        run2 = client.post(
            f"/api/team-tasks/{task_ids[1]}/run",
            headers=_auth_header(keys["alice"]),
        )
        assert run2.status_code == 200
        run3 = client.post(
            f"/api/team-tasks/{task_ids[2]}/run",
            headers=_auth_header(keys["alice"]),
        )
        assert run3.status_code == 429
        assert "too many concurrent" in run3.json()["detail"]
    finally:
        # Always release so the daemon threads can exit and the test
        # session doesn't leak workers.
        _BlockingRunner.release()


def test_list_tasks_room_scope_membership(tmp_path: Path) -> None:
    """GET /api/team-tasks?room_id=X enforces membership on X."""
    client, _, keys = _build_app(tmp_path)
    _create_room(client, keys, "room-alice", owner="alice")
    _create_room(client, keys, "room-bob", owner="bob")
    client.post(
        "/api/team-tasks",
        json={"room_id": "room-alice", "title": "alice task"},
        headers=_auth_header(keys["alice"]),
    )

    # alice listing her own room is OK
    own = client.get(
        "/api/team-tasks?room_id=room-alice",
        headers=_auth_header(keys["alice"]),
    )
    assert own.status_code == 200

    # alice listing bob's room is 403
    other = client.get(
        "/api/team-tasks?room_id=room-bob",
        headers=_auth_header(keys["alice"]),
    )
    assert other.status_code == 403


def test_unscoped_task_list_only_contains_member_rooms(tmp_path: Path) -> None:
    client, _, keys = _build_app(tmp_path)
    _create_room(client, keys, "room-alice", owner="alice")
    _create_room(client, keys, "room-bob", owner="bob")
    client.post(
        "/api/team-tasks",
        json={"room_id": "room-alice", "title": "alice task"},
        headers=_auth_header(keys["alice"]),
    )
    client.post(
        "/api/team-tasks",
        json={"room_id": "room-bob", "title": "bob secret task"},
        headers=_auth_header(keys["bob"]),
    )

    listed = client.get("/api/team-tasks", headers=_auth_header(keys["alice"]))

    assert listed.status_code == 200
    assert [item["title"] for item in listed.json()["tasks"]] == ["alice task"]


def test_auth_on_without_membership_resolver_fails_closed(tmp_path: Path) -> None:
    store = IdentityStore()
    store.add(Identity(actor_id="alice"), api_key_plaintext="sk-alice")
    app = FastAPI()
    app.include_router(
        create_team_tasks_router(
            state_path=tmp_path / "tasks.json",
            identity_store=store,
            require_auth=True,
        )
    )
    client = TestClient(app)
    headers = _auth_header("sk-alice")

    assert client.get("/api/team-tasks", headers=headers).status_code == 503
    assert (
        client.post(
            "/api/team-tasks",
            headers=headers,
            json={"room_id": "unverified-room", "title": "must fail"},
        ).status_code
        == 503
    )


def test_single_user_dev_mode_skips_membership_check(tmp_path: Path) -> None:
    """When require_auth=False (single-user dev mode), the membership
    resolver is a no-op so tests / local dev flows aren't broken."""
    app = FastAPI()
    rooms = create_team_rooms_router(state_path=tmp_path / "rooms.json")
    app.include_router(rooms)
    tasks = create_team_tasks_router(
        state_path=tmp_path / "tasks.json",
        require_auth=False,
        room_membership_resolver=rooms.list_room_members,
    )
    app.include_router(tasks)
    client = TestClient(app)

    create_room = client.post(
        "/api/teams",
        json={
            "id": "room-x",
            "name": "Room X",
            "members": [{"name": "anyone", "role": "owner"}],
        },
    )
    assert create_room.status_code == 200

    # No auth header at all — should still work in dev mode
    resp = client.post(
        "/api/team-tasks",
        json={"room_id": "room-x", "title": "no-auth dev task"},
    )
    assert resp.status_code == 200
    assert resp.json()["title"] == "no-auth dev task"


def test_concurrency_cap_lock_holds_under_burst(tmp_path: Path) -> None:
    """Burst-fire 6 /run requests with cap=2; exactly 2 should win,
    rest 429. Guards against the TOCTOU window between cap-check and
    running{} insert."""
    import concurrent.futures

    _BlockingRunner.reset()
    try:
        client, _, keys = _build_app(tmp_path, _BlockingRunner, max_concurrent_runs=2)
        _create_room(client, keys, "room-alpha", owner="alice")

        task_ids = []
        for i in range(6):
            create = client.post(
                "/api/team-tasks",
                json={"room_id": "room-alpha", "title": f"burst-{i}"},
                headers=_auth_header(keys["alice"]),
            )
            task_ids.append(create.json()["id"])

        def _fire(tid: str) -> int:
            return client.post(
                f"/api/team-tasks/{tid}/run",
                headers=_auth_header(keys["alice"]),
            ).status_code

        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            statuses = list(pool.map(_fire, task_ids))

        accepted = sum(1 for s in statuses if s == 200)
        rejected = sum(1 for s in statuses if s == 429)
        assert accepted == 2, f"expected exactly 2 accepted, got {accepted}: {statuses}"
        assert rejected == 4, f"expected exactly 4 rejected, got {rejected}: {statuses}"
    finally:
        _BlockingRunner.release()
    assert rejected == 4, f"expected exactly 4 rejected, got {rejected}: {statuses}"
