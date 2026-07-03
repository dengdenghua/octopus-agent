"""Strip model-controllable privilege-escalation kwargs before dispatch.

A handful of skill-handler parameters are *internal privilege overrides*,
not real tool inputs:

* ``allow_sensitive`` — tells :func:`path_guard.check_path` to skip the
  sensitive-file denylist (``~/.ssh``, ``/etc/shadow``, …) *and* the
  user-configured read denylist, even inside the sandbox.
* ``allow_private`` — tells :func:`url_guard.check_url` to skip the SSRF /
  private-IP protection.

``tool_spec_builder`` hides ``allow_sensitive`` from the published tool
schema, but the schema is ``additionalProperties: True`` (skills carry no
formal parameter schema, so the model infers arg names from the
description). That means a model — or, worse, an *indirect prompt
injection* riding in tool output — can still smuggle ``allow_sensitive`` /
``allow_private`` into a tool call's input dict, and the executor passes the
dict straight to ``handler(**args)``. The result is a read of in-workspace
secrets (``.env``) or an SSRF to the internal network, defeating guards
that are otherwise correct.

The model never has a legitimate reason to set these. Trusted internal /
admin / audit callers that genuinely need the override invoke the skill
handlers (or ``check_path`` / ``check_url``) **directly**, never through the
model tool-call path. So every model→handler boundary drops them first.
"""

from __future__ import annotations

from typing import Any

# Internal privilege overrides that must never be honoured when they arrive
# in model-supplied tool input. Keep in sync with the rationale above and
# with ``tool_spec_builder._INTERNAL_PARAMS`` (which only governs schema
# *visibility*, not runtime enforcement).
MODEL_FORBIDDEN_ARGS: frozenset[str] = frozenset(
    {
        "allow_sensitive",
        "allow_private",
    }
)


def strip_model_controlled_overrides(
    args: Any,
) -> tuple[Any, list[str]]:
    """Return ``args`` with any model-forbidden privilege flags removed.

    Returns a ``(cleaned_args, stripped_keys)`` tuple. ``stripped_keys`` is
    a sorted list of the keys that were dropped (empty when nothing was
    stripped), suitable for audit/telemetry. ``args`` is returned unchanged
    (same object) when it is not a dict or carries none of the flags, so the
    common path allocates nothing.
    """
    if not isinstance(args, dict):
        return args, []
    stripped = sorted(k for k in MODEL_FORBIDDEN_ARGS if k in args)
    if not stripped:
        return args, []
    cleaned = {k: v for k, v in args.items() if k not in MODEL_FORBIDDEN_ARGS}
    return cleaned, stripped
