"""Realtime driver for the isolated Codex App Server execution backend.

Octopus remains the public control plane: it owns the authenticated outer
thread, durable journal, approvals, interruption, UI items, and final status.
Codex owns only the inner coding loop for a selected ``codex-cli`` local
partner.  The adapter never exposes Codex protocol objects to the frontend and
never lets a failed security check fall through to a weaker executor.
"""

from __future__ import annotations

import contextlib
import logging
import os
import time
from pathlib import Path
from typing import Any

from runtime.execution.agents.local_partner_bridge import (
    blackboard_brief,
    harvest_to_blackboard,
    partner_identity,
)
from runtime.execution.codex_backend.backend import (
    CodexBackendUnavailable,
    CodexExecutionRequest,
    CodexExecutionSession,
)
from runtime.execution.codex_backend.events import (
    CodexEventState,
    translate_notification,
)
from runtime.execution.codex_backend.security import (
    CodexSandboxMode,
    CodexSecurityError,
    CodexSecurityPolicy,
    CodexSidecarSecurity,
)
from runtime.execution.codex_backend.types import RemoteError, RequestTimeoutError
from runtime.platform.process.paths import app_paths
from runtime.platform.runtime_policy.feature_flags import is_on, resolution
from runtime.protocol import AgentMessageItem, ServerMethod, TurnStatus
from runtime.safety.sandboxing.sandbox import (
    effective_process_sandbox_mode,
    resolved_process_backend,
)

_logger = logging.getLogger(__name__)

_PRODUCTION_MODES = frozenset({"commercial", "production", "server", "shared"})
_NOTIFICATION_POLL_S = 0.5
_HEARTBEAT_INTERVAL_S = 5.0
_INTERRUPT_GRACE_S = 5.0
_DEFAULT_TURN_TIMEOUT_S = 30.0 * 60.0
_MAX_TURN_TIMEOUT_S = 4.0 * 60.0 * 60.0
_INVALID_REQUEST = -32600
_METHOD_NOT_FOUND = -32601
_NOT_SUBMITTED_STEER_MESSAGES = frozenset(
    {
        "active turn uses a different output schema",
        "cannot steer a compact turn",
        "cannot steer a review turn",
        "no active turn to steer",
    }
)


def _deployment_mode() -> str:
    return str(os.environ.get("OCTOPUS_DEPLOYMENT_MODE") or "local").strip().lower()


def _explicit_feature_flag() -> bool | None:
    value, source = resolution("execution.codex_app_server")
    if source in (None, "default"):
        return None
    # Production enablement is a security decision, so JSON numbers, objects,
    # and other merely truthy file values are not accepted as an explicit yes.
    return value if type(value) is bool else False


def agent_is_codex_app_server_partner(agent: Any) -> bool:
    """Return whether routing should enter the Codex App Server boundary.

    Local/single-user deployments enable it by default and retain an explicit
    opt-out to the hardened one-shot adapter.  Production-like deployments
    always enter this boundary even while disabled so they fail closed instead
    of silently running the weaker legacy CLI path.
    """

    capabilities = getattr(agent, "capabilities", None)
    identity = partner_identity(capabilities)
    if identity is None or identity[0] != "codex-cli":
        return False
    if isinstance(capabilities, dict) and capabilities.get("codex_app_server") is False:
        return _deployment_mode() in _PRODUCTION_MODES
    flag = _explicit_feature_flag()
    if _deployment_mode() in _PRODUCTION_MODES:
        return True
    return is_on("execution.codex_app_server") if flag is not None else True


def _require_enabled_for_deployment() -> None:
    if _deployment_mode() in _PRODUCTION_MODES and _explicit_feature_flag() is not True:
        raise CodexSecurityError(
            "Codex App Server is disabled for this production-like deployment; "
            "set OCTOPUS_CODEX_APP_SERVER_ENABLED=true only after hard sandbox "
            "and tenant credential provisioning are configured"
        )


def _turn_timeout_s() -> float:
    raw = str(os.environ.get("OCTOPUS_CODEX_APP_SERVER_TIMEOUT") or "").strip()
    if not raw:
        return _DEFAULT_TURN_TIMEOUT_S
    try:
        return min(_MAX_TURN_TIMEOUT_S, max(30.0, float(raw)))
    except (TypeError, ValueError):
        _logger.warning("invalid OCTOPUS_CODEX_APP_SERVER_TIMEOUT=%r; using default", raw)
        return _DEFAULT_TURN_TIMEOUT_S


def _is_within(candidate: Path, root: Path) -> bool:
    try:
        candidate.relative_to(root)
    except ValueError:
        return False
    return True


def _state_root_for_workspace(workspace: Path) -> Path:
    explicit = str(os.environ.get("OCTOPUS_CODEX_STATE_DIR") or "").strip()
    if explicit:
        path = Path(explicit).expanduser()
        if not path.is_absolute():
            raise CodexSecurityError("OCTOPUS_CODEX_STATE_DIR must be absolute")
        return path.resolve(strict=False)

    candidates = (
        app_paths().data_dir / "codex_backend",
        Path.home() / ".octopus" / "codex_backend",
    )
    resolved_workspace = workspace.resolve(strict=True)
    for candidate in candidates:
        resolved_candidate = candidate.expanduser().resolve(strict=False)
        if not (
            _is_within(resolved_candidate, resolved_workspace)
            or _is_within(resolved_workspace, resolved_candidate)
        ):
            return resolved_candidate
    raise CodexSecurityError("no non-overlapping Codex state directory is available")


def _source_codex_home() -> Path | None:
    explicit = str(os.environ.get("OCTOPUS_CODEX_SOURCE_HOME") or "").strip()
    if explicit:
        source = Path(explicit).expanduser()
        if not source.is_absolute():
            raise CodexSecurityError("OCTOPUS_CODEX_SOURCE_HOME must be absolute")
        return source.resolve(strict=False)
    if _deployment_mode() in _PRODUCTION_MODES:
        return None
    # Local desktop/CLI use deliberately reuses the current OS user's Codex
    # login, but the security layer copies only a validated private auth.json
    # into a principal/thread-scoped CODEX_HOME.  The rest of ~/.codex is never
    # inherited.
    return (Path.home() / ".codex").resolve(strict=False)


def _sandbox_mode(context: dict[str, Any]) -> CodexSandboxMode:
    raw_policy = context.get("sandbox_policy")
    raw_type = raw_policy.get("type") if isinstance(raw_policy, dict) else None
    normalized = str(raw_type or "").strip().replace("_", "-").casefold()
    if normalized in {"readonly", "read-only"}:
        return "read-only"
    # ``danger-full-access`` is intentionally capped here.  Codex may request
    # one-operation escalation through Octopus, but a client cannot select an
    # unbrokered full-access inner turn.
    return "workspace-write"


def _partner_command(agent: Any) -> tuple[str, ...]:
    identity = partner_identity(getattr(agent, "capabilities", None))
    if identity is None or identity[0] != "codex-cli":
        raise CodexSecurityError("Codex App Server driver requires a codex-cli partner")
    command = str(identity[1]).strip()
    if not command or "\x00" in command:
        raise CodexSecurityError("Codex executable is invalid")
    # Strict parsing is part of the security contract: a Codex upgrade must
    # fail visibly instead of silently ignoring a now-unknown isolation field.
    return (command, "app-server", "--strict-config", "--listen", "stdio://")


def _request_for_turn(
    runtime: Any,
    turn: Any,
    intent: Any,
    agent: Any,
    *,
    text: str,
) -> CodexExecutionRequest:
    context = getattr(intent, "user_context", None)
    context = dict(context) if isinstance(context, dict) else {}
    raw_cwd = context.get("cwd")
    if not isinstance(raw_cwd, str) or not raw_cwd.strip():
        raise CodexSecurityError("Codex execution requires a server-resolved workspace")
    workspace = Path(raw_cwd.strip()).expanduser()
    if not workspace.is_absolute():
        raise CodexSecurityError("server-resolved Codex workspace must be absolute")
    try:
        workspace = workspace.resolve(strict=True)
    except OSError as exc:
        raise CodexSecurityError("server-resolved Codex workspace does not exist") from exc
    if not workspace.is_dir():
        raise CodexSecurityError("server-resolved Codex workspace is not a directory")

    owner = str(context.get("owner_actor_id") or "local").strip() or "local"
    tenant = str(context.get("tenant_id") or "local").strip() or "local"
    realm = str(os.environ.get("OCTOPUS_CODEX_REALM") or app_paths().data_dir.resolve())
    model = str(context.get("partner_model") or "").strip()
    if model.casefold() in {"", "auto", "default"}:
        model = ""
    effort = str(context.get("reasoning_effort") or "").strip()

    prompt = text
    brief = blackboard_brief(str(getattr(turn, "id", "") or ""))
    if brief:
        prompt = f"{brief}\n\n---\n\n{text}"

    return CodexExecutionRequest(
        outer_thread_id=str(getattr(turn, "thread_id", "") or ""),
        outer_turn_id=str(getattr(turn, "id", "") or ""),
        workspace=workspace,
        realm_id=realm,
        tenant_id=tenant,
        principal_id=owner,
        prompt=prompt,
        command=_partner_command(agent),
        source_codex_home=_source_codex_home(),
        model=model or None,
        effort=effort or None,
        sandbox_mode=_sandbox_mode(context),
    )


async def _heartbeat(emitter: Any, turn: Any, *, started_at: float) -> None:
    await emitter.notify(
        ServerMethod.TURN_HEARTBEAT,
        {
            "threadId": turn.thread_id,
            "turnId": turn.id,
            "role": "codex-app-server",
            "elapsedMs": max(0, int((time.monotonic() - started_at) * 1000)),
        },
    )


def _final_agent_text(turn: Any) -> str:
    for item in reversed(getattr(turn, "items", ())):
        if (
            isinstance(item, AgentMessageItem)
            and getattr(item, "message_kind", "answer") == "answer"
        ):
            text = str(item.text or "").strip()
            if text:
                return text
    return ""


def _steer_was_not_submitted(error: RemoteError) -> bool:
    """Recognize responses that prove an optimistic steer had no effect."""

    if error.code == _METHOD_NOT_FOUND:
        return True
    if error.code != _INVALID_REQUEST:
        return False
    return error.message in _NOT_SUBMITTED_STEER_MESSAGES or error.message.startswith(
        "expected active turn id `"
    )


async def drive_codex_app_server(
    runtime: Any,
    turn: Any,
    log: Any,
    emitter: Any,
    intent: Any,
    agent: Any,
    provider: Any,
    *,
    text: str,
) -> bool:
    """Run one outer turn through Codex and stream it into native UI items.

    Returns ``False`` only when the versioned App Server API is unavailable
    before ``turn/start``.  The caller then uses the already-hardened one-shot
    adapter.  Every security failure and every post-start failure is terminal.
    """

    _require_enabled_for_deployment()
    request = _request_for_turn(runtime, turn, intent, agent, text=text)
    security = CodexSidecarSecurity(
        CodexSecurityPolicy(
            state_root=_state_root_for_workspace(request.workspace),
            allowed_workspace_roots=(request.workspace,),
            deployment_mode=_deployment_mode(),
        )
    )
    session = CodexExecutionSession(
        request,
        security=security,
        approval_provider=provider,
        is_interrupted=lambda: bool(emitter.is_turn_interrupted(turn.id)),
        process_backend=resolved_process_backend(effective_process_sandbox_mode()),
    )
    try:
        try:
            await session.start()
        except CodexBackendUnavailable:
            if session.turn_started or _deployment_mode() in _PRODUCTION_MODES:
                raise
            from runtime.sensing.gateway.realtime_local_partner import drive_local_partner

            _logger.info("Codex App Server unavailable before turn/start; using hardened exec")
            await drive_local_partner(
                runtime,
                turn,
                log,
                emitter,
                intent,
                agent,
                provider,
                text=text,
            )
            return False

        bridge_state = runtime._make_bridge_state(turn.thread_id, turn.id, agent=agent)
        event_state = CodexEventState()
        started_at = time.monotonic()
        last_heartbeat = started_at
        interrupt_started: float | None = None
        interrupt_requested = False
        saw_terminal = False
        live_steering_supported = True
        timeout_s = _turn_timeout_s()

        while not saw_terminal:
            now = time.monotonic()
            if now - started_at >= timeout_s and not interrupt_requested:
                interrupt_requested = True
                interrupt_started = now
                turn.status = TurnStatus.CANCELLED
                turn.outcome_reason = "codex_timeout"
                turn.interrupt_reason = "Codex 代码任务超过运行时限"
                with contextlib.suppress(Exception):
                    await session.interrupt(timeout_s=2.0)
            elif emitter.is_turn_interrupted(turn.id) and not interrupt_requested:
                interrupt_requested = True
                interrupt_started = now
                turn.status = TurnStatus.CANCELLED
                turn.outcome_reason = "user_cancelled"
                turn.interrupt_reason = emitter.get_interrupt_reason(turn.id) or "用户停止了任务"
                with contextlib.suppress(Exception):
                    await session.interrupt(timeout_s=2.0)

            if interrupt_started is not None and now - interrupt_started >= _INTERRUPT_GRACE_S:
                await runtime._apply_react_event(
                    turn,
                    log,
                    emitter,
                    bridge_state,
                    {
                        "type": "react_cancelled",
                        "reason": turn.interrupt_reason or turn.outcome_reason,
                    },
                )
                break

            if not interrupt_requested:
                await runtime._publish_discovered_steering(turn, emitter)
                if live_steering_supported:
                    corrections = runtime._drain_turn_steering(turn.id)
                    if corrections:
                        try:
                            await session.steer("\n\n".join(corrections), timeout_s=2.0)
                        except RemoteError as exc:
                            if not _steer_was_not_submitted(exc):
                                raise
                            # The peer proved it did not accept the steer. Put
                            # the payload back so the outer lifecycle continues
                            # it on the same durable Codex thread after terminal.
                            runtime._restore_turn_steering(turn.id, corrections)
                            live_steering_supported = False

            if now - last_heartbeat >= _HEARTBEAT_INTERVAL_S:
                last_heartbeat = now
                await _heartbeat(emitter, turn, started_at=started_at)

            try:
                notification = await session.next_notification(timeout_s=_NOTIFICATION_POLL_S)
            except RequestTimeoutError:
                continue

            for event in translate_notification(notification, event_state):
                await runtime._apply_react_event(
                    turn,
                    log,
                    emitter,
                    bridge_state,
                    event,
                )
            if notification.method == "turn/completed":
                saw_terminal = True

        if not saw_terminal and turn.status == TurnStatus.IN_PROGRESS:
            await runtime._apply_react_event(
                turn,
                log,
                emitter,
                bridge_state,
                {
                    "type": "react_error",
                    "kind": "codex_missing_terminal",
                    "message": "Codex App Server ended without a terminal turn event",
                },
            )
        with contextlib.suppress(Exception):
            await bridge_state.flush(
                turn,
                log,
                emitter,
                status=bridge_state.prose_status_for_turn(turn.status),
            )
        answer = _final_agent_text(turn)
        if answer:
            harvest_to_blackboard(
                str(getattr(turn, "id", "") or ""),
                str(getattr(agent, "agent_id", "") or "codex-cli"),
                answer,
            )
        return True
    finally:
        await session.close()


__all__ = ["agent_is_codex_app_server_partner", "drive_codex_app_server"]
