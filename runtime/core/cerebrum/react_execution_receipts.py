"""Server-owned provenance for ReAct execution receipts."""

from __future__ import annotations

from typing import Any


def _execution_receipt_trust(beak_step: Any) -> tuple[bool, str]:
    """Read server-owned provenance from a completed ToolExecutor Step.

    Missing/legacy/failed dispatches fail closed. The executor computes these
    fields from the actual captured handler, so this layer never performs a
    second registry lookup or trusts model/plugin-controlled metadata.
    """

    result = getattr(beak_step, "result", None)
    if result is None or getattr(result, "trusted_execution", False) is not True:
        return False, str(getattr(result, "execution_source", "") or "untrusted")
    return True, str(getattr(result, "execution_source", "") or "canonical_builtin")


__all__ = ["_execution_receipt_trust"]
