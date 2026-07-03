"""C2 regression: failed write/exec tools must not be silently auto-retried.

``stream_react_loop`` re-runs a failed tool's action once. For non-idempotent
tools (write / edit / exec / delete / dangerous) a re-run would double any side
effects the first attempt already had (a partial write, or a shell command that
ran before its result failed to parse), so the loop now gates the retry on
``_retry_safe_affinity``.
"""

from __future__ import annotations

from runtime.core.cerebrum.react_loop import _retry_safe_affinity


def test_idempotent_tools_are_retry_safe() -> None:
    assert _retry_safe_affinity(["read"]) is True
    assert _retry_safe_affinity(["search", "read"]) is True
    assert _retry_safe_affinity([]) is True  # known affinity, no side-effecting tags


def test_side_effecting_tools_are_not_retry_safe() -> None:
    for affinity in (
        ["write"],
        ["edit"],
        ["exec"],
        ["delete"],
        ["dangerous"],
        ["read", "write"],  # any single side-effecting tag is enough
    ):
        assert _retry_safe_affinity(affinity) is False, affinity


def test_unknown_affinity_is_fail_closed() -> None:
    # affinity we could not determine must NOT be auto-retried
    assert _retry_safe_affinity(None) is False
