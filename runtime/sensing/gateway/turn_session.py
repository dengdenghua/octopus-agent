"""Turn session metadata assembly for realtime execution."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any


def build_turn_metadata(
    *,
    thread_id: str,
    body: dict[str, Any],
    store: Any,
) -> dict[str, Any]:
    """Merge per-turn context with persisted thread metadata."""
    ctx = body.get("context") or {}
    if not isinstance(ctx, dict):
        ctx = {}
    raw_config = body.get("config")
    config = raw_config if isinstance(raw_config, dict) else {}
    raw_meta = config.get("metadata")
    config_meta = raw_meta if isinstance(raw_meta, dict) else {}
    metadata: dict[str, Any] = {}

    if ctx.get("raw_identity") is True:
        metadata["identity_lock_override"] = False

    stored_meta: dict[str, Any] = {}
    try:
        existing = store.get(thread_id) if store is not None else None
        stored_meta = (existing or {}).get("metadata", {}) if existing else {}
    except (KeyError, AttributeError):
        stored_meta = {}

    # Keep model selection in one place. This also preserves compatibility
    # with older clients that send ``context.model`` or top-level ``model``.
    from runtime.platform.process.turn_model import resolve_turn_model

    resolved_model = resolve_turn_model(body, {"metadata": stored_meta})

    mode_val = config_meta.get("mode") or ctx.get("mode") or stored_meta.get("mode") or "chat"
    if isinstance(mode_val, str) and mode_val:
        metadata["mode"] = mode_val
    explicit_conversation_mode = isinstance(ctx.get("mode"), str) and ctx.get("mode") in {
        "chat",
        "flash",
        "inspiration",
        "conversation",
        "discuss",
    }

    for key in ("team_id", "team_name", "project", "agent", "agent_name"):
        value = config_meta.get(key) or ctx.get(key) or stored_meta.get(key)
        if isinstance(value, str) and value.strip():
            metadata[key] = value.strip()

    extra_ws: list[str] = []
    ew = stored_meta.get("extra_workspaces")
    if isinstance(ew, list):
        extra_ws.extend(x for x in ew if isinstance(x, str) and x)

    wp = ctx.get("workspace_path") or stored_meta.get("workspace_path")
    if isinstance(wp, str) and wp.strip():
        clean = wp.strip()
        if Path(clean).expanduser().is_absolute():
            if clean not in extra_ws:
                extra_ws.insert(0, clean)
        else:
            logging.getLogger(__name__).warning(
                "build_turn_metadata: rejecting relative workspace_path %r for thread %s",
                clean,
                thread_id,
            )
            wp = None

    if extra_ws:
        metadata["extra_workspaces"] = extra_ws
        if isinstance(wp, str) and wp.strip():
            metadata["workspace_path"] = wp.strip()

    sb_mode = ctx.get("sandbox_mode") or stored_meta.get("sandbox_mode")
    if isinstance(sb_mode, str) and sb_mode in ("sandbox", "full"):
        metadata["sandbox_mode"] = sb_mode

    for key in (
        "capability_mode",
        "code_mode",
        "agent_mode",
        "workspace_scope",
        "personal_workspace_path",
        "interaction_mode",
        "tool_surface",
        "browser_surface",
        "browser_session_policy",
        "browser_track_preference",
        "browser_permission_policy",
        "browser_evidence_policy",
        "browser_operation_mode",
        "chrome_operation_mode",
    ):
        if explicit_conversation_mode and key in {
            "capability_mode",
            "code_mode",
            "agent_mode",
            "workspace_scope",
            "personal_workspace_path",
        }:
            value = ctx.get(key)
        else:
            value = ctx.get(key) or stored_meta.get(key)
        if isinstance(value, str) and value.strip():
            metadata[key] = value.strip()
        elif isinstance(value, bool):
            metadata[key] = value
    if resolved_model is not None:
        metadata["model_name"] = resolved_model
    value = ctx.get("personal_workspace_enabled")
    if value is None and not explicit_conversation_mode:
        value = stored_meta.get("personal_workspace_enabled")
    if isinstance(value, bool):
        metadata["personal_workspace_enabled"] = value

    runtime_surfaces = ctx.get("runtime_surfaces")
    if runtime_surfaces is None and not explicit_conversation_mode:
        runtime_surfaces = stored_meta.get("runtime_surfaces")
    if isinstance(runtime_surfaces, list):
        clean_surfaces = [
            item.strip()
            for item in runtime_surfaces
            if isinstance(item, str) and item.strip()
        ]
        if clean_surfaces:
            metadata["runtime_surfaces"] = clean_surfaces

    allowed_write_paths = ctx.get("allowed_write_paths")
    if allowed_write_paths is None and not explicit_conversation_mode:
        allowed_write_paths = stored_meta.get("allowed_write_paths")
    if isinstance(allowed_write_paths, list):
        clean_write_paths = [
            item.strip()
            for item in allowed_write_paths
            if isinstance(item, str) and item.strip()
        ]
        if clean_write_paths:
            metadata["allowed_write_paths"] = clean_write_paths

    project_signals = ctx.get("project_signals") or stored_meta.get("project_signals")
    if isinstance(project_signals, dict):
        metadata["project_signals"] = project_signals

    # Team-room turn context. Without these the team turn silently degrades to
    # single-agent ReAct: serve_mesh drives 蜂群 (fan-out) vs 集群 routing,
    # team_mode tags the turn, and agent_roster is the member list the
    # fan-out / planner / swarm need.
    # ``partner_model`` lets the UI override a local CLI partner's model
    # (codex/claude), passed straight to ``-m``. It is the CLI's own model
    # namespace — kept separate from ``model_name`` (octopus's) on purpose.
    for key in ("serve_mesh", "team_mode", "partner_model"):
        value = ctx.get(key) or stored_meta.get(key)
        if isinstance(value, str) and value.strip():
            metadata[key] = value.strip()
    for key in ("subagent_enabled", "is_plan_mode"):
        value = ctx.get(key)
        if value is None:
            value = stored_meta.get(key)
        if isinstance(value, bool):
            metadata[key] = value
    roster = ctx.get("agent_roster") or stored_meta.get("agent_roster")
    if isinstance(roster, list) and roster:
        metadata["agent_roster"] = roster

    return metadata


def build_turn_session(
    *,
    actor: str | None,
    agent: Any,
    thread_id: str,
    body: dict[str, Any],
    store: Any,
) -> Any:
    """Assemble the per-turn ``Session`` object from request and state."""
    from runtime.platform.process.session import Session

    metadata = build_turn_metadata(thread_id=thread_id, body=body, store=store)
    return Session(
        actor=actor,
        agent=agent,
        thread_id=thread_id,
        conversation_id=thread_id,
        metadata=metadata,
    )


__all__ = ["build_turn_metadata", "build_turn_session"]
