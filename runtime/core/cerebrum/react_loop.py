
from __future__ import annotations

import contextlib
import json
import logging
import re
import time
import uuid
from collections.abc import Callable, Iterator
from typing import TYPE_CHECKING, Any

from runtime.core.cerebrum.completion_receipt import build_completion_receipt
from runtime.core.cerebrum.react_context import (
    _build_code_context_prelude,
    _build_project_profile_prompt,
    _compress_context,
    _format_skill_catalog,
    _load_project_rules,
    _prefetch_related_files,
    _restore_messages_from_checkpoint,
    _serialize_messages_for_checkpoint,
)
from runtime.core.cerebrum.react_execution import (
    _build_progress_summary,
    _build_research_progress_summary,
    _detect_phase,
    _execute_action_via_beak,
    _persist_react_trajectory,
    _reset_kg_throttle_for_tests,
    _run_auto_diagnostics,
    _update_working_set,
)
from runtime.core.cerebrum.react_guards import (
    _code_mode_completion_guard,
    _completion_phrase_without_todo_guard,
    _path_verification_policy_guard,
    _unverified_write_followup_guard,
)
from runtime.core.cerebrum.react_parsing import (
    _ACTION_RE,
    _FINAL_RE,
    _THOUGHT_RE,
    _escape_md_brackets,
    _is_format_violation,
    _parse_action,
    _parse_step,
    _placeholder_observation,
    _safe_for_streamdown,
    _summarize_observation,
)
from runtime.core.cerebrum.react_types import (
    _DEFAULT_REACT_RECIPES,
    REACT_NO_TOOLS_NOTE,
    REACT_SYSTEM_PROMPT_BASE,
    ReActRecipe,
    ReActResult,
    ReActStep,
)
from runtime.core.cerebrum.todo_protocol import (
    context_mode,
    render_todo_protocol_guidance,
    should_require_todo_protocol,
)
from runtime.platform.config.builder import StackProtocol
from runtime.platform.models import ParsedIntent, Step, TaskId
from runtime.safety.approval.approval_gate import ApprovalProvider
from runtime.safety.experiments.variant import ABSplitter
from runtime.safety.validation.prompt_injection import (
    injection_taint_gates,
    is_untrusted_tool,
    mark_injection_taint,
    reset_injection_taint,
    scan_for_injection,
    set_injection_gate_handled,
    wrap_untrusted_observation,
)

if TYPE_CHECKING:
    from runtime.execution.agents.base import Agent

_logger = logging.getLogger(__name__)


def _looks_like_observation_echo(text: str) -> bool:
    """True when model prose is leaked tool/protocol text, not an answer."""
    stripped = (text or "").lstrip()
    if not stripped:
        return False
    head = stripped[:240].lower()
    return (
        head.startswith("observation:")
        or head.startswith("[1/")
        or head.startswith("<tool_invocation")
        or head.startswith("<tool_call")
        or head.startswith("<function")
        or "(real tool execution succeeded)" in head
    )


# ── Guard telemetry (P1 evolution-loop feed) ──────────────────────
# Lazily-initialised singleton sink. evaluate_guards() calls the
# returned recorder with (label, category) for every firing guard.
# Disabled by env var OCTOPUS_DISABLE_GUARD_TELEMETRY=1 so tests and
# air-gapped runs can opt out. Initialisation failures degrade to a
# no-op — telemetry must never break the loop.
_GUARD_TELEMETRY_SINGLETON: Any = None
_GUARD_TELEMETRY_INIT_DONE = False


def _guard_hit_recorder() -> Callable[[str, str], None] | None:
    """Return a ``recorder(label, category)`` callable, or None when
    telemetry is disabled / unavailable."""
    global _GUARD_TELEMETRY_SINGLETON, _GUARD_TELEMETRY_INIT_DONE
    import os

    if os.environ.get("OCTOPUS_DISABLE_GUARD_TELEMETRY") == "1":
        return None
    if not _GUARD_TELEMETRY_INIT_DONE:
        _GUARD_TELEMETRY_INIT_DONE = True
        try:
            from runtime.safety.evolution.guard_telemetry import GuardTelemetry
            _GUARD_TELEMETRY_SINGLETON = GuardTelemetry()
        except Exception as _exc:  # noqa: BLE001 — telemetry must not break loop
            _logger.debug("guard telemetry unavailable: %s", _exc)
            _GUARD_TELEMETRY_SINGLETON = None
    sink = _GUARD_TELEMETRY_SINGLETON
    if sink is None:
        return None
    return lambda label, category: sink.record(label, category)


def _reset_guard_telemetry_for_tests() -> None:
    """Reset the telemetry singleton — used by tests for isolation."""
    global _GUARD_TELEMETRY_SINGLETON, _GUARD_TELEMETRY_INIT_DONE
    _GUARD_TELEMETRY_SINGLETON = None
    _GUARD_TELEMETRY_INIT_DONE = False


# ── Operator kill-switch for individual guards ────────────────────
# Two-layer source — env var is the emergency knob, settings.yaml is
# the persistent project-level baseline.
#
# Env var: OCTOPUS_DISABLED_GUARDS="label1,label2"
# YAML:    safety:
#            disabled_guards:
#              - label1
#              - label2
#
# Both sources are MERGED (union) — env var adds to whatever YAML
# already disables, never replaces. Operators can flip env at runtime
# to add to the persistent list without editing the file.
#
# Whitespace around labels is stripped so an env var like
# 'magic-number guard, long-function guard' works.
# Re-read fresh on each call so an operator changing the env or
# YAML at runtime takes effect on the next turn.
#
# Audit trail: when the disabled set CHANGES we emit one log line and
# (when telemetry is wired) one structured record so a future operator
# can answer "when did this guard get turned off and by whom".

_LAST_DISABLED_SET: frozenset[str] | None = None
_DEFAULT_SETTINGS_PATHS: tuple[str, ...] = (
    "config.local.yaml",
    "config.yaml",
    "config.example.yaml",
)


def _disabled_guards_from_yaml(
    candidate_paths: tuple[str, ...] = _DEFAULT_SETTINGS_PATHS,
) -> frozenset[str]:
    """Read ``safety.disabled_guards`` from the first existing config.

    Returns frozenset on success; empty frozenset on any failure
    (file missing / unreadable / no PyYAML / wrong shape). Never
    raises — settings being broken must not break the loop.
    """
    import os
    for raw_path in candidate_paths:
        try:
            if not os.path.exists(raw_path):
                continue
        except Exception:  # noqa: BLE001
            continue
        try:
            import yaml  # type: ignore[import-untyped]
        except ImportError:
            return frozenset()
        try:
            with open(raw_path, encoding="utf-8") as fh:
                data = yaml.safe_load(fh.read()) or {}
        except Exception:  # noqa: BLE001
            return frozenset()
        if not isinstance(data, dict):
            return frozenset()
        safety = data.get("safety") or {}
        if not isinstance(safety, dict):
            return frozenset()
        # Source A: safety.disabled_guards: [label, label, ...]
        out: set[str] = set()
        raw = safety.get("disabled_guards") or []
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, str) and item.strip():
                    out.add(item.strip())
        # Source B: safety.guard_overrides: {label: bool}
        # Per-spec on/off knob — operators can selectively re-enable
        # guards that the project baseline disabled, or vice versa.
        # Only the "False" entries contribute to the disabled set;
        # explicit "True" wins over a same-label disabled_guards entry.
        overrides = safety.get("guard_overrides") or {}
        if isinstance(overrides, dict):
            for label, enabled in overrides.items():
                if not isinstance(label, str) or not label.strip():
                    continue
                clean = label.strip()
                if isinstance(enabled, bool):
                    if enabled:
                        out.discard(clean)
                    else:
                        out.add(clean)
        return frozenset(out)
    return frozenset()


def _disabled_guard_labels() -> frozenset[str]:
    """Return labels of guards disabled via env var OR settings.yaml.

    Sources are unioned: env-var entries add to the YAML baseline.
    """
    import os
    raw = os.environ.get("OCTOPUS_DISABLED_GUARDS", "")
    if not raw.strip():
        env_set: frozenset[str] = frozenset()
    else:
        env_set = frozenset(
            part.strip() for part in raw.split(",") if part.strip()
        )
    yaml_set = _disabled_guards_from_yaml()
    current = env_set | yaml_set
    _audit_disabled_set_change(current)
    return current


def _audit_disabled_set_change(current: frozenset[str]) -> None:
    """Log + record telemetry when the disabled-guard set changes.

    Idempotent: only fires when ``current`` differs from the last
    observed value. The very first call after process start ALSO
    fires when the set is non-empty so a fresh process inheriting
    OCTOPUS_DISABLED_GUARDS leaves a trail.
    """
    global _LAST_DISABLED_SET
    if current == _LAST_DISABLED_SET:
        return
    previous = _LAST_DISABLED_SET
    _LAST_DISABLED_SET = current
    if previous is None and not current:
        # Process start with empty set — nothing notable to record.
        return
    added = sorted(current - (previous or frozenset()))
    removed = sorted((previous or frozenset()) - current)
    _logger.warning(
        "OCTOPUS_DISABLED_GUARDS changed: now=%s added=%s removed=%s",
        sorted(current), added, removed,
    )
    sink = _GUARD_TELEMETRY_SINGLETON
    if sink is None:
        return
    with contextlib.suppress(Exception):
        sink.record(
            label="__kill_switch_change__",
            category="audit",
            metadata={
                "now": sorted(current),
                "added": added,
                "removed": removed,
            },
        )


def _reset_disabled_set_for_tests() -> None:
    """Reset the cached last-seen set — used by tests for isolation."""
    global _LAST_DISABLED_SET
    _LAST_DISABLED_SET = None


# ── Periodic auto-checkpoint (P3 — long-task durability) ──────────
# Existing checkpoints fire only on explicit pause or final-answer.
# When a process is hard-killed (SIGKILL, OOM, container restart) the
# turn loses everything between the last checkpoint and the kill.
# Periodic auto-checkpoint plugs that gap: every N iterations the
# loop writes the same shape of checkpoint that pause writes, so a
# resume request can pick up at the last completed iteration.
#
# Opt-in via OCTOPUS_CHECKPOINT_EVERY_N env var (e.g. "5"). 0 / unset
# means off — preserves legacy behaviour exactly. Errors during
# checkpoint write are swallowed; turn proceeds normally.

_DEFAULT_CHECKPOINT_INTERVAL = 0  # off by default


def _checkpoint_interval() -> int:
    """How often (in iterations) to write an auto-checkpoint.

    Reads ``OCTOPUS_CHECKPOINT_EVERY_N`` fresh on each call so an
    operator can flip the knob without a restart. Returns ``0`` when
    the value is missing, blank, or unparseable — i.e. feature off.
    """
    import os
    raw = os.environ.get("OCTOPUS_CHECKPOINT_EVERY_N", "").strip()
    if not raw:
        return _DEFAULT_CHECKPOINT_INTERVAL
    try:
        n = int(raw)
    except ValueError:
        return _DEFAULT_CHECKPOINT_INTERVAL
    return n if n > 0 else _DEFAULT_CHECKPOINT_INTERVAL


def _should_auto_checkpoint(iteration: int, interval: int) -> bool:
    """Whether iteration ``iteration`` should trigger an auto-checkpoint.

    Centralised so tests can drive it without spinning up the full
    react_loop. Returns False when ``interval <= 0`` (feature off) or
    when ``iteration <= 0`` (we never write a checkpoint at iteration
    0 — there's nothing to resume to). Otherwise fires when iteration
    is a non-zero multiple of ``interval``.
    """
    if interval <= 0 or iteration <= 0:
        return False
    return iteration % interval == 0


# ── Distributed checkpoint mirror (P3 cross-machine durability) ────
# Optional layer on top of the local journal: each auto-checkpoint
# also pushes a JSON snapshot to a shared KV store (Redis-shaped) so
# another machine can pick up the task. Off by default. Turn on via
# ``OCTOPUS_CHECKPOINT_MIRROR_URL=redis://...`` env var.

_CHECKPOINT_MIRROR_SINGLETON: Any = None
_CHECKPOINT_MIRROR_INIT_DONE = False


def _checkpoint_mirror() -> Any:
    """Return the shared ``CheckpointMirror`` instance, or None.

    Disabled when ``OCTOPUS_CHECKPOINT_MIRROR_URL`` is unset / empty.
    Build failures (redis package missing, bad URL) silently disable
    the mirror — the local journal is the source of truth, mirroring
    is a best-effort overlay.
    """
    global _CHECKPOINT_MIRROR_SINGLETON, _CHECKPOINT_MIRROR_INIT_DONE
    import os
    if not _CHECKPOINT_MIRROR_INIT_DONE:
        _CHECKPOINT_MIRROR_INIT_DONE = True
        url = os.environ.get("OCTOPUS_CHECKPOINT_MIRROR_URL", "").strip()
        if not url:
            _CHECKPOINT_MIRROR_SINGLETON = None
        else:
            try:
                from runtime.core.cerebrum.checkpoint_mirror import (
                    build_checkpoint_mirror_from_url,
                )
                _CHECKPOINT_MIRROR_SINGLETON = build_checkpoint_mirror_from_url(url)
            except Exception as _exc:  # noqa: BLE001 — fail-soft
                _logger.debug("checkpoint mirror init failed: %s", _exc)
                _CHECKPOINT_MIRROR_SINGLETON = None
    return _CHECKPOINT_MIRROR_SINGLETON


def _reset_checkpoint_mirror_for_tests() -> None:
    """Reset the cached mirror singleton — used by tests for isolation."""
    global _CHECKPOINT_MIRROR_SINGLETON, _CHECKPOINT_MIRROR_INIT_DONE
    _CHECKPOINT_MIRROR_SINGLETON = None
    _CHECKPOINT_MIRROR_INIT_DONE = False


def _mirror_checkpoint(task_id: Any, checkpoint_dict: dict[str, Any]) -> None:
    """Best-effort write to the distributed mirror. Errors swallowed."""
    mirror = _checkpoint_mirror()
    if mirror is None:
        return
    with contextlib.suppress(Exception):
        mirror.put(str(task_id), checkpoint_dict)


def _rehydrate_messages_from_steps(messages: list, steps: list[ReActStep]) -> list:
    """Append missing step transcript when resuming from a checkpoint.

    Periodic checkpoints are written at a point where ``steps_snapshot``
    already includes the completed iteration, but ``messages_snapshot``
    may still be the pre-step conversation. Without this bridge a
    killed process can resume with the internal step list restored while
    the model cannot see the last Action/Observation in its prompt.
    """
    if not steps:
        return messages
    from runtime.platform.models.llm import Message

    existing = "\n".join(
        str(getattr(message, "content", "") or "") for message in messages
    )
    hydrated = list(messages)
    for step in steps:
        action = (step.action or "").strip()
        observation = (step.observation or "").strip()
        thought = (step.thought or "").strip()
        if not action and not observation:
            continue
        if action and action in existing and (
            not observation or observation in existing
        ):
            continue
        assistant_lines: list[str] = []
        if thought:
            assistant_lines.append(f"Thought: {thought}")
        if action:
            assistant_lines.append(f"Action: {action}")
        if assistant_lines:
            assistant_content = "\n".join(assistant_lines)
            hydrated.append(Message(role="assistant", content=assistant_content))
            existing += "\n" + assistant_content
        if observation and observation not in existing:
            # TokenJuice on rehydration too — when resuming a
            # paused/checkpointed thread, prior tool observations
            # have to ride into the new prompt. Compressing them
            # saves tokens proportional to history depth.
            _obs_text = observation
            try:
                from runtime.core.cerebrum.token_juicer import (
                    is_enabled as _juice_enabled,
                )
                from runtime.core.cerebrum.token_juicer import (
                    juice as _juice,
                )
                if _juice_enabled():
                    _juiced, _stats = _juice(observation)
                    if _stats.passes:
                        _obs_text = _juiced
            except (ImportError, ValueError, TypeError):  # noqa: BLE001 — juice is best-effort, fall back to raw
                pass
            user_content = f"Observation: {_obs_text}\n\n继续下一轮推理。"
            hydrated.append(Message(role="user", content=user_content))
            existing += "\n" + user_content
    return hydrated


def _background_task_info_from_observation(observation: str | None) -> dict[str, Any] | None:
    """Extract a background shell snapshot from a rendered tool observation."""

    if not isinstance(observation, str) or not observation.strip():
        return None
    payload = observation.split("\n", 1)[1] if "\n" in observation else observation
    try:
        data = json.loads(payload)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    task_id = data.get("task_id")
    if not isinstance(task_id, str) or not task_id:
        return None
    if data.get("running") is True or data.get("status") == "running":
        return data
    return None


_VERIFICATION_TOOL_KINDS: dict[str, str] = {
    "run_tests": "test",
    "lint_check": "lint",
    "format_code": "lint",
}


def _verification_kind_from_command(command: str) -> str | None:
    """Classify shell commands that are actually verification steps."""

    text = f" {command.lower()} "
    test_markers = (
        " pytest",
        " -m pytest",
        " unittest",
        " vitest",
        " jest",
        " playwright test",
        " npm test",
        " npm run test",
        " pnpm test",
        " pnpm run test",
        " yarn test",
        " cargo test",
        " go test",
        " dotnet test",
    )
    lint_markers = (
        " eslint",
        " ruff check",
        " flake8",
        " biome lint",
        " npm run lint",
        " pnpm lint",
        " pnpm run lint",
        " yarn lint",
    )
    typecheck_markers = (
        " tsc",
        " vue-tsc",
        " pyright",
        " mypy",
        " py_compile",
        " npm run typecheck",
        " pnpm typecheck",
        " pnpm run typecheck",
        " yarn typecheck",
    )
    build_markers = (
        " npm run build",
        " pnpm build",
        " pnpm run build",
        " yarn build",
        " cargo build",
        " go build",
        " dotnet build",
        " mvn package",
        " gradle build",
    )
    if any(marker in text for marker in test_markers):
        return "test"
    if any(marker in text for marker in lint_markers):
        return "lint"
    if any(marker in text for marker in typecheck_markers):
        return "typecheck"
    if any(marker in text for marker in build_markers):
        return "build"
    return None


def _command_from_tool_step(beak_step: Step, output: dict[str, Any]) -> str:
    action_args = getattr(getattr(beak_step, "action", None), "args", {}) or {}
    raw = action_args.get("command") or action_args.get("cmd")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    if isinstance(raw, list):
        return " ".join(str(part) for part in raw)
    argv = output.get("argv")
    if isinstance(argv, list):
        return " ".join(str(part) for part in argv)
    return ""


def _tool_event_extras_from_beak_step(
    beak_step: Step | None,
    tool_name: str,
) -> dict[str, Any]:
    """Surface structured beak metadata on realtime tool_end events."""

    if beak_step is None:
        return {}
    result = getattr(beak_step, "result", None)
    output = getattr(result, "output", None)
    if not isinstance(output, dict):
        return {}

    extras: dict[str, Any] = {}
    diff = output.get("diff_preview") or output.get("diff")
    if isinstance(diff, str) and diff.strip():
        extras["diff"] = diff

    command = _command_from_tool_step(beak_step, output)
    kind = _VERIFICATION_TOOL_KINDS.get(tool_name)
    if kind is None and tool_name in {"exec_shell", "shell_command", "bash"}:
        kind = _verification_kind_from_command(command)
    if kind is not None:
        stdout = output.get("stdout")
        stderr = output.get("stderr")
        exit_code = output.get("exit_code")
        success = output.get("success")
        if not isinstance(success, bool) and isinstance(exit_code, int):
            success = exit_code == 0
        extras["verification"] = {
            "command": command or output.get("command") or tool_name,
            "kind": kind,
            "exit_code": exit_code if isinstance(exit_code, int) else None,
            "success": bool(success) if isinstance(success, bool) else None,
            "stdout_tail": stdout if isinstance(stdout, str) else None,
            "stderr_tail": stderr if isinstance(stderr, str) else None,
        }
    return extras


def _beak_step_effective_success(step: Any) -> bool:
    result = getattr(step, "result", None)
    if getattr(result, "status", "success") != "success":
        return False

    output = getattr(result, "output", None)
    if not isinstance(output, dict):
        return True

    success = output.get("success")
    if isinstance(success, bool):
        return success

    exit_code = output.get("exit_code")
    if isinstance(exit_code, int):
        return exit_code == 0

    return True


def _format_background_task_heartbeat(task_ids: list[str]) -> str:
    """Render the periodic 'background tasks still running' nudge.

    Kept as a tiny helper so test_background_task_heartbeat can assert
    the exact wording without spinning up the full ReAct loop.
    """
    ids_str = ", ".join(task_ids)
    return (
        "[background-task-tracker]\n"
        f"Background processes still registered: {ids_str}.\n"
        "Use read_shell_output(task_id) to check progress, or "
        "kill_shell(task_id) to stop.\n"
        "If you've already finalised the task without checking, do so now."
    )


def _react_completion_receipt(
    *,
    final_answer: str | None,
    terminated_reason: str,
    effective_success: bool,
    executed_beak_steps: list[Any],
) -> dict[str, object]:
    if terminated_reason == "final_answer" and final_answer and effective_success:
        run_status = "completed"
    elif terminated_reason in {"paused", "cancelled"}:
        run_status = "pending"
    else:
        run_status = "failed"

    tool_statuses = [
        str(getattr(getattr(step, "result", None), "status", "") or "")
        for step in executed_beak_steps
    ]
    statuses = [
        ("completed" if status == "success" else status)
        for status in tool_statuses
        if status
    ] or [run_status]
    if run_status != "completed":
        statuses.append(run_status)

    artifact_count = 0
    for step in executed_beak_steps:
        files = getattr(getattr(step, "result", None), "files_modified", None)
        if isinstance(files, list):
            artifact_count += len(files)

    warnings: list[str] = []
    if terminated_reason != "final_answer":
        warnings.append(f"terminated:{terminated_reason}")

    return build_completion_receipt(
        statuses,
        contract_warnings=warnings,
        artifact_count=artifact_count,
        output_present=bool(final_answer),
    ).to_dict()

_SCOPED_ARTIFACT_WRITE_TOOLS = frozenset({
    "write_text_file",
    "append_text_file",
    "edit_text_file",
    "edit_file",
    "multi_edit_file",
})


def _skill_available_in_executor(executor: Any, skill_name: str) -> bool:
    """Check if a skill is registered and available in the executor."""
    if executor is None:
        return False
    try:
        registry = getattr(executor, "registry", None)
        if registry is None:
            return False
        if hasattr(registry, "has") and callable(registry.has):
            return bool(registry.has(skill_name))
        if hasattr(registry, "is_enabled") and callable(registry.is_enabled):
            return bool(registry.is_enabled(skill_name))
        return False
    except (AttributeError, TypeError, ValueError):
        return False


def _build_user_message_content(
    text: str,
    attachments: Any,
) -> Any:
    """Construct the user-message ``content`` payload.

    When the request carries one or more image attachments with a usable
    URL (data: URL preferred, hosted https URL acceptable), we emit a
    list of OpenAI-shaped blocks::

        [
          {"type": "text", "text": ...},
          {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}},
          ...
        ]

    Vision-capable routers (anthropic / openai / gemini / molili) all
    accept this shape. Non-vision routers fall back to plain text via
    their own input filtering, so we don't need to gate by model here.

    When no image attachments are present, returns plain ``text``
    unchanged so we don't break callers that assume a string.
    """
    text = (text or "").strip()
    image_blocks = _image_blocks_from_attachments(attachments)
    if not image_blocks:
        return text
    blocks: list[dict[str, Any]] = []
    if text:
        blocks.append({"type": "text", "text": text})
    blocks.extend(image_blocks)
    return blocks


def _image_blocks_from_attachments(attachments: Any) -> list[dict[str, Any]]:
    """Extract OpenAI-shaped image_url blocks from raw attachment dicts.

    Recognized shapes (any of these is enough):

    - ``data_url`` field with a ``data:image/...;base64,...`` string
    - ``url`` field that is itself a ``data:image/...`` URL
    - ``url`` field with ``mediaType`` / ``mime_type`` starting with
      ``image/`` (we trust the caller, no fetch)

    Filename-extension is a last-resort hint when no media type is set.
    """
    if not isinstance(attachments, list):
        return []
    blocks: list[dict[str, Any]] = []
    for item in attachments:
        if not isinstance(item, dict):
            continue
        url = ""
        candidate = item.get("data_url") or item.get("dataUrl")
        if isinstance(candidate, str) and candidate.startswith("data:image/"):
            url = candidate
        else:
            raw_url = item.get("url") or item.get("artifact_url")
            if isinstance(raw_url, str) and raw_url.strip():
                if raw_url.startswith("data:image/") or _looks_like_image_attachment(item):
                    url = raw_url
        if not url:
            continue
        blocks.append({"type": "image_url", "image_url": {"url": url}})
    return blocks


def _looks_like_image_attachment(item: dict[str, Any]) -> bool:
    """Heuristic: does this attachment look like an image?"""
    mt = (
        item.get("mediaType")
        or item.get("media_type")
        or item.get("mime_type")
        or ""
    )
    if isinstance(mt, str) and mt.lower().startswith("image/"):
        return True
    name = item.get("filename") or item.get("name") or ""
    if isinstance(name, str):
        ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
        if ext in {"png", "jpg", "jpeg", "gif", "webp", "bmp"}:
            return True
    return False


def _is_scoped_artifact_write(tool_name: str, args: dict[str, Any] | None) -> bool:
    """Allow routine non-code deliverables without an approval round trip."""
    if tool_name not in _SCOPED_ARTIFACT_WRITE_TOOLS or not isinstance(args, dict):
        return False
    raw_path = args.get("path")
    if not isinstance(raw_path, str) or not raw_path.strip():
        return False

    from pathlib import Path

    from runtime.platform.process.scope import resolve_write_scope, thread_artifact_root
    from runtime.platform.process.session import current_session

    session = current_session()
    if session is None:
        return False
    scope = resolve_write_scope(session)
    if scope.mode in {"code", "plan"}:
        return False

    artifact_root = thread_artifact_root(
        session.thread_id or "default",
        explicit_root=(
            session.metadata.get("_artifact_output_root")
            if isinstance(session.metadata.get("_artifact_output_root"), str)
            else None
        ),
    )
    supplied_sandbox = args.get("sandbox_dir")
    sandbox = (
        Path(supplied_sandbox).expanduser()
        if isinstance(supplied_sandbox, str) and supplied_sandbox.strip()
        else artifact_root
    )
    target = Path(raw_path).expanduser()
    if not target.is_absolute():
        target = sandbox / target
    try:
        target.resolve(strict=False).relative_to(artifact_root.resolve(strict=False))
    except (OSError, ValueError):
        return False
    return True


def _estimate_context_fullness(messages: list, model: str | None) -> float:
    """Rough fraction of the model's context budget consumed by ``messages``.

    Uses a coarse character-count proxy (no tokenizer in the hot path) and
    a model-name-keyed budget. Returned value is clamped to ``[0.0, 1.0]``.
    """
    try:
        used_chars = sum(len(str(getattr(m, "content", m))) for m in messages)
    except (TypeError, AttributeError):
        used_chars = 0

    name = (model or "").lower()
    if (
        "claude-3-5" in name
        or "claude-4" in name
        or "claude-sonnet" in name
    ):
        budget = 600_000
    elif "gpt-4o" in name or "gpt-5" in name:
        budget = 400_000
    else:
        budget = 100_000

    if budget <= 0:
        return 0.0
    ratio = used_chars / budget
    if ratio < 0.0:
        return 0.0
    if ratio > 1.0:
        return 1.0
    return ratio


_CONTEXT_PRESSURE_NUDGE = (
    "[context-pressure] (level={level})\n"
    "You are approaching the context window. Before this turn ends:\n"
    "1. Update todo_write so every in-flight item shows accurate status.\n"
    "2. In your next Thought, write a one-paragraph \"resume state\":\n"
    "   - what you were about to do\n"
    "   - any file paths you've written to\n"
    "   - the next concrete action you'd take if continuing\n"
    "This message survives compaction; raw step history may not."
)


def _long_task_budget_limits(
    *,
    is_research_mode: bool,
    is_swarm_mode: bool,
    max_tokens_budget: int,
    max_usd_budget: float,
) -> tuple[int, float, float]:
    """Return accounting limits and pause threshold for this ReAct turn."""
    if is_swarm_mode:
        return (
            max(max_tokens_budget, 250_000),
            max(max_usd_budget, 5.0),
            0.95,
        )
    if is_research_mode:
        return (
            max(max_tokens_budget, 150_000),
            max(max_usd_budget, 3.0),
            0.95,
        )
    return max_tokens_budget, max_usd_budget, 0.8


# Re-exports for tests/test_react_loop.py — the helpers live in
# react_parsing / react_execution / react_guards now, but tests import them
# from this module. Listing them in __all__ keeps ruff from auto-removing
# the imports as "unused".
__all__ = [
    "ReActResult",
    "ReActStep",
    "_build_code_context_prelude",
    "_code_mode_completion_guard",
    "_escape_md_brackets",
    "_execute_action_via_beak",
    "_format_skill_catalog",
    "_parse_action",
    "_parse_step",
    "_placeholder_observation",
    "_reset_kg_throttle_for_tests",
    "_reset_react_variants_for_tests",
    "_safe_for_streamdown",
    "get_react_variant_stats",
    "pick_react_variant",
    "record_react_variant_result",
    "run_react_loop",
    "stream_react_loop",
]


# Tools that mutate the workspace. When a multi-action block contains
# any of these we force serial dispatch — concurrent file writes can
# clobber each other and the auto-diagnostics path expects a single
# resolved_name.
_WRITE_TOOLS: frozenset[str] = frozenset({
    "write_text_file", "edit_file", "multi_edit_file",
    "edit_text_file", "edit_code", "str_replace",
    "write_file", "create_file",
})

# Default cap on parallel actions. Beyond this we still execute every
# call but slice them into pool-sized batches; protects against a
# model hallucinating 30 read_files at once.
_MAX_PARALLEL_ACTIONS = 4


def _dispatch_parallel_actions(
    actions: list[str],
    *,
    stack: Any,
    executor: Any,
    iteration: int,
    react_task_id: Any,
    agent: Any,
    intent: ParsedIntent,
) -> Iterator[Any]:
    """Concurrent multi-action dispatcher (口子 2).

    Generator helper invoked via ``yield from`` from the main loop.
    Yields the same ``tool_start`` / ``tool_end`` events the legacy
    single-action path emits, one pair per action, with unique
    ``call_id`` per call. Returns ``(merged_observation, results)``
    via StopIteration.value.

    Force-serial fallbacks (executes via the same path but sequenced
    rather than threaded):
      * Any action targets a known write tool.
      * Any action's parsed name is unregistered (so we surface a
        "tool not found" observation immediately rather than after
        partial work has run).
    """
    import concurrent.futures as _cf

    parsed_pairs: list[tuple[str, dict[str, Any]] | None] = [
        _parse_action(a) for a in actions
    ]
    from runtime.safety.approval.approval_gate import assess_approval_risk

    resolved_names: list[str | None] = []
    has_unregistered = False
    has_write_tool = False
    # Risky/untrusted tools must run serially (inline, in this thread) so
    # the injection-taint contextvar the executor reads/writes is visible —
    # the parallel thread-pool path doesn't propagate it. Running them
    # inline also lets an untrusted tool's taint apply to a later risky tool
    # in the same batch via the executor's chokepoint block.
    has_risky_or_untrusted = False
    for p in parsed_pairs:
        if p is None:
            resolved_names.append(None)
            has_unregistered = True
            continue
        name = p[0]
        registry = getattr(executor, "registry", None)
        if registry is None or not registry.has(name):
            resolved_names.append(None)
            has_unregistered = True
        else:
            resolved_names.append(name)
            if name in _WRITE_TOOLS:
                has_write_tool = True
            if assess_approval_risk(name).level in {"medium", "high", "critical"}:
                has_risky_or_untrusted = True
            else:
                try:
                    _aff = registry.get(name).affinity
                except (KeyError, AttributeError):
                    _aff = None
                if is_untrusted_tool(name, _aff):
                    has_risky_or_untrusted = True

    # Pre-allocate per-action call_ids so tool_start/tool_end can be
    # paired even if work runs out-of-order.
    call_ids = [uuid.uuid4().hex[:12] for _ in actions]
    started_at = [time.monotonic() for _ in actions]

    # Emit tool_start for every action up-front so the UI shows them
    # in parallel even if we end up running serially below.
    for idx in range(len(actions)):
        name = resolved_names[idx] or "unknown"
        _input_preview = parsed_pairs[idx][1] if parsed_pairs[idx] else None
        yield {
            "type": "tool_start",
            "tool_name": name,
            "tool_call_id": call_ids[idx],
            "iteration": iteration,
            "input_preview": _input_preview,
            "parallel_batch_size": len(actions),
        }

    serial = has_write_tool or has_unregistered or has_risky_or_untrusted

    def _run_one(idx: int) -> tuple[str | None, Any]:
        # Skip dispatch for unregistered tools — the single-action
        # path's "(tool not registered)" message is reproduced here
        # so the model gets a uniform observation.
        if resolved_names[idx] is None:
            return (
                f"(工具未注册或无法解析) action: {actions[idx][:200]}",
                None,
            )
        return _execute_action_via_beak(
            stack,
            actions[idx],
            react_task_id=react_task_id,
            react_step_counter=iteration,
            agent=agent,
            intent=intent,
        )

    observations: list[str | None] = [None] * len(actions)
    beak_steps: list[Any] = [None] * len(actions)
    if serial or len(actions) <= 1:
        for idx in range(len(actions)):
            obs, bk = _run_one(idx)
            observations[idx] = obs
            beak_steps[idx] = bk
    else:
        max_workers = min(len(actions), _MAX_PARALLEL_ACTIONS)
        with _cf.ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {
                pool.submit(_run_one, idx): idx for idx in range(len(actions))
            }
            for fut in _cf.as_completed(futures):
                idx = futures[fut]
                try:
                    obs, bk = fut.result()
                except Exception as exc:  # noqa: BLE001 — surface any worker exception as a tool error observation
                    obs, bk = (
                        f"(工具执行异常) {type(exc).__name__}: {exc}",
                        None,
                    )
                observations[idx] = obs
                beak_steps[idx] = bk

    # Emit tool_end events in declared (action) order so the UI
    # transcript matches the model's intent.
    results: list[dict[str, object]] = []
    merged_lines: list[str] = []
    n = len(actions)
    for idx in range(n):
        obs = observations[idx]
        bk = beak_steps[idx]
        name = resolved_names[idx] or "unknown"
        _ok = not (
            obs is not None
            and isinstance(obs, str)
            and obs.startswith(("(工具失败)", "(工具执行异常)", "(工具未注册"))
        )
        if bk is not None:
            _ok = _beak_step_effective_success(bk)
        _duration_ms = int((time.monotonic() - started_at[idx]) * 1000)
        # Indirect prompt-injection defense: a tool whose output is
        # external (web/browser/MCP) is attacker-influenceable. Fence its
        # observation as DATA-not-instructions before it re-enters the
        # model's context, and flag known injection markers. The UI
        # preview keeps the raw text; only the model-facing copy is
        # wrapped. Failed-tool observations are error strings, not
        # untrusted content, so they're left alone.
        model_obs = obs
        if _ok and isinstance(obs, str) and obs:
            _reg = getattr(executor, "registry", None)
            _affinity: list[str] | None = None
            if _reg is not None and resolved_names[idx] and _reg.has(name):
                try:
                    _affinity = _reg.get(name).affinity
                except (KeyError, AttributeError):
                    _affinity = None
            if is_untrusted_tool(name, _affinity):
                _scan = scan_for_injection(obs)
                model_obs = wrap_untrusted_observation(
                    obs, source=name, scan=_scan,
                )
                if _scan.flagged:
                    # Taint the turn so a later high-risk tool is forced
                    # through human approval (read at the approval gate).
                    mark_injection_taint(_scan.severity)
                    _logger.warning(
                        "prompt-injection markers in %s output "
                        "(severity=%s, signals=%s)",
                        name, _scan.severity, ",".join(_scan.labels),
                    )
        yield {
            "type": "tool_end",
            "tool_name": name,
            "tool_call_id": call_ids[idx],
            "iteration": iteration,
            "status": "success" if _ok else "error",
            "output_preview": (
                _summarize_observation(obs)
                if isinstance(obs, str) and obs
                else obs
            ),
            "duration_ms": _duration_ms,
            "parallel_batch_size": n,
            **_tool_event_extras_from_beak_step(bk, name),
        }
        results.append({
            "tool_name": name,
            "ok": _ok,
            "observation": model_obs or "",
            "duration_ms": _duration_ms,
            "call_id": call_ids[idx],
        })
        # Per-call header keeps the model from confusing which
        # observation belongs to which action.
        merged_lines.append(
            f"[{idx + 1}/{n} {name}]\n{model_obs or '(no output)'}"
        )

    merged_obs = "\n\n".join(merged_lines)
    return merged_obs, results


def stream_react_loop(
    stack: StackProtocol,
    intent: ParsedIntent,
    agent: Agent | None,
    *,
    model: str | None = None,
    max_iterations: int = 30,
    temperature: float = 0.3,
    enable_tools: bool = True,
    resume_task_id: TaskId | None = None,
    thread_id: str = "",
    max_tokens_budget: int = 50000,
    max_usd_budget: float = 0.5,
    approval_provider: ApprovalProvider | None = None,
    output_chunk_sink: Callable[[str, str, str], None] | None = None,
    step_evaluator: Callable[[dict[str, Any]], float | None] | None = None,
    planning_mode: bool = False,
    reasoning_effort: str | None = None,
) -> Iterator[dict[str, Any]]:
    # ╔══════════════════════════════════════════════════════════════════╗
    # ║ stream_react_loop · navigation map (comment-only; do not split). ║
    # ║                                                                  ║
    # ║   PHASE 1 · entry guards / router resolution     (this section)  ║
    # ║   PHASE 2 · mode + budget detection              ~L1037          ║
    # ║   PHASE 3 · system + volatile prompt assembly    ~L1049          ║
    # ║   PHASE 4 · message bootstrap + start yield      ~L1640          ║
    # ║   PHASE 5 · pre-loop state init + resume         ~L1664          ║
    # ║   PHASE 6 · main iteration loop                  ~L1835          ║
    # ║       6a · cancel / pause guard                  ~L1836          ║
    # ║       6b · LLM call + Final-Answer anchor stream ~L1901          ║
    # ║       6c · parse step / format-violation         ~L2148          ║
    # ║       6d · action dispatch + observation         ~L2258          ║
    # ║       6e · nudges + guards + step yield          ~L2594          ║
    # ║       6f · auto-checkpoint + step evaluator      ~L2694          ║
    # ║       6g · housekeeping (msg append / continue)  ~L2778          ║
    # ║   PHASE 7 · post-loop terminal handling          ~L2954          ║
    # ║       (pause / cancel / forced max-iter convergence)             ║
    # ║   PHASE 8 · finalization + react_completed yield ~L3063          ║
    # ║                                                                  ║
    # ║ Why one big function: closure state (~25 vars) + interleaved     ║
    # ║ yield points + checkpoint/resume coupling make extraction        ║
    # ║ semantics-changing. See ADR-008 + feedback_runtime_behavior.     ║
    # ╚══════════════════════════════════════════════════════════════════╝

    # ── PHASE 1 · entry guards / router resolution ─────────────────────
    router = getattr(getattr(stack, "planner", None), "router", None)
    if router is None:
        _logger.warning("react_loop: stack.planner.router 不可用,无法进入 ReAct")
        return None

    from runtime.platform.models.llm import (
        Message,
        ModelRequest,
        normalize_reasoning_effort,
        thinking_budget_for_effort,
    )

    _reasoning_effort = normalize_reasoning_effort(reasoning_effort)

    # Planning mode used to disable tool execution outright (the
    # model produced a plan, the user approved, then a follow-up turn
    # re-ran with ``planning_mode=false``). That hard-stop confused
    # users — the UI shows nothing happening and ``Action: web_search``
    # falls through to the "(未执行观察) 本次 ReAct 未启用工具执行"
    # placeholder. Updated semantics (2026-05-31): planning_mode keeps
    # tool execution ON; the system prompt simply nudges the model to
    # write/update plan.md first before substantial tool work. The
    # ``exit_plan_mode`` skill flow is still available for explicit
    # human-in-the-loop approval, but auto-detection no longer strands
    # the turn in plan-only territory.
    executor = getattr(stack, "executor", None) if enable_tools else None
    tools_active = executor is not None

    # Expose the live approval provider through the session so the
    # ``exit_plan_mode`` skill can issue an interactive approval
    # request without re-plumbing the param through every layer.
    try:
        from runtime.platform.process.session import current_session as _cs_for_provider
        _session_for_provider = _cs_for_provider()
        if (
            _session_for_provider is not None
            and _session_for_provider.metadata is not None
            and approval_provider is not None
        ):
            _session_for_provider.metadata["_approval_provider"] = approval_provider
    except (ImportError, AttributeError):  # noqa: BLE001 — session layer optional in tests
        pass

    # ── PHASE 2 · mode + budget detection ──────────────────────────────
    from runtime.platform.models import TaskId as _TaskId
    react_task_id: TaskId = (
        resume_task_id if resume_task_id is not None else _TaskId(uuid.uuid4())
    )

    _camouflage_variant_name = "baseline"
    _camouflage_suffix = ""
    try:
        from runtime.safety.experiments.scheduler import (
            get_camouflage_scheduler,
        )
        _camouflage_variant_name, _camouflage_suffix = (
            get_camouflage_scheduler().assign_variant_suffix(str(react_task_id))
        )
    except ImportError:
        _logger.debug("camouflage scheduler not available", exc_info=True)

    # ── PHASE 3 · system + volatile prompt assembly ────────────────────
    system_parts: list[str] = [REACT_SYSTEM_PROMPT_BASE]
    # Volatile sections — per-turn signals (date / user prefs /
    # camouflage A-B / memory recall / output_style / thinking).
    # Routed to a prepended user message so they don't poison the
    # system prompt's byte-stable cache prefix. See
    # ``runtime/core/cerebrum/stable_prompt.py`` for the rationale.
    volatile_parts: list[str] = []

    from datetime import datetime as _dt
    volatile_parts.append(
        f"\n当前日期: {_dt.now().strftime('%Y-%m-%d %A')}。"
        " 搜索时请注意信息时效性,优先引用最新来源。"
    )
    _uc = intent.user_context or {}
    _wp = _uc.get("workspace_path") or _uc.get("metadata", {}).get("workspace_path")
    _metadata = _uc.get("metadata") or {}
    _goal_mode_value = (
        _uc.get("goal_mode")
        or _metadata.get("goal_mode")
        or _uc.get("completion_policy")
        or _metadata.get("completion_policy")
    )
    _is_goal_mode = _goal_mode_value is True or (
        isinstance(_goal_mode_value, str)
        and _goal_mode_value.lower() in {"goal", "goal_mode", "true"}
    )
    _is_code_mode = bool(
        _uc.get("mode") == "code"
        or _metadata.get("mode") == "code"
        or _uc.get("capability_mode")
        or _metadata.get("capability_mode")
        or (isinstance(_wp, str) and _wp.strip())
    )
    _browser_regression_enabled = bool(
        _uc.get("browser_regression_enabled")
        or _metadata.get("browser_regression_enabled")
    )
    _browser_regression_preview_url = (
        _uc.get("browser_regression_preview_url")
        or _metadata.get("browser_regression_preview_url")
    )
    _mode_value = str(_uc.get("mode") or _metadata.get("mode") or "").lower()
    _capability_mode_value = str(
        _uc.get("capability_mode") or _metadata.get("capability_mode") or ""
    ).lower()
    _is_swarm_mode = (
        _mode_value in {"swarm", "swarms", "agent_swarm", "agent-swarm"}
        or _capability_mode_value in {"swarm", "swarms", "agent_swarm", "agent-swarm"}
    )
    if _is_swarm_mode and max_iterations < 100:
        max_iterations = 100
    _goal_for_mode = str(intent.normalized_goal or intent.raw or "")
    _is_research_mode = (
        _mode_value in {"deep", "deep_research", "research"}
        or bool(re.search(
            r"调研|研究报告|市场研究|行业报告|竞品分析|deep\s*research|market\s*research|research\s*report",
            _goal_for_mode,
            re.IGNORECASE,
        ))
    )
    # Research turns often need: web_search × N → browse × N →
    # follow-up search → synthesize → refine. The default 30 cap
    # tends to cut off mid-synthesis, leaving the user with no
    # report. Lift to 100 (same floor as swarm) so the
    # convergence-prompt path at max_iter has real research material
    # to compose from.
    if _is_research_mode and max_iterations < 100:
        max_iterations = 100
    # Goal mode runs to user-defined completion (every todo marked
    # ``completed`` AND required verification recorded), enforced by
    # ``_todo_protocol_completion_guard``. The iteration cap exists
    # only as a runaway-safeguard; the guard already gates Final
    # Answer on real progress, so we lift the cap effectively to
    # "as long as it takes". 10000 is the implementation cap; in
    # practice goal mode terminates via the protocol guard, not the
    # iteration counter.
    _GOAL_MODE_MAX_ITER = 10_000
    if _is_goal_mode and max_iterations < _GOAL_MODE_MAX_ITER:
        max_iterations = _GOAL_MODE_MAX_ITER
    (
        _active_max_tokens_budget,
        _active_max_usd_budget,
        _budget_pause_threshold,
    ) = _long_task_budget_limits(
        is_research_mode=_is_research_mode,
        is_swarm_mode=_is_swarm_mode,
        max_tokens_budget=max_tokens_budget,
        max_usd_budget=max_usd_budget,
    )
    _budget_auto_pause_enabled = bool(
        _uc.get("budget_auto_pause")
        or _metadata.get("budget_auto_pause")
        or intent.flags.get("budget_auto_pause", False)
    )
    _todo_protocol_mode = context_mode(_uc)
    _todo_protocol_required = should_require_todo_protocol(
        intent.normalized_goal,
        _uc,
    )
    _todo_protocol_visible = False
    if isinstance(_wp, str) and _wp.strip():
        system_parts.append(
            f"\n当前工作目录: {_wp.strip()}\n"
            "所有文件操作（list_cwd / read_file / write 等）的相对路径都基于此目录。"
            "分析项目时请从这个目录开始,不要使用其他目录。"
        )
        _rules = _load_project_rules(_wp.strip())
        if _rules:
            system_parts.append(
                "\n<project-rules>\n" + _rules + "\n</project-rules>"
            )
        _profile = _build_project_profile_prompt(_wp.strip(), include_diagnostics=_is_code_mode)
        if _profile:
            system_parts.append(
                "\n<project-profile>\n" + _profile + "\n</project-profile>"
            )
        if _is_code_mode:
            system_parts.append(
                "\n<code-mode>\n"
                "**编程三阶段** (强制):\n"
                "1. **理解** (1-3 轮): `list_cwd` + `read_file` 摸清目录与关键文件;"
                "禁止写操作。Discovery 用 `list_cwd`/`read_file`/`grep_text`/`glob_files`,"
                "不要用 `exec_shell` 跑 find/ls/cat/grep。\n"
                "2. **执行** (2-N 轮): `todo_write` 列计划 → 小步改 (`edit_file`/`multi_edit_file`/"
                "`propose_patch`) → 改完立即验证。每改 1 处立即跑相应 lint/typecheck/test,"
                "不要积攒 5 处一起跑。\n"
                "3. **验证** (1-2 轮): 项目自带 lint/typecheck/test 跑过再 Final Answer。"
                "失败回阶段 2 修;不要 fake 验证通过。\n"
                "**第一轮 Thought 必须声明阶段**(理解/执行/验证)。\n"
                "**收工硬约束**: 仍有 pending/in_progress todo、改动未验证、"
                "或工具/权限/登录阻塞时, 不能给完成式 Final Answer;"
                "用 Final Answer 描述阻塞 + 列出未完成 todo + 已做过的验证。\n"
                "</code-mode>"
            )
            if _browser_regression_enabled:
                _preview_line = (
                    f"优先测试预览地址: {_browser_regression_preview_url}\n"
                    if isinstance(_browser_regression_preview_url, str)
                    and _browser_regression_preview_url.strip()
                    else "如果当前任务产出了可预览页面，请先启动或定位预览地址。\n"
                )
                system_parts.append(
                    "\n<browser-regression-guidance>\n"
                    "用户已在代码模式开启 UI 回归。完成代码修改和静态验证后，如果改动涉及前端、HTML、样式、交互或可视输出，"
                    "必须补充浏览器回归检查。\n"
                    + _preview_line +
                    "浏览器回归应模拟真人操作：使用可见鼠标移动、点击、输入和滚动路径，检查关键交互、布局、控制台错误和明显视觉回归。"
                    "发现问题时回到执行阶段修复，再重新验证。\n"
                    "如果没有可测试 UI、缺少登录/权限或预览无法启动，请在 Final Answer 里明确说明阻塞原因和已完成的静态验证。\n"
                    "</browser-regression-guidance>"
                )
        if _is_goal_mode:
            system_parts.append(
                "\n<goal-mode-guidance>\n"
                "当前为 Goal 模式。Goal 模式比普通计划模式更严格: "
                "你必须把用户目标拆成可执行计划, 用 todo_write 记录完整清单, "
                "并按清单推进。\n"
                "不要因为完成了部分计划就结束; 只有当用户目标已达成、"
                "所有 todo 都是 completed、且必要验证已完成时, 才能给完成式 Final Answer。\n"
                "如果发现原计划不够或目标变化, 必须调用 todo_write 更新完整清单, "
                "继续执行新的计划。\n"
                "如果被权限、登录、外部信息或用户决策阻塞, 先更新 todo_write 标出阻塞项, "
                "再明确向用户请求所需输入。\n"
                "</goal-mode-guidance>"
            )

        # Long-task / large-context guidance — only relevant when the
        # turn is going to be more than a couple of rounds. Skipping
        # short / chat turns keeps the system prompt small for them
        # and improves prompt cache hits across turn types.
        if _todo_protocol_required or _is_research_mode or _is_swarm_mode or _is_goal_mode:
            system_parts.append(
                "\n<long-task>\n"
                "**深度**: 长任务变体 max_iter 60-100 轮; 跑到第 10/20 轮会有 system 检查,"
                "实诚回答(还在推进/已经完成/工具连续失败); 答完了就停, 别凑轮数。\n"
                "**大项目**: 文件 >20 个时不要试图全读 — 维护"
                "「工作集」(直接相关 3-8 个文件), 已读过的不要在后续 Thought 复述。"
                "context 接近上限时优先保留: 当前正在改的文件 > 任务目标 > 历史推理。\n"
                "**进度**: 第一轮 todo_write 列完整计划 → 每完成一步立即更新 →"
                "完成里程碑在 Thought 给一句话总结。\n"
                "</long-task>"
            )

        # Memory + skill-template playbook — only inject when the user's
        # request looks like one we've seen before, otherwise the model
        # is just told about features it doesn't need this turn.
        if _todo_protocol_required:
            system_parts.append(
                "\n<memory-and-templates>\n"
                "**模板复用** (低成本高回报): 看到「以后也按这格式 / 做成 X 那样」→"
                "先 `list_learned_skills()`(0 token), 命中就 `apply_skill(name, request)`,"
                "没命中再考虑 `learn_skill_from_text(name, sample, golden_samples=[...])`"
                "(framework 会用 golden_samples 校验模板才落盘)。\n"
                "**记忆四档**(按需,不要每次都用):\n"
                "  - `recall` — 用户提到旧上下文 → 第一轮就查\n"
                "  - `remember` — 项目级事实(项目名 / deadline / API key 路径)\n"
                "  - `note_user` — 用户偏好(语言 / 详略 / 技术水平)\n"
                "  - `update_soul` — 你自己的持久教训(不是一次性观察)\n"
                "</memory-and-templates>"
            )

        # User long-term preferences — persistent settings the user has
        # asked us to honor across turns (e.g. "always 4-space indent",
        # "no Co-Authored-By footer"). Injected before reporting-cadence
        # so cadence/tool guidance can't shadow user-stated defaults.
        try:
            from runtime.memory.users.user_preferences import (
                _load_user_preferences as _load_prefs,
            )
            _prefs = _load_prefs(_uc.get("actor") or _metadata.get("actor"))
        except ImportError:
            _logger.debug("user_preferences module not available", exc_info=True)
            _prefs = {}
        except Exception:  # noqa: BLE001 - never break turn startup
            _logger.debug("user_preferences load failed", exc_info=True)
            _prefs = {}
        if _prefs:
            _pref_lines = [f"- {k}: {v}" for k, v in sorted(_prefs.items())]
            system_parts.append(
                "\n<user-preferences>\n"
                "用户的长期偏好（影响默认行为；用户在本轮另有要求时以本轮为准）:\n"
                + "\n".join(_pref_lines)
                + "\n</user-preferences>"
            )

        # Cadence + final-answer shape — applies to every mode that
        # has visible tool work (octopus optimisation §27 + §30).
        # Skipped for pure chat where there's no work to report on.
        if _todo_protocol_required:
            system_parts.append(
                "\n<reporting-cadence>\n"
                "**进度节奏**(避免闷头干 N 步再一次性 dump):\n"
                "- 每改 2-3 个文件、或每完成一个清单项, 在下一轮 Thought 里给\n"
                "  一句话进度("
                "本轮做了 X / 接下来 Y / 若 Z 不对请打断"
                ")\n"
                "- 不要积攒 5+ 步成果再统一汇报 — 用户看不到你做了什么就\n"
                "  无法 mid-course 纠偏\n"
                "- 单次 Thought 不超过 6 行;真要展开就拆成多轮\n"
                "</reporting-cadence>\n"
                "<final-answer-shape>\n"
                "**Final Answer 结构**(任务完成时;请求协助时另议):\n"
                "- 第 1 行: 一句话总结(做了什么 / 状态如何)\n"
                "- 改动: 列出修改/新建的文件路径(逐行,绝对或工作目录相对)\n"
                "- 验证: 跑过的命令 + 关键结果("
                "如 `pytest tests/foo.py -q` → 4 passed"
                ")\n"
                "- 未做(可选): 故意跳过的、需要后续做的\n"
                "调研/报告类任务输出报告本身, 但仍在结尾附改动 + 来源说明。\n"
                "</final-answer-shape>\n"
                "<tool-choice-policy>\n"
                "**工具选择硬约束**(优先级 / 危险性 / cwd):\n"
                "- 文件发现: 用 `list_cwd` / `glob_files`(若可用); **不要**\n"
                "  `exec_shell(\"find ...\")` / `exec_shell(\"ls ...\")`\n"
                "- 内容搜索: 用 `code_search` / `grep`(项目内置, 跨平台);\n"
                "  **不要** `exec_shell(\"grep -r ...\")`\n"
                "- 文件读取: 用 `read_file` 带 `offset`/`limit`(超 2000 行\n"
                "  必带);**不要** `exec_shell(\"cat\"/\"head\"/\"tail\")`\n"
                "- exec_shell 限定用途: 编译 / 测试 / 构建 / git / 跑特定\n"
                "  CLI(那种没专用 skill 的 ad-hoc 命令)\n"
                "- 长运行命令(dev server / watcher / docker compose / 长测试):\n"
                "  用 `exec_shell(run_in_background=True)` 或 `background_exec`, 然后用\n"
                "  `read_shell_output(task_id)` / `read_background_output(task_id)` 轮询;\n"
                "  结束时用 `kill_shell(task_id)` / `kill_background_exec(task_id)`\n"
                "- **危险命令预审**: 调 exec_shell 前在 Thought 里分类:\n"
                "  * destructive(`rm -rf` / drop database / `git push --force`\n"
                "    main / chmod 777 / sudo / docker rm -f / kubectl delete):\n"
                "    描述影响范围, 然后 Final Answer 请求用户确认;**不要**\n"
                "    赌默认 approval 会兜住\n"
                "  * mutating(普通 git commit / npm install / pytest -x):\n"
                "    继续\n"
                "  * read-only(`ls` / `git status` / `cat README`): 安静继续\n"
                "- **cwd 习惯**: 多个 exec_shell 调用之间 cwd 可能被工具重置;\n"
                "  显式用 `exec_shell(cwd=...)` 参数, **不要**在 command 字\n"
                "  符串里 `cd X && do Y`(`cd` 失败是 silent 的)\n"
                "- **Edit 失败时**: old_string 不唯一就 (a) 加上下文使其唯一,\n"
                "  或 (b) `replace_all=True`;不要把同一调用换个壳重发\n"
                "- **并行 tool_use**: 同一轮里 emit 的多个 tool_use blocks,\n"
                "  如果它们彼此**没有数据依赖**(典型: 多个 `read_file` 读\n"
                "  不同文件 / `Read(a) + Glob(...) + Bash(git status)`),\n"
                "  尽量在一个 assistant message 里一次性 emit,\n"
                "  框架会并发执行 → 单 turn 速度大幅加快。\n"
                "  反例: 第一个 `read_file` 的结果决定第二个 `edit_file` 的\n"
                "  参数 → 必须串行(分两轮 emit),不要塞一起。\n"
                "</tool-choice-policy>"
            )
    try:
        from runtime.core.cerebrum.output_styles import render_output_style
        output_style_value = (
            _uc.get("output_style")
            or _metadata.get("output_style")
            or ""
        )
        _output_style_block = render_output_style(output_style_value)
        if _output_style_block:
            # Volatile: user can switch per turn; would break cache prefix.
            volatile_parts.append(_output_style_block)
    except (ImportError, AttributeError):
        _logger.debug("output_styles overlay not available", exc_info=True)
    try:
        from runtime.core.cerebrum.thinking_mode import render_thinking_guidance
        _thinking_guidance = render_thinking_guidance(_uc.get("thinking_plan"))
    except (ImportError, AttributeError):
        _logger.debug("thinking_mode guidance not available", exc_info=True)
        _thinking_guidance = ""
    if _thinking_guidance:
        # Volatile: changes whenever the model picks a new thinking plan.
        volatile_parts.append(_thinking_guidance)
    system_parts.append(
        "\n<user-facing-process-language>\n"
        "Internal tool names are execution details, not product language. "
        "Use names like `call_agent_parallel`, `web_search`, `fetch_url`, "
        "`todo_write`, `bb_keys`, or `query_skill` only inside tool actions "
        "and private reasoning. In Final Answer and any user-facing prose, "
        "describe the work in human terms instead: call a teammate, search "
        "sources, read webpages, make a plan, or check team context. Do not "
        "show raw tool names unless the user explicitly asks for technical "
        "debug details.\n"
        "</user-facing-process-language>"
    )
    if (
        not _is_swarm_mode
        and _mode_value not in {"chat", "flash", "inspiration"}
    ):
        system_parts.append(
            "\n<agent-auto-delegation-guidance>\n"
            "Current mode is single-agent Agent/ReAct. You remain the lead, "
            "but you may use real subagents when parallelism will materially "
            "improve speed or quality.\n"
            "\n"
            "Use `call_agent_parallel` proactively when the task has 2-4 "
            "independent work lanes: e.g. market research lanes, competitor "
            "comparison lanes, frontend/backend/test investigation lanes, "
            "or reproduce/read-code/review lanes. This tool spawns real "
            "specialist turns concurrently; it is not a display shortcut.\n"
            "\n"
            "Decision policy:\n"
            "- Simple or sequential work: do it yourself with atomic tools.\n"
            "- Large ambiguous work: first clarify if needed, then "
            "todo_write a visible plan before fan-out.\n"
            "- If using subagents, make exactly one `call_agent_parallel` "
            "batch for the current turn. Pick roles from the actual lanes "
            "(researcher, explorer, debugger, reviewer, architect, "
            "security-review). Do not call serial `call_agent`.\n"
            "- Ask workers for compact, evidence-backed findings and any "
            "files touched. After the observation returns, synthesize the "
            "outputs yourself, resolve conflicts, verify critical claims, "
            "and produce one integrated final result.\n"
            "- Never finish with raw worker logs or a partial plan. If "
            "workers fail partially, use the surviving outputs and state "
            "the residual risk.\n"
            "</agent-auto-delegation-guidance>"
        )
    if _is_swarm_mode:
        system_parts.append(
            "\n<swarm-orchestration-guidance>\n"
            "Current mode is SWARM. Treat swarm as an adaptive long-task "
            "orchestration mode, not a fixed template.\n"
            "\n"
            "Decision policy:\n"
            "- If the user's request is simple or can be completed by the "
            "lead in one short pass, do NOT spawn subagents; answer or use "
            "the smallest necessary tool path.\n"
            "- If the task is large, long-running, research-heavy, or has "
            "independent work lanes, create/update a visible todo_write plan "
            "first. Use stage-like item names such as task analysis, parallel "
            "research/execution round N, synthesis, quality review, and "
            "delivery only when those stages are actually needed.\n"
            "- For durable research/report/build tasks, write or update "
            "`plan.md` before substantial execution when a workspace/file "
            "output is available.\n"
            "- Choose skills dynamically. For research/report work, prefer "
            "`deep-research-swarm` -> `report-writing` -> `docx` when the "
            "user explicitly asked for a file deliverable. When the user "
            "did not specify a format, default to a markdown report "
            "rendered directly in the chat reply (the UI renders it "
            "natively) and skip the `.docx` export. If a needed skill is "
            "missing, say which capability is missing and use the best "
            "available real tools.\n"
            "- Use `call_agent_parallel` only for independent subtasks. Pick "
            "the number and roles from the task itself; do not force a fixed "
            "headcount. Good roles include researcher, explorer, architect, "
            "reviewer, debugger, and security-review.\n"
            "- Ask parallel workers to write compact findings to blackboard "
            "keys with `bb_write`; after the batch, read them with `bb_keys` "
            "and `bb_read`, synthesize conflicts, and cross-check important "
            "claims before final delivery.\n"
            "- Never finish with only raw worker logs, a partial plan, or "
            "'still working' prose. Final Answer must include the integrated "
            "result and any created file paths. If blocked, update todo_write "
            "and ask for the specific missing input.\n"
            "</swarm-orchestration-guidance>"
        )
    if _is_research_mode:
        # Mode-aware skill chain: ``deep-research-swarm`` is reserved
        # for swarm mode (TeamRunner with native tool_use). In single-
        # agent / Agent mode (the common case here when ``_is_research_mode``
        # is true but ``_is_swarm_mode`` is false) we point the model
        # at ``deep-research`` instead — the single-agent counterpart
        # that returns the 7-phase instruction document the parent
        # ReAct loop drives via plain ``web_search`` / ``fetch_url``.
        _research_skill = (
            "deep-research-swarm" if _is_swarm_mode else "deep-research"
        )
        system_parts.append(
            "\n<research-skill-chain-guidance>\n"
            "This turn is a research/report task. Drive the work through "
            "the visible research-skill chain when the corresponding "
            "skills are available, otherwise fall back to atomic tools.\n"
            "Suggested workflow (skip steps the user did not ask for):\n"
            "1. Create or update a concrete `plan.md` for the task with "
            "`write_text_file` before substantial research begins.\n"
            f"2. Call `{_research_skill}` to load the research workflow, "
            "then follow it for evidence collection and cross-checking.\n"
            "3. **Default deliverable is the report rendered directly in "
            "the chat reply (markdown).** The chat UI renders headings, "
            "tables, and citations natively, so a long-form markdown "
            "answer is already the final product — do NOT auto-export to "
            ".docx / .pdf / any other file format unless the user "
            "explicitly asked for that format.\n"
            "4. Only when the user asks for a file deliverable: call "
            "`report-writing` and/or `docx` (or the appropriate format "
            "skill) to produce the file, then include the file path in "
            "the final answer alongside the chat-rendered summary.\n"
            "5. Do not finish with only 'still searching' / 'still "
            "writing' prose — the final answer must contain the actual "
            "report text.\n"
            "If one of the optional skills is not visible, state which "
            "capability is missing, then fall back to the best available "
            "tools without pretending the skill chain ran.\n"
            "</research-skill-chain-guidance>"
        )
        system_parts.append(
            "\n<research-final-guidance>\n"
            "当前任务具有调研/研究报告性质。工具搜索与浏览只是证据收集阶段，不能把过程模板当作最终回答。\n"
            "在给 Final Answer 前，必须输出用户可直接阅读的完整报告正文；"
            "报告至少包含：执行摘要、关键结论、分维度分析、对比表或清单、"
            "风险/不确定性、建议、来源说明。\n"
            "如果搜索轮次或预算接近上限，不要停在「正在整理/继续搜索」；"
            "应基于已有证据生成阶段性完整报告，并清楚标注仍需补证的点。\n"
            "</research-final-guidance>"
        )

    _file_inspection_tools_visible = False
    if tools_active:
        try:
            from runtime.core.cerebrum.capability_router import (
                activate_capabilities,
            )
            _capability_activation = activate_capabilities(
                intent.normalized_goal,
                user_context=_uc,
                registry=executor.registry,
            )
            _capability_activation_prompt = (
                _capability_activation.render_prompt()
            )
        except (ImportError, AttributeError, TypeError, ValueError):
            _logger.debug(
                "capability activation prompt unavailable",
                exc_info=True,
            )
            _capability_activation_prompt = ""
            _capability_activation = None
        if _capability_activation_prompt:
            volatile_parts.append(_capability_activation_prompt)

        # Side effects of mention parsing:
        #   1. Auto-load pinned plugins so the model can use them this turn.
        #   2. Persist mention history for cross-thread autocomplete ranking.
        # Both are best-effort; failures don't block the turn.
        if _capability_activation is not None:
            try:
                if _capability_activation.pinned_plugins:
                    from runtime.core.cerebrum.plugin_auto_load import (
                        auto_load_pinned_plugins,
                    )
                    plugin_report = auto_load_pinned_plugins(
                        _capability_activation.pinned_plugins,
                    )
                    obs = plugin_report.render_observation()
                    if obs:
                        volatile_parts.append(
                            f"<plugin-activation>\n{obs}\n</plugin-activation>",
                        )
            except (ImportError, AttributeError, TypeError):
                _logger.debug(
                    "plugin auto-load failed", exc_info=True,
                )

            try:
                import time as _time

                from runtime.memory.users.mention_history import (
                    get_mention_history_store,
                )
                actor = (
                    str(_uc.get("user_id") or _uc.get("actor") or "anonymous")
                    if isinstance(_uc, dict) else "anonymous"
                )
                store = get_mention_history_store()
                ts = _time.time()
                items: list[tuple[str, str]] = []
                for ident in _capability_activation.pinned_plugins:
                    items.append(("plugin", ident))
                for ident in _capability_activation.pinned_skills:
                    items.append(("skill", ident))
                for ident in _capability_activation.pinned_agents:
                    items.append(("agent", ident))
                for ident in _capability_activation.pinned_packs:
                    items.append(("pack", ident))
                if items:
                    store.record_batch(actor, items, ts=ts)
            except (ImportError, AttributeError, OSError, TypeError):
                _logger.debug(
                    "mention history record failed", exc_info=True,
                )

        catalog = _format_skill_catalog(
            executor.registry,
            agent=agent,
            user_context=_uc,
            goal=intent.normalized_goal,
        )
        if catalog:
            _file_inspection_tools_visible = (
                "  - list_cwd:" in catalog and "  - read_file:" in catalog
            )
            _todo_protocol_visible = "  - todo_write:" in catalog
            system_parts.append(catalog)
            if _todo_protocol_visible:
                system_parts.append(render_todo_protocol_guidance(
                    required=_todo_protocol_required,
                    mode=_todo_protocol_mode,
                ))
    else:
        system_parts.append(REACT_NO_TOOLS_NOTE)
    if planning_mode:
        # New semantics (2026-05-31): "plan first, then execute" — not
        # "plan only and stop". Long tasks benefit from a written plan
        # before tool work, but the user should NOT have to send a
        # second turn to actually run the plan. Old prompt forced the
        # model to halt after planning; updated prompt nudges it to
        # write plan.md, then keep going with real tool calls.
        system_parts.append(
            "PLAN-FIRST MODE — Before substantial tool work, write or "
            "update a brief ``plan.md`` (or todo_write entries) outlining "
            "the goal, the steps you'll take, and what the deliverable "
            "looks like. After the plan is recorded, **continue executing "
            "the plan in the same turn** using real tools (web_search, "
            "fetch_url, write_text_file, etc.). Do NOT stop after the "
            "plan — the user expects the work, not just an outline. The "
            "Final Answer must include the integrated result, not the "
            "plan alone.",
        )
    if agent is not None and getattr(agent, "soul", None):
        try:
            from runtime.execution.agents.loader import compose_runtime_soul
            runtime_soul = compose_runtime_soul(agent)
        except (ImportError, AttributeError):
            _logger.debug("compose_runtime_soul not available", exc_info=True)
            runtime_soul = agent.soul
        if runtime_soul:
            system_parts.insert(0, runtime_soul)
    try:
        from runtime.safety.validation import get_constitution_summary
        _constitution = get_constitution_summary()
    except ImportError:
        _logger.debug("constitution module not available", exc_info=True)
        _constitution = ""
    if _constitution:
        system_parts.append(_constitution)
    try:
        from runtime.core.cerebrum.llm_planner import (
            _render_team_roster_section,
        )
        _team_block = _render_team_roster_section(intent.user_context or {})
    except (ImportError, AttributeError):
        _logger.debug("team roster rendering not available", exc_info=True)
        _team_block = ""
    if _team_block:
        system_parts.append(_team_block)

    try:
        from runtime.memory.runtime_state.hub import (
            MemoryHub,
            MemoryQuery,
            format_records_for_prompt,
        )
        _agent_id_for_memory = (
            str(getattr(agent, "agent_id", "") or "") if agent is not None else None
        )
        _project_for_memory = (
            str(_wp).strip() if isinstance(_wp, str) and str(_wp).strip() else None
        )
        _team_id_for_memory = _uc.get("team_id") or _metadata.get("team_id")
        _team_id_for_memory = (
            str(_team_id_for_memory).strip()
            if isinstance(_team_id_for_memory, str)
            and str(_team_id_for_memory).strip()
            else None
        )
        _memory_block = format_records_for_prompt(
            MemoryHub(
                repo_root=_project_for_memory,
                planner=getattr(stack, "planner", None),
            ).retrieve(
                MemoryQuery(
                    text=intent.normalized_goal,
                    agent_id=_agent_id_for_memory,
                    project=_project_for_memory,
                    team_id=_team_id_for_memory,
                    limit=8,
                )
            ),
        )
    except Exception:
        _logger.debug("memory hub prompt injection failed", exc_info=True)
        _memory_block = ""
    if _memory_block:
        # Volatile: changes per-turn with the recall query result.
        volatile_parts.append(_memory_block)

    if _camouflage_suffix:
        # Volatile: A/B variant rotates per-turn.
        volatile_parts.append(_camouflage_suffix)

    # Compose: system prompt is the byte-stable prefix; per-turn
    # signals (date / output_style / thinking / memory recall /
    # camouflage variant) ride on a prepended synthetic user
    # message so they don't break the cache prefix.
    from runtime.core.cerebrum.stable_prompt import (
        render_volatile_as_user_message,
    )
    _volatile_text = (
        "\n\n".join(volatile_parts).strip() if volatile_parts else ""
    )
    messages: list[Message] = [
        Message(role="system", content="\n\n".join(system_parts)),
    ]
    if _volatile_text:
        messages.append(
            Message(
                role="user",
                content=render_volatile_as_user_message(_volatile_text),
            ),
        )
    conv_history = (intent.user_context or {}).get("conversation_messages")
    if isinstance(conv_history, list) and conv_history:
        profile_mems = (intent.user_context or {}).get("profile_memories")
        if isinstance(profile_mems, list) and profile_mems:
            try:
                from runtime.memory.users.profile import render_profile_memories
                mem_block = render_profile_memories(profile_mems)
            except (ImportError, AttributeError, TypeError):
                mem_block = ""
            if mem_block:
                messages.append(Message(role="system", content=mem_block))
        for item in conv_history[:-1]:
            if not isinstance(item, dict):
                continue
            role = item.get("role")
            content = item.get("content")
            if role not in ("user", "assistant", "system"):
                continue
            if (
                isinstance(content, str) and content.strip()
                or isinstance(content, list) and content
            ):
                messages.append(Message(role=role, content=content))
    _no_startup_code_context_modes = {
        "chat",
        "conversation",
        "inspiration",
        "brainstorm",
        "discuss",
    }
    _startup_code_context_allowed = (
        _is_code_mode
        and _mode_value not in _no_startup_code_context_modes
        and _capability_mode_value not in _no_startup_code_context_modes
    )
    if (
        _startup_code_context_allowed
        and isinstance(_wp, str)
        and _wp.strip()
        and resume_task_id is None
    ):
        startup_context = _build_code_context_prelude(_wp.strip())
        if startup_context:
            messages.append(Message(role="user", content=startup_context))
    messages.append(
        Message(
            role="user",
            content=_build_user_message_content(
                intent.normalized_goal,
                intent.user_context.get("attachments", []),
            ),
        ),
    )

    effective_model = (
        model if model and model not in ("octopus-agent", "")
        else getattr(stack.planner, "planner_model", None) or "molili"
    )

    # ── PHASE 4 · message bootstrap done; emit react_started ───────────
    yield {
        "type": "react_started",
        "task_id": str(react_task_id),
        "thread_id": thread_id or None,
        "max_iterations": max_iterations,
    }

    # ── PHASE 4.5 · agent auto-delegation short-circuit ────────────────
    # When the user prompt has a single, unambiguous @agent: pin AND no
    # competing routing signals, we can save one full LLM round trip by
    # delegating directly. The plan only fires when ALL of these hold:
    #   - tools_active (delegation is a tool path)
    #   - not planning_mode (plan mode wants the model to think first)
    #   - the prompt passes plan_auto_delegation's heuristics
    #   - the executor's registry has the call_agent skill
    # On success, we inject the subagent's output as an Observation-style
    # user message so the next LLM turn synthesizes the final answer
    # against real evidence rather than re-planning the delegation.
    _auto_delegated = False
    if tools_active and not planning_mode:
        try:
            from runtime.core.cerebrum.agent_auto_delegate import (
                plan_auto_delegation,
            )
            _delegation_plan = plan_auto_delegation(
                intent.normalized_goal,
                registry=getattr(executor, "agent_registry", None)
                or getattr(stack, "agent_registry", None)
                or getattr(executor, "registry", None),
            )
        except (ImportError, AttributeError, TypeError):
            _delegation_plan = None
        if (
            _delegation_plan is not None
            and _delegation_plan.should_delegate
            and _skill_available_in_executor(executor, "call_agent")
        ):
            try:
                from runtime.execution.subagents.bridge import call_subagent
                _logger.info(
                    "react_loop auto-delegating to agent=%s reason=%s",
                    _delegation_plan.target_agent,
                    _delegation_plan.reason,
                )
                yield {
                    "type": "auto_delegation_started",
                    "target_agent": _delegation_plan.target_agent,
                    "reason": _delegation_plan.reason,
                }
                _delegate_result = call_subagent(
                    agent_id=_delegation_plan.target_agent or "",
                    prompt=_delegation_plan.cleaned_prompt,
                    context={
                        "thread_id": thread_id or "",
                        "source": "auto_delegation",
                        "parent_task_id": str(react_task_id),
                    },
                    timeout_s=120,
                )
                _delegate_output = str(
                    _delegate_result.get("output", "") or "",
                ).strip()
                _delegate_ok = bool(_delegate_result.get("success", False))
                if _delegate_ok and _delegate_output:
                    # Inject as a synthetic Observation so the model's
                    # next turn writes the Final Answer directly.
                    obs_block = (
                        "<auto-delegation-observation>\n"
                        f"Auto-delegated to @agent:{_delegation_plan.target_agent}.\n"
                        f"Reason: {_delegation_plan.reason}.\n"
                        f"Subagent output:\n\n{_delegate_output}\n"
                        "</auto-delegation-observation>\n\n"
                        "Use this as the primary evidence for your Final "
                        "Answer. Add your own synthesis or follow-up only "
                        "if the user's request demands more than the "
                        "subagent's output already covers."
                    )
                    messages.append(Message(role="user", content=obs_block))
                    _auto_delegated = True
                    yield {
                        "type": "auto_delegation_completed",
                        "target_agent": _delegation_plan.target_agent,
                        "output_length": len(_delegate_output),
                    }
                else:
                    err = str(_delegate_result.get("error", "") or "")
                    _logger.info(
                        "auto-delegation produced no usable output "
                        "(success=%s, error=%s) — falling back to model",
                        _delegate_ok, err,
                    )
                    yield {
                        "type": "auto_delegation_skipped",
                        "target_agent": _delegation_plan.target_agent,
                        "reason": err or "no output",
                    }
            except (ImportError, AttributeError, TypeError, ValueError) as exc:
                _logger.debug(
                    "auto-delegation failed; falling back to model: %s",
                    exc, exc_info=True,
                )
                yield {
                    "type": "auto_delegation_skipped",
                    "target_agent": getattr(
                        _delegation_plan, "target_agent", None,
                    ),
                    "reason": f"{type(exc).__name__}: {exc}",
                }

    # ── PHASE 5 · pre-loop state init + checkpoint resume ──────────────
    from runtime.core.cerebrum.pause_control import get_pause_controller
    _pause = get_pause_controller()
    _agent_id_for_pause = str(getattr(agent, "agent_id", "") or "")
    _pause.register_active(
        str(react_task_id),
        thread_id=thread_id or "",
        agent_id=_agent_id_for_pause,
        max_iterations=max_iterations,
        max_tokens=_active_max_tokens_budget,
        max_usd=_active_max_usd_budget,
    )

    steps: list[ReActStep] = []
    executed_beak_steps: list[Step] = []
    # Clear any prompt-injection taint from a prior turn in this context,
    # then INHERIT the spawning parent's taint when this loop is a subagent
    # spun up in a fresh thread/context (the taint contextvar doesn't cross
    # the thread-pool boundary, so the parent passes it explicitly via the
    # intent). Without this, delegating a risky action to a subagent would
    # wash the taint clean.
    reset_injection_taint()
    _inherited_taint = intent.user_context.get("_inherited_injection_taint")
    if isinstance(_inherited_taint, str) and _inherited_taint not in ("", "none"):
        mark_injection_taint(_inherited_taint)
    final_answer: str | None = None
    final_answer_segments: list[str] = []
    final_answer_emitted = False
    terminated_reason = "max_iter"
    resume_from_iter = 0

    # Throughput sampler — chars/sec across all delta yields. We emit a
    # ``throughput`` event every ~500ms so the UI can show a live
    # tokens-per-second indicator without flooding the WebSocket. Chars
    # are a useful proxy: at the cost of being model-dependent, they
    # don't require a tokenizer in the hot path.
    _throughput_started_at = time.monotonic()
    _throughput_chars = 0
    _throughput_last_emit = _throughput_started_at
    _throughput_interval_s = 0.5

    _working_set: dict[str, dict[str, Any]] = {}
    _progress_summary = ""
    _current_phase = "understand"
    _known_background_tasks: dict[str, dict[str, Any]] = {}
    _resume_event: dict[str, Any] | None = None

    if resume_task_id is not None:
        journal = getattr(stack, "journal", None)
        if journal is not None:
            try:
                ckpts = [
                    e for e in journal.read_by_type("react_checkpoint")
                    if str(getattr(e, "task_id", "")) == str(resume_task_id)
                ]
                if ckpts:
                    last = ckpts[-1]
                    from runtime.core.cerebrum.checkpoint_integrity import (
                        validate_checkpoint_state,
                    )
                    _checkpoint_state = {
                        "messages_snapshot": last.messages_snapshot,
                        "steps_snapshot": last.steps_snapshot,
                        "working_set_snapshot": getattr(
                            last, "working_set_snapshot", [],
                        ),
                        "progress_summary": getattr(last, "progress_summary", ""),
                        "current_phase": getattr(last, "current_phase", ""),
                    }
                    _integrity = validate_checkpoint_state(
                        _checkpoint_state,
                        iteration=last.iteration_completed,
                    )
                    if not _integrity.resume_safe:
                        _logger.warning(
                            "react_loop resume checkpoint rejected (task %s): %s",
                            resume_task_id,
                            ", ".join(_integrity.errors),
                        )
                        raise ValueError("unsafe checkpoint")
                    resume_from_iter = last.iteration_completed
                    if last.messages_snapshot:
                        messages = _restore_messages_from_checkpoint(last.messages_snapshot)
                    if last.steps_snapshot:
                        steps = [
                            ReActStep(
                                iteration=s.get("iteration", 0),
                                thought=s.get("thought", ""),
                                action=s.get("action", ""),
                                observation=s.get("observation", ""),
                            )
                            for s in last.steps_snapshot
                            if isinstance(s, dict)
                        ]
                        messages = _rehydrate_messages_from_steps(messages, steps)
                    if getattr(last, "working_set_snapshot", None):
                        _working_set = {
                            f["path"]: f
                            for f in last.working_set_snapshot
                            if isinstance(f, dict) and f.get("path")
                        }
                    if getattr(last, "progress_summary", ""):
                        _progress_summary = last.progress_summary
                    if getattr(last, "current_phase", ""):
                        _current_phase = last.current_phase
                    if (
                        getattr(last, "has_final_answer", False)
                        and getattr(last, "final_answer", "")
                    ):
                        final_answer = str(last.final_answer)
                        terminated_reason = "final_answer"
                        resume_from_iter = max_iterations
                    react_task_id = resume_task_id
                    _resume_event = {
                        "type": "react_resumed",
                        "task_id": str(resume_task_id),
                        "checkpoint_iteration": last.iteration_completed,
                        "resume_from_iteration": resume_from_iter,
                        "restored_step_count": len(steps),
                        "has_final_answer": bool(final_answer),
                        "current_phase": _current_phase,
                        "progress_summary": _progress_summary,
                    }
                    _logger.info(
                        "react_loop resuming from iteration %d (task %s)",
                        resume_from_iter, resume_task_id,
                    )
            except (AttributeError, KeyError, TypeError, ValueError):
                _logger.debug("resume checkpoint loading failed", exc_info=True)

    if _resume_event is not None:
        yield _resume_event

    consecutive_format_violations = 0
    # Allow two consecutive zero-anchor rounds before bailing. The
    # first violation is often a model warming up — it dumps a chunk
    # of plain markdown / JSON before remembering to use the
    # ``Action:`` anchor. Setting this to 1 used to terminate the
    # loop on the very first round, killing tool work that would have
    # happened on round 2. Two rounds tolerates the warmup but still
    # bails fast when the model genuinely cannot follow ReAct format.
    _format_violation_bail_at = 2
    _context_pressure_signaled: bool = False

    from runtime.platform.models.llm import (
        model_supports_thinking as _supports_thinking,
    )
    _resolved_model = effective_model
    if hasattr(router, "_resolve"):
        try:
            _sub = router._resolve(effective_model)
            if _sub is not router:
                _resolved_model = (
                    getattr(_sub, "default_model", None)
                    or effective_model
                )
        except (AttributeError, TypeError):  # noqa: BLE001 — subrouter doesn't expose default_model; fall back to effective_model
            pass
    _wants_thinking = _supports_thinking(_resolved_model)
    # Per-iteration ``max_tokens`` ceiling. Non-thinking models used to
    # cap at 2000 tokens, which is fine for a chatty back-and-forth but
    # truncates long-form generation mid-sentence — research reports
    # are typically 4-6k tokens of markdown and were getting cut at
    # ~2k char before the model could reach the conclusion. The model
    # then read the finish_reason as "length" and (without the
    # continuation logic below) decided the task was done, emitting a
    # short summary instead of resuming. 8k is enough for a single
    # report section; the continuation path catches anything longer.
    _max_tokens_per_iter = 4096 if _wants_thinking else 8000

    if resume_task_id is not None:
        _grant = _pause.consume_grant(str(resume_task_id))
        _extra_iters = int(_grant.get("extra_iterations") or 0)
        if _extra_iters > 0:
            max_iterations = max_iterations + _extra_iters
            _logger.info(
                "react_loop resume grant: +%d iterations for task %s "
                "(new max=%d)",
                _extra_iters, resume_task_id, max_iterations,
            )
        _pause.clear(str(resume_task_id))

    for i in range(resume_from_iter, max_iterations):
        # ── PHASE 6a · cancel / pause guard ────────────────────────────
        # Cancellation check — runs before pause check so a tripped
        # token wins over an in-flight pause request. The ambient
        # token is set by the request handler (e.g. FastAPI's
        # disconnect watcher); when ``CancellationToken.none()`` is
        # active the call is essentially free (one bool read).
        try:
            from runtime.safety.approval.cancellation import current_cancellation_token
            _ct = current_cancellation_token()
            if _ct.is_cancelled:
                terminated_reason = "cancelled"
                _logger.info(
                    "react_loop cancelled at iteration %d (task %s) — reason=%s",
                    i, react_task_id, _ct.reason or "client disconnected",
                )
                break
        except (ImportError, AttributeError, TypeError):  # noqa: BLE001 — cancellation subsystem unavailable; proceed normally
            pass

        if _pause.is_pause_requested(str(react_task_id) if react_task_id else None):
            terminated_reason = "paused"
            _logger.info(
                "react_loop paused at iteration %d (task %s) — checkpoint written",
                i, react_task_id,
            )
            journal = getattr(stack, "journal", None)
            if journal is not None:
                with contextlib.suppress(Exception):
                    journal.write_react_checkpoint(
                        task_id=react_task_id,
                        iteration_completed=i,
                        max_iterations=max_iterations,
                        messages_snapshot=_serialize_messages_for_checkpoint(messages),
                        steps_snapshot=[
                            {
                                "iteration": s.iteration,
                                "thought": s.thought,
                                "action": s.action,
                                "observation": s.observation,
                            }
                            for s in steps
                        ],
                        has_final_answer=False,
                        working_set_snapshot=list(_working_set.values()),
                        progress_summary=_progress_summary,
                        current_phase=_current_phase,
                    )
                try:
                    req_meta = _pause.get_request(str(react_task_id))
                    journal.write_task_paused(
                        task_id=str(react_task_id) if react_task_id else "",
                        reason=req_meta.reason if req_meta else "external",
                        requested_by=req_meta.requested_by if req_meta else "",
                        iteration=i,
                    )
                except (AttributeError, ImportError):
                    _logger.debug("pause journal write failed", exc_info=True)
            _pause.mark_paused(str(react_task_id) if react_task_id else "")
            _pause.unregister_active(str(react_task_id) if react_task_id else "")
            yield {
                "type": "react_paused",
                "iteration": i,
                "task_id": str(react_task_id) if react_task_id else None,
            }
            break

        # ── PHASE 6b · LLM call + Final-Answer anchor stream ───────────
        try:
            req = ModelRequest(
                model=effective_model,
                messages=list(messages),
                max_tokens=_max_tokens_per_iter,
                temperature=temperature,
                enable_thinking=_wants_thinking,
                reasoning_effort=_reasoning_effort,
                thinking_budget=thinking_budget_for_effort(
                    _reasoning_effort,
                    _max_tokens_per_iter,
                ),
            )
            text_parts: list[str] = []
            thinking_parts: list[str] = []
            resp = None
            # Once we detect the ``Final Answer:`` anchor in the streaming
            # text we switch to live token streaming so short tasks see
            # first-byte latency closer to the LLM's TTFT instead of full
            # response time. Pre-anchor chunks must stay buffered because
            # they may contain Thought:/Action: prose that must not leak.
            _final_stream_started = False
            _streamed_final_chars = 0

            def _maybe_emit_throughput(chars: int) -> dict[str, Any] | None:
                nonlocal _throughput_last_emit
                _now = time.monotonic()
                if _now - _throughput_last_emit < _throughput_interval_s:
                    return None
                _elapsed = _now - _throughput_started_at
                _throughput_last_emit = _now
                return {
                    "type": "throughput",
                    "chars": chars,
                    "elapsed_ms": int(_elapsed * 1000),
                    "chars_per_sec": (
                        chars / _elapsed if _elapsed > 0 else 0.0
                    ),
                }

            for evt in router.call_stream(req):
                # Check cancellation between SSE chunks so the
                # interrupt button can break us out of a slow /
                # hung upstream without waiting for the read timeout.
                # ``current_cancellation_token`` is a contextvar set
                # by the gateway's interrupt watcher when the user
                # clicks 停止.
                _ct_inner = current_cancellation_token()
                if _ct_inner is not None and _ct_inner.is_cancelled:
                    break
                if evt.type == "text_delta":
                    text_parts.append(evt.delta)
                    if _final_stream_started:
                        # Already past the anchor — every subsequent
                        # token is part of the user-visible answer.
                        if evt.delta:
                            yield {
                                "type": "text_delta",
                                "delta": evt.delta,
                                "iteration": i + 1,
                            }
                            _streamed_final_chars += len(evt.delta)
                            _throughput_chars += len(evt.delta)
                            _tp = _maybe_emit_throughput(_throughput_chars)
                            if _tp is not None:
                                yield _tp
                    else:
                        # Look for the Final Answer anchor in the joined
                        # buffer. Once it appears we can flush the
                        # post-anchor portion and switch to live mode for
                        # the rest of the stream — this is what makes
                        # short tasks feel responsive instead of
                        # blocking on full response decode.
                        joined = "".join(text_parts)
                        m = _FINAL_RE.search(joined)
                        if m and m.group(1).strip():
                            answer_so_far = m.group(1)
                            # Don't pre-stream when the answer body
                            # contains tool-call leaders. The parser will
                            # later reclassify these as Actions and
                            # suppress them from the visible answer; if
                            # we leak them now the user sees raw XML/JSON
                            # before the real tool fires.
                            if (
                                "<tool_call>" in answer_so_far
                                or "<tool_invocation" in answer_so_far
                                or "<function=" in answer_so_far
                                or "```" in answer_so_far
                            ):
                                # Keep buffering; the post-loop emitter
                                # will decide what (if anything) is
                                # safe to surface.
                                pass
                            elif answer_so_far:
                                yield {
                                    "type": "text_delta",
                                    "delta": answer_so_far,
                                    "iteration": i + 1,
                                }
                                _streamed_final_chars = len(answer_so_far)
                                _throughput_chars += len(answer_so_far)
                                _tp = _maybe_emit_throughput(
                                    _throughput_chars
                                )
                                if _tp is not None:
                                    yield _tp
                                _final_stream_started = True
                        elif (
                            len(joined) >= 120
                            and not _THOUGHT_RE.search(joined)
                            and not _ACTION_RE.search(joined)
                            and not _looks_like_observation_echo(joined)
                            and "<tool_call>" not in joined
                            and "<tool_invocation" not in joined
                            and "<function=" not in joined
                        ):
                            # Zero-anchor chat-style answer: model is
                            # writing plain markdown (no Thought/Action/
                            # Final Answer markers). Without this branch
                            # the salvage path at end of iteration emits
                            # all 700+ chars at once after a wasted
                            # second LLM round (zero-anchor needs 2
                            # consecutive rounds to bail). With it, the
                            # user sees text streaming the moment it's
                            # clear ReAct format isn't coming.
                            yield {
                                "type": "text_delta",
                                "delta": joined,
                                "iteration": i + 1,
                            }
                            _streamed_final_chars = len(joined)
                            _throughput_chars += len(joined)
                            _tp = _maybe_emit_throughput(_throughput_chars)
                            if _tp is not None:
                                yield _tp
                            _final_stream_started = True
                elif evt.type == "thinking_delta":
                    thinking_parts.append(evt.delta)
                    yield {
                        "type": "thinking_delta",
                        "delta": evt.delta,
                        "iteration": i + 1,
                    }
                    _throughput_chars += len(evt.delta or "")
                    _tp = _maybe_emit_throughput(_throughput_chars)
                    if _tp is not None:
                        yield _tp
                elif evt.type == "done":
                    resp = evt.final
            if resp is None:
                from runtime.platform.models.llm import ModelResponse
                resp = ModelResponse(
                    text="".join(text_parts),
                    thinking="".join(thinking_parts),
                    model=effective_model,
                )
        except Exception as exc:
            _logger.warning(
                "react_loop iter %d LLM 调用失败 (%s): %s",
                i, type(exc).__name__, exc,
            )
            if not steps:
                _err_msg = str(exc)
                _err_kind = (
                    "auth"
                    if "current_actor" in _err_msg or "登录" in _err_msg
                    else "router"
                )
                yield {
                    "type": "react_error",
                    "kind": _err_kind,
                    "message": _err_msg,
                    "iteration": i,
                    "task_id": str(react_task_id) if react_task_id else None,
                }
                _pause.unregister_active(str(react_task_id))
                return None
            terminated_reason = "error"
            break

        raw_text = "".join(text_parts)
        try:
            _in_tok = int(getattr(resp, "input_tokens", 0) or 0)
            _out_tok = int(getattr(resp, "output_tokens", 0) or 0)
            _tok = _in_tok + _out_tok
            _cost_obj = getattr(resp, "cost", None)
            _cost = float(getattr(_cost_obj, "usd", 0) or 0) if _cost_obj else 0.0
            _journal = getattr(stack, "journal", None)
            if _journal is not None and hasattr(_journal, "write_token_usage"):
                with contextlib.suppress(Exception):
                    _journal.write_token_usage(
                        task_id=str(react_task_id),
                        iteration=i + 1,
                        input_tokens=_in_tok,
                        output_tokens=_out_tok,
                        cost_usd=_cost,
                        model=str(getattr(resp, "model", "") or ""),
                    )
            _updated = _pause.update_active_usage(
                str(react_task_id),
                tokens_delta=_tok,
                cost_delta=_cost,
            )
            if (
                _budget_auto_pause_enabled
                and
                _updated is not None
                and react_task_id is not None
                and not _pause.is_pause_requested(str(react_task_id))
            ):
                _token_pct = (
                    _updated.tokens_spent / _updated.max_tokens
                    if _updated.max_tokens > 0 else 0
                )
                _usd_pct = (
                    _updated.cost_usd / _updated.max_usd
                    if _updated.max_usd > 0 else 0
                )
                if (
                    _token_pct >= _budget_pause_threshold
                    or _usd_pct >= _budget_pause_threshold
                ):
                    _logger.info(
                        "react_loop budget auto-pause · task %s · "
                        "tokens %d/%d (%.0f%%) · usd %.3f/%.3f (%.0f%%)",
                        react_task_id,
                        _updated.tokens_spent, _updated.max_tokens,
                        _token_pct * 100,
                        _updated.cost_usd, _updated.max_usd,
                        _usd_pct * 100,
                    )
                    _pause.request_pause(
                        task_id=str(react_task_id),
                        reason="budget_near_limit",
                        requested_by="system",
                        note=(
                            f"自动暂停 · tokens {_updated.tokens_spent:,}/"
                            f"{_updated.max_tokens:,} "
                            f"({int(_token_pct*100)}%) · "
                            f"${_updated.cost_usd:.3f}/"
                            f"${_updated.max_usd:.3f} "
                            f"({int(_usd_pct*100)}%) · 加预算继续"
                        ),
                        thread_id=thread_id or "",
                        agent_id=_agent_id_for_pause,
                    )
        except (AttributeError, TypeError):
            _logger.debug("budget check failed", exc_info=True)

        # ── PHASE 6c · parse step / format-violation check ─────────────
        text = (resp.text or raw_text or "").strip()
        step, maybe_final = _parse_step(text, iteration=i + 1)
        if (
            _looks_like_observation_echo(text)
            and not step.observation
            and not step.action
            and maybe_final is None
        ):
            step.observation = text
        _finish_reason = (getattr(resp, "finish_reason", "") or "").strip().lower()
        _length_limited = _finish_reason in {
            "length",
            "max_tokens",
            "max_output_tokens",
            "output_limit",
            "token_limit",
        }
        _length_limit_should_continue = False
        if maybe_final and not _final_stream_started:
            # Fall-through emission for routers that don't actually
            # stream (e.g. tests, non-streaming providers): yield the
            # parsed final once. When _final_stream_started is true the
            # user has already seen these tokens live, so skip to avoid
            # duplicate text in the transcript.
            yield {
                "type": "text_delta",
                "delta": maybe_final,
                "iteration": i + 1,
            }

        # Chat-style answer recovery: the model produced plain
        # markdown without any ReAct anchor BUT we already streamed
        # it live via the 120-char early-flush branch in the LLM
        # call loop above. Treat that streamed prose AS the final
        # answer — don't waste a second LLM round to bail. Without
        # this short-circuit, real chat-style replies (mimo's
        # default shape) burn the bail-at budget and emit the same
        # text twice on iteration N+1.
        if (
            _final_stream_started
            and not maybe_final
            and step.action.lower() in {"none", "n/a", ""}
            and not _looks_like_observation_echo(text)
            and not _FINAL_RE.search(text)
        ):
            final_answer = text
            terminated_reason = "final_answer"
            final_answer_emitted = True
            steps.append(step)
            break

        if _is_format_violation(step, maybe_final):
            # Length-limited generation gets a free pass on the
            # zero-anchor format violation. The model didn't emit a
            # final answer because it ran out of tokens mid-sentence,
            # not because it broke the protocol — the continuation
            # branch below will inject a "Continue exactly where it
            # stopped" nudge and the next iteration will finish.
            _is_length_truncated = (
                (getattr(resp, "finish_reason", "") or "").strip().lower()
                in {"length", "max_tokens", "max_output_tokens", "output_limit", "token_limit"}
            )
            if _is_length_truncated:
                # Surface the partial text so the user sees streaming
                # progress; don't count it against bail-at.
                if text and not maybe_final:
                    yield {
                        "type": "text_delta",
                        "delta": text,
                        "iteration": i + 1,
                    }
                consecutive_format_violations = 0
            else:
                consecutive_format_violations += 1
                _logger.warning(
                    "react_loop iter %d · LLM produced zero ReAct anchors "
                    "(consec=%d/%d) · raw head=%r",
                    i + 1,
                    consecutive_format_violations,
                    _format_violation_bail_at,
                    text[:200],
                )
                if consecutive_format_violations >= _format_violation_bail_at:
                    # Salvage the model's raw output as the final reply.
                    # Without this yield the gateway records a turn that
                    # produced no text → frontend renders the stream as
                    # "本次回复已中断" even though the model spoke. This
                    # is the most common shape of zero-anchor: a research
                    # / chat-style answer in plain markdown without
                    # ``Final Answer:`` prefix. Treat it as the answer
                    # rather than silently discarding it.
                    # If the chat-style early-flush branch above already
                    # streamed this text live, skip the duplicate yield —
                    # otherwise the user sees the answer twice.
                    if text and not maybe_final and not _final_stream_started:
                        yield {
                            "type": "text_delta",
                            "delta": text,
                            "iteration": i + 1,
                        }
                    _persist_react_trajectory(
                        stack,
                        react_task_id=react_task_id,
                        beak_steps=executed_beak_steps,
                        success=False,
                    )
                    _pause.unregister_active(str(react_task_id))
                    return None
        else:
            consecutive_format_violations = 0

        resp_thinking = (getattr(resp, "thinking", "") or "").strip()
        if resp_thinking and not step.thought:
            step.thought = resp_thinking

        _throughput_chars += len(text)
        _tp = _maybe_emit_throughput(_throughput_chars)
        if _tp is not None:
            yield _tp

        # ── PHASE 6d · action dispatch + observation ───────────────────
        observation: str | None = step.observation or None
        resolved_name: str | None = None
        tool_ok = False
        tool_action_requested = (
            tools_active
            and step.action
            and step.action.lower() not in {"none", "n/a", ""}
        )

        if tool_action_requested:
            observation = None
            step.observation = ""
            maybe_final = None

        # Multi-action fast path: when the model emitted >1 tool call
        # in a single Action: block, dispatch them concurrently and
        # merge observations. Keeps the legacy single-action path
        # below untouched — that branch only runs when there is
        # exactly one action, preserving every existing
        # approval/retry/cancel/background-task behavior.
        _parallel_handled = False
        if (
            tool_action_requested
            and len(step.actions) > 1
        ):
            _parallel_obs, _parallel_results = yield from _dispatch_parallel_actions(
                step.actions,
                stack=stack,
                executor=executor,
                iteration=i + 1,
                react_task_id=react_task_id,
                agent=agent,
                intent=intent,
            )
            if _parallel_obs is not None:
                observation = _parallel_obs
                step.observation = _parallel_obs
                step.action_results = _parallel_results
                tool_ok = all(r.get("ok") for r in _parallel_results)
                _parallel_handled = True

        if not _parallel_handled and not step.observation:
            will_attempt_tool = (
                tool_action_requested
            )
            if will_attempt_tool:
                parsed = _parse_action(step.action)
                resolved_name = (
                    parsed[0]
                    if parsed and executor.registry.has(parsed[0])
                    else None
                )
                if resolved_name is not None:
                    call_id = uuid.uuid4().hex[:12]
                    _input_preview = parsed[1] if parsed else None
                    _tool_started_at = time.monotonic()
                    yield {
                        "type": "tool_start",
                        "tool_name": resolved_name,
                        "tool_call_id": call_id,
                        "iteration": i + 1,
                        "input_preview": _input_preview,
                    }
                    _auto_approve = (
                        intent.user_context.get("auto_approve", False)
                        or intent.flags.get("auto_approve", False)
                    )
                    from runtime.safety.approval.approval_gate import (
                        ApprovalRequest,
                        AutoDenyProvider,
                        approval_action_for_tool,
                    )
                    try:
                        from runtime.platform.process.session import current_session as _cs_ap
                        _sess_ap = _cs_ap()
                        _risk_policy_raw = (
                            getattr(_sess_ap, "metadata", {}) or {}
                        ).get("approval_risk_policy") if _sess_ap is not None else None
                    except (AttributeError, TypeError):
                        _risk_policy_raw = None
                    _approval_risk, _approval_action, _approval_policy = approval_action_for_tool(
                        resolved_name,
                        str(_input_preview)[:500] if _input_preview else "",
                        policy=_risk_policy_raw,
                    )
                    _scoped_artifact_write = _is_scoped_artifact_write(
                        resolved_name,
                        _input_preview,
                    )
                    _permission_mode_value = str(
                        intent.user_context.get("permission_mode")
                        or _metadata.get("permission_mode")
                        or ""
                    ).lower()
                    _accept_edits_auto_approve = (
                        _permission_mode_value in {"acceptedits", "accept-edits"}
                        and resolved_name in _WRITE_TOOLS
                    )
                    # Injection taint gate (hard): if untrusted content
                    # carrying injection markers entered this turn, a
                    # risky tool can no longer auto-run — force it through
                    # human approval, overriding auto_approve and the
                    # scoped-write / accept-edits fast paths. This is the
                    # escalation from the in-context warning to an actual
                    # stop: a poisoned page can't drive an exec_shell /
                    # write / send behind the user's back. Gate at medium+
                    # so EXFILTRATION (egress tools = medium — the classic
                    # injection payload) is caught, not just destructive
                    # high-risk tools; only pure low-risk reads still
                    # auto-run after taint.
                    if (
                        injection_taint_gates()
                        and _approval_risk.level in {"medium", "high", "critical"}
                    ):
                        _auto_approve = False
                        _scoped_artifact_write = False
                        _accept_edits_auto_approve = False
                        if _approval_action not in {"ask", "confirm", "deny"}:
                            _approval_action = "ask"
                        _approval_risk = _approval_risk.with_injection_taint()
                    if (
                        _approval_action == "deny"
                        and not _auto_approve
                        and not _scoped_artifact_write
                    ):
                        yield {
                            "type": "tool_end",
                            "tool_name": resolved_name,
                            "tool_call_id": call_id,
                            "iteration": i + 1,
                            "status": "rejected",
                            "output_preview": (
                                f"Denied by approval risk policy "
                                f"(risk={_approval_risk.level}: {_approval_risk.reason})"
                            ),
                            "duration_ms": int((time.monotonic() - _tool_started_at) * 1000),
                            "risk": _approval_risk.to_dict(),
                            "approval_action": _approval_action,
                            "approval_policy": _approval_policy.to_dict(),
                        }
                        observation = (
                            "(å·¥å…·è¢«é£Žé™©ç­–ç•¥æ‹’ç») æ­¤æ“ä½œè¢« approval risk policy æ‹’ç»ï¼Œ"
                            "è¯·æ¢ä¸€ç§æ–¹å¼æˆ–è¯¢é—®ç”¨æˆ·ã€‚"
                        )
                        continue
                    if (
                        _approval_action in {"ask", "confirm"}
                        and not _auto_approve
                        and not _scoped_artifact_write
                        and not _accept_edits_auto_approve
                    ):
                        _provider = approval_provider or AutoDenyProvider()
                        _approval_detail = (
                            f"{resolved_name} wants to execute "
                            f"(risk={_approval_risk.level}: {_approval_risk.reason})"
                        )
                        yield {
                            "type": "tool_approval_request",
                            "tool_name": resolved_name,
                            "tool_call_id": call_id,
                            "args_preview": str(_input_preview)[:500] if _input_preview else "",
                            "detail": _approval_detail,
                            "risk": _approval_risk.to_dict(),
                            "approval_action": _approval_action,
                            "approval_policy": _approval_policy.to_dict(),
                        }
                        _decision = _provider.request(
                            ApprovalRequest(
                                thread_id=thread_id,
                                tool_name=resolved_name,
                                tool_call_id=call_id,
                                args_preview=str(_input_preview)[:500] if _input_preview else "",
                                detail=_approval_detail,
                            ),
                            timeout=120.0,
                        )
                        if not _decision.approved:
                            yield {
                                "type": "tool_end",
                                "tool_name": resolved_name,
                                "tool_call_id": call_id,
                                "iteration": i + 1,
                                "status": "rejected",
                                "output_preview": _decision.reason or "User denied tool execution",
                                "duration_ms": int((time.monotonic() - _tool_started_at) * 1000),
                            }
                            observation = (
                                "(工具被用户拒绝) 用户拒绝了此操作，"
                                "请换一种方式或询问用户。"
                            )
                            continue
                    if output_chunk_sink is not None:
                        from runtime.core.cerebrum.tool_output_sink import push_sink
                        _bound_call_id = call_id

                        def _local_sink(
                            stream: str,
                            chunk: str,
                            bound_call_id: str = _bound_call_id,
                        ) -> None:
                            output_chunk_sink(bound_call_id, stream, chunk)

                        def _sink_scope() -> Any:
                            return push_sink(_local_sink)
                    else:
                        def _sink_scope() -> Any:
                            return contextlib.nullcontext()
                    # This single-action path ran its own approval gate
                    # (incl. the injection-taint escalation) above, so tell
                    # the executor's chokepoint block this call was reviewed
                    # — otherwise it would double-block an approved tool.
                    with _sink_scope():
                        set_injection_gate_handled(True)
                        try:
                            observation, beak_step = _execute_action_via_beak(
                                stack,
                                step.action,
                                react_task_id=react_task_id,
                                react_step_counter=i + 1,
                                agent=agent,
                                intent=intent,
                            )
                        finally:
                            set_injection_gate_handled(False)
                    if beak_step is not None:
                        executed_beak_steps.append(beak_step)
                    # Tool may have been killed mid-run by the cancel
                    # token. Detect this so we can label the event and
                    # break the loop — skipping the retry and the next
                    # LLM round, which would both waste budget.
                    _ct_post = None
                    try:
                        from runtime.safety.approval.cancellation import (
                            current_cancellation_token,
                        )
                        _ct_post = current_cancellation_token()
                    except (ImportError, AttributeError, TypeError):  # noqa: BLE001 — cancellation subsystem unavailable; post-tool cancel check skipped
                        pass
                    _was_cancelled = bool(_ct_post and _ct_post.is_cancelled)

                    tool_ok = not (
                        observation is not None
                        and observation.startswith(("(工具失败)", "(工具执行异常)"))
                    )
                    if beak_step is not None:
                        tool_ok = _beak_step_effective_success(beak_step)
                    if _was_cancelled:
                        yield {
                            "type": "tool_end",
                            "tool_name": resolved_name,
                            "tool_call_id": call_id,
                            "iteration": i + 1,
                            "status": "cancelled",
                            "output_preview": "(已取消) 用户中断了此操作。",
                            "duration_ms": int((time.monotonic() - _tool_started_at) * 1000),
                        }
                        terminated_reason = "cancelled"
                        break
                    if not tool_ok and observation:
                        _logger.info(
                            "react_loop iter %d · tool %s failed, auto-retrying once",
                            i + 1, resolved_name,
                        )
                        with _sink_scope():
                            set_injection_gate_handled(True)
                            try:
                                retry_obs, retry_step = _execute_action_via_beak(
                                    stack,
                                    step.action,
                                    react_task_id=react_task_id,
                                    react_step_counter=i + 1,
                                    agent=agent,
                                    intent=intent,
                                )
                            finally:
                                set_injection_gate_handled(False)
                        if retry_step is not None:
                            executed_beak_steps.append(retry_step)
                        retry_ok = not (
                            retry_obs is not None
                            and retry_obs.startswith(("(工具失败)", "(工具执行异常)"))
                        )
                        if retry_step is not None:
                            retry_ok = _beak_step_effective_success(retry_step)
                        if retry_ok:
                            observation = retry_obs
                            beak_step = retry_step
                            tool_ok = True
                        else:
                            observation = (
                                observation + "\n[自动重试仍失败，请换方法或调整参数]"
                            )
                    _background_task = (
                        _background_task_info_from_observation(observation)
                        if tool_ok and resolved_name in {"background_exec", "exec_shell"}
                        else None
                    )
                    if _background_task is not None:
                        yield {
                            "type": "tool_background",
                            "tool_name": resolved_name,
                            "tool_call_id": call_id,
                            "iteration": i + 1,
                            "status": "running",
                            "task_id": _background_task["task_id"],
                            "snapshot": _background_task,
                            "output_preview": (
                                _summarize_observation(observation)
                                if isinstance(observation, str) and observation
                                else observation
                            ),
                            "duration_ms": int((time.monotonic() - _tool_started_at) * 1000),
                        }
                    else:
                        yield {
                            "type": "tool_end",
                            "tool_name": resolved_name,
                            "tool_call_id": call_id,
                            "iteration": i + 1,
                            "status": "success" if tool_ok else "error",
                            "output_preview": (
                                _summarize_observation(observation)
                                if isinstance(observation, str) and observation
                                else observation
                            ),
                            "duration_ms": int((time.monotonic() - _tool_started_at) * 1000),
                            **_tool_event_extras_from_beak_step(beak_step, resolved_name),
                        }
                    # Indirect prompt-injection defense (single-action
                    # path; mirrors _dispatch_parallel_actions): fence an
                    # external tool's output as data before it becomes the
                    # observation the model reads next.
                    if tool_ok and isinstance(observation, str) and observation:
                        _pi_affinity: list[str] | None = None
                        try:
                            if executor.registry.has(resolved_name):
                                _pi_affinity = executor.registry.get(
                                    resolved_name,
                                ).affinity
                        except (KeyError, AttributeError):
                            _pi_affinity = None
                        if is_untrusted_tool(resolved_name, _pi_affinity):
                            _pi_scan = scan_for_injection(observation)
                            observation = wrap_untrusted_observation(
                                observation, source=resolved_name, scan=_pi_scan,
                            )
                            if _pi_scan.flagged:
                                # Taint the turn → force human approval on a
                                # later high-risk tool (read at the gate).
                                mark_injection_taint(_pi_scan.severity)
                                _logger.warning(
                                    "prompt-injection markers in %s output "
                                    "(severity=%s, signals=%s)",
                                    resolved_name, _pi_scan.severity,
                                    ",".join(_pi_scan.labels),
                                )
                else:
                    observation, beak_step = _execute_action_via_beak(
                        stack,
                        step.action,
                        react_task_id=react_task_id,
                        react_step_counter=i + 1,
                        agent=agent,
                        intent=intent,
                    )
                    if beak_step is not None:
                        executed_beak_steps.append(beak_step)
            if observation is None:
                observation = _placeholder_observation(step.action)
            step.observation = observation

        if _is_code_mode and observation and _current_phase in ("execute", "verify"):
            _write_tools = frozenset({
                "write_text_file", "edit_file", "multi_edit_file",
                "edit_text_file", "edit_code", "str_replace",
                "write_file", "create_file",
            })
            if resolved_name in _write_tools and tool_ok:
                _auto_diag = _run_auto_diagnostics(
                    stack,
                    workspace_path=_wp if isinstance(_wp, str) else None,
                )
                if _auto_diag:
                    step.observation = observation + "\n\n[自动诊断结果]\n" + _auto_diag
                _prefetch = _prefetch_related_files(step.action, _working_set)
                if _prefetch:
                    step.observation = (
                        (step.observation or observation)
                        + "\n\n[关联文件预读]\n" + _prefetch
                    )

        # ── PHASE 6e · in-flight nudges + guards + step yield ──────────
        # ── In-flight nudges (octopus optimisation §15 + §18) ───
        # Two soft guards that fire DURING the loop, not at Final
        # Answer time. They append a short reminder to this step's
        # observation so the model sees it before composing the
        # next action. Both are silent when the model is already
        # doing the right thing.
        _steps_with_current = steps + [step]
        _midflight_nudges: list[str] = []
        # Track any background process snapshot present in this
        # step's observation so the periodic heartbeat below can
        # remind the model about live processes.
        _bg_task_info = _background_task_info_from_observation(step.observation)
        if _bg_task_info is not None:
            _bg_task_id = _bg_task_info.get("task_id")
            if isinstance(_bg_task_id, str) and _bg_task_id:
                _known_background_tasks[_bg_task_id] = _bg_task_info
        # Heartbeat: every 5 iterations (i > 0 and i % 5 == 0),
        # if we have any registered background tasks, append a
        # reminder to the NEXT step's observation injection.
        if (
            i > 0
            and i % 5 == 0
            and _known_background_tasks
        ):
            _midflight_nudges.append(
                _format_background_task_heartbeat(
                    list(_known_background_tasks.keys())
                )
            )
        _completion_nudge = _completion_phrase_without_todo_guard(
            _steps_with_current,
            todo_protocol_required=_todo_protocol_required and _todo_protocol_visible,
        )
        if _completion_nudge:
            _midflight_nudges.append(
                f"[completion-tracker]\n{_completion_nudge}"
            )
        _verify_nudge = _unverified_write_followup_guard(
            _steps_with_current,
            is_code_mode=_is_code_mode,
        )
        if _verify_nudge:
            _midflight_nudges.append(
                f"[verification-tracker]\n{_verify_nudge}"
            )
        # Context-pressure signal — fires once per turn when the rolling
        # message list approaches the model's context budget. Gives the
        # model a chance to write a "resume state" hand-off paragraph
        # before _compress_context starts dropping older steps.
        if not _context_pressure_signaled:
            _ctx_ratio = _estimate_context_fullness(messages, effective_model)
            if _ctx_ratio > 0.80:
                _midflight_nudges.append(
                    _CONTEXT_PRESSURE_NUDGE.format(level=f"{_ctx_ratio:.0%}")
                )
                _context_pressure_signaled = True
        if _midflight_nudges:
            step.observation = (
                ((step.observation or "") + "\n\n") if step.observation else ""
            ) + "\n\n".join(_midflight_nudges)

        if maybe_final and (
            _is_code_mode
            or (_todo_protocol_required and _todo_protocol_visible)
        ):
            _steps_with_current = steps + [step]
            from runtime.core.cerebrum.react_guards import (
                GuardContext,
                evaluate_guards,
            )
            _guard_ctx = GuardContext(
                steps=_steps_with_current,
                final_answer=maybe_final,
                is_code_mode=_is_code_mode,
                todo_protocol_required=_todo_protocol_required,
                todo_protocol_visible=_todo_protocol_visible,
                file_inspection_tools_visible=_file_inspection_tools_visible,
                tools_active=tools_active,
                goal=intent.normalized_goal,
            )
            _guard_hit = evaluate_guards(
                _guard_ctx,
                recorder=_guard_hit_recorder(),
                disabled_labels=_disabled_guard_labels(),
            )
            if _guard_hit is not None:
                _guard_label, _guard_message = _guard_hit
                maybe_final = None
                step.observation = (
                    ((step.observation or "") + "\n\n") if step.observation else ""
                ) + f"[{_guard_label}]\n" + _guard_message

        _public_progress_summary = (
            _progress_summary
            if _is_code_mode
            else _build_research_progress_summary(steps + [step])
        )

        yield {
            "type": "react_step_complete",
            "iteration": step.iteration,
            "thought": step.thought,
            "action": step.action,
            "observation": step.observation,
            "task_id": str(react_task_id),
            "current_phase": _current_phase if _is_code_mode else None,
            "working_set": list(_working_set.values()) if _is_code_mode else None,
            "progress_summary": _public_progress_summary,
        }

        # ── PHASE 6f · auto-checkpoint + step evaluator ────────────────
        # ── Periodic auto-checkpoint (P3 long-task durability) ──
        # Mirrors the pause path's checkpoint write so a SIGKILL or
        # OOM restart can resume from the last completed iteration.
        # Off by default — opt-in via OCTOPUS_CHECKPOINT_EVERY_N=N.
        # Failures are swallowed; the turn must not break because
        # we couldn't snapshot.
        _ckpt_interval = _checkpoint_interval()
        if maybe_final is None and _should_auto_checkpoint(step.iteration, _ckpt_interval):
            _ckpt_journal_auto = getattr(stack, "journal", None)
            _auto_ckpt_payload = {
                "task_id": str(react_task_id) if react_task_id else "",
                "iteration_completed": step.iteration,
                "max_iterations": max_iterations,
                "messages_snapshot": _serialize_messages_for_checkpoint(messages),
                "steps_snapshot": [
                    {
                        "iteration": s.iteration,
                        "thought": s.thought,
                        "action": s.action,
                        "observation": s.observation,
                    }
                    for s in (steps + [step])
                ],
                "has_final_answer": False,
                "working_set_snapshot": list(_working_set.values()),
                "progress_summary": _progress_summary,
                "current_phase": _current_phase,
            }
            if _ckpt_journal_auto is not None and hasattr(
                _ckpt_journal_auto, "write_react_checkpoint",
            ):
                with contextlib.suppress(Exception):
                    _ckpt_journal_auto.write_react_checkpoint(
                        task_id=react_task_id,
                        iteration_completed=step.iteration,
                        max_iterations=max_iterations,
                        messages_snapshot=_auto_ckpt_payload["messages_snapshot"],
                        steps_snapshot=_auto_ckpt_payload["steps_snapshot"],
                        has_final_answer=False,
                        working_set_snapshot=_auto_ckpt_payload["working_set_snapshot"],
                        progress_summary=_progress_summary,
                        current_phase=_current_phase,
                    )
            # Best-effort distributed mirror — off unless
            # OCTOPUS_CHECKPOINT_MIRROR_URL is set. Same payload as the
            # journal write so downstream consumers see one shape.
            _mirror_checkpoint(react_task_id, _auto_ckpt_payload)

        # ── Step evaluator (optional) ────────────────────────
        # When wired, the evaluator scores the just-completed step.
        # A score below 0.3 triggers a retry hint injected into the
        # conversation so the LLM self-corrects on the next iteration.
        # This implements the "separate evaluator from generator"
        # pattern from Anthropic's harness-design research.
        if step_evaluator is not None:
            try:
                _eval_score = step_evaluator({
                    "iteration": step.iteration,
                    "thought": step.thought,
                    "action": step.action,
                    "observation": step.observation,
                    "progress_summary": _public_progress_summary,
                })
                if isinstance(_eval_score, (int, float)) and _eval_score < 0.3:
                    _retry_hint = (
                        f"[evaluator] The previous step scored {_eval_score:.2f}/1.0 "
                        f"— quality is below threshold. Please reconsider your "
                        f"approach and try a different strategy."
                    )
                    from runtime.platform.models.llm import Message

                    messages.append(Message(
                        role="user",
                        content=_retry_hint,
                    ))
                    yield {
                        "type": "evaluator_retry_hint",
                        "iteration": step.iteration,
                        "score": _eval_score,
                        "hint": _retry_hint,
                    }
            except Exception as _eval_exc:
                _logger.debug("step_evaluator raised: %s", _eval_exc)

        steps.append(step)

        # ── PHASE 6g · housekeeping (msg append / continue / loop tail)
        # Mid-turn plan exit: model called exit_plan_mode and user approved.
        # Switch from "plan only" to "execute" without ending the turn.
        if planning_mode:
            try:
                from runtime.platform.process.session import current_session as _cs_plan
                _session_obj = _cs_plan()
            except (ImportError, AttributeError):  # noqa: BLE001
                _session_obj = None
            if (
                _session_obj is not None
                and _session_obj.metadata is not None
                and _session_obj.metadata.pop("_plan_mode_exit_approved", False)
            ):
                planning_mode = False
                enable_tools = True
                executor = getattr(stack, "executor", None)
                tools_active = executor is not None
                _logger.info(
                    "plan_mode exited mid-turn; continuing execution in same turn",
                )

        if _is_code_mode and step.action and step.action.lower() not in {"none", "n/a", ""}:
            _update_working_set(_working_set, step, _current_phase)
            _current_phase = _detect_phase(step, _current_phase)
            _progress_summary = _build_progress_summary(steps, _working_set, _current_phase)

        _has_real_observation = bool(
            step.observation and step.observation != "N/A"
        )
        _has_response_tool_calls = bool(getattr(resp, "tool_calls", None))
        _length_limit_should_continue = (
            _length_limited
            and not (_has_response_tool_calls or _has_real_observation)
        )
        _checkpoint_has_final = (
            maybe_final is not None and not _length_limit_should_continue
        )
        if react_task_id is not None and _checkpoint_has_final:
            _ckpt_journal = getattr(stack, "journal", None)
            if _ckpt_journal is not None and hasattr(_ckpt_journal, "write_react_checkpoint"):
                try:
                    from runtime.platform.models import ArmId
                    _ckpt_journal.write_react_checkpoint(
                        react_task_id,
                        arm_id=ArmId("react_arm"),
                        iteration_completed=i + 1,
                        max_iterations=max_iterations,
                        messages_snapshot=_serialize_messages_for_checkpoint(messages),
                        steps_snapshot=[
                            {
                                "iteration": s.iteration,
                                "thought": s.thought,
                                "action": s.action,
                                "observation": s.observation,
                            }
                            for s in steps
                        ],
                        has_final_answer=_checkpoint_has_final,
                        final_answer=maybe_final if _checkpoint_has_final else "",
                        working_set_snapshot=list(_working_set.values()),
                        progress_summary=_progress_summary,
                        current_phase=_current_phase,
                    )
                except (OSError, TypeError):
                    _logger.debug("checkpoint write failed", exc_info=True)
        if maybe_final and _length_limit_should_continue:
            final_answer_segments.append(maybe_final)
            maybe_final = None

        if maybe_final:
            if final_answer_segments:
                final_answer = "".join(final_answer_segments + [maybe_final])
                final_answer_segments.clear()
            else:
                final_answer = maybe_final
            # The normal final-answer path has already streamed the model
            # text above. Forced convergence / pause paths synthesize a
            # final answer later via ``router.call`` and need an explicit
            # realtime delta before the generator returns.
            final_answer_emitted = True
            terminated_reason = "final_answer"
            break

        if (
            react_task_id is not None
            and max_iterations >= 15
            and (max_iterations - (i + 1)) <= 3
            and not _pause.is_pause_requested(str(react_task_id))
        ):
            remaining = max_iterations - (i + 1)
            _logger.info(
                "react_loop auto-pause at iter %d · task %s · %d left · "
                "will checkpoint next loop top",
                i + 1, react_task_id, remaining,
            )
            _pause.request_pause(
                task_id=str(react_task_id),
                reason="iteration_near_limit",
                requested_by="system",
                note=(
                    f"自动暂停 · 已跑 {i + 1}/{max_iterations} 轮 · "
                    f"剩余 {remaining} 轮 · 点继续并加预算可接续"
                ),
                thread_id=thread_id or "",
                agent_id=_agent_id_for_pause,
            )

        messages.append(Message(role="assistant", content=text))
        # Length-limit continuation. When the upstream model truncated
        # its response (finish_reason=="length" / "max_tokens" / etc.)
        # the assistant message we just appended is mid-sentence — the
        # model itself doesn't know it stopped early, so on the NEXT
        # iteration it will either repeat work or give up and write a
        # short summary. Inject a user message asking it to continue
        # exactly where it left off so long-form generation (research
        # reports, code files, plans) can finish across multiple
        # iterations without the user seeing a half-finished doc.
        if _length_limit_should_continue:
            messages.append(
                Message(
                    role="user",
                    content=(
                        "Your previous response was cut off by the output "
                        "length limit. Continue exactly where it stopped — "
                        "do NOT repeat earlier text, do NOT restart the "
                        "report, do NOT switch to writing a summary or "
                        "calling todo_write. Resume from the exact "
                        "character you stopped at and finish every "
                        "remaining section."
                    ),
                )
            )
            _logger.info(
                "react_loop iter %d · finish_reason=length, injecting continue prompt",
                i + 1,
            )
        elif step.observation and step.observation != "N/A":
            # TokenJuice: compress the observation before it enters
            # the message stream so the next LLM round sees a leaner
            # version. The full observation is preserved in
            # step.observation for journal / display / guards. Off
            # by default — opt in via OCTOPUS_TOKEN_JUICE=1.
            _obs_for_model = step.observation
            try:
                from runtime.core.cerebrum.token_juicer import (
                    is_enabled as _juice_enabled,
                )
                from runtime.core.cerebrum.token_juicer import (
                    juice as _juice,
                )
                if _juice_enabled():
                    _juiced, _stats = _juice(step.observation)
                    if _stats.passes:
                        _obs_for_model = _juiced
                        _logger.debug(
                            "token_juice iter %d · %d→%d chars (%.1f%% saved) passes=%s",
                            i + 1, _stats.before, _stats.after,
                            (1 - _stats.ratio) * 100,
                            ",".join(_stats.passes),
                        )
            except (ImportError, ValueError, TypeError):
                _logger.debug("token_juice unavailable", exc_info=True)
            messages.append(
                Message(role="user", content=f"Observation: {_obs_for_model}\n\n继续下一轮推理。")
            )

        messages = _compress_context(
            messages, max_tokens=60000, router=router, model=effective_model,
            is_code_mode=_is_code_mode,
        )

        with contextlib.suppress(Exception):
            _pause.update_active_iteration(str(react_task_id), i + 1)

    # ── PHASE 7 · post-loop terminal handling ──────────────────────────
    # (paused / cancelled / forced max-iter convergence)
    if terminated_reason == "paused":
        final_answer = (
            "当前进度已暂停并保存，等待继续。你可以补充信息，或点击继续从 checkpoint 接着执行。"
        )

    if terminated_reason == "cancelled":
        # User pressed Stop. Emit a terminal event so the consumer can
        # finalize the turn promptly, then exit without asking the LLM
        # for one more "final answer" round — that would both waste
        # budget and defeat the whole point of cancellation.
        yield {"type": "react_cancelled", "iteration": i + 1}
        with contextlib.suppress(Exception):
            _pause.unregister_active(str(react_task_id))
        return

    if final_answer is None:
        try:
            messages.append(
                Message(
                    role="user",
                    content=(
                        "已达最大迭代次数。当前是 code 模式: 如果仍有未完成 todo、未验证代码改动、"
                        "或存在权限/登录/信息缺失阻塞, 不要宣称完成; "
                        "请明确请求用户协助并列出被阻塞的 todo。"
                        "只有所有 todo completed 且验证通过, 才给 Final Answer。"
                        if _is_code_mode
                        else "已达最大迭代次数,请基于以上推理直接给出 Final Answer。"
                    ),
                )
            )
            if _is_research_mode and not _is_code_mode:
                messages.append(
                    Message(
                        role="user",
                        content=(
                            "研究报告收敛要求：不要继续输出过程模板或「正在整理」。"
                            "请基于已有搜索、浏览和材料证据，直接输出完整 Final Answer。"
                            "Final Answer 必须是一份可阅读报告，至少包含：执行摘要、关键结论、"
                            "分维度分析、对比/推荐、风险与不确定性、下一步建议、来源说明。"
                        ),
                    )
                )
            if _is_swarm_mode and not _is_code_mode:
                messages.append(
                    Message(
                        role="user",
                        content=(
                            "SWARM convergence requirement: stop generating "
                            "process-only updates. Based on completed todos, "
                            "skill outputs, subagent results, and blackboard "
                            "findings, produce the integrated Final Answer now. "
                            "Include a concise stage summary, final conclusions, "
                            "quality-review notes, and any created file paths. "
                            "If the work is blocked, name the exact blocker and "
                            "the incomplete todo instead of claiming completion."
                        ),
                    )
                )
            resp = router.call(
                ModelRequest(
                    model=effective_model,
                    messages=messages,
                    max_tokens=5000 if (_is_research_mode or _is_swarm_mode) else 400,
                    temperature=0.2,
                )
            )
            text = (resp.text or "").strip()
            final_m = _FINAL_RE.search(text)
            if final_m:
                final_answer = final_m.group(1).strip()
                if _is_code_mode:
                    _guard_message = (
                        _path_verification_policy_guard(
                            steps,
                            final_answer,
                            is_code_mode=True,
                        )
                        or _code_mode_completion_guard(steps, final_answer)
                    )
                    if _guard_message:
                        final_answer = (
                            "我还不能把这个 code 任务标记为完成。\n\n"
                            f"{_guard_message}\n\n"
                            "请点击继续让我接着执行, 或提供必要的权限/登录/信息后我再继续。"
                        )
            else:
                _logger.warning(
                    "react_loop 强制收敛未得 Final Answer · raw head=%r",
                    text[:200],
                )
                _persist_react_trajectory(
                    stack,
                    react_task_id=react_task_id,
                    beak_steps=executed_beak_steps,
                    success=False,
                )
                _pause.unregister_active(str(react_task_id))
                return None
        except (AttributeError, TypeError, ValueError) as exc:
            _logger.warning("react_loop 强制收敛失败 (%s): %s", type(exc).__name__, exc)
            _persist_react_trajectory(
                stack,
                react_task_id=react_task_id,
                beak_steps=executed_beak_steps,
                success=False,
            )
            _pause.unregister_active(str(react_task_id))
            return None

    if final_answer and not final_answer_emitted:
        # ── PHASE 8 · finalization + react_completed yield ─────────────
        yield {
            "type": "text_delta",
            "delta": final_answer,
            "iteration": (steps[-1].iteration + 1) if steps else 1,
        }
        final_answer_emitted = True

    any_step_failed = any(not _beak_step_effective_success(s) for s in executed_beak_steps)
    effective_success = not any_step_failed
    final_success = effective_success and terminated_reason not in {"paused", "cancelled", "error"}
    _persist_react_trajectory(
        stack,
        react_task_id=react_task_id,
        beak_steps=executed_beak_steps,
        success=effective_success,
    )
    try:
        from runtime.safety.experiments.scheduler import (
            get_camouflage_scheduler,
        )
        get_camouflage_scheduler().record_outcome(
            str(react_task_id),
            success=final_success,
        )
    except ImportError:
        _logger.debug("camouflage scheduler not available for recording outcome", exc_info=True)
    _pause.unregister_active(str(react_task_id))
    completion_receipt = _react_completion_receipt(
        final_answer=final_answer,
        terminated_reason=terminated_reason,
        effective_success=effective_success,
        executed_beak_steps=executed_beak_steps,
    )
    yield {
        "type": "react_completed",
        "iteration": steps[-1].iteration if steps else 0,
        "terminated_reason": terminated_reason,
        "has_final_answer": bool(final_answer),
        "success": final_success,
        "completion_receipt": completion_receipt,
    }
    return ReActResult(
        final_answer=final_answer,
        steps=steps,
        terminated_reason=terminated_reason,
        success=effective_success,
        completion_receipt=completion_receipt,
    )


_REACT_SPLITTER: ABSplitter | None = None


def _build_default_splitter() -> ABSplitter:
    from runtime.safety.experiments.variant import ABSplitter, Variant
    return ABSplitter(
        [Variant(name=r.name, payload=r, weight=1.0) for r in _DEFAULT_REACT_RECIPES],
        seed=42,
    )


def _get_splitter() -> ABSplitter:
    global _REACT_SPLITTER
    if _REACT_SPLITTER is None:
        _REACT_SPLITTER = _build_default_splitter()
    return _REACT_SPLITTER


def pick_react_variant(
    *, task_id: str | None = None,
) -> ReActRecipe:
    splitter = _get_splitter()
    v = splitter.next_variant() if task_id is None else splitter.assign_for(task_id)
    return v.payload  # type: ignore[return-value]


def record_react_variant_result(variant_name: str, *, success: bool) -> None:
    splitter = _get_splitter()
    with contextlib.suppress(KeyError):
        splitter.record_outcome(variant_name, success=success)


def get_react_variant_stats() -> list[dict[str, Any]]:
    splitter = _get_splitter()
    out: list[dict[str, Any]] = []
    for name in splitter.names:
        s = splitter.stats[name]
        v = splitter.get(name)
        recipe: ReActRecipe = v.payload
        out.append({
            "name": name,
            "max_iterations": recipe.max_iterations,
            "temperature": recipe.temperature,
            "assignments": s.assignments,
            "successes": s.successes,
            "failures": s.failures,
            "success_rate": round(s.success_rate, 3),
        })
    return out


def _reset_react_variants_for_tests() -> None:
    global _REACT_SPLITTER
    _REACT_SPLITTER = None


def run_react_loop(
    stack: StackProtocol,
    intent: ParsedIntent,
    agent: Agent | None,
    *,
    model: str | None = None,
    max_iterations: int = 30,
    temperature: float = 0.3,
    enable_tools: bool = True,
    resume_task_id: TaskId | None = None,
    thread_id: str | None = None,
    approval_provider: ApprovalProvider | None = None,
) -> ReActResult | None:
    gen = stream_react_loop(
        stack, intent, agent,
        model=model,
        max_iterations=max_iterations,
        temperature=temperature,
        enable_tools=enable_tools,
        resume_task_id=resume_task_id,
        thread_id=thread_id or "",
        approval_provider=approval_provider,
    )
    try:
        while True:
            next(gen)
    except StopIteration as stop:
        return stop.value  # type: ignore[no-any-return]
