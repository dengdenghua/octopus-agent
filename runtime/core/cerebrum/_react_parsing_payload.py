"""Payload anti-pattern detectors for concurrent / single-flight code.

Extracted from ``react_parsing.py``. These are pure, deterministic
``_payload_has_*`` text heuristics (no ``ReActStep`` dependency) that
flag concurrency / single-flight / path-boundary anti-patterns embedded
in write payloads. The guard layer wraps them with step-shape handlers.

Self-contained: depends only on the standard library.
"""

from __future__ import annotations

import re

_AMBIGUOUS_INFLIGHT_IDENTITY_RE = re.compile(
    r"if\s+(?:self\.)?(?P<map>[A-Za-z_][A-Za-z0-9_]*)\.get\(\s*"
    r"(?P<key>[A-Za-z_][A-Za-z0-9_]*)\s*\)\s+is\s+(?:not\s+)?"
    r"(?P<pending>[A-Za-z_][A-Za-z0-9_]*)\s*:"
)


def _payload_has_inflight_identity_comparison(text: str) -> bool:
    return bool(text and _AMBIGUOUS_INFLIGHT_IDENTITY_RE.search(text))


def _payload_has_ambiguous_inflight_leader_election(text: str) -> bool:
    """Detect re-reading an in-flight map to infer who created its entry.

    Once a shared pending object has been inserted, both its creator and every
    follower read the same object back.  An identity comparison performed
    after leaving the lock therefore cannot elect a leader; all callers can
    take the loader path.  A creator flag captured inside the locked
    ``pending is None`` branch is the auditable form.
    """
    if not text or "pending" not in text.lower() or ".get(" not in text:
        return False
    for match in _AMBIGUOUS_INFLIGHT_IDENTITY_RE.finditer(text):
        map_name = re.escape(match.group("map"))
        key_name = re.escape(match.group("key"))
        pending_name = re.escape(match.group("pending"))
        creates_entry = re.search(
            rf"if\s+{pending_name}\s+is\s+None\s*:"
            rf"[\s\S]{{0,700}}(?:self\.)?{map_name}\[\s*{key_name}\s*\]\s*=\s*"
            rf"{pending_name}\b",
            text,
        )
        explicit_election = re.search(r"\b(?:is_)?leader\s*=", text)
        if creates_entry and not explicit_election:
            return True
    return False


_WAITER_CALL_RE = re.compile(r"\.wait(?:_for)?\s*\([^\n]*\)|\.wait\s*\(\s*\)")
_MAPPING_POP_RE = re.compile(r"\.(?:pop)\(\s*(?P<key>[A-Za-z_][A-Za-z0-9_]*)\s*(?:,|\))")


def _payload_has_destructive_waiter_result_pop(text: str) -> bool:
    """Whether followers destructively consume one shared load result."""
    if not text or ".pop(" not in text or ".wait" not in text:
        return False
    for wait_match in _WAITER_CALL_RE.finditer(text):
        # Inspect only the follower's post-wait return path.  A later leader
        # branch may legitimately remove the in-flight map entry *after* it
        # publishes result/exception on a mutable object; the old unbounded
        # regex crossed that return boundary and misclassified safe cleanup.
        segment = text[wait_match.end() : wait_match.end() + 1200]
        terminal = re.search(r"\b(?:return|raise)\b", segment)
        if terminal is not None:
            segment = segment[: terminal.end()]
        if _MAPPING_POP_RE.search(segment):
            return True
    return False


_STALE_IMMUTABLE_WAITER_FALLBACK_RE = re.compile(
    r"\.wait(?:_for)?\s*\([^\n]*\)"
    r"[\s\S]{0,1600}?"
    r"(?P<map>(?:self\.)?[A-Za-z_][A-Za-z0-9_]*)\.get\(\s*"
    r"(?P<key>[A-Za-z_][A-Za-z0-9_]*)\s*,\s*"
    r"(?P<snapshot>[A-Za-z_][A-Za-z0-9_]*)\s*\)"
)
_DELETED_PENDING_WAITER_READ_RE = re.compile(
    r"\.wait(?:_for)?\s*\([^\n]*\)"
    r"[\s\S]{0,1600}?"
    r"(?P<map>(?:self\.)?[A-Za-z_][A-Za-z0-9_]*)\[\s*"
    r"(?P<key>[A-Za-z_][A-Za-z0-9_]*)\s*\]"
)


def _payload_has_stale_immutable_waiter_snapshot(text: str) -> bool:
    """Detect a waiter falling back to an immutable pre-wait tuple snapshot.

    Replacing ``pending[key]`` with a new tuple and then deleting the entry is
    not visible through the tuple a follower captured before ``wait()``.  A
    post-wait ``map.get(key, pending)`` therefore falls back to stale
    ``(event, None, None)`` and can return ``None`` or hide an exception.
    Mutable pending objects are safe because the captured object itself is
    updated before the event is signalled.
    """
    if not text or ".wait" not in text or "del " not in text:
        return False
    for match in _STALE_IMMUTABLE_WAITER_FALLBACK_RE.finditer(text):
        map_name = re.escape(match.group("map"))
        key_name = re.escape(match.group("key"))
        snapshot_name = re.escape(match.group("snapshot"))
        tuple_snapshot = re.search(
            rf"(?:[A-Za-z_][A-Za-z0-9_]*\s*,\s*){{2,}}[A-Za-z_][A-Za-z0-9_]*"
            rf"\s*=\s*{snapshot_name}\b",
            text,
        )
        tuple_replacement = re.search(
            rf"{map_name}\[\s*{key_name}\s*\]\s*=\s*\(",
            text,
        )
        deletes_entry = re.search(
            rf"del\s+{map_name}\[\s*{key_name}\s*\]",
            text,
        )
        if tuple_snapshot and tuple_replacement and deletes_entry:
            return True
    for match in _DELETED_PENDING_WAITER_READ_RE.finditer(text):
        map_name = re.escape(match.group("map"))
        key_name = re.escape(match.group("key"))
        tuple_replacement = re.search(
            rf"{map_name}\[\s*{key_name}\s*\]\s*=\s*\(",
            text,
        )
        deletes_entry = re.search(
            rf"del\s+{map_name}\[\s*{key_name}\s*\]",
            text,
        )
        if tuple_replacement and deletes_entry:
            return True
    return False


_TERMINAL_PENDING_TUPLE_RE = re.compile(
    r"(?P<map>(?:self\.)?[A-Za-z_][A-Za-z0-9_]*(?:pending|inflight)[A-Za-z0-9_]*)"
    r"\[\s*(?P<key>[A-Za-z_][A-Za-z0-9_]*)\s*\]\s*=\s*\("
    r"(?P<body>[^\n)]{1,500})\)",
    re.IGNORECASE,
)


def _payload_has_terminal_pending_entry_leak(text: str) -> bool:
    """Detect a completed in-flight tuple that is never removed.

    Keeping a terminal ``pending[key] = (event, value, error)`` entry makes
    every later caller look like a follower.  In a TTL cache that means an
    expired key can keep returning the old completed flight forever; a failed
    flight can likewise poison every retry.  Waiters may retain a mutable
    per-flight object, but the key must leave the *in-flight map* once the
    leader has published terminal state.
    """
    if not text or ".wait" not in text or ".set(" not in text or "loader(" not in text:
        return False
    assignments = list(_TERMINAL_PENDING_TUPLE_RE.finditer(text))
    if len(assignments) < 2:
        return False
    by_slot: dict[tuple[str, str], list[re.Match[str]]] = {}
    for match in assignments:
        slot = (match.group("map"), match.group("key"))
        by_slot.setdefault(slot, []).append(match)
    for (map_name, key_name), slot_assignments in by_slot.items():
        bodies = [match.group("body") for match in slot_assignments]
        has_initial_state = any(body.count("None") >= 2 for body in bodies)
        has_terminal_state = any(body.count("None") < 2 for body in bodies)
        if not (has_initial_state and has_terminal_state):
            continue
        escaped_map = re.escape(map_name)
        escaped_key = re.escape(key_name)
        removes_slot = re.search(
            rf"(?:del\s+{escaped_map}\[\s*{escaped_key}\s*\]"
            rf"|{escaped_map}\.pop\(\s*{escaped_key}\b)",
            text,
        )
        if not removes_slot:
            return True
    return False


def _payload_has_loader_barrier_deadlock(text: str) -> bool:
    """Detect a test loader waiting alone on a ``threading.Barrier``.

    In a single-flight test only the elected leader enters ``loader``;
    followers wait on the flight event.  A barrier placed inside that loader
    can therefore never collect the follower threads and deadlocks the test.
    Synchronising workers *before* ``get_or_load`` is the valid pattern.
    """
    if not text or "Barrier(" not in text or "get_or_load" not in text:
        return False
    lines = text.splitlines()
    for index, line in enumerate(lines):
        definition = re.match(
            r"^(?P<indent>[ \t]+)def\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*\(",
            line,
            re.IGNORECASE,
        )
        if definition is None or "loader" not in definition.group("name").lower():
            continue
        indent_width = len(definition.group("indent").expandtabs(4))
        body_lines: list[str] = []
        for candidate in lines[index + 1 :]:
            if not candidate.strip():
                body_lines.append(candidate)
                continue
            candidate_indent = len(candidate) - len(candidate.lstrip(" \t"))
            if candidate_indent <= indent_width:
                break
            body_lines.append(candidate)
        body = "\n".join(body_lines)
        for wait in re.finditer(
            r"(?P<barrier>[A-Za-z_][A-Za-z0-9_]*)\.wait\s*\(",
            body,
        ):
            barrier = wait.group("barrier")
            assignment = re.search(
                rf"\b{re.escape(barrier)}\s*=\s*(?:threading\.)?Barrier\s*\("
                r"\s*(?P<parties>\d+)",
                text,
            )
            if assignment is None:
                continue
            total_waits = len(re.findall(rf"\b{re.escape(barrier)}\.wait\s*\(", text))
            loader_name = re.escape(definition.group("name"))
            passed_to_cache = re.search(
                rf"get_or_load\s*\([^\n]{{0,300}}\b{loader_name}\b",
                text,
            )
            parties = int(assignment.group("parties"))
            # The only bounded loader-barrier shape we tolerate is an
            # explicit two-party rendezvous between the elected loader and
            # one controller thread.  With N>2, extra static wait sites do
            # not prove N runtime participants (v31 had Barrier(5) but only
            # loader + main thread could ever reach it).  Worker threads in a
            # single-flight test wait on the flight event, not in loader.
            if passed_to_cache and not (parties == 2 and total_waits >= 2):
                return True
    return False


def _payload_has_wait_while_lock_held(text: str) -> bool:
    """Detect blocking on an event/future while retaining a map mutex."""
    if not text or ".wait(" not in text or "lock" not in text.lower():
        return False
    lines = text.splitlines()
    for index, line in enumerate(lines):
        context = re.match(
            r"^(?P<indent>[ \t]*)with\s+(?P<lock>(?:self\.)?[A-Za-z_][A-Za-z0-9_]*lock[A-Za-z0-9_]*)\s*:",
            line,
            re.IGNORECASE,
        )
        if context is None:
            continue
        indent_width = len(context.group("indent").expandtabs(4))
        body_lines: list[str] = []
        for candidate in lines[index + 1 :]:
            if not candidate.strip():
                body_lines.append(candidate)
                continue
            candidate_indent = len(candidate) - len(candidate.lstrip(" \t"))
            if candidate_indent <= indent_width:
                break
            body_lines.append(candidate)
        body = "\n".join(body_lines)
        if re.search(r"\b[A-Za-z_][A-Za-z0-9_.]*\.wait\s*\(", body):
            return True
    for acquire in re.finditer(
        r"(?P<lock>(?:self\.)?[A-Za-z_][A-Za-z0-9_]*lock[A-Za-z0-9_]*)"
        r"\.acquire\s*\(",
        text,
        re.IGNORECASE,
    ):
        lock_name = re.escape(acquire.group("lock"))
        release = re.search(rf"{lock_name}\.release\s*\(", text[acquire.end() :])
        segment_end = acquire.end() + (release.start() if release is not None else 1600)
        segment = text[acquire.end() : segment_end]
        if re.search(r"\b[A-Za-z_][A-Za-z0-9_.]*\.wait\s*\(", segment):
            return True
    return False


_SINGLE_PASS_URL_DECODE_RE = re.compile(r"\bunquote(?:_plus)?\s*\(")
_PATH_BOUNDARY_PAYLOAD_MARKERS = (
    "pathboundaryerror",
    "relative_to(",
    "commonpath(",
    "is_relative_to(",
    "symlink",
    "path traversal",
)


def _payload_has_single_pass_url_decode(text: str) -> bool:
    """Detect one-shot URL decoding in path-boundary validation.

    A single ``unquote`` turns a double-encoded traversal into a still-
    encoded path, so a subsequent canonical containment check sees an
    innocuous filename.  Repeated decoding in a loop (or two explicit nested
    decodes) is not flagged.  Callers must separately establish that the
    payload belongs to path-boundary code before treating this as a defect.
    """

    if not text:
        return False
    calls = list(_SINGLE_PASS_URL_DECODE_RE.finditer(text))
    if len(calls) != 1:
        return False
    call_line_start = text.rfind("\n", 0, calls[0].start()) + 1
    call_line = text[call_line_start : text.find("\n", calls[0].end())]
    call_indent = len(call_line) - len(call_line.lstrip(" \t"))
    prefix_lines = text[:call_line_start].splitlines()
    for line in reversed(prefix_lines):
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" \t"))
        if indent >= call_indent:
            continue
        stripped = line.strip()
        if re.match(r"(?:while\b|for\b).*:\s*(?:#.*)?$", stripped):
            return False
        # The nearest enclosing block is not a loop; outer blocks cannot
        # make the call repeat without the call being nested under them.
        break
    return True


def _payload_looks_like_path_boundary(text: str) -> bool:
    lowered = str(text or "").lower()
    return "unquote" in lowered and any(
        marker in lowered for marker in _PATH_BOUNDARY_PAYLOAD_MARKERS
    )
