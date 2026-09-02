"""Turn session metadata assembly for realtime execution."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

_ADAPTIVE_TEAM_ORCHESTRATION_CONTRACT = """## Adaptive team orchestration

This is a temporary coordination capability granted because the current turn has a real multi-agent roster. It does not change any agent's permanent identity or skills.

- Start from the user's outcome and acceptance criteria. Build the smallest useful team plan for this turn; do not force a preset SOP or involve every member.
- Choose specialists by capability, tools, evidence access, cost, and independence. State each active member's scope and expected output; avoid overlapping assignments unless deliberate cross-checking is useful.
- Infer real dependencies. Run independent work in parallel and dependent work in sequence. Use the available team, delegation, task, and shared-context mechanisms rather than impersonating specialists.
- Treat the plan as provisional. After each material result, failure, user correction, or missing-evidence signal, reassess the remaining work and add, remove, retry, reroute, merge, or stop work as needed.
- Keep coordination state compact: objective, constraints, decisions, evidence/artifacts, unresolved questions, and next actions. Prefer shared task/blackboard state over repeatedly copying the full conversation.
- Add review only where risk or uncertainty justifies it. A reviewer must be independent from the producer when practical. Define pass/return/conditional-pass criteria from the requested deliverable, not from a hard-coded role chain.
- Report meaningful phase changes and blockers without narrating internal chatter. Finish only when the user's acceptance criteria are met or clearly explain the remaining gap and safest recovery path.
- Only the coordinating/owner agent manages this plan. A participating member executes its assigned scope and must not create a nested team unless the coordinator explicitly delegates that authority.
"""


def _unique_roster_agent_ids(roster: list[Any]) -> list[str]:
    """Return stable unique agent ids from the permissive frontend roster wire."""

    seen: set[str] = set()
    result: list[str] = []
    for item in roster:
        if isinstance(item, str):
            raw = item
        elif isinstance(item, dict):
            raw = str(item.get("agent_id") or item.get("id") or item.get("name") or "")
        else:
            raw = ""
        agent_id = raw.strip()
        if not agent_id or agent_id in seen:
            continue
        seen.add(agent_id)
        result.append(agent_id)
    return result


def _grant_adaptive_team_orchestration(metadata: dict[str, Any]) -> None:
    """Grant the coordinator contract for a real multi-agent turn.

    The grant is derived server-side from the canonical turn metadata. The
    client cannot turn a solo role into an orchestrator by sending a magic
    skill id, and nothing is persisted into the role's permanent profile.
    """

    roster = metadata.get("agent_roster")
    if not isinstance(roster, list) or len(_unique_roster_agent_ids(roster)) < 2:
        return
    mode = str(metadata.get("mode") or "").strip().lower()
    mesh = str(metadata.get("serve_mesh") or "").strip().lower()
    team_mode = str(metadata.get("team_mode") or "").strip().lower()
    if mode != "team" and mesh not in {"cluster", "swarm"} and team_mode != "cowork":
        return

    existing = str(metadata.get("mode_contract") or "").strip()
    metadata["adaptive_team_orchestration"] = True
    adaptive = _ADAPTIVE_TEAM_ORCHESTRATION_CONTRACT.strip()
    metadata["mode_contract"] = (
        existing
        if existing.startswith("## Adaptive team orchestration")
        else "\n\n".join(part for part in (adaptive, existing) if part)
    )


def thread_owner_agent_id(*, thread_id: str, store: Any) -> str:
    """Return the immutable persona bound to an existing solo thread.

    A role selection is allowed to choose the owner when the thread is first
    created.  Later turns may arrive with stale browser state, but they must
    not move the same conversation into another role's history or execute it
    as another persona.
    """
    if store is None:
        return ""
    try:
        existing = store.get(thread_id)
    except (KeyError, AttributeError):
        return ""
    metadata = (existing or {}).get("metadata", {}) if existing else {}
    if not isinstance(metadata, dict):
        return ""
    for key in ("owner_agent_id", "agent", "agent_name", "agent_id", "assistant_id"):
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def build_turn_metadata(
    *,
    thread_id: str,
    body: dict[str, Any],
    store: Any,
    authoritative_workspace: Path | None = None,
    owner_actor_id: str | None = None,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    """Merge per-turn context with persisted thread metadata.

    ``authoritative_workspace`` is supplied only after the authenticated
    realtime boundary has verified/allocated it. In that mode all persisted
    and per-turn filesystem grants are presentation input, not authority.
    """
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

    for key in ("team_id", "team_name", "project"):
        value = config_meta.get(key) or ctx.get(key) or stored_meta.get(key)
        if isinstance(value, str) and value.strip():
            metadata[key] = value.strip()

    # A thread's persona is chosen once, at creation.  In particular, do not
    # let a stale ``context.agent_name`` disagree with persisted
    # ``metadata.agent``: the snapshot writer normalises both names to
    # ``agent``, so accepting both used to move one conversation between role
    # shards on alternating turns.
    stored_agent = thread_owner_agent_id(thread_id=thread_id, store=store)
    if stored_agent:
        metadata["agent"] = stored_agent
        metadata["agent_name"] = stored_agent
    else:
        for key in ("agent", "agent_name"):
            value = config_meta.get(key) or ctx.get(key)
            if isinstance(value, str) and value.strip():
                metadata[key] = value.strip()

    if authoritative_workspace is not None:
        metadata["workspace_path"] = str(authoritative_workspace)
        if isinstance(owner_actor_id, str) and owner_actor_id.strip():
            metadata["owner_actor_id"] = owner_actor_id.strip()
        if isinstance(tenant_id, str) and tenant_id.strip():
            metadata["tenant_id"] = tenant_id.strip()
    else:
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
        "personal_mode",
        "mode_preset",
        "workflow_preset",
        "skill_pack_profile",
        "verification_policy",
        "mode_contract",
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
        if authoritative_workspace is not None and key == "personal_workspace_path":
            continue
        if explicit_conversation_mode and key in {
            "capability_mode",
            "code_mode",
            "agent_mode",
            "personal_mode",
            "mode_preset",
            "workflow_preset",
            "skill_pack_profile",
            "verification_policy",
            "mode_contract",
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
    personal_instructions = ctx.get("personal_instructions")
    if personal_instructions is None and not explicit_conversation_mode:
        personal_instructions = stored_meta.get("personal_instructions")
    if isinstance(personal_instructions, str) and personal_instructions.strip():
        metadata["personal_instructions"] = personal_instructions.strip()[:2000]
    for key in ("default_skill_packs", "default_plugins"):
        value = ctx.get(key)
        if value is None and not explicit_conversation_mode:
            value = stored_meta.get(key)
        if isinstance(value, list):
            metadata[key] = [
                item.strip() for item in value[:32] if isinstance(item, str) and item.strip()
            ]
    browser_regression_enabled = ctx.get("browser_regression_enabled")
    if browser_regression_enabled is None and not explicit_conversation_mode:
        browser_regression_enabled = stored_meta.get("browser_regression_enabled")
    if isinstance(browser_regression_enabled, bool):
        metadata["browser_regression_enabled"] = browser_regression_enabled
    if resolved_model is not None:
        metadata["model_name"] = resolved_model
    # Guardian independent review is an opt-in per-turn decision; pass the
    # config through from the client context so high-risk actions can be
    # routed to the independent reviewer without a server restart.
    for _gkey in (
        "guardian_review_enabled",
        "guardian_review_per_turn_limit",
        "guardian_review_timeout_s",
        "guardian_review_model",
    ):
        _gval = ctx.get(_gkey)
        if _gval is None and not explicit_conversation_mode:
            _gval = stored_meta.get(_gkey)
        if _gval is not None and not (isinstance(_gval, str) and not _gval.strip()):
            metadata[_gkey] = _gval
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
            item.strip() for item in runtime_surfaces if isinstance(item, str) and item.strip()
        ]
        if clean_surfaces:
            metadata["runtime_surfaces"] = clean_surfaces

    if authoritative_workspace is None:
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
    for key in ("serve_mesh", "team_mode"):
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

    # Real multi-agent turns temporarily grant their owner the ability to
    # plan, route, review, and re-plan work. Run this after effective roster
    # and mode merging; role profiles remain untouched.
    _grant_adaptive_team_orchestration(metadata)

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


__all__ = ["build_turn_metadata", "build_turn_session", "thread_owner_agent_id"]
