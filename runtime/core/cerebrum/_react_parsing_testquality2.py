"""Production-hygiene detectors for ReAct write steps.

Extracted from ``react_parsing.py``. Owns the print-in-production-path,
hardcoded-path, async-without-await, log-swallow, and long-function
detectors — each exposing a ``_detect_*_in_payload`` predicate plus a
``_step_introduces_*`` adapter.

Depends on ``react_types`` and the ``_react_parsing_steps`` /
``_react_parsing_verification`` helpers (``_extract_step_path``,
``_extract_step_payloads``, ``_is_test_path``).
"""

from __future__ import annotations

import re

from runtime.core.cerebrum._react_parsing_steps import (
    _extract_step_path,
    _extract_step_payloads,
)
from runtime.core.cerebrum._react_parsing_verification import _is_test_path
from runtime.core.cerebrum.react_types import ReActStep

# ──────────────────────────────────────────────────────────────────
# §44 — print() in production-path detection
# ──────────────────────────────────────────────────────────────────
# octopus-agent uses ``logging`` everywhere (79 modules, 68 _logger
# calls; zero existing prints in runtime/core or runtime/safety).
# Adding a bare ``print(...)`` to non-test runtime code is a debug
# leftover. We only flag NEW prints — existing ones (e.g. CLI entry
# points that intentionally use stdout) being moved aren't flagged.
#
# Conservative: ``sys.stdout.write`` and ``rich.print`` aren't caught
# here. They're rarer and have legitimate UX uses.

_PRINT_CALL_RE = re.compile(r"(?:^|[^A-Za-z_.])print\s*\(")

# Files where print() is legitimate — CLI scripts, repl helpers, and
# explicit stdout-emitting entry points. Anything in scripts/ or
# tools/ is exempt because those are user-facing programs.
_PRINT_EXEMPT_PATH_PATTERNS: tuple[str, ...] = (
    "/scripts/",
    "/tools/",
    "/cli/",
    "/repl/",
    "/runtime/cli.py",
    "/runtime/__main__.py",
)


def _payload_has_print_call(text: str) -> bool:
    if not text:
        return False
    return bool(_PRINT_CALL_RE.search(text))


def _path_is_print_exempt(path: str) -> bool:
    norm = "/" + path.replace("\\", "/").lstrip("/").lower()
    return any(pattern in norm for pattern in _PRINT_EXEMPT_PATH_PATTERNS)


def _step_introduces_print(step: ReActStep) -> bool:
    """Whether this write step adds a NEW ``print(...)`` call to a
    non-test, non-CLI Python file."""
    path = _extract_step_path(step)
    if not path or not path.lower().endswith((".py", ".pyi")):
        return False
    if _is_test_path(path):
        return False
    if _path_is_print_exempt(path):
        return False
    new_text, old_text = _extract_step_payloads(step)
    return _payload_has_print_call(new_text) and not _payload_has_print_call(old_text)


# ──────────────────────────────────────────────────────────────────
# §45 — hardcoded personal/machine path detection
# ──────────────────────────────────────────────────────────────────
# Catch the failure mode where the agent hardcodes:
#   * ``C:\Users\<name>\...`` (Windows user dir)
#   * ``/Users/<name>/...`` (macOS user dir)
#   * ``/home/<name>/...`` (Linux user dir, name != ``runner``/``user``)
#   * ``/tmp/<specific>`` baked into runtime code (not configurable)
#
# We exempt obvious non-secret references (``/tmp/`` at module-level
# in scripts/) and accept ``getenv`` / ``os.path.expanduser`` rewrites
# silently (the diff sees them as "new" but they're correct).

_HARDCODED_PATH_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "Windows user dir",
        re.compile(
            r"[\"']?[A-Za-z]:(?:\\\\|\\|/)+Users(?:\\\\|\\|/)+"
            r"(?!Public(?:\\\\|\\|/))[A-Za-z0-9_.\-]+(?:\\\\|\\|/)+",
        ),
    ),
    (
        "macOS user dir",
        re.compile(r"[\"']/Users/(?!Shared/)[A-Za-z0-9_.\-]+/"),
    ),
    (
        "Linux user home",
        re.compile(r"[\"']/home/(?!runner/|user/|root/|ubuntu/)[A-Za-z0-9_.\-]+/"),
    ),
)


def _detect_hardcoded_paths_in_payload(text: str) -> list[str]:
    if not text:
        return []
    hits: list[str] = []
    for label, pattern in _HARDCODED_PATH_PATTERNS:
        if pattern.search(text):
            hits.append(label)
    return hits


def _step_introduces_hardcoded_path(step: ReActStep) -> list[str]:
    """Labels of any new hardcoded personal/machine paths introduced.

    Skips test paths (test fixtures legitimately reference local dirs)
    and non-text-content code files. Diffs new vs old payload.
    """
    path = _extract_step_path(step)
    if not path:
        return []
    if _is_test_path(path):
        return []
    norm = path.lower()
    if not norm.endswith(
        (".py", ".pyi", ".ts", ".tsx", ".js", ".jsx", ".yaml", ".yml", ".toml", ".json", ".env")
    ):
        return []
    new_text, old_text = _extract_step_payloads(step)
    new_hits = set(_detect_hardcoded_paths_in_payload(new_text))
    old_hits = set(_detect_hardcoded_paths_in_payload(old_text))
    return sorted(new_hits - old_hits)


# ──────────────────────────────────────────────────────────────────
# §57 — async without await detection
# ──────────────────────────────────────────────────────────────────
# Catch the failure mode where a function is defined with ``async def``
# but its body doesn't await anything, doesn't yield, and doesn't use
# async-with / async-for. Such a function returns a coroutine that
# the caller probably doesn't await — meaning the body never runs.
# This is one of the most common Python concurrency bugs.
#
# Skip rules:
#   * test paths (test fixtures legitimately have empty async stubs)
#   * non-Python files
#   * abstract methods and protocols (decorated with @abstractmethod
#     or whose body is just ``...``) — those are intentionally empty.

_ASYNC_DEF_BLOCK_RE = re.compile(
    r"(?:^|\n)(?P<indent>[ \t]*)async\s+def\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*"
    r"\([^)]*\)\s*(?:->\s*[^:\n]+)?\s*:"
    r"(?P<body>(?:\n(?P=indent)[ \t]+[^\n]*|\n\s*$)*)",
)
_AWAIT_OR_YIELD_RE = re.compile(
    r"\b(?:await\b|yield\b)|\basync\s+(?:for|with)\b",
)
_ABSTRACT_DECORATOR_RE = re.compile(
    r"@(?:abc\.)?abstractmethod\b|@(?:typing\.)?overload\b",
)


def _async_body_uses_await(body: str) -> bool:
    """True iff the body contains await / yield / async-for / async-with.

    Bare ``...`` / ``pass`` bodies and abstract stubs return False —
    callers should still skip those via the surrounding heuristic
    (the §57 detector itself ignores ``...`` / ``pass``-only bodies).
    """
    if not body:
        return False
    return bool(_AWAIT_OR_YIELD_RE.search(body))


def _is_abstract_or_stub_body(body: str) -> bool:
    """Whether the body is a bare ``...`` / ``pass`` / docstring-only stub."""
    stripped_lines: list[str] = []
    in_docstring = False
    docstring_quote: str | None = None
    for raw in (body or "").splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        if in_docstring:
            if docstring_quote and docstring_quote in raw:
                in_docstring = False
            continue
        if stripped.startswith(('"""', "'''")):
            opener = '"""' if stripped.startswith('"""') else "'''"
            if opener in stripped[3:]:
                continue
            in_docstring = True
            docstring_quote = opener
            continue
        if stripped.startswith("#"):
            continue
        stripped_lines.append(stripped)
    if not stripped_lines:
        return True
    return all(
        line in {"pass", "...", "raise NotImplementedError", "raise NotImplementedError()"}
        for line in stripped_lines
    )


def _detect_async_without_await_in_payload(text: str) -> list[str]:
    """Return list of async function names whose body lacks await/yield."""
    if not text:
        return []
    out: list[str] = []
    for match in _ASYNC_DEF_BLOCK_RE.finditer(text):
        name = match.group("name")
        body = match.group("body") or ""
        if _is_abstract_or_stub_body(body):
            continue
        # Look upwards for an @abstractmethod decorator on the
        # immediately preceding lines (within 3 lines).
        head = text[max(0, match.start() - 200) : match.start()]
        recent_decorators = head.rsplit("\n", 4)[-3:]
        if any(_ABSTRACT_DECORATOR_RE.search(line) for line in recent_decorators):
            continue
        if not _async_body_uses_await(body):
            out.append(name)
    return out


def _step_introduces_async_without_await(step: ReActStep) -> list[str]:
    """List of new async functions with non-trivial bodies that never
    await/yield. Only fires for non-test Python paths."""
    path = _extract_step_path(step)
    if not path or not path.lower().endswith((".py", ".pyi")):
        return []
    if _is_test_path(path):
        return []
    new_text, old_text = _extract_step_payloads(step)
    new_hits = set(_detect_async_without_await_in_payload(new_text))
    old_hits = set(_detect_async_without_await_in_payload(old_text))
    return sorted(new_hits - old_hits)


# ──────────────────────────────────────────────────────────────────
# §59 — exception-swallow-via-log detection
# ──────────────────────────────────────────────────────────────────
# Catch the failure mode where the model "fixes" an exception by
# logging it and then either returning or continuing — silently
# discarding the failure. This is the LESS obvious sibling of §30:
# §30 catches ``except: pass``; §59 catches ``except: log.error(...)``
# without raising. To the next reader the log call looks like proper
# error handling — but the call STILL swallows the error.
#
# Heuristic: after an ``except`` header (any type), the body matches
# ``log<something>(...)`` (warning/error/exception/info) AND nothing
# in the body re-raises (``raise``, ``raise X``, ``return``-with-error,
# or ``raise from``). We don't try to be smart about "logged then
# raised" — those use ``raise`` and we accept them.

_EXCEPT_HEAD_ANY_RE = re.compile(
    r"(?:^|\n)(?P<indent>[ \t]*)except\b[^\n]*:[ \t]*\n",
)
_LOG_CALL_RE = re.compile(
    r"\b(?:log(?:ger)?|_logger|logging)\s*\.\s*"
    r"(?:debug|info|warn|warning|error|exception|critical|fatal)\s*\(",
)
_RERAISE_RE = re.compile(r"\braise\b")


def _payload_has_log_swallow(text: str) -> bool:
    """Detect ``except SomeError: log.error(...)`` without a re-raise."""
    if not text:
        return False
    for match in _EXCEPT_HEAD_ANY_RE.finditer(text):
        indent = match.group("indent")
        body_indent_marker = indent + " "  # body must be more indented
        # Read body lines until we hit a line at the same indent or less.
        rest = text[match.end() :]
        body_lines: list[str] = []
        for raw in rest.splitlines():
            stripped = raw.rstrip()
            if not stripped.strip():
                body_lines.append(raw)
                continue
            if not raw.startswith(body_indent_marker):
                break
            body_lines.append(raw)
        body = "\n".join(body_lines)
        if not _LOG_CALL_RE.search(body):
            continue
        if _RERAISE_RE.search(body):
            continue
        return True
    return False


def _step_introduces_log_swallow(step: ReActStep) -> bool:
    """Whether this write step adds a NEW log-and-swallow pattern."""
    path = _extract_step_path(step)
    if not path or not path.lower().endswith((".py", ".pyi")):
        return False
    if _is_test_path(path):
        return False
    new_text, old_text = _extract_step_payloads(step)
    return _payload_has_log_swallow(new_text) and not _payload_has_log_swallow(old_text)


# ──────────────────────────────────────────────────────────────────
# §61 — long-function detection
# ──────────────────────────────────────────────────────────────────
# Catch the failure mode where the model writes a single function
# longer than _LONG_FUNCTION_THRESHOLD lines. Long functions are
# harder to test, harder to read, and tend to bundle multiple
# responsibilities. We don't flag refactors that move existing long
# code — only NEW long bodies introduced by this trajectory.
#
# We're conservative: count only the function's own body lines (not
# nested defs), exclude blank lines and comments, and only fire when
# the new payload contains a fresh def whose body exceeds the
# threshold AND that exact name doesn't appear in the old payload.

_LONG_FUNCTION_THRESHOLD = 150

_FUNCTION_BLOCK_RE = re.compile(
    r"(?:^|\n)(?P<indent>[ \t]*)(?:async\s+)?def\s+"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*\([^)]*\)\s*"
    r"(?:->\s*[^:\n]+)?\s*:"
    r"(?P<body>(?:\n(?P=indent)[ \t]+[^\n]*|\n\s*$)*)",
)


def _count_function_body_lines(body: str) -> int:
    """Substantive (non-blank, non-comment, non-docstring) body lines."""
    if not body:
        return 0
    count = 0
    in_docstring = False
    docstring_quote: str | None = None
    for raw in body.splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        if in_docstring:
            if docstring_quote and docstring_quote in raw:
                in_docstring = False
            continue
        if stripped.startswith(('"""', "'''")):
            opener = '"""' if stripped.startswith('"""') else "'''"
            after = stripped[3:]
            if opener in after:
                continue
            in_docstring = True
            docstring_quote = opener
            continue
        if stripped.startswith("#"):
            continue
        count += 1
    return count


def _detect_long_functions_in_payload(text: str) -> list[tuple[str, int]]:
    """Return ``[(name, body_line_count)]`` for functions whose body
    exceeds ``_LONG_FUNCTION_THRESHOLD`` lines."""
    if not text:
        return []
    out: list[tuple[str, int]] = []
    for match in _FUNCTION_BLOCK_RE.finditer(text):
        body = match.group("body") or ""
        lines = _count_function_body_lines(body)
        if lines > _LONG_FUNCTION_THRESHOLD:
            out.append((match.group("name"), lines))
    return out


def _step_introduces_long_function(step: ReActStep) -> list[tuple[str, int]]:
    """List of ``(name, line_count)`` for new long functions added.

    Skips test paths (long parametrized fixtures) and non-Python files.
    Diffs new vs old payload by function NAME — moving an existing
    long function around isn't flagged.
    """
    path = _extract_step_path(step)
    if not path or not path.lower().endswith((".py", ".pyi")):
        return []
    if _is_test_path(path):
        return []
    new_text, old_text = _extract_step_payloads(step)
    new_long = _detect_long_functions_in_payload(new_text)
    old_long_names = {name for name, _lines in _detect_long_functions_in_payload(old_text)}
    return [(name, lines) for name, lines in new_long if name not in old_long_names]
