"""Todo introspection + code-write / payload extraction helpers.

Extracted from ``react_parsing.py``. Owns todo introspection
(``_latest_todo_items`` / ``_coerce_todo_action_items``), the code-write
predicates (``_has_code_write`` / ``_is_code_write_step`` /
``_has_verification_requiring_code_write``), and the shared write-step
payload/ path extraction helpers (``_extract_step_path`` /
``_extract_step_payloads``) used by every ``_step_*`` detector.

Depends only on ``react_types`` and the ``_react_parsing_tools`` leaf.
"""

from __future__ import annotations

import json
import os as _os
from typing import Any

from runtime.core.cerebrum._react_parsing_tools import _parse_action
from runtime.core.cerebrum.react_types import ReActStep


def _latest_todo_items(steps: list[ReActStep]) -> list[dict[str, Any]]:
    """Return the most recent todo_write payload from the trajectory.

    Inspects every individual action in ``step.actions`` so that native
    tool-use rounds (which join parallel calls into ``step.action`` with
    ``; ``) are still introspected call-by-call. Falls back to
    ``step.action`` for legacy text-protocol steps.
    """
    for step in reversed(steps):
        actions = step.actions or ([step.action] if step.action else [])
        for action in reversed(actions):
            parsed = _parse_action(action)
            if parsed is None:
                continue
            name, args = parsed
            if name != "todo_write":
                continue
            # The todo_write tool accepts three input aliases (items /
            # todos / tasks — see agent_meta_skills._todo_write).  All
            # three must be checked here, otherwise a model that emits
            # ``todo_write({"tasks": [...]})`` (a valid call that
            # executes successfully) is invisible to the completion
            # guard, which then rejects with "no checklist recorded".
            raw_items = args.get("items") or args.get("todos") or args.get("tasks") or []
            items = _coerce_todo_action_items(raw_items)
            if items:
                return [item for item in items if isinstance(item, dict)]
    return []


def _coerce_todo_action_items(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return _coerce_todo_action_items(json.loads(value))
        except json.JSONDecodeError:
            return []
    if isinstance(value, dict):
        return _coerce_todo_action_items(
            value.get("items") or value.get("todos") or value.get("tasks")
        )
    return []


def _has_code_write(steps: list[ReActStep]) -> bool:
    return any(_is_code_write_step(step) for step in steps)


def _has_verification_requiring_code_write(steps: list[ReActStep]) -> bool:
    """Whether the trajectory changed source-like files that need a verifier.

    The write tools are shared by coding tasks and artifact-producing tasks.
    A research report such as ``output/market-report.md`` is a persistent
    write, but it is not a code change and asking the agent to run lint or
    typecheck after producing it is both misleading and impossible in many
    personal workspaces.  Keep the broad ``_has_code_write`` signal for
    mutation-oriented guards; use this narrower signal only where a code
    verification command is required.
    """
    return any(_is_verification_requiring_code_write_step(step) for step in steps)


# Canonical write-tool set. Kept as a module-level constant so the
# completion guard, the post-write verification guard, and the public
# ``_has_code_write`` helper all stay aligned. Adding a new edit-style
# skill (e.g. ``patch_file_v2``) needs exactly one update here.
_CODE_WRITE_TOOLS: frozenset[str] = frozenset(
    {
        # Legacy text writers
        "write_text_file",
        "append_text_file",
        "edit_text_file",
        # Newer Edit-style skills (octopus optimisation §2.1 / §2.2)
        "edit_file",
        "multi_edit_file",
        # Aliases used by other registries / external integrations
        "edit_code",
        "str_replace",
        "write_file",
        "create_file",
        "apply_patch",
    }
)


def _is_code_write_step(step: ReActStep) -> bool:
    """Whether this step performed a real code-writing action.

    Used by both the final-answer guard and the in-flight "you wrote
    code, now verify it" guard. Centralising the tool-set means
    contributors adding a new edit-style skill only need to register
    it in ``_CODE_WRITE_TOOLS`` above.
    """
    actions = step.actions or ([step.action] if step.action else [])
    for action in actions:
        parsed = _parse_action(action)
        if parsed is not None and parsed[0] in _CODE_WRITE_TOOLS:
            return True
    return False


_NON_CODE_ARTIFACT_SUFFIXES: frozenset[str] = frozenset(
    {
        ".adoc",
        ".markdown",
        ".md",
        ".rst",
        ".txt",
    }
)


def _is_verification_requiring_code_write_step(step: ReActStep) -> bool:
    """Return ``True`` for a write that targets code or has no safe target.

    Unknown write shapes deliberately remain verification-requiring.  The
    only exemption is a clearly named prose artifact, so a missing/invalid
    path cannot accidentally weaken code-mode completion safeguards.
    """
    actions = step.actions or ([step.action] if step.action else [])
    for action in actions:
        parsed = _parse_action(action)
        if parsed is None or parsed[0] not in _CODE_WRITE_TOOLS:
            continue
        _name, args = parsed
        path = args.get("path") or args.get("file") or args.get("file_path")
        if not isinstance(path, str) or not path.strip():
            return True
        suffix = _os.path.splitext(path.strip().lower())[1]
        if suffix not in _NON_CODE_ARTIFACT_SUFFIXES:
            return True
    return False


def _extract_step_path(step: ReActStep) -> str | None:
    """Return the ``path`` / ``file`` / ``file_path`` arg of a write step,
    or ``None`` when the step isn't a write or has no path argument."""
    # Mutation guards share this helper.  Do not let a read-only action that
    # happens to carry the same ``path`` argument masquerade as an edit (for
    # example ``read_file(runtime/protocol/items.py)`` previously tripped the
    # wire-schema-change guard and demanded a contract test).
    if not _is_code_write_step(step):
        return None
    parsed = _parse_action(step.action)
    if parsed is None:
        return None
    _name, args = parsed
    value = args.get("path") or args.get("file") or args.get("file_path")
    return value if isinstance(value, str) else None


def _extract_step_payloads(step: ReActStep) -> tuple[str, str]:
    """Return ``(new_text, old_text)`` for a write step.

    Concatenates ``content`` / ``new_string`` / ``new_str`` (and the
    same fields inside every ``edits`` entry) into ``new_text``, and
    ``old_string`` / ``old_str`` (top-level + per-edit) into ``old_text``.

    Centralises the payload-extraction shape used by every
    ``_step_introduces_*`` / ``_step_replaced_*`` helper. Returns
    ``("", "")`` if the step isn't a write or can't be parsed —
    callers should treat that as "nothing to inspect".
    """
    if not _is_code_write_step(step):
        return ("", "")
    parsed = _parse_action(step.action)
    if parsed is None:
        return ("", "")
    _name, args = parsed
    new_chunks: list[str] = []
    old_chunks: list[str] = []
    for key in ("content", "new_string", "new_str"):
        value = args.get(key)
        if isinstance(value, str):
            new_chunks.append(value)
    for key in ("old_string", "old_str"):
        value = args.get(key)
        if isinstance(value, str):
            old_chunks.append(value)
    edits = args.get("edits")
    if isinstance(edits, list):
        for edit in edits:
            if not isinstance(edit, dict):
                continue
            for key in ("new_string", "new_str", "content"):
                value = edit.get(key)
                if isinstance(value, str):
                    new_chunks.append(value)
            for key in ("old_string", "old_str"):
                value = edit.get(key)
                if isinstance(value, str):
                    old_chunks.append(value)
    return ("\n".join(new_chunks), "\n".join(old_chunks))
