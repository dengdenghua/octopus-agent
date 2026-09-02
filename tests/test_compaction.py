"""Tests for context compaction.

Two layers:

1. Pure ``compact()`` function — does it pick the right range, build
   a summary, and leave the keep-recent turns untouched?
2. Integration with ``EventLog`` — does ``turn_compacted`` + ``replay()``
   produce the expected surviving turn list?
"""

from __future__ import annotations

from pathlib import Path

from runtime.memory.threads.compaction import (
    CompactionPolicy,
    CompactionResult,
    compact,
    compaction_trigger_tokens,
    estimate_turns_tokens,
    should_compact,
)
from runtime.memory.threads.event_log import EventLog, LoggedEvent
from runtime.platform.models.primitives import new_id
from runtime.protocol.items import (
    AgentMessageItem,
    CommandExecutionItem,
    ErrorItem,
    McpToolCallItem,
    PlanItem,
    TodoEntry,
    TodoListItem,
    Turn,
    TurnStatus,
    UserMessageItem,
)


def _make_turn(
    idx: int,
    thread_id: str = "th",
    user_text: str = "",
    agent_text: str = "",
    command: str | None = None,
    items_extra: list | None = None,
) -> Turn:
    items: list = []
    if user_text:
        items.append(UserMessageItem(text=user_text))
    if agent_text:
        items.append(AgentMessageItem(text=agent_text))
    if command:
        items.append(CommandExecutionItem(command=command))
    if items_extra:
        items.extend(items_extra)
    return Turn(
        id=f"trn_{idx:04d}_{new_id().hex[:6]}",
        threadId=thread_id,
        status=TurnStatus.COMPLETED,
        items=items,
    )


class TestTrigger:
    def test_no_compact_when_under_threshold(self) -> None:
        turns = [_make_turn(i) for i in range(5)]
        assert should_compact(turns, CompactionPolicy(trigger_at=20, keep_recent=10)) is False

    def test_no_compact_when_disabled(self) -> None:
        turns = [_make_turn(i) for i in range(50)]
        assert should_compact(turns, CompactionPolicy(trigger_at=5, keep_recent=10)) is False

    def test_fires_when_over_threshold(self) -> None:
        turns = [_make_turn(i) for i in range(25)]
        assert should_compact(turns, CompactionPolicy(trigger_at=20, keep_recent=10)) is True


class TestTokenVolumeTrigger:
    """W7: compaction must also fire on token volume, not just turn count.

    The count path misses few-turns-huge-content threads — a couple of
    20k-token tool dumps blow a 128k window long before turn 24.
    """

    def test_fires_below_turn_threshold_on_volume(self) -> None:
        # 6 turns × ~30k chars ≈ 60k estimated tokens — far under the
        # turn threshold but over the token one.
        turns = [_make_turn(i, user_text=f"ask-{i} ", agent_text="x" * 30_000) for i in range(6)]
        policy = CompactionPolicy(
            trigger_at=24,
            keep_recent=2,
            trigger_tokens=10_000,
        )
        assert len(turns) < policy.trigger_at
        assert should_compact(turns, policy) is True

    def test_volume_path_disabled_by_default(self) -> None:
        turns = [_make_turn(i, user_text="ask", agent_text="x" * 30_000) for i in range(6)]
        # trigger_tokens unset → historical count-only behaviour.
        assert should_compact(turns, CompactionPolicy(trigger_at=24, keep_recent=2)) is False

    def test_volume_respects_keep_recent_floor(self) -> None:
        # Over budget but nothing older than the keep window to fold —
        # triggering would burn a summariser call for a guaranteed no-op
        # and oscillate every turn.
        turns = [_make_turn(i, agent_text="x" * 30_000) for i in range(3)]
        policy = CompactionPolicy(trigger_at=24, keep_recent=10, trigger_tokens=1_000)
        assert should_compact(turns, policy) is False

    def test_token_triggered_compact_produces_summary(self) -> None:
        turns = [
            _make_turn(i, user_text=f"ask-{i}", agent_text=f"ans-{i} " + "y" * 20_000)
            for i in range(8)
        ]
        policy = CompactionPolicy(trigger_at=24, keep_recent=3, trigger_tokens=5_000)
        result = compact("th", turns, policy)
        assert result is not None
        # Everything older than the keep window folds into one summary.
        assert result.superseded_ids == [t.id for t in turns[:5]]
        assert len(result.summary_turn.items) == 1

    def test_estimation_covers_heavy_item_kinds(self) -> None:
        # MCP tool results, file diffs and reasoning content are the
        # usual volume hogs — the estimator must count them all.
        from runtime.protocol.items import (
            FileChange,
            FileChangeItem,
            McpToolCallItem,
            ReasoningItem,
        )

        turns = [
            _make_turn(
                0,
                items_extra=[
                    McpToolCallItem(
                        server="srv",
                        tool="search",
                        result={"rows": ["r" * 3_000] * 3},
                    ),
                    FileChangeItem(
                        changes=[
                            FileChange(path="a.py", op="update", diff="+" + "d" * 6_000),
                        ]
                    ),
                    ReasoningItem(content="think " * 1_000),
                ],
            ),
        ]
        # ~9k (mcp) + ~6k (diff) + ~5k (reasoning) chars at en/4 → ≥4k tokens.
        assert estimate_turns_tokens(turns) >= 4_000

    def test_estimation_is_zero_for_empty_thread(self) -> None:
        assert estimate_turns_tokens([]) == 0

    def test_cjk_not_halved_vs_react_scale(self) -> None:
        # The trigger must use the same token units as
        # context_budget_tokens_for_model (cn/1.5 + en/4). A chars//3
        # estimate would halve Chinese threads and delay compaction
        # past the window the budget was derived from.
        cn_turns = [_make_turn(0, user_text="中" * 3_000)]
        assert estimate_turns_tokens(cn_turns) >= 2_000  # 3000/1.5 = 2000


class TestTriggerTokensDerivation:
    """The token trigger derives from the model's advertised window.

    128k / 256k / 1M models must compact at different volumes instead
    of sharing one flat guess; unresolvable ids (``auto``) fall back
    to the 256k convention rather than firing on every thread.
    """

    def test_unresolvable_model_falls_back_to_256k_convention(self) -> None:
        assert compaction_trigger_tokens(None) == 230_400
        assert compaction_trigger_tokens("auto") == 230_400

    def test_known_model_families_use_name_heuristics(self) -> None:
        # Non-custom models skip operator config and land in the
        # resolver's family heuristics: 200k claude → 150k budget,
        # 256k glm/deepseek → 230.4k budget.
        assert compaction_trigger_tokens("claude-sonnet-4-5") == 150_000
        assert compaction_trigger_tokens("glm-5.2") == 230_400

    def test_trigger_scales_with_window(self) -> None:
        # The whole point: a 1M-window model gets ~8x the headroom of
        # a 128k one instead of a shared flat threshold.
        small = compaction_trigger_tokens("claude-sonnet-4-5")
        large = compaction_trigger_tokens("glm-5.2")
        assert large > small * 1.5


class TestCompact:
    def test_returns_none_below_trigger(self) -> None:
        turns = [_make_turn(i) for i in range(5)]
        assert compact("th", turns, CompactionPolicy(trigger_at=20, keep_recent=10)) is None

    def test_summary_covers_stale_range_only(self) -> None:
        turns = [_make_turn(i, user_text=f"ask-{i}", agent_text=f"ans-{i}") for i in range(25)]
        policy = CompactionPolicy(trigger_at=20, keep_recent=10)
        result = compact("th", turns, policy)
        assert isinstance(result, CompactionResult)
        assert len(result.superseded_ids) == 15  # 25 - keep_recent(10)
        # Should not include any of the kept-recent ids.
        recent_ids = {t.id for t in turns[-10:]}
        assert not recent_ids.intersection(result.superseded_ids)

    def test_summary_text_references_all_stale_turns(self) -> None:
        turns = [_make_turn(i, user_text=f"ask-{i}", agent_text=f"ans-{i}") for i in range(15)]
        policy = CompactionPolicy(trigger_at=10, keep_recent=5)
        result = compact("th", turns, policy)
        assert result is not None
        text = result.summary_turn.items[0].text  # type: ignore[attr-defined]
        # 15 - 5 = 10 stale → summary should mention them by count
        assert "[turn 1/10" in text
        assert "[turn 10/10" in text
        assert "ask-0" in text

    def test_custom_summariser_used(self) -> None:
        turns = [_make_turn(i, user_text=f"ask-{i}") for i in range(15)]
        called: list[int] = []

        def summariser(stale):  # type: ignore[no-untyped-def]
            called.append(len(stale))
            return "my-custom-summary"

        result = compact(
            "th",
            turns,
            CompactionPolicy(
                trigger_at=10,
                keep_recent=5,
                custom_summariser=summariser,
            ),
        )
        assert result is not None
        assert called == [10]
        item = result.summary_turn.items[0]
        assert getattr(item, "text", "") == "my-custom-summary"

    def test_respects_max_summary_chars(self) -> None:
        turns = [_make_turn(i, user_text=f"ask {i}") for i in range(50)]
        result = compact(
            "th",
            turns,
            CompactionPolicy(trigger_at=15, keep_recent=5, max_summary_chars=120),
        )
        assert result is not None
        item = result.summary_turn.items[0]
        assert len(getattr(item, "text", "")) <= 120

    def test_summary_counts_non_text_operational_items(self) -> None:
        turn = Turn(
            threadId="th",
            status=TurnStatus.COMPLETED,
            items=[
                UserMessageItem(text="run tools"),
                McpToolCallItem(server="fs", tool="read", result={"ok": True}),
                PlanItem(text="1. inspect\n2. patch"),
                TodoListItem(plan=[TodoEntry(title="ship", status="completed")]),
                ErrorItem(message="tool failed"),
            ],
        )
        result = compact(
            "th",
            [turn, _make_turn(1)],
            CompactionPolicy(trigger_at=2, keep_recent=1),
        )
        assert result is not None
        text = result.summary_turn.items[0].text  # type: ignore[attr-defined]
        assert "1 MCP tool call(s)" in text
        assert "1 plan item(s)" in text
        assert "1 todo list(s)" in text
        assert "error: tool failed" in text


class TestEventLogIntegration:
    def test_replay_drops_superseded_turns_and_inserts_summary(self, tmp_path: Path) -> None:
        log = EventLog(tmp_path / "th.jsonl")
        log.thread_started("th")

        turns = [_make_turn(i, user_text=f"u-{i}") for i in range(5)]
        for t in turns:
            log.turn_started("th", t)
            for it in t.items:
                log.item_started("th", t.id, it)
                log.item_completed("th", t.id, it)
            log.turn_completed("th", t.id, TurnStatus.COMPLETED)

        # Compact the first 3.
        policy = CompactionPolicy(trigger_at=5, keep_recent=2)
        assert should_compact(turns, policy) is True
        result = compact("th", turns, policy)
        assert result is not None
        log.turn_compacted("th", result.summary_turn, result.superseded_ids)

        rebuilt = log.replay()
        ids = [t.id for t in rebuilt]
        # Summary replaces the first 3; kept-recent 2 intact.
        assert ids == [result.summary_turn.id] + [t.id for t in turns[-2:]]

    def test_compaction_event_leaves_prior_events_untouched(self, tmp_path: Path) -> None:
        """Append-only invariant: the raw events for the superseded
        turns are still on disk. A downstream audit that ignores
        ``turn_compacted`` events sees the full history."""
        log = EventLog(tmp_path / "th.jsonl")
        log.thread_started("th")
        turns = [_make_turn(i) for i in range(3)]
        for t in turns:
            log.turn_started("th", t)
            log.turn_completed("th", t.id, TurnStatus.COMPLETED)

        result = compact(
            "th",
            turns,
            CompactionPolicy(trigger_at=3, keep_recent=1),
        )
        assert result is not None
        log.turn_compacted("th", result.summary_turn, result.superseded_ids)

        all_events = list(log.iter_events())
        turn_started_ids = [e.turn_id for e in all_events if e.event == "turn_started"]
        assert turn_started_ids == [t.id for t in turns]

    def test_replay_ignores_identical_stale_compaction(self, tmp_path: Path) -> None:
        """Two workers may compact the same snapshot concurrently.

        The first event wins. Replaying the second must not append a duplicate
        summary after the kept recent turns merely because its source turns
        have already been replaced.
        """
        log = EventLog(tmp_path / "th.jsonl")
        log.thread_started("th")
        turns = [_make_turn(i, user_text=f"u-{i}") for i in range(5)]
        for turn in turns:
            log.turn_started("th", turn)
            log.turn_completed("th", turn.id, TurnStatus.COMPLETED)

        policy = CompactionPolicy(trigger_at=5, keep_recent=2)
        first = compact("th", turns, policy)
        second = compact("th", turns, policy)
        assert first is not None and second is not None
        log.turn_compacted("th", first.summary_turn, first.superseded_ids)
        log.turn_compacted("th", second.summary_turn, second.superseded_ids)

        assert [turn.id for turn in log.replay()] == [
            first.summary_turn.id,
            turns[3].id,
            turns[4].id,
        ]

    def test_replay_ignores_partially_overlapping_stale_compaction(
        self,
        tmp_path: Path,
    ) -> None:
        """A wider stale snapshot cannot replace only its still-live suffix."""
        log = EventLog(tmp_path / "th.jsonl")
        log.thread_started("th")
        turns = [_make_turn(i, user_text=f"u-{i}") for i in range(5)]
        for turn in turns:
            log.turn_started("th", turn)
            log.turn_completed("th", turn.id, TurnStatus.COMPLETED)

        first = compact(
            "th",
            turns,
            CompactionPolicy(trigger_at=5, keep_recent=2),
        )
        stale_wider = compact(
            "th",
            turns,
            CompactionPolicy(trigger_at=5, keep_recent=1),
        )
        assert first is not None and stale_wider is not None
        log.turn_compacted("th", first.summary_turn, first.superseded_ids)
        log.turn_compacted(
            "th",
            stale_wider.summary_turn,
            stale_wider.superseded_ids,
        )

        assert [turn.id for turn in log.replay()] == [
            first.summary_turn.id,
            turns[3].id,
            turns[4].id,
        ]

    def test_replay_ignores_reordered_or_non_prefix_compaction(self, tmp_path: Path) -> None:
        """Only the exact, ordered visible prefix is a valid replacement base."""
        log = EventLog(tmp_path / "th.jsonl")
        log.thread_started("th")
        turns = [_make_turn(i, user_text=f"u-{i}") for i in range(5)]
        for turn in turns:
            log.turn_started("th", turn)
            log.turn_completed("th", turn.id, TurnStatus.COMPLETED)

        reordered = compact(
            "th",
            turns,
            CompactionPolicy(trigger_at=5, keep_recent=2),
        )
        non_prefix = compact(
            "th",
            turns,
            CompactionPolicy(trigger_at=5, keep_recent=3),
        )
        assert reordered is not None and non_prefix is not None
        log.turn_compacted(
            "th",
            reordered.summary_turn,
            list(reversed(reordered.superseded_ids)),
        )
        log.turn_compacted(
            "th",
            non_prefix.summary_turn,
            [turns[1].id, turns[2].id],
        )

        assert [turn.id for turn in log.replay()] == [turn.id for turn in turns]

    def test_replay_ignores_malformed_compaction_lineage(self, tmp_path: Path) -> None:
        """Empty, duplicate, or non-string source ids cannot form a CAS key."""
        log = EventLog(tmp_path / "th.jsonl")
        log.thread_started("th")
        turns = [_make_turn(i, user_text=f"u-{i}") for i in range(3)]
        for turn in turns:
            log.turn_started("th", turn)
            log.turn_completed("th", turn.id, TurnStatus.COMPLETED)

        invalid_lineages: list[list[object]] = [
            [],
            [turns[0].id, turns[0].id],
            [turns[0].id, 7],
        ]
        for index, lineage in enumerate(invalid_lineages):
            summary = _make_turn(100 + index, agent_text="invalid summary")
            log.append(
                LoggedEvent(
                    event="turn_compacted",
                    threadId="th",
                    turnId=summary.id,
                    payload={
                        "summaryTurn": summary.model_dump(by_alias=True, mode="json"),
                        "supersededTurnIds": lineage,
                    },
                )
            )

        assert [turn.id for turn in log.replay()] == [turn.id for turn in turns]

    def test_replay_applies_valid_second_generation_compaction(self, tmp_path: Path) -> None:
        """A later compaction may legitimately fold the prior summary prefix."""
        log = EventLog(tmp_path / "th.jsonl")
        log.thread_started("th")
        turns = [_make_turn(i, user_text=f"u-{i}") for i in range(5)]
        for turn in turns:
            log.turn_started("th", turn)
            log.turn_completed("th", turn.id, TurnStatus.COMPLETED)

        first = compact(
            "th",
            turns,
            CompactionPolicy(trigger_at=5, keep_recent=2),
        )
        assert first is not None
        log.turn_compacted("th", first.summary_turn, first.superseded_ids)

        turn_5 = _make_turn(5, user_text="u-5")
        log.turn_started("th", turn_5)
        log.turn_completed("th", turn_5.id, TurnStatus.COMPLETED)
        visible = log.replay()
        assert [turn.id for turn in visible] == [
            first.summary_turn.id,
            turns[3].id,
            turns[4].id,
            turn_5.id,
        ]

        second = compact(
            "th",
            visible,
            CompactionPolicy(trigger_at=4, keep_recent=1),
        )
        assert second is not None
        assert second.superseded_ids == [
            first.summary_turn.id,
            turns[3].id,
            turns[4].id,
        ]
        log.turn_compacted("th", second.summary_turn, second.superseded_ids)

        assert [turn.id for turn in log.replay()] == [
            second.summary_turn.id,
            turn_5.id,
        ]
