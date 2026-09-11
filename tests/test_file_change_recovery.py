from types import SimpleNamespace

import pytest

from runtime.protocol.items import FileChange, FileChangeItem, FileHunk, Turn, TurnStatus
from runtime.sensing.gateway.realtime_cerebrum import CerebrumRuntime
from runtime.sensing.gateway.realtime_gateway import _RpcError


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invalid", ["missing", "tampered", "truncated", "changed", "inherited", None]
)
async def test_revert_requires_real_evidence_and_survives_replay(tmp_path, invalid):
    runtime = CerebrumRuntime(stack=object(), agent=object(), logs_root=str(tmp_path / "logs"))
    target = tmp_path / "file.txt"
    target.write_text("new\n" if invalid != "changed" else "user edit\n", encoding="utf-8")
    original = target.read_bytes()
    diff = "--- a/file.txt\n+++ b/file.txt\n@@ -1,1 +1,1 @@\n-old\n+new\n"
    log = runtime._log_for("thread")
    if invalid == "inherited":
        from runtime.memory.threads.event_log import LoggedEvent

        log.append(
            LoggedEvent(
                event="thread_started", threadId="thread", payload={"forkedTurnIds": ["turn"]}
            )
        )
    log.turn_started("thread", Turn(id="turn", threadId="thread"))
    if invalid != "missing":
        log.item_completed(
            "thread",
            "turn",
            FileChangeItem(
                id="change",
                changes=[
                    FileChange(
                        path=str(target),
                        op="update",
                        diff=diff,
                        diffTruncated=invalid == "truncated",
                        hunks=[
                            FileHunk(
                                id="hunk",
                                oldStart=1,
                                oldLines=1,
                                newStart=1,
                                newLines=1,
                                body="-old\n+new\n",
                            )
                        ],
                    )
                ],
            ),
        )
    log.turn_completed("thread", "turn", TurnStatus.COMPLETED)

    async def notify(*args):
        pass

    emitter = SimpleNamespace(actor_id=None, notify=notify)
    params = {
        "threadId": "thread",
        "turnId": "turn",
        "itemId": "change",
        "hunkId": "hunk",
        "path": str(target),
        "decision": "rejected",
        "diff": diff.replace("-old", "-forged") if invalid == "tampered" else diff,
    }
    if invalid:
        with pytest.raises(_RpcError):
            await runtime._handle_hunk_decide(params, emitter)
        assert target.read_bytes() == original
    else:
        await runtime._handle_hunk_decide({**params, "decision": "accepted"}, emitter)
        assert target.read_bytes() == original
        assert log.replay()[0].items[0].changes[0].hunks[0].decision == "accepted"
        await runtime._handle_hunk_decide(params, emitter)
        assert target.read_text() == "old\n"
        assert log.replay()[0].items[0].changes[0].hunks[0].decision == "rejected"
        # Lost reply/retry must not reverse-apply the same edit twice.
        await runtime._handle_hunk_decide(params, emitter)
        assert target.read_text() == "old\n"
        with pytest.raises(_RpcError):
            await runtime._handle_hunk_decide({**params, "decision": "accepted"}, emitter)
