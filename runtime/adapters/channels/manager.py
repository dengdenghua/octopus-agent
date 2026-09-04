from __future__ import annotations

import concurrent.futures
import contextlib
import contextvars
import logging
import sys
import time
from hashlib import sha256
from typing import Any, cast

from runtime.adapters.instrumentation import trace_stage
from runtime.memory.journal import journal_context
from runtime.platform.models import (
    ArmId,
    Budget,
    BudgetLimits,
    ParsedIntent,
)
from runtime.platform.step_format import (
    step_effective_success as _step_effective_success,
)
from runtime.platform.step_format import (
    summarize_step_for_stream as _summarize_step_for_stream,
)

from .base import Channel, ChannelMetadata, InboundMessage, OutboundMessage
from .operations import ChannelOperationsStore
from .store import ThreadConversationStore

logger = logging.getLogger(__name__)


class ChannelRoutingError(RuntimeError):
    pass


# Task/thread-local delivery target · set around an inbound IM turn so an
# agent (e.g. 章鱼助手 octopus) can remember which channel/thread a cron
# delivery (订阅推送) should be pushed back to. ContextVars propagate to
# child tasks/threads spawned within the turn, so skills called by the
# planner can read it via ``current_channel_target()``.
_current_channel_target: contextvars.ContextVar[tuple[str, str] | None] = contextvars.ContextVar(
    "ch_current_channel_target", default=None
)


def current_channel_target() -> tuple[str, str] | None:
    """Return the ``(channel_id, thread_id)`` of the current IM turn, if any."""
    return _current_channel_target.get()


class ChannelManager:
    def __init__(
        self,
        *,
        stack: Any,
        agent_registry: Any,
        group_registry: Any | None = None,
        store: ThreadConversationStore | None = None,
        operations_store: ChannelOperationsStore | None = None,
        default_agent_id: str | None = None,
        budget_tokens: int = 50_000,
        budget_usd: float = 0.50,
        strict_gate: bool = False,
    ) -> None:
        """ChannelManager · registers routes inbound/outbound.

        Parameters
        ----------
        strict_gate:
            When True, ``register()`` raises ``RuntimeError`` if the
            adapter's ``send()`` does not call ``self.safe_send()`` /
            ``check_outbound()`` before any network call. Default
            False (advisory warning) for backward compatibility —
            production deployments should set True to enforce the
            constitution gate chain (PRIV-2, PRIV-4). Source code
            that cannot be introspected still only warns (not the
            developer's fault).
        """
        self._stack = stack
        self._agent_registry = agent_registry
        self._group_registry = group_registry
        self._store = store or ThreadConversationStore()
        self._operations = operations_store or ChannelOperationsStore()
        self._default_agent_id = default_agent_id
        self._budget_tokens = budget_tokens
        self._budget_usd = budget_usd
        self._strict_gate = strict_gate
        self._channels: dict[str, Channel] = {}
        # Populated by the channels settings router and persisted across
        # restarts.  Keeping these on the runtime manager makes the saved UI
        # choice part of the actual dispatch path rather than display-only
        # configuration.
        self._channel_assignments: dict[str, str] = {}
        self._channel_group_assignments: dict[str, str] = {}
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=8, thread_name_prefix="ch-send"
        )

    def register(self, channel: Channel) -> None:
        if not channel.channel_id:
            raise ValueError(
                f"channel {type(channel).__name__} missing channel_id",
            )
        if channel.channel_id in self._channels:
            raise ValueError(
                f"duplicate channel_id: {channel.channel_id!r}",
            )
        channel.bind_dispatcher(self.process_inbound)

        # Constitution-gate audit · does this adapter's send() call
        # safe_send / check_outbound before any network call?
        # Advisory by default (warning) · strict in production
        # (raises RuntimeError, refuses registration). See
        # docs/constitution.md · PRIV-2, PRIV-4.
        _audit_channel_for_gate(channel, strict=self._strict_gate)

        self._channels[channel.channel_id] = channel

    def has(self, channel_id: str) -> bool:
        return channel_id in self._channels

    def get(self, channel_id: str) -> Channel:
        return self._channels[channel_id]

    def channel_ids(self) -> list[str]:
        return sorted(self._channels)

    def __len__(self) -> int:
        return len(self._channels)

    # ─── Lifecycle ──────────────────────────────

    def start_all(self) -> None:
        for ch in self._channels.values():
            ch.start()

    def stop_all(self) -> None:
        for ch in self._channels.values():
            with contextlib.suppress(Exception):
                ch.stop()
        self.shutdown()

    def send_async(self, channel_id: str, msg: OutboundMessage) -> concurrent.futures.Future:
        if channel_id not in self._channels:
            raise ChannelRoutingError(f"unknown channel: {channel_id!r}")
        return self._executor.submit(self.send_to_channel, channel_id, msg)

    def shutdown(self, wait: bool = True) -> None:
        self._executor.shutdown(wait=wait)

    def process_inbound(self, msg: InboundMessage) -> OutboundMessage:
        if msg.channel_id not in self._channels:
            raise ChannelRoutingError(
                f"unknown channel: {msg.channel_id!r}",
            )
        if not msg.content or not msg.content.strip():
            raise ChannelRoutingError("empty content")

        message_key = self._inbound_message_key(msg)
        if message_key and not self._operations.claim_inbound(msg.channel_id, message_key):
            conversation_id = self._store.get(msg.channel_id, msg.thread_id) or ""
            return OutboundMessage(
                channel_id=msg.channel_id,
                thread_id=msg.thread_id,
                content="",
                metadata=cast(
                    ChannelMetadata,
                    {
                        **dict(msg.metadata),
                        "conversation_id": conversation_id,
                        "duplicate": True,
                    },
                ),
            )

        try:
            with (
                self._track_turn(msg.channel_id),
                trace_stage(
                    "channels.process_inbound",
                    channel_id=msg.channel_id,
                    thread_id=msg.thread_id,
                ),
            ):
                conv_id = self._store.get_or_create(
                    msg.channel_id,
                    msg.thread_id,
                )
                intent = ParsedIntent(
                    raw=msg.content,
                    intent_type="task",
                    normalized_goal=msg.content,
                )

                outbound_meta = cast(ChannelMetadata, dict(msg.metadata))
                group = self._pick_group(msg)
                if group is not None:
                    reply_text, collaboration_meta = self._run_group(
                        group=group,
                        msg=msg,
                        conversation_id=conv_id,
                    )
                    outbound_meta.pop("agent_id", None)
                    outbound_meta.update(collaboration_meta)
                else:
                    agent = self._pick_agent(msg)
                    with journal_context(
                        agent_id=agent.agent_id,
                        conversation_id=conv_id,
                    ):
                        tok = _current_channel_target.set((msg.channel_id, msg.thread_id))
                        try:
                            reply_text = self._plan_and_run(agent, intent)
                        finally:
                            _current_channel_target.reset(tok)
                    outbound_meta.pop("group_id", None)
                    outbound_meta["agent_id"] = agent.agent_id
                outbound_meta["conversation_id"] = conv_id
                out = OutboundMessage(
                    channel_id=msg.channel_id,
                    thread_id=msg.thread_id,
                    content=reply_text,
                    metadata=outbound_meta,
                )
                self._channels[msg.channel_id].send(out)
            if message_key:
                self._operations.complete_inbound(msg.channel_id, message_key)
            return out
        except Exception:
            # Do not turn a transient model/provider failure into a permanent
            # webhook drop.  The provider can safely retry this event.
            if message_key:
                self._operations.release_inbound(msg.channel_id, message_key)
            raise

    @staticmethod
    def _inbound_message_key(msg: InboundMessage) -> str | None:
        """Resolve a stable provider event identity without retaining its body."""
        for key in (
            "message_id",
            "msg_id",
            "slack_ts",
            "interaction_id",
            "mattermost_post_id",
            "event_id",
            "teams_activity_id",
            "google_chat_message",
            "message_guid",
            "message_reference_id",
            "item_id",
            "message_sid",
        ):
            value = msg.metadata.get(key)  # type: ignore[literal-required]
            if value is not None and str(value).strip():
                # Provider event IDs are already scoped to the channel.  Do
                # not include the parsed sender: a retry may omit or format
                # that field differently while referring to the same event.
                return f"{key}:{value}"
        if msg.received_at is not None:
            content_digest = sha256(msg.content.encode("utf-8", errors="replace")).hexdigest()
            return (
                f"fallback:{msg.thread_id}:{msg.sender_id}:"
                f"{msg.received_at.isoformat()}:{content_digest}"
            )
        return None

    def send_to_channel(
        self,
        channel_id: str,
        msg: OutboundMessage,
    ) -> str | None:
        ch = self._channels.get(channel_id)
        if ch is None:
            raise ChannelRoutingError(f"unknown channel: {channel_id!r}")
        try:
            ch.send(msg)
        except Exception as exc:
            self._operations.record_error(channel_id, exc)
            raise
        self._operations.record_outbound(channel_id)
        return None

    def edit_on_channel(
        self,
        channel_id: str,
        msg: OutboundMessage,
        original_message_id: str,
    ) -> None:
        ch = self._channels.get(channel_id)
        if ch is None:
            raise ChannelRoutingError(f"unknown channel: {channel_id!r}")
        try:
            if ch.supports_edit:
                ch.edit(msg, original_message_id)
            else:
                ch.send(msg)
        except Exception as exc:
            self._operations.record_error(channel_id, exc)
            raise
        self._operations.record_outbound(channel_id)

    def channel_supports_edit(self, channel_id: str) -> bool:
        ch = self._channels.get(channel_id)
        return ch.supports_edit if ch is not None else False

    def deliver_cron_result(
        self,
        channel_id: str,
        thread_id: str,
        result_text: str,
    ) -> None:
        ch = self._channels.get(channel_id)
        if ch is None:
            return
        msg = OutboundMessage(
            channel_id=channel_id,
            thread_id=thread_id,
            content=result_text,
            metadata={"source": "cron"},
        )
        try:
            ch.send(msg)
        except Exception as exc:
            self._operations.record_error(channel_id, exc)
            raise
        self._operations.record_outbound(channel_id)

    @contextlib.contextmanager
    def _track_turn(self, channel_id: str) -> Any:
        self._operations.record_inbound(channel_id)
        try:
            yield
        except Exception as exc:
            self._operations.record_error(channel_id, exc)
            raise
        else:
            self._operations.record_outbound(channel_id)

    def channel_diagnostics(self, channel_id: str) -> dict[str, Any]:
        """Return one credential-free operational snapshot for the UI/API."""
        ch = self._channels.get(channel_id)
        if ch is None:
            raise ChannelRoutingError(f"unknown channel: {channel_id!r}")
        state = self._operations.snapshot(channel_id)
        state.update(
            {
                "thread_count": self._store.count_for_channel(channel_id),
                "capabilities": {
                    "edit": bool(ch.supports_edit),
                    "typing": bool(ch.supports_typing),
                    "reactions": bool(ch.supports_reactions),
                    "health_probe": type(ch).health_check is not Channel.health_check,
                },
            }
        )
        return state

    def probe_channel(self, channel_id: str) -> dict[str, Any]:
        """Run the adapter's real health check and persist its outcome."""
        ch = self._channels.get(channel_id)
        if ch is None:
            raise ChannelRoutingError(f"unknown channel: {channel_id!r}")
        started = time.perf_counter()
        error: BaseException | str | None = None
        if type(ch).health_check is Channel.health_check:
            self._operations.record_probe(
                channel_id,
                healthy=None,
                latency_ms=0,
            )
            return self.channel_diagnostics(channel_id)
        try:
            healthy = bool(ch.health_check())
            if not healthy:
                error = "health check returned false"
        except Exception as exc:
            healthy = False
            error = exc
        latency_ms = round((time.perf_counter() - started) * 1000)
        self._operations.record_probe(
            channel_id,
            healthy=healthy,
            latency_ms=latency_ms,
            error=error,
        )
        return self.channel_diagnostics(channel_id)

    def _pick_agent(self, msg: InboundMessage) -> Any:
        """Explicit metadata > saved channel assignment > default > intent."""
        explicit = msg.metadata.get("agent_id")
        if isinstance(explicit, str) and explicit:
            if self._agent_registry.has(explicit):
                return self._agent_registry.get(explicit)
            raise ChannelRoutingError(
                f"metadata agent_id not found: {explicit!r}",
            )

        assigned = self._channel_assignments.get(msg.channel_id)
        if assigned:
            if self._agent_registry.has(assigned):
                return self._agent_registry.get(assigned)
            logger.warning(
                "channel %r has stale agent assignment %r; falling back",
                msg.channel_id,
                assigned,
            )

        if self._default_agent_id and self._agent_registry.has(
            self._default_agent_id,
        ):
            return self._agent_registry.get(self._default_agent_id)

        intent = ParsedIntent(
            raw=msg.content,
            intent_type="task",
            normalized_goal=msg.content,
        )
        picked = self._agent_registry.pick_for_intent(intent)
        if picked is None:
            raise ChannelRoutingError(
                f"no agent matches intent from channel={msg.channel_id!r} "
                f"(goal={msg.content[:60]!r}) · "
                "set default_agent_id or msg.metadata['agent_id']",
            )
        return picked

    def _pick_group(self, msg: InboundMessage) -> Any | None:
        """Resolve an explicitly or persistently assigned collaboration team.

        An explicit per-message agent target intentionally bypasses the saved
        team so adapters can still implement directed mentions.
        """
        if msg.metadata.get("agent_id"):
            return None
        explicit = msg.metadata.get("group_id")
        group_id = explicit if isinstance(explicit, str) and explicit else None
        if group_id is None:
            group_id = self._channel_group_assignments.get(msg.channel_id)
        if not group_id:
            return None
        if self._group_registry is None or not self._group_registry.has(group_id):
            if explicit:
                raise ChannelRoutingError(f"metadata group_id not found: {group_id!r}")
            logger.warning(
                "channel %r has stale group assignment %r; falling back",
                msg.channel_id,
                group_id,
            )
            return None
        return self._group_registry.get(group_id)

    def _run_group(
        self,
        *,
        group: Any,
        msg: InboundMessage,
        conversation_id: str,
    ) -> tuple[str, ChannelMetadata]:
        """Run one bounded team turn and render it for a plain IM surface."""
        from runtime.execution.agents.group_fanout import run_group_fanout

        members: list[dict[str, Any]] = []
        for agent_id in list(getattr(group, "members", []) or []):
            if not self._agent_registry.has(agent_id):
                continue
            agent = self._agent_registry.get(agent_id)
            members.append(
                {
                    "agent_id": agent.agent_id,
                    "display_name": agent.display_name,
                }
            )
        if not members:
            raise ChannelRoutingError(
                f"assigned group {group.group_id!r} has no available members",
            )

        def _call_member(*, agent_id: str, prompt: str, timeout_s: int) -> dict[str, Any]:
            del timeout_s  # The graph runtime owns its per-step timeouts.
            agent = self._agent_registry.get(agent_id)
            intent = ParsedIntent(raw=prompt, intent_type="task", normalized_goal=prompt)
            with journal_context(agent_id=agent_id, conversation_id=conversation_id):
                tok = _current_channel_target.set((msg.channel_id, msg.thread_id))
                try:
                    output = self._plan_and_run(agent, intent)
                finally:
                    _current_channel_target.reset(tok)
            failed = output.startswith(("（无法", "[planner error]", "[runner error]"))
            return {
                "success": not failed,
                "output": output if not failed else "",
                "error": output if failed else None,
            }

        result = run_group_fanout(
            msg.content,
            members,
            agent_caller=_call_member,
            max_members=min(len(members), 8),
            max_concurrency=min(len(members), 4),
            turn_id=f"channel:{msg.channel_id}:{conversation_id}",
            speaker=msg.sender_id or "用户",
        )
        successful = [
            reply
            for reply in result.get("replies") or []
            if reply.get("ok") and str(reply.get("reply") or "").strip()
        ]
        if successful:
            title = str(getattr(group, "display_name", "") or group.group_id)
            blocks = [
                f"{reply['display_name']}\n{str(reply['reply']).strip()}" for reply in successful
            ]
            reply_text = f"{title} · 团队回复\n\n" + "\n\n".join(blocks)
        else:
            reply_text = f"（团队 {group.group_id} 本轮没有成员生成有效回复）"
        synthesis = result.get("synthesis") or {}
        return reply_text, ChannelMetadata(
            group_id=str(group.group_id),
            primary_agent_id=str(synthesis.get("primary_agent_id") or ""),
            member_agent_ids=[str(member["agent_id"]) for member in members],
            collaboration_spoke=int(result.get("spoke") or 0),
            collaboration_count=int(result.get("count") or 0),
        )

    def _plan_and_run(self, agent: Any, intent: ParsedIntent) -> str:
        plan_kwargs: dict[str, Any] = {
            "allowed_skills": agent.allowed_skill_union(),
        }
        try:
            from runtime.execution.agents.loader import compose_runtime_soul

            runtime_soul = compose_runtime_soul(agent)
        except (ImportError, TypeError, AttributeError, OSError):  # noqa: BLE001
            runtime_soul = agent.soul
        if runtime_soul:
            plan_kwargs["soul"] = runtime_soul

        # Planner can fail in three ways that all surface as the same
        # symptom from a channel adapter (Discord/Telegram/etc. just
        # see "(task success · no output content)"):
        #   1. PlannerError — no rule matched, no fallback skill set
        #   2. LLMPlanner returns empty nodes (parsing glitch / model
        #      bailed) — graph runs zero steps, trajectory is empty
        #   3. Any unexpected exception during plan() — bubbles up
        #      and the channel renders nothing
        # Catch all three here and produce a self-explaining reply
        # rather than a silent dead bubble.
        try:
            try:
                graph = self._stack.planner.plan(intent, **plan_kwargs)
            except TypeError:
                graph = self._stack.planner.plan(intent)
        except Exception as exc:  # noqa: BLE001 — bottom of channel pipeline
            return f"（无法为该请求生成执行计划：{type(exc).__name__}: {exc}）"

        if not graph.nodes:
            return (
                "（计划器未生成任何执行步骤 · 可能是技能集合里没有匹配项 · "
                f"原始请求："
                f"{intent.normalized_goal[:120]}）"
            )

        arm_id = ArmId("unassigned")
        if len(agent.arms) > 0:
            first = next(iter(agent.arms))
            arm_id = ArmId(str(first.arm_id))

        budget = Budget(
            task_id=graph.task_id,
            limits=BudgetLimits(
                tokens=self._budget_tokens,
                usd=self._budget_usd,
            ),
        )
        traj = self._stack.runtime.run(
            graph,
            budget=budget,
            caller=f"channels/{agent.agent_id}",
            arm_id=arm_id,
        )
        return self._assistant_text_from_trajectory(traj)

    @staticmethod
    def _assistant_text_from_trajectory(traj: Any) -> str:
        """Render a trajectory as a channel-bound reply.

        Two passes, in priority order:

        1. **Content pass** — if any step's output carries a real
           ``content``/``text`` payload (the shape skills should
           emit when they have user-facing text), prefer that.
           Multiple content payloads concatenate with newlines.
        2. **Step-summary fallback** — when nothing carried text,
           render every step as a one-line ``✓ skill(args) → out``
           summary using the same formatter the OpenAI gateway
           uses. This is what users actually want when a skill ran
           but emitted only structured output (e.g. a search that
           returned a list of result dicts).

        Only when both passes produce nothing — typically because
        the trajectory has zero steps — do we fall back to the
        ``(task … · no output content)`` sentinel.
        """
        content_lines: list[str] = []
        for step in traj.steps:
            out = step.result.output
            if out is None:
                continue
            if isinstance(out, dict):
                if "content" in out and isinstance(out["content"], str):
                    content_lines.append(out["content"])
                elif "text" in out and isinstance(out["text"], str):
                    content_lines.append(out["text"])
            elif isinstance(out, str) and out.strip():
                content_lines.append(out)

        if content_lines:
            return "\n".join(content_lines)

        # No text payload — render step-by-step summaries so the
        # user can at least see what ran.
        summary_lines: list[str] = []
        for step in traj.steps:
            try:
                summary_lines.append(_summarize_step_for_stream(step))
            except (AttributeError, TypeError):  # noqa: BLE001 — formatter is best-effort
                continue

        if summary_lines:
            effective_ok = bool(traj.outcome.success) and all(
                _step_effective_success(s) for s in traj.steps
            )
            tag = "OK" if effective_ok else "FAILED"
            return "\n".join(
                summary_lines + ["", f"[{tag} · {len(traj.steps)} step(s)]"],
            )

        status = "success" if traj.outcome.success else "failed"
        return f"(task {status} · no output content)"


# ═══════════════════════════════════════════════════════════
# Constitution gate audit
# ═══════════════════════════════════════════════════════════


def _audit_channel_for_gate(channel: Channel, *, strict: bool = False) -> None:
    """Scan a channel's ``send`` implementation · warn (or raise)
    if it appears to bypass the constitution gate.

    Parameters
    ----------
    strict:
        When True, raise ``RuntimeError`` instead of logging a
        warning when ``send()`` does not call ``safe_send`` /
        ``check_outbound``. Source-not-inspectable still only
        warns (can't verify, not the developer's fault).

    Detection is conservative:

    * Inspect ``send``'s source code
    * Look for a call to ``safe_send`` or ``check_outbound``
    * Neither present → warn (or raise if strict)
    * Either present → trust the author (they know what they're
      doing · maybe the check happens in a helper)

    False negatives are possible (someone could do the check in
    a differently-named wrapper); false positives are limited to
    "you passed the audit but actually don't gate". In advisory
    mode the warning is non-blocking · registration succeeds
    regardless. In strict mode registration is refused.
    """
    import inspect
    import logging as _logging

    _logger = _logging.getLogger("runtime.adapters.channels.constitution_audit")

    send_method = getattr(type(channel), "send", None)
    if send_method is None:
        return  # abstract base used directly; let the __init__ fail

    try:
        src = inspect.getsource(send_method)
    except (OSError, TypeError):
        # Couldn't introspect via the standard path. This often happens
        # when the class lives in a module imported through an editable
        # install whose linecache points to a stale/doubled path (e.g.
        # pytest collecting from a non-canonical CWD on Windows). Try
        # one more time by resolving the source file through the module
        # the method belongs to — that path is set at import time and
        # is more reliable than ``__code__.co_filename``.
        src = None
        try:
            mod = sys.modules.get(getattr(send_method, "__module__", ""))
            mod_file = getattr(mod, "__file__", None)
            if mod_file:
                with open(mod_file, encoding="utf-8") as fh:
                    mod_src = fh.read()
                # Re-parse with linecache to pick up the source for the
                # specific method via its qualname.
                import re as _re_fb

                qual = getattr(send_method, "__qualname__", "")
                # ``qualname`` is e.g. ``MyAdapter.send``; the class
                # block is what we want to scope the search to.
                cls_name = qual.rsplit(".", 1)[0] if "." in qual else ""
                if cls_name:
                    # Find the class block start, then scan for ``def send``
                    # within it. This is intentionally permissive — false
                    # positives in scoping just reduce the audit coverage.
                    cls_match = _re_fb.search(
                        rf"^class\s+{_re_fb.escape(cls_name)}\b",
                        mod_src,
                        _re_fb.MULTILINE,
                    )
                    if cls_match:
                        # Capture from class declaration to next dedented
                        # ``class``/``def`` at column 0, or end of file.
                        tail = mod_src[cls_match.start() :]
                        next_top = _re_fb.search(
                            r"\n(?:class|def)\s",
                            tail[1:],
                        )
                        cls_body = tail if next_top is None else tail[: next_top.end()]
                        src = cls_body
        except (OSError, UnicodeDecodeError, AttributeError):  # noqa: BLE001 — fallback path; original audit warning fires below
            src = None
        if src is None:
            _logger.warning(
                "Channel adapter %s.send source not inspectable · "
                "cannot verify constitution-gate usage. See "
                "docs/constitution.md · consider calling self.safe_send(msg).",
                type(channel).__name__,
            )
            return
    assert src is not None

    # Signal: a CALL to safe_send / check_outbound · not just a
    # mention. Require the ``(`` · so a comment like
    # ``# DELIBERATELY omits self.safe_send`` doesn't fool the
    # audit. Also strip Python comments so even a "safe_send(" in
    # a comment doesn't count. This is a simple heuristic · an AST
    # parse would be more correct but adds a dependency for a
    # soft-warning path that's fine being fuzzy.
    import re as _re

    # Strip line comments · keep docstrings (they'd be above the
    # body, don't matter for call detection).
    src_no_comments = _re.sub(r"#.*$", "", src, flags=_re.MULTILINE)
    gate_markers = (
        "safe_send(",
        "check_outbound(",
        "@constitutional_gate",
    )
    if any(marker in src_no_comments for marker in gate_markers):
        return

    msg = (
        f"Channel adapter {type(channel).__name__}.send does NOT appear to call "
        "self.safe_send() or constitution.check_outbound() before "
        "sending. Outbound messages from this channel will NOT be "
        "PII-scrubbed or secret-blocked. See docs/constitution.md "
        "(PRIV-2, PRIV-4). Standard template:\n"
        "    def send(self, msg):\n"
        "        verdict = self.safe_send(msg)\n"
        "        if verdict.action == 'block':\n"
        "            return\n"
        "        self._platform_api(verdict.sanitized)"
    )
    _logger.warning("%s", type(channel).__name__)
    _logger.warning("%s", msg)
    if strict:
        raise RuntimeError(
            f"{type(channel).__name__}.send bypasses the constitution gate "
            f"(no safe_send/check_outbound call found). "
            f"Registration refused in strict_gate mode. "
            f"See docs/constitution.md · PRIV-2, PRIV-4."
        )
