from __future__ import annotations

import hashlib
import json
import logging
import threading
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

_LOG = logging.getLogger("octopus.turn_scoring")

# Where the per-agent scores file lives (under the agent's own
# core dir, alongside SOUL.md and MEMORY.md).
_SCORES_FILENAME = ".scores.jsonl"

# Keep the file bounded · drop oldest lines when over this. 5000
# turns is well over a year of casual use, plenty for any
# correlation analysis we do.
_MAX_LINES_KEEP: int = 5000

# Module-level lock · serializes appends across the SSE pump
# threads + ephemeral sub-agent runners + UI reads. Coarse but
# fine: per-turn write rate is at most 1 / second, contention is
# nil.
_FILE_LOCK = threading.Lock()


@dataclass(slots=True)
class TurnScore:
    """One scored turn · serialized to a single jsonl line."""

    ts: str  # ISO-8601 wall time
    agent_id: str
    score: float  # 0.0 / 0.5 / 1.0
    reason: str  # short tag (e.g. "success", "tool_errors",
    # "interrupted", "no_reply")
    soul_hash: str  # 8-char MD5 of SOUL.md at score time
    rounds: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    duration_ms: int = 0
    thread_id: str = ""
    turn_id: str = ""


# ═══════════════════════════════════════════════════════════
# Scoring
# ═══════════════════════════════════════════════════════════


def score_turn_outcome(
    *,
    has_final_reply: bool,
    tool_error_count: int = 0,
    rounds_used: int = 0,
    rounds_max: int = 30,
    interrupted: bool = False,
    duration_ms: int = 0,
    timeout_ms: int | None = None,
) -> tuple[float, str]:
    """Pure scoring function · no I/O · easy to unit test.

    Returns ``(score, reason)`` where reason is a short tag
    summarizing the dominant signal.

    Decision rules (first match wins):
        - interrupted/cancelled        → 0.0  "interrupted"
        - no final reply               → 0.0  "no_reply"
        - exceeded timeout             → 0.0  "timeout"
        - hit max rounds without reply → 0.0  "round_cap"
        - had tool errors > 0          → 0.5  "tool_errors"
        - rounds >= 80% of max         → 0.5  "near_round_cap"
        - else                         → 1.0  "success"
    """
    if interrupted:
        return (0.0, "interrupted")
    if not has_final_reply:
        if rounds_used >= rounds_max:
            return (0.0, "round_cap")
        return (0.0, "no_reply")
    if timeout_ms is not None and duration_ms >= timeout_ms:
        return (0.0, "timeout")
    if tool_error_count > 0:
        return (0.5, "tool_errors")
    if rounds_max > 0 and rounds_used >= int(rounds_max * 0.8):
        return (0.5, "near_round_cap")
    return (1.0, "success")


def _project_root() -> Path:
    from runtime.platform.process.paths import project_root

    return project_root()


def _scores_path(agent_id: str) -> Path:
    return _project_root() / "agents" / agent_id / "agent-core" / _SCORES_FILENAME


def _soul_hash(agent_id: str) -> str:
    """8-char MD5 of the agent's current SOUL.md (or empty)."""
    soul = _project_root() / "agents" / agent_id / "agent-core" / "SOUL.md"
    if not soul.exists():
        return ""
    try:
        return hashlib.md5(soul.read_bytes(), usedforsecurity=False).hexdigest()[:8]
    except Exception:  # noqa: BLE001
        return ""


def record_turn_score(
    *,
    agent_id: str,
    score: float,
    reason: str,
    rounds: int = 0,
    input_tokens: int = 0,
    output_tokens: int = 0,
    duration_ms: int = 0,
    thread_id: str = "",
    turn_id: str = "",
) -> Path | None:
    """Append a TurnScore to the agent's `.scores.jsonl`. Returns the
    path written, or None if the agent_id is empty / disk failure.

    Wrapped in best-effort try/except — scoring is a side-feature,
    a write failure must NEVER kill the user's turn.
    """
    if not agent_id:
        return None
    path = _scores_path(agent_id)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        ts = TurnScore(
            ts=datetime.now().isoformat(timespec="seconds"),
            agent_id=agent_id,
            score=float(score),
            reason=reason,
            soul_hash=_soul_hash(agent_id),
            rounds=int(rounds),
            input_tokens=int(input_tokens),
            output_tokens=int(output_tokens),
            duration_ms=int(duration_ms),
            thread_id=thread_id or "",
            turn_id=turn_id or "",
        )
        line = json.dumps(asdict(ts), ensure_ascii=False) + "\n"
        with _FILE_LOCK:
            with path.open("a", encoding="utf-8") as fh:
                fh.write(line)
            _trim_if_oversized_locked(path)
    except Exception as exc:  # noqa: BLE001
        _LOG.warning(
            "record_turn_score failed for %s: %s",
            agent_id,
            exc,
        )
        return None
    return path


def _trim_if_oversized_locked(path: Path) -> None:
    """If file > MAX_LINES, rewrite keeping only the most recent
    ``_MAX_LINES_KEEP`` lines. Caller holds ``_FILE_LOCK``."""
    try:
        # Cheap line count without holding the whole file in memory:
        # only count if > some threshold byte size to avoid stat-then-
        # noop on every write.
        if path.stat().st_size < (_MAX_LINES_KEEP * 200):
            return
        with path.open("r", encoding="utf-8") as fh:
            lines = fh.readlines()
        if len(lines) <= _MAX_LINES_KEEP:
            return
        keep = lines[-_MAX_LINES_KEEP:]
        # Atomic-ish rewrite via temp file in same dir.
        tmp = path.with_suffix(".jsonl.tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            fh.writelines(keep)
        tmp.replace(path)
    except OSError:  # noqa: BLE001
        # Trim is opportunistic; never crash on it.
        pass


# ═══════════════════════════════════════════════════════════
# Read / aggregate
# ═══════════════════════════════════════════════════════════


def read_recent_scores(
    agent_id: str,
    limit: int = 50,
) -> list[TurnScore]:
    """Return up to ``limit`` most recent TurnScore entries
    (newest first). Empty list if no file."""
    path = _scores_path(agent_id)
    if not path.exists() or not agent_id:
        return []
    out: list[TurnScore] = []
    try:
        with _FILE_LOCK, path.open("r", encoding="utf-8") as fh:
            lines = fh.readlines()
    except Exception:  # noqa: BLE001
        return []
    for raw in reversed(lines):
        raw = raw.strip()
        if not raw:
            continue
        try:
            d = json.loads(raw)
            out.append(
                TurnScore(
                    ts=str(d.get("ts", "")),
                    agent_id=str(d.get("agent_id", "")),
                    score=float(d.get("score", 0.0)),
                    reason=str(d.get("reason", "")),
                    soul_hash=str(d.get("soul_hash", "")),
                    rounds=int(d.get("rounds", 0) or 0),
                    input_tokens=int(d.get("input_tokens", 0) or 0),
                    output_tokens=int(d.get("output_tokens", 0) or 0),
                    duration_ms=int(d.get("duration_ms", 0) or 0),
                    thread_id=str(d.get("thread_id", "")),
                    turn_id=str(d.get("turn_id", "")),
                )
            )
        except Exception:  # noqa: BLE001
            continue
        if len(out) >= limit:
            break
    return out


def analyze_soul_impact(
    agent_id: str,
    *,
    window: int = 20,
    drop_threshold: float = 0.2,
) -> dict[str, Any]:
    """Compare avg score before vs after the most recent SOUL change.

    Algorithm:
        - Read up to 2*window recent scores.
        - Find the position where ``soul_hash`` last changed.
        - Split: scores BEFORE that pivot vs AFTER.
        - Compute avg on each side · only with at least
          ``min(window, 5)`` samples per side, otherwise inconclusive.
        - If avg dropped by > drop_threshold → flag.

    Returns a dict suitable for direct skill output:

        {
          "ok": True,
          "verdict": "no_change" | "improved" | "regressed" |
                     "inconclusive",
          "before_avg": float | None,
          "after_avg": float | None,
          "delta": float | None,
          "before_n": int,
          "after_n": int,
          "current_soul_hash": str,
          "previous_soul_hash": str | None,
          "suggestion": str,
        }
    """
    scores = read_recent_scores(agent_id, limit=2 * window)
    if not scores:
        return {
            "ok": False,
            "verdict": "no_data",
            "suggestion": "no scores recorded yet · run a few turns first",
        }
    current_hash = scores[0].soul_hash
    # Find the index where soul_hash changed (going from newest to
    # oldest). All entries [0..pivot-1] are "after" (current SOUL),
    # entries [pivot..] are "before" (previous SOUL).
    pivot: int | None = None
    previous_hash: str | None = None
    for i, s in enumerate(scores):
        if s.soul_hash != current_hash:
            pivot = i
            previous_hash = s.soul_hash
            break

    if pivot is None:
        # No SOUL change in the recent window — nothing to compare.
        avg_now = sum(s.score for s in scores) / max(1, len(scores))
        return {
            "ok": True,
            "verdict": "no_change",
            "current_soul_hash": current_hash,
            "previous_soul_hash": None,
            "after_avg": round(avg_now, 3),
            "before_avg": None,
            "delta": None,
            "after_n": len(scores),
            "before_n": 0,
            "suggestion": (
                f"SOUL unchanged across last {len(scores)} turns · "
                f"avg score {avg_now:.2f}/1.0 · no action needed"
            ),
        }

    after = scores[:pivot]
    before = scores[pivot : pivot + window]  # cap at window
    min_samples = min(window, 5)
    if len(after) < min_samples or len(before) < min_samples:
        return {
            "ok": True,
            "verdict": "inconclusive",
            "current_soul_hash": current_hash,
            "previous_soul_hash": previous_hash,
            "after_avg": round(
                sum(s.score for s in after) / max(1, len(after)),
                3,
            )
            if after
            else None,
            "before_avg": round(
                sum(s.score for s in before) / max(1, len(before)),
                3,
            )
            if before
            else None,
            "delta": None,
            "after_n": len(after),
            "before_n": len(before),
            "suggestion": (
                f"need ≥ {min_samples} samples per side · "
                f"have before={len(before)}, after={len(after)} · "
                f"run more turns before judging the latest SOUL change"
            ),
        }

    avg_before = sum(s.score for s in before) / len(before)
    avg_after = sum(s.score for s in after) / len(after)
    delta = avg_after - avg_before

    if delta < -drop_threshold:
        verdict = "regressed"
        suggestion = (
            f"avg score dropped {abs(delta):.2f} after the SOUL "
            f"change ({avg_before:.2f} → {avg_after:.2f}) · "
            f"consider `revert_soul(steps_back=1, "
            f"reason='regression after lesson')`"
        )
    elif delta > drop_threshold:
        verdict = "improved"
        suggestion = (
            f"avg score rose {delta:+.2f} after the SOUL change "
            f"({avg_before:.2f} → {avg_after:.2f}) · keep the "
            f"current lessons"
        )
    else:
        verdict = "neutral"
        suggestion = (
            f"avg score barely changed ({avg_before:.2f} → "
            f"{avg_after:.2f}) · the latest lesson is not "
            f"clearly hurting or helping yet"
        )
    return {
        "ok": True,
        "verdict": verdict,
        "current_soul_hash": current_hash,
        "previous_soul_hash": previous_hash,
        "after_avg": round(avg_after, 3),
        "before_avg": round(avg_before, 3),
        "delta": round(delta, 3),
        "after_n": len(after),
        "before_n": len(before),
        "suggestion": suggestion,
    }


__all__ = [
    "TurnScore",
    "score_turn_outcome",
    "record_turn_score",
    "read_recent_scores",
    "analyze_soul_impact",
]
