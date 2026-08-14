"""Incremental goal projection cache (dsh session-surface goal fold).

``GoalService.current()`` folds the whole scoped event list per read; the
projection cache is the read surface: seeded once from the journal, then
advanced incrementally (live journals via the event bridge, base journals
via the service's own writes), with an as-of watermark so consumers can
order frames. These tests cover seeding, O(1) advancement, scope
isolation, live fan-out, malformed-row tolerance, and lifecycle parity.
"""

from __future__ import annotations

from runtime.memory.goals import (
    GoalProjection,
    GoalProjectionCache,
    GoalService,
    GoalTimelineEntry,
    derive_goal_timeline,
)
from runtime.memory.journal import InMemoryJournal, Journal
from runtime.memory.journal._journal_models import GoalChangeEvent
from runtime.sensing.gateway.streaming_journal import StreamingJournal


class _CountingJournal(Journal):
    """Base-style journal that counts ``read_all`` calls (proves no re-read)."""

    def __init__(self) -> None:
        self._inner = InMemoryJournal()
        self.reads = 0

    def write(self, event: object) -> None:
        self._inner.write(event)

    def read_all(self) -> list:
        self.reads += 1
        return self._inner.read_all()


def test_seed_reflects_existing_goal_and_matches_current() -> None:
    journal = InMemoryJournal()
    svc = GoalService(journal)
    created = svc.create("先有鸡还是先有蛋", max_goal_rounds=5)
    svc.edit("先有蛋")

    cache = GoalProjectionCache(journal)
    proj = cache.current()
    assert isinstance(proj, GoalProjection)
    assert proj.as_of == 2
    assert proj.folded.goal is not None
    assert proj.folded.goal.id == created.goal.id
    assert proj.folded.goal.objective == "先有蛋"
    assert proj.folded.goal.phase == "active"
    # The cache's folded view equals the authoritative full fold.
    assert proj.folded == svc.current()


def test_base_journal_advances_without_rerending_journal() -> None:
    journal = _CountingJournal()
    svc = GoalService(journal)
    # Construction seeds the cache once.
    assert journal.reads == 1

    svc.create("目标", max_goal_rounds=3)
    svc.pause()
    svc.resume()
    svc.complete()

    # The verbs' CAS fold re-reads the journal, but the SURFACE cache is
    # advanced by direct pushes — surface reads never re-read the journal.
    reads_after_verbs = journal.reads
    proj = svc.surface()
    for _ in range(5):
        assert svc.surface().as_of == 4
    assert journal.reads == reads_after_verbs
    assert proj.as_of == 4
    assert proj.folded.goal is not None
    assert proj.folded.goal.phase == "complete"
    assert proj.folded == svc.current()


def test_watermark_only_counts_scoped_goal_changes() -> None:
    journal = InMemoryJournal()
    svc = GoalService(journal)
    svc.create("目标")
    journal.write_user_message("普通消息")
    journal.write(GoalChangeEvent(change={"kind": "bogus"}))
    proj = svc.surface()
    assert proj.as_of == 1


def test_scope_isolation_on_shared_journal() -> None:
    journal = StreamingJournal(InMemoryJournal())
    svc_a = GoalService(journal, agent_id="agent-a")
    svc_b = GoalService(journal, agent_id="agent-b")

    svc_a.create("A 的目标")
    # A's write must not leak into B's surface.
    proj_b = svc_b.surface()
    assert proj_b.as_of == 0
    assert proj_b.folded.goal is None
    assert svc_a.surface().folded.goal is not None


def test_live_journal_updates_through_subscription() -> None:
    journal = StreamingJournal(InMemoryJournal())
    svc = GoalService(journal, agent_id="agent-a")
    cache = GoalProjectionCache(journal, agent_id="agent-a")
    assert cache.current().as_of == 0

    svc.create("直播目标")
    # The subscription fired synchronously inside ``StreamingJournal.write``.
    assert cache.current().as_of == 1
    assert cache.current().folded.goal is not None
    assert cache.current().folded.goal.objective == "直播目标"

    # A different writer on the same journal advances the cache too.
    svc_b = GoalService(journal, agent_id="agent-b")
    svc_b.create("B 的目标")
    assert cache.current().as_of == 1  # scoped away


def test_malformed_goal_change_row_is_skipped() -> None:
    journal = InMemoryJournal()
    journal.write(GoalChangeEvent(change={"kind": "bogus"}))
    cache = GoalProjectionCache(journal)
    proj = cache.current()
    assert proj.as_of == 0
    assert proj.folded.goal is None


def test_surface_tracks_full_lifecycle_parity() -> None:
    journal = InMemoryJournal()
    svc = GoalService(journal)
    svc.create("生命周期")
    svc.pause()
    svc.resume()
    svc.block(code="needs-user", message="需要确认")
    svc.resume()
    svc.complete()
    svc.clear()

    proj = svc.surface()
    assert proj.as_of == 7
    assert proj.folded == svc.current()
    assert proj.folded.goal is None
    assert proj.folded.last_ref is not None


def test_blocked_goal_can_complete_without_blocked_reason() -> None:
    """dsh ``withPhase``: a complete snapshot must not carry blockedReason.

    ``_transition`` used to copy the current blocked reason into the
    completed snapshot, tripping the strict decoder's exact-fields rule
    (``GOAL_INVALID_BLOCK_REASON``) and making blocked→complete unusable.
    """
    journal = InMemoryJournal()
    svc = GoalService(journal)
    svc.create("受阻目标")
    svc.block(code="needs-user", message="等待确认")
    svc.resume()
    completed = svc.complete()

    assert completed.goal is not None
    assert completed.goal.phase == "complete"
    assert completed.goal.blocked_reason is None
    assert svc.surface().folded.goal.blocked_reason is None
    assert svc.surface().folded == svc.current()
    # The committed complete row survives the strict decoder on replay.
    from runtime.memory.goals import fold_goal

    replayed = fold_goal(
        [e for e in journal.read_all() if getattr(e, "event_type", "") == "goal_change"]
    )
    assert replayed.goal is not None
    assert replayed.goal.phase == "complete"
    assert replayed.goal.blocked_reason is None


def test_close_stops_live_updates() -> None:
    journal = StreamingJournal(InMemoryJournal())
    svc = GoalService(journal)
    cache = GoalProjectionCache(journal)
    cache.close()

    svc.create("关闭后不更新")
    assert cache.current().as_of == 0
    # Service surface (its own cache) still advances normally.
    assert svc.surface().as_of == 1


def test_apply_change_rejects_invalid_change_silently() -> None:
    from runtime.memory.goals import GoalSnapshot
    from runtime.memory.goals.fold import GoalSnapshotChange

    cache = GoalProjectionCache(InMemoryJournal())
    # A transition on an empty fold (no current goal) must not raise.
    cache.apply_change(
        GoalSnapshotChange(
            operation="pause",
            goal=GoalSnapshot(
                id="a" * 32,
                revision=2,
                objective="无主",
                phase="paused",
                max_goal_rounds=5,
            ),
            rounds_started=0,
            created_at=1,
            updated_at=1,
        )
    )
    assert cache.current().as_of == 0
    assert cache.current().folded.goal is None


def test_timeline_archives_full_lifecycle_in_order() -> None:
    journal = InMemoryJournal()
    svc = GoalService(journal)
    svc.create("第一个目标")
    svc.complete()
    svc.create("第二个目标", max_goal_rounds=2)
    svc.block(code="needs-user", message="等待")
    svc.resume()
    svc.complete()
    svc.create("第三个目标")
    svc.clear()

    entries = derive_goal_timeline(journal)
    assert [e.objective for e in entries] == ["第一个目标", "第二个目标", "第三个目标"]
    assert [e.final_phase for e in entries] == ["complete", "complete", "cleared"]
    assert [e.final_revision for e in entries] == [2, 4, 2]
    assert all(isinstance(e, GoalTimelineEntry) for e in entries)
    assert entries[0].cleared_at is None
    assert entries[2].cleared_at is not None
    assert entries[2].rounds_started == 0
    assert entries[0].created_at <= entries[0].updated_at


def test_timeline_scopes_across_writers() -> None:
    journal = StreamingJournal(InMemoryJournal())
    svc_a = GoalService(journal, agent_id="agent-a")
    svc_b = GoalService(journal, agent_id="agent-b")
    svc_a.create("A 的目标")
    svc_b.create("B 的目标")

    assert [e.objective for e in derive_goal_timeline(journal, agent_id="agent-a")] == [
        "A 的目标"
    ]
    assert [e.objective for e in derive_goal_timeline(journal, agent_id="agent-b")] == [
        "B 的目标"
    ]
    assert len(derive_goal_timeline(journal)) == 2


def test_timeline_skips_malformed_rows_and_unrelated_events() -> None:
    journal = InMemoryJournal()
    journal.write_user_message("普通消息")
    svc = GoalService(journal)
    svc.create("目标")
    # A malformed row after the fold's last strict read must not break the
    # archive derivation (the strict service fold itself stays fail-loud).
    journal.write(GoalChangeEvent(change={"kind": "bogus"}))

    entries = derive_goal_timeline(journal)
    assert len(entries) == 1
    assert entries[0].objective == "目标"


def test_timeline_tombstone_without_create_still_archives() -> None:
    from runtime.memory.goals.domain import GoalClearChange, GoalRef

    journal = InMemoryJournal()
    journal.write(
        GoalChangeEvent(
            change=GoalClearChange(
                cleared=GoalRef(id="a" * 32, revision=3),
                cleared_at=100,
            ).to_dict()
        )
    )
    entries = derive_goal_timeline(journal)
    assert len(entries) == 1
    assert entries[0].goal_id == "a" * 32
    assert entries[0].final_phase == "cleared"
    assert entries[0].final_revision == 3
    assert entries[0].cleared_at == 100
