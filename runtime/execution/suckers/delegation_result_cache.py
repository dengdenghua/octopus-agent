"""Spawn-level content-hash result cache · resume a graph without respawning.

The identity of a spawn is what it was asked to do, not when it was asked:
``(agent_id, resolved prompt, model tier, context digest)``. Hash those and a
re-declared node that would redo identical work can replay the recorded result
instead of spending a spawn.

Scope is deliberately narrow:

* Activation is EXPLICIT. A cache exists only when a caller (today:
  ``call_agent_graph`` with a ``resume_token``) creates one and hands it to the
  spawn path. Nothing else - ``run_orchestration``'s rounds, votes, retries -
  changes behaviour, because re-sampling with a fresh model draw is sometimes
  the point of a repeated prompt, and the runtime cannot tell that case apart
  from the wasteful one. Only a caller who knows it wants determinism opts in.
* Storage is in-memory and token-scoped. A token is a namespace with a FIFO
  shelf life; process restart forgets everything (resume across restarts would
  need journal persistence and is a different feature). The token is generated
  on the trusted side - a model cannot pre-seed a cache because it cannot
  predict the token.

The one rule that must never bend: **only completed, non-empty results enter
the store.** A failure, an empty output, or an interrupted spawn is exactly the
work a resume exists to REDO; caching any of them would pin one bad run onto
every future resume with the same token.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import threading
from dataclasses import dataclass, field
from typing import Any

# Context keys that differ per invocation without changing the work: closures
# (unstable reprs), ambient stacks, routing decisions made per-call, and
# per-spawn bookkeeping. Stripped before hashing so a resumed node's key
# matches the original's.
_VOLATILE_CONTEXT_KEYS = frozenset(
    {
        "event_emitter",
        "react_stack",
        "subagent_route_decision",
        "subagent_session_id",
        "subagent_report_delivery",
        "subagent_source_path",
        "subagent_scope",
        "caller_thread_id",
        "timeout_s",
        "skill_policy_sources",
        "skill_policy_reason_map",
        "dynamic_skill_grant_note",
    }
)

_MAX_ENTRIES_PER_TOKEN = 256
_MAX_TOKENS = 128


def _digest_context(context: dict[str, Any] | None) -> str:
    """Stable digest of the context fields that shape the work.

    Volatile keys are dropped first; the rest is canonical JSON. A value no
    JSON encoder accepts falls back to ``repr`` so the digest still terminates -
    such a value is by definition not content the caller controls, and its
    inclusion can only make the key more specific, never less.
    """
    ctx = {k: v for k, v in (context or {}).items() if k not in _VOLATILE_CONTEXT_KEYS}
    try:
        blob = json.dumps(ctx, sort_keys=True, ensure_ascii=False, default=repr)
    except (TypeError, ValueError):  # pragma: no cover - default=repr covers it
        blob = repr(sorted(ctx.items(), key=lambda kv: str(kv[0])))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def compute_spawn_cache_key(
    *,
    agent_id: str,
    prompt: str,
    cheap: bool = False,
    context: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
) -> str:
    """Content hash identifying one spawn's work.

    ``extra`` carries identity-bearing fields the caller knows about but that
    don't live in the context - e.g. a node's ``output_schema``, which changes
    what a valid reply looks like even though the prompt is unchanged.
    """
    material = json.dumps(
        {
            "agent_id": str(agent_id),
            "prompt": str(prompt),
            "cheap": bool(cheap),
            "context": _digest_context(context),
            "extra": extra or {},
        },
        sort_keys=True,
        ensure_ascii=False,
        default=repr,
    )
    return "spawn:v1:" + hashlib.sha256(material.encode("utf-8")).hexdigest()


# What is stored per entry: the success payload a caller needs to replay the
# node, and nothing that describes THIS run's plumbing (spec_index, retry
# flags, route decisions - all of it would be a lie about the replayed run).
_SNAPSHOT_FIELDS = ("agent_id", "codename", "output", "parsed", "schema_ok")


@dataclass
class SpawnResultCache:
    """One token's replay store. Thread-safe: parallel lanes put concurrently."""

    token: str
    _entries: dict[str, dict[str, Any]] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def get(self, key: str) -> dict[str, Any] | None:
        with self._lock:
            hit = self._entries.get(key)
            return dict(hit) if hit is not None else None

    def put(self, key: str, result: dict[str, Any]) -> bool:
        """Store a result. Returns False (and stores nothing) unless the result
        is a completed, non-empty success - the rule this cache exists under.

        Completion is judged by the fields that are actually present on an
        envelope entry, NOT by a ``success`` flag. ``_build_parallel_envelope``
        drops that flag from ``successes`` (membership in the list IS the
        success signal), so requiring it here made every real spawn unstorable
        while hand-built test envelopes carrying ``success: True`` passed - the
        cache looked correct and cached nothing in production.

        So: an explicit ``success: False`` still rejects, a missing flag is
        treated as "the caller already classified this as a success", and the
        partial/round-cap/converged markers reject regardless - those describe a
        spawn that stopped early, which is exactly what a resume must redo.
        """
        if not isinstance(result, dict):
            return False
        if result.get("success") is False:
            return False
        if any(
            result.get(marker)
            for marker in ("partial", "round_cap_exceeded", "converged_early", "error")
        ):
            return False
        if not str(result.get("output") or "").strip():
            return False
        snapshot = {k: result[k] for k in _SNAPSHOT_FIELDS if k in result}
        snapshot["success"] = True
        with self._lock:
            if len(self._entries) < _MAX_ENTRIES_PER_TOKEN or key in self._entries:
                self._entries[key] = snapshot
                return True
        return False

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)


_TOKEN_STORE: dict[str, SpawnResultCache] = {}
_STORE_LOCK = threading.Lock()


def create_spawn_cache(token: str = "") -> SpawnResultCache:
    """Create (and register) a fresh cache. Token generated when omitted."""
    tok = str(token or "").strip() or f"src-{secrets.token_urlsafe(9)}"
    cache = SpawnResultCache(token=tok)
    with _STORE_LOCK:
        while len(_TOKEN_STORE) >= _MAX_TOKENS:
            _TOKEN_STORE.pop(next(iter(_TOKEN_STORE)))  # FIFO: oldest token goes
        _TOKEN_STORE[tok] = cache
    return cache


def load_spawn_cache(token: str) -> SpawnResultCache | None:
    """Look up a previously issued cache. ``None`` for unknown/expired tokens -
    the caller decides whether that is an error (a resume with a typo'd token
    should fail loud, not silently re-run everything the caller thought was
    cached).
    """
    with _STORE_LOCK:
        return _TOKEN_STORE.get(str(token or "").strip())


def reset_spawn_cache_store() -> None:
    """Test seam: drop every token. Production code never needs this."""
    with _STORE_LOCK:
        _TOKEN_STORE.clear()
