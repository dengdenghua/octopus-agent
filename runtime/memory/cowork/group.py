"""WeChat-style thread group: membership / mode / context-grant as folded events.

The design conclusion from the conversation made concrete:

- **A thread *is* the group.** A 1:1 chat is just the N=2 degenerate case — there
  is no separate "team" entity. ``fold_state`` reconstructs the current roster +
  mode by folding an append-only event log, so "add / remove anyone at any time"
  is just appending an event.
- **Membership is event-sourced**, not a snapshot: invite / leave / mute / mode
  events anchored at a message index, so the timeline can show "Alice pulled Bob
  in at message 42" and a re-opened thread restores its exact state.
- **Context-grant on join** is the privacy seam: when you pull someone into an
  ongoing thread you choose *what slice of history* they get (all / from-here /
  a range / summary only) — so prior private context never silently leaks and a
  specialist pulled in for one question isn't handed 500 messages.
- **Collaboration mode** (chat / cluster / swarm) is a non-destructive overlay:
  switching it changes *who responds*, never the membership or history.

This module is pure (no I/O) so the folding + grant + speaker logic is fully
unit-tested; persistence lives in ``group_store`` and the shared blackboard is
the existing ``SqliteBlackboard`` namespaced by thread id.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, cast

# Who a roster entry *is* — the accountability axis.
#
#   agent  a bare AI. The platform answers for it; nobody owns it personally.
#   role   a 数字员工: a role-bound AI with a named human owner
#          (``Member.accountable_owner``), so a person — not the platform —
#          answers for what it does.
#   human  a person.
#
# Deliberately distinct from ``MemberRole`` (participant/observer), which is the
# "may it speak" axis. Do not collapse the two.
MemberKind = Literal["agent", "role", "human"]
# Who is *currently driving* a member. A 数字员工 can be handed over to its owner
# (``human``), but never both at once: see ``responders``.
DriverKind = Literal["ai", "human"]
MemberRole = Literal["participant", "observer"]
GrantScope = Literal["all", "from_join", "range", "summary"]
GroupMode = Literal["chat", "cluster", "swarm"]

# What a *recorded message* claims about its sender. Resolved by the server from
# the roster at write time and never self-reported, because an AI must not be
# able to label its own output as human work. ``unknown`` is a real, load-bearing
# state: an unattributable sender stays unattributable rather than being
# optimistically filed under "agent".
SenderKind = Literal["agent", "role", "human", "unknown"]
SenderDriver = Literal["ai", "human", "unknown"]

EventAction = Literal[
    "invite", "leave", "mute", "unmute", "mode", "room_link", "workspace_link", "drive"
]

DEFAULT_MODE: GroupMode = "chat"
VALID_MODES: frozenset[str] = frozenset({"chat", "cluster", "swarm"})
LEGACY_PROJECT_MODE = "project"


def normalize_group_mode(value: object) -> GroupMode | None:
    """Project the old four-mode wire/storage contract onto response modes.

    ``project`` used to mean both "this thread has project state" and "route
    the next chat message into Project OS".  A project binding is now an
    independent capability, so legacy events and old clients safely fall back
    to ordinary chat.  Unknown values remain invalid instead of silently
    widening the response contract.
    """

    if not isinstance(value, str):
        return None
    if value == LEGACY_PROJECT_MODE:
        return DEFAULT_MODE
    if value in VALID_MODES:
        return cast("GroupMode", value)
    return None


@dataclass(frozen=True)
class ContextGrant:
    """What slice of thread history a newly-invited member may see."""

    scope: GrantScope = "all"
    from_msg: int | None = None  # for scope="range"
    to_msg: int | None = None  # for scope="range"

    def to_dict(self) -> dict:
        return {"scope": self.scope, "from_msg": self.from_msg, "to_msg": self.to_msg}

    @classmethod
    def from_dict(cls, raw: dict | None) -> ContextGrant:
        if not isinstance(raw, dict):
            return cls()
        scope = raw.get("scope")
        if scope not in ("all", "from_join", "range", "summary"):
            scope = "all"
        return cls(
            scope=scope,
            from_msg=_as_int(raw.get("from_msg")),
            to_msg=_as_int(raw.get("to_msg")),
        )


def normalize_member_kind(value: object) -> MemberKind:
    """Widen a stored/wire member kind onto the three-member accountability axis.

    Unknown values collapse to ``agent`` — the *narrowest* claim. Collapsing the
    other way (``agent`` → ``role``) would manufacture a 数字员工 that no human
    answers for, which is precisely the failure this axis exists to prevent.
    """

    if value == "human":
        return "human"
    if value == "role":
        return "role"
    return "agent"


def normalize_driver_kind(value: object) -> DriverKind | None:
    """``None`` when absent/invalid so callers can distinguish "not stated"."""

    return value if value in ("ai", "human") else None


def sender_identity(
    state: GroupState | None, member_id: str
) -> tuple[SenderKind, SenderDriver]:
    """What a message written by ``member_id`` records about its sender.

    Read off the *roster* at write time, never off the message — a sender must
    not be able to label its own output. When the sender is not on the roster we
    return ``("unknown", "unknown")``: guessing ``agent`` here would fabricate an
    attribution in what is meant to be an audit trail.
    """

    member = state.member(member_id) if state is not None and member_id else None
    if member is None:
        return ("unknown", "unknown")
    return (member.kind, member.driver)


@dataclass
class MemberEvent:
    """One append-only membership/mode event on a thread's timeline."""

    action: EventAction
    actor: str  # who performed it (member id; "" for system)
    target_id: str = ""  # member affected (invite/leave/mute/drive); "" for mode
    target_kind: MemberKind = "agent"
    role: MemberRole = "participant"
    grant: ContextGrant = field(default_factory=ContextGrant)
    mode: GroupMode | None = None  # for action="mode"
    at_message: int | None = None  # message index this event is anchored to
    ts: str = ""  # ISO timestamp (stamped by the store)
    seq: int = 0  # monotonic order within the thread (stamped by the store)
    # For action="workspace_link": {"id", "name", "mount_type"} describing the
    # bound workspace. ``None`` for all other actions.
    workspace: dict | None = None
    # For action="invite": the human accountable for a ``role`` (数字员工)
    # member. Empty for ``agent`` / ``human`` members.
    owner: str = ""
    # For action="drive": who now holds the wheel of ``target_id``.
    driver: DriverKind | None = None

    def to_dict(self) -> dict:
        return {
            "action": self.action,
            "actor": self.actor,
            "target_id": self.target_id,
            "target_kind": self.target_kind,
            "role": self.role,
            "grant": self.grant.to_dict(),
            "mode": self.mode,
            "at_message": self.at_message,
            "ts": self.ts,
            "seq": self.seq,
            "workspace": self.workspace,
            "owner": self.owner,
            "driver": self.driver,
        }

    @classmethod
    def from_dict(cls, raw: dict) -> MemberEvent:
        action = raw.get("action")
        if action not in (
            "invite",
            "leave",
            "mute",
            "unmute",
            "mode",
            "room_link",
            "workspace_link",
            "drive",
        ):
            raise ValueError(f"unknown member event action: {action!r}")
        mode = normalize_group_mode(raw.get("mode"))
        ws_raw = raw.get("workspace")
        workspace = dict(ws_raw) if isinstance(ws_raw, dict) else None
        return cls(
            action=action,
            actor=str(raw.get("actor") or ""),
            target_id=str(raw.get("target_id") or ""),
            target_kind=normalize_member_kind(raw.get("target_kind")),
            role="observer" if raw.get("role") == "observer" else "participant",
            grant=ContextGrant.from_dict(raw.get("grant")),
            mode=mode,
            at_message=_as_int(raw.get("at_message")),
            ts=str(raw.get("ts") or ""),
            seq=int(raw.get("seq") or 0),
            workspace=workspace,
            owner=str(raw.get("owner") or ""),
            driver=normalize_driver_kind(raw.get("driver")),
        )


@dataclass
class Member:
    """A folded, currently-present member of the group."""

    id: str
    kind: MemberKind
    role: MemberRole
    joined_at_message: int | None
    grant: ContextGrant
    muted: bool = False
    invited_by: str = ""
    # The human accountable for a ``role`` (数字员工) member. Empty for
    # platform-owned ``agent`` members and for ``human`` members (who are their
    # own anchor). See ``identity_problem``.
    accountable_owner: str = ""
    # Who is driving right now. Always "human" for ``kind == "human"``.
    driver: DriverKind = "ai"

    @property
    def is_takeover(self) -> bool:
        """True when a person currently holds the wheel of a non-human member.

        This is the single fact the UI needs to answer "托管的还是真人接管的".
        """

        return self.kind != "human" and self.driver == "human"

    def identity_problem(self) -> str | None:
        """Why this member cannot be attributed, or ``None`` if it can.

        A 数字员工 with no named owner is not a 数字员工 — it is a bare AI
        wearing a role label, i.e. exactly the unattributable middle state this
        axis exists to forbid. Surfaced (not raised) so a bad historical roster
        still folds and can be reported, instead of taking the whole thread down.
        """

        if self.kind == "role" and not self.accountable_owner.strip():
            return "role member without an accountable owner"
        if self.kind == "human" and self.driver != "human":
            return "human member not driven by a human"
        return None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "role": self.role,
            "joined_at_message": self.joined_at_message,
            "grant": self.grant.to_dict(),
            "muted": self.muted,
            "invited_by": self.invited_by,
            "accountable_owner": self.accountable_owner,
            "driver": self.driver,
            "is_takeover": self.is_takeover,
            "identity_problem": self.identity_problem(),
        }


@dataclass
class GroupState:
    """The current group: roster (in join order) + active collaboration mode."""

    roster: list[Member] = field(default_factory=list)
    mode: GroupMode = DEFAULT_MODE
    event_count: int = 0
    room_id: str | None = None  # linked Team Room (the session's other surface)
    # Linked Workspace info (``{"id", "name", "mount_type"}``) when a
    # ``workspace_link`` event has been folded in; ``None`` otherwise. The
    # *latest* ``workspace_link`` event wins, mirroring the ``room_link`` rule.
    workspace: dict | None = None

    @property
    def is_one_to_one(self) -> bool:
        """A 1:1 is the degenerate group: at most one AI-side member + at most
        one human. 数字员工 (``role``) count on the AI side — a chat with a
        digital employee and its owner is still a 1:1, not a team.
        The UI uses this to stay lightweight, not to branch the data model."""
        ai_members = sum(1 for m in self.roster if m.kind != "human")
        humans = sum(1 for m in self.roster if m.kind == "human")
        return ai_members <= 1 and humans <= 1

    @property
    def takeovers(self) -> list[Member]:
        """Members a person is currently driving (托管 → 接管)."""

        return [m for m in self.roster if m.is_takeover]

    @property
    def unattributed(self) -> list[Member]:
        """Members that cannot be attributed to anyone — see ``identity_problem``."""

        return [m for m in self.roster if m.identity_problem() is not None]

    def member(self, member_id: str) -> Member | None:
        return next((m for m in self.roster if m.id == member_id), None)

    def to_dict(self) -> dict:
        return {
            "roster": [m.to_dict() for m in self.roster],
            "mode": self.mode,
            "event_count": self.event_count,
            "is_one_to_one": self.is_one_to_one,
            "room_id": self.room_id,
            "workspace": self.workspace,
            "takeover_ids": [m.id for m in self.takeovers],
            "unattributed_ids": [m.id for m in self.unattributed],
        }


def _as_int(value: object) -> int | None:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def fold_state(events: list[MemberEvent], until_seq: int | None = None) -> GroupState:
    """Reconstruct the current group by folding the membership event log.

    Order is by ``seq``. invite adds (or re-adds — joined_at_message refreshes);
    leave removes; mute/unmute toggle; drive moves the wheel between the AI and
    its owner; mode sets the active overlay. Removed members simply drop from the
    roster — their past blackboard writes stay (attributed) because the blackboard
    is a separate, append-only store.

    ``until_seq`` folds only events up to and including that seq — that's all
    "replay to a point" / "fork at message N" need, for free, because the whole
    state is event-sourced."""
    members: dict[str, Member] = {}
    mode: GroupMode = DEFAULT_MODE
    room_id: str | None = None
    workspace: dict | None = None
    scoped = events if until_seq is None else [e for e in events if e.seq <= until_seq]
    for ev in sorted(scoped, key=lambda e: e.seq):
        if ev.action == "invite":
            if not ev.target_id:
                continue
            members[ev.target_id] = Member(
                id=ev.target_id,
                kind=ev.target_kind,
                role=ev.role,
                joined_at_message=ev.at_message,
                grant=ev.grant,
                muted=False,
                invited_by=ev.actor,
                accountable_owner=ev.owner,
                # A person is always their own driver; an AI-side member starts
                # out on its own unless a drive event says otherwise.
                driver="human" if ev.target_kind == "human" else "ai",
            )
        elif ev.action == "leave":
            members.pop(ev.target_id, None)
        elif ev.action in ("mute", "unmute"):
            m = members.get(ev.target_id)
            if m is not None:
                m.muted = ev.action == "mute"
        elif ev.action == "drive":
            m = members.get(ev.target_id)
            # Refuse to fold nonsense rather than recording a wrong attribution:
            # a person is never driven by an AI.
            if m is None or ev.driver is None:
                continue
            if m.kind == "human" and ev.driver == "ai":
                continue
            m.driver = ev.driver
        elif ev.action == "mode":
            normalized_mode = normalize_group_mode(ev.mode)
            if normalized_mode is not None:
                mode = normalized_mode
        elif ev.action == "room_link":
            room_id = ev.target_id or None
        elif ev.action == "workspace_link":
            # The latest workspace_link event wins; fall back to target_id for
            # the workspace id when the ``workspace`` dict isn't populated.
            ws = dict(ev.workspace) if isinstance(ev.workspace, dict) else {}
            if ev.target_id and not ws.get("id"):
                ws["id"] = ev.target_id
            workspace = ws or None
    return GroupState(
        roster=list(members.values()),
        mode=mode,
        event_count=len(scoped),
        room_id=room_id,
        workspace=workspace,
    )


def visible_message_range(member: Member, current_max_message: int) -> tuple[int, int] | None:
    """The [lo, hi] message indices ``member`` is allowed to see, from its grant.

    Returns ``None`` for scope="summary" (the member gets a summary, not raw
    history). This is the privacy seam that makes pulling someone into an ongoing
    thread safe: they see exactly the granted slice, not the whole transcript."""
    grant = member.grant
    if grant.scope == "all":
        return (0, current_max_message)
    if grant.scope == "from_join":
        return (member.joined_at_message or 0, current_max_message)
    if grant.scope == "range":
        lo = grant.from_msg if grant.from_msg is not None else 0
        hi = grant.to_msg if grant.to_msg is not None else current_max_message
        return (max(0, lo), max(lo, hi))
    return None  # summary → no raw range


def responders(state: GroupState, addressed: list[str] | None = None) -> list[str]:
    """Who should act this turn — the bridge from *mode* to *behaviour*.

    This is how "modes" stop being a manual switch and become automatic:
      - chat:    @addressed members, else the sole agent (a true 1:1), else
                 nobody (wait for an @mention) — like a real group chat.
      - cluster: the leader (first agent participant) orchestrates.
      - swarm:   every unmuted agent participant works in parallel.
    Observers and muted members never respond; humans aren't auto-driven.

    数字员工 (``kind == "role"``) respond exactly like bare agents — they are
    still AI on the wire. The one thing that removes a member from this list is
    **a person currently driving it**: while the owner holds the wheel the AI
    must stand down, or the same mouth would have two drivers and no utterance
    could be attributed to either. That is a hard rule, not a preference.
    """
    agents = [
        m
        for m in state.roster
        if m.kind != "human"
        and m.role == "participant"
        and not m.muted
        and m.driver != "human"
    ]
    if addressed:
        targeted = [m.id for m in agents if m.id in set(addressed)]
        if targeted:
            return targeted
    if state.mode == "swarm":
        return [m.id for m in agents]
    if state.mode == "cluster":
        return [agents[0].id] if agents else []
    # chat: the sole agent answers a 1:1; otherwise wait to be addressed.
    return [agents[0].id] if len(agents) == 1 else []
