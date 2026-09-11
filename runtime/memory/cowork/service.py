"""Membership service — the actor-agnostic write path.

The HTTP router attributes mutations to the authenticated *human*. But a real
team also has members pulling in *other* members: "this needs a DB expert, I'll
grab @db-agent." ``MemberEvent.actor`` is already a free-form id, so an agent's
delegation tool can call these helpers with ``actor=<its own id>`` to assemble
the team it needs — agent-initiated membership, no special case.

Thin wrappers over ``GroupStore.append`` so both the router and in-process agent
tools share one validated write path.
"""

from __future__ import annotations

from runtime.memory.cowork.group import (
    VALID_MODES,
    ContextGrant,
    MemberEvent,
    normalize_driver_kind,
    normalize_group_mode,
    normalize_member_kind,
)
from runtime.memory.cowork.group_store import GroupStore


def invite_member(
    store: GroupStore,
    thread_id: str,
    *,
    actor: str,
    target_id: str,
    kind: str = "agent",
    role: str = "participant",
    grant: ContextGrant | None = None,
    at_message: int | None = None,
    owner: str = "",
) -> MemberEvent:
    """Pull a member into the thread. ``actor`` may be a human OR an agent id —
    that's the whole agent-initiated-invite feature.

    ``kind="role"`` invites a 数字员工 and requires ``owner``: the human who
    answers for it. Without an owner it is just a bare AI wearing a role label,
    so we refuse instead of creating an unattributable member."""
    if not target_id:
        raise ValueError("target_id is required")
    member_kind = normalize_member_kind(kind)
    normalized_owner = str(owner or "").strip()
    if member_kind == "role" and not normalized_owner:
        raise ValueError("a role member requires an accountable owner")
    return store.append(
        thread_id,
        MemberEvent(
            action="invite",
            actor=actor or "system",
            target_id=target_id,
            target_kind=member_kind,
            role="observer" if role == "observer" else "participant",
            grant=grant or ContextGrant(),
            at_message=at_message,
            owner=normalized_owner if member_kind == "role" else "",
        ),
    )


def set_driver(
    store: GroupStore,
    thread_id: str,
    *,
    actor: str,
    target_id: str,
    driver: str,
) -> MemberEvent:
    """Hand a member's wheel to its AI (``driver="ai"``) or to a person
    (``driver="human"`` — 接管).

    Rejected for a human member: a person is never driven by an AI."""
    normalized = normalize_driver_kind(driver)
    if normalized is None:
        raise ValueError("driver must be one of ('ai', 'human')")
    state = store.state(thread_id)
    member = state.member(target_id)
    if member is None:
        raise ValueError(f"{target_id} is not a member of {thread_id}")
    if member.kind == "human" and normalized == "ai":
        raise ValueError("a human member is always driven by a human")
    if member.kind == "role" and normalized == "human" and not member.accountable_owner:
        raise ValueError("a role member without an accountable owner cannot be taken over")
    return store.append(
        thread_id,
        MemberEvent(
            action="drive",
            actor=actor or "system",
            target_id=target_id,
            driver=normalized,
        ),
    )


def remove_member(store: GroupStore, thread_id: str, *, actor: str, target_id: str) -> MemberEvent:
    return store.append(
        thread_id,
        MemberEvent(action="leave", actor=actor or "system", target_id=target_id),
    )


def set_mode(store: GroupStore, thread_id: str, *, actor: str, mode: str) -> MemberEvent:
    normalized_mode = normalize_group_mode(mode)
    if normalized_mode is None:
        raise ValueError(f"mode must be one of {sorted(VALID_MODES)}")
    return store.append(
        thread_id,
        MemberEvent(action="mode", actor=actor or "system", mode=normalized_mode),
    )
