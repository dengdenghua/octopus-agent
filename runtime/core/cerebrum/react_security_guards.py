"""Security + quality guards (post-step / pre-Final-Answer gates).

Extracted from ``react_guards.py`` (2026-06-06) — paired with the
detectors in ``react_security_detectors.py``. Each guard returns
either ``None`` (let Final Answer through) or a message explaining
why the model must keep working.

╔══════════════════════════════════════════════════════════════════════╗
║ react_security_guards.py · navigation map (~350 lines).              ║
║                                                                      ║
║   §63 dynamic exec (eval / exec / __import__)        ~L36           ║
║   §65 shell injection (subprocess shell=True)         ~L92           ║
║   §66 unsafe deserialization (pickle / yaml.load)     ~L146          ║
║   §67 network call inside loop                        ~L203          ║
║   §69 repeated string literal                         ~L251          ║
║   §70 magic number (time/size unit)                   ~L308          ║
║                                                                      ║
║ Each guard has a paired ``_trajectory_*_hits(steps)`` predicate     ║
║ that walks the recent-step window and aggregates detector output.   ║
╚══════════════════════════════════════════════════════════════════════╝
"""

from __future__ import annotations

from runtime.core.cerebrum.react_parsing import (
    _parse_action,
    _step_introduces_dynamic_exec,
    _step_introduces_magic_number,
    _step_introduces_network_in_loop,
    _step_introduces_repeated_literal,
    _step_introduces_shell_injection,
    _step_introduces_unsafe_deser,
)
from runtime.core.cerebrum.react_types import ReActStep

# ``_final_answer_requests_user_help`` lives in react_guards.py and has
# nuanced tail-inspection logic + extensive marker tables. Import it
# lazily at call time to avoid a circular import (react_guards imports
# this module to wire the guards into its registry).


def _user_help_requested(final_answer: str) -> bool:
    from runtime.core.cerebrum.react_guards import _final_answer_requests_user_help
    return _final_answer_requests_user_help(final_answer)


# ──────────────────────────────────────────────────────────────────
# §63 — eval / exec / __import__ guard
# ──────────────────────────────────────────────────────────────────

_DYNAMIC_EXEC_LOOKBACK = 12


def _trajectory_dynamic_exec_hits(steps: list[ReActStep]) -> dict[str, str]:
    out: dict[str, str] = {}
    window = steps[-_DYNAMIC_EXEC_LOOKBACK:] if steps else []
    for step in window:
        labels = _step_introduces_dynamic_exec(step)
        if not labels:
            continue
        parsed = _parse_action(step.action)
        if parsed is None:
            continue
        _name, args = parsed
        path = args.get("path") or args.get("file") or args.get("file_path")
        if isinstance(path, str):
            out[path] = ", ".join(labels)
    return out


def _dynamic_exec_guard(
    steps: list[ReActStep],
    final_answer: str,
    *,
    is_code_mode: bool,
) -> str | None:
    if not steps:
        return None
    if _user_help_requested(final_answer):
        return None
    hits = _trajectory_dynamic_exec_hits(steps)
    if not hits:
        return None
    items = list(hits.items())
    preview = "; ".join(f"{path} ({label})" for path, label in items[:3])
    if len(items) > 3:
        preview += f"; +{len(items) - 3} more"
    return (
        f"Cannot finish yet: dynamic-execution call(s) added to runtime "
        f"code: {preview}. ``eval`` / ``exec`` / ``__import__`` open "
        "the door to code-injection bugs and make static analysis useless. "
        "Almost any legitimate need has a safer alternative: "
        "``ast.literal_eval`` for parsing literals, an explicit dispatch "
        "dict for plugin loading, ``importlib.import_module`` for "
        "well-known module names. If you genuinely need dynamic exec, "
        "explicitly justify it in the Final Answer and confirm input "
        "is trusted."
    )


# ──────────────────────────────────────────────────────────────────
# §65 — shell-injection guard
# ──────────────────────────────────────────────────────────────────

_SHELL_INJECTION_LOOKBACK = 12


def _trajectory_shell_injection_hits(steps: list[ReActStep]) -> dict[str, str]:
    out: dict[str, str] = {}
    window = steps[-_SHELL_INJECTION_LOOKBACK:] if steps else []
    for step in window:
        labels = _step_introduces_shell_injection(step)
        if not labels:
            continue
        parsed = _parse_action(step.action)
        if parsed is None:
            continue
        _name, args = parsed
        path = args.get("path") or args.get("file") or args.get("file_path")
        if isinstance(path, str):
            out[path] = ", ".join(labels)
    return out


def _shell_injection_guard(
    steps: list[ReActStep],
    final_answer: str,
    *,
    is_code_mode: bool,
) -> str | None:
    if not steps:
        return None
    if _user_help_requested(final_answer):
        return None
    hits = _trajectory_shell_injection_hits(steps)
    if not hits:
        return None
    items = list(hits.items())
    preview = "; ".join(f"{p} ({label})" for p, label in items[:3])
    if len(items) > 3:
        preview += f"; +{len(items) - 3} more"
    return (
        f"Cannot finish yet: shell-injection surface(s) added: {preview}. "
        "``subprocess(..., shell=True)`` / ``os.system`` / ``os.popen`` "
        "evaluate the entire command via the shell, so any non-static "
        "argument is a code-injection risk. Pass an argv LIST instead "
        "(``subprocess.run(['cmd', arg1, arg2])``) — that bypasses the "
        "shell entirely. If you legitimately need shell features (pipes, "
        "globs), justify it in the Final Answer."
    )


# ──────────────────────────────────────────────────────────────────
# §66 — unsafe deserialization guard
# ──────────────────────────────────────────────────────────────────

_UNSAFE_DESER_LOOKBACK = 12


def _trajectory_unsafe_deser_hits(steps: list[ReActStep]) -> dict[str, str]:
    out: dict[str, str] = {}
    window = steps[-_UNSAFE_DESER_LOOKBACK:] if steps else []
    for step in window:
        labels = _step_introduces_unsafe_deser(step)
        if not labels:
            continue
        parsed = _parse_action(step.action)
        if parsed is None:
            continue
        _name, args = parsed
        path = args.get("path") or args.get("file") or args.get("file_path")
        if isinstance(path, str):
            out[path] = ", ".join(labels)
    return out


def _unsafe_deser_guard(
    steps: list[ReActStep],
    final_answer: str,
    *,
    is_code_mode: bool,
) -> str | None:
    if not steps:
        return None
    if _user_help_requested(final_answer):
        return None
    hits = _trajectory_unsafe_deser_hits(steps)
    if not hits:
        return None
    items = list(hits.items())
    preview = "; ".join(f"{p} ({label})" for p, label in items[:3])
    if len(items) > 3:
        preview += f"; +{len(items) - 3} more"
    return (
        f"Cannot finish yet: unsafe deserialization call(s) added: {preview}. "
        "``pickle.loads`` / ``marshal.loads`` / ``yaml.load`` (without "
        "``Loader=SafeLoader``) execute arbitrary code on attacker-"
        "controlled input. Use ``json.loads`` for data exchange, "
        "``yaml.safe_load`` for YAML, or a typed schema validator "
        "(pydantic, msgpack with strict mode) instead. If you must use "
        "pickle (e.g. for trusted ML model weights), explicitly justify "
        "the trust boundary in the Final Answer."
    )


# ──────────────────────────────────────────────────────────────────
# §67 — network-in-loop guard
# ──────────────────────────────────────────────────────────────────

_NETWORK_IN_LOOP_LOOKBACK = 12


def _trajectory_network_in_loop_paths(steps: list[ReActStep]) -> list[str]:
    seen: list[str] = []
    seen_set: set[str] = set()
    window = steps[-_NETWORK_IN_LOOP_LOOKBACK:] if steps else []
    for step in window:
        if not _step_introduces_network_in_loop(step):
            continue
        parsed = _parse_action(step.action)
        if parsed is None:
            continue
        _name, args = parsed
        path = args.get("path") or args.get("file") or args.get("file_path")
        if isinstance(path, str) and path not in seen_set:
            seen.append(path)
            seen_set.add(path)
    return seen


def _network_in_loop_guard(
    steps: list[ReActStep],
    final_answer: str,
    *,
    is_code_mode: bool,
) -> str | None:
    if not is_code_mode or not steps:
        return None
    if _user_help_requested(final_answer):
        return None
    paths = _trajectory_network_in_loop_paths(steps)
    if not paths:
        return None
    preview = "; ".join(paths[:3])
    if len(paths) > 3:
        preview += f"; +{len(paths) - 3} more"
    return (
        f"Cannot finish yet: network call inside a loop added in {preview}. "
        "An O(n) loop that issues a network call per iteration scales "
        "poorly and is rarely the right approach. Consider: (a) batching "
        "the calls (e.g. one bulk endpoint instead of N individual GETs), "
        "(b) async + ``asyncio.gather`` for fan-out, or (c) caching "
        "the result outside the loop if the data is invariant. If a "
        "per-iteration network call is genuinely required (e.g. paginated "
        "API), justify it in the Final Answer."
    )


# ──────────────────────────────────────────────────────────────────
# §69 — duplicate-string-literal guard
# ──────────────────────────────────────────────────────────────────

_REPEATED_LITERAL_LOOKBACK = 12


def _trajectory_repeated_literal_hits(
    steps: list[ReActStep],
) -> dict[str, list[tuple[str, int]]]:
    out: dict[str, list[tuple[str, int]]] = {}
    window = steps[-_REPEATED_LITERAL_LOOKBACK:] if steps else []
    for step in window:
        repeats = _step_introduces_repeated_literal(step)
        if not repeats:
            continue
        parsed = _parse_action(step.action)
        if parsed is None:
            continue
        _name, args = parsed
        path = args.get("path") or args.get("file") or args.get("file_path")
        if isinstance(path, str):
            out[path] = repeats
    return out


def _repeated_literal_guard(
    steps: list[ReActStep],
    final_answer: str,
    *,
    is_code_mode: bool,
) -> str | None:
    if not is_code_mode or not steps:
        return None
    if _user_help_requested(final_answer):
        return None
    hits = _trajectory_repeated_literal_hits(steps)
    if not hits:
        return None
    items = list(hits.items())
    parts: list[str] = []
    for path, repeats in items[:3]:
        repeat_strs = ", ".join(f"{lit!r}({n}x)" for lit, n in repeats[:2])
        parts.append(f"{path}: {repeat_strs}")
    preview = "; ".join(parts)
    if len(items) > 3:
        preview += f"; +{len(items) - 3} more files"
    return (
        f"Cannot finish yet: repeated string literal(s) introduced: "
        f"{preview}. Strings appearing 3+ times in a payload should "
        "usually be a named constant — that way a typo / spelling "
        "change happens in one place and the constant's name documents "
        "intent. If the repetition is intentional (e.g. test fixtures, "
        "user-facing copy that should stay literal), justify it in the "
        "Final Answer."
    )


# ──────────────────────────────────────────────────────────────────
# §70 — magic number guard
# ──────────────────────────────────────────────────────────────────

_MAGIC_NUMBER_LOOKBACK = 12


def _trajectory_magic_number_hits(steps: list[ReActStep]) -> dict[str, list[int]]:
    out: dict[str, list[int]] = {}
    window = steps[-_MAGIC_NUMBER_LOOKBACK:] if steps else []
    for step in window:
        nums = _step_introduces_magic_number(step)
        if not nums:
            continue
        parsed = _parse_action(step.action)
        if parsed is None:
            continue
        _name, args = parsed
        path = args.get("path") or args.get("file") or args.get("file_path")
        if isinstance(path, str):
            out[path] = nums
    return out


def _magic_number_guard(
    steps: list[ReActStep],
    final_answer: str,
    *,
    is_code_mode: bool,
) -> str | None:
    if not is_code_mode or not steps:
        return None
    if _user_help_requested(final_answer):
        return None
    hits = _trajectory_magic_number_hits(steps)
    if not hits:
        return None
    items = list(hits.items())
    parts: list[str] = []
    for path, nums in items[:3]:
        parts.append(f"{path}: {', '.join(str(n) for n in nums[:3])}")
    preview = "; ".join(parts)
    if len(items) > 3:
        preview += f"; +{len(items) - 3} more files"
    return (
        f"Cannot finish yet: magic number(s) introduced: {preview}. "
        "Bare numeric literals like ``86400`` (seconds in a day) or "
        "``1048576`` (1 MiB in bytes) should be named constants — "
        "the name documents intent, prevents typos, and makes the "
        "value reusable. Use ``SECONDS_PER_DAY = 86400`` or "
        "``datetime.timedelta(days=1).total_seconds()`` instead. "
        "If the number is genuinely arbitrary (e.g. a hash table size "
        "you tuned empirically), document the choice in a comment."
    )


__all__ = [
    "_dynamic_exec_guard",
    "_magic_number_guard",
    "_network_in_loop_guard",
    "_repeated_literal_guard",
    "_shell_injection_guard",
    "_trajectory_dynamic_exec_hits",
    "_trajectory_magic_number_hits",
    "_trajectory_network_in_loop_paths",
    "_trajectory_repeated_literal_hits",
    "_trajectory_shell_injection_hits",
    "_trajectory_unsafe_deser_hits",
    "_unsafe_deser_guard",
]
