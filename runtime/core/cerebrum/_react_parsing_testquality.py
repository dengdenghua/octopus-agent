"""Test-correctness detectors for ReAct write steps.

Extracted from ``react_parsing.py``. Owns the weak-test / no-assertion /
mock-only / generic-name / deleted-test / undocumented-skip detectors —
each exposing a ``_detect_*_in_payload`` predicate plus a
``_step_introduces_*`` adapter.

Depends on ``react_types``, the ``_react_parsing_tools`` leaf, and the
``_react_parsing_steps`` / ``_react_parsing_verification`` helpers
(``_is_test_path``).
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
# §42 — weak-test-assertion detection
# ──────────────────────────────────────────────────────────────────
# Catch the failure mode where the model satisfies the §20 test-coverage
# guard by writing a test that doesn't actually test anything:
#   * ``assert True`` / ``assert 1`` / ``assert x is not None``
#     (where x is the function under test, returning anything)
#   * test body is just ``pass``
#   * test body is just a single ``assert <one_var>`` with no comparison
#
# Only fires for files that are themselves test files AND were ADDED
# (not modified) in this trajectory — we don't second-guess pre-existing
# weak tests, and we don't try to grade quality, only catch obvious
# nothing-burgers.

_TEST_FUNC_RE = re.compile(
    r"(?:^|\n)def\s+(?P<name>test_[A-Za-z0-9_]+)\s*\([^)]*\)\s*(?:->\s*[^:\n]+)?\s*:"
    r"(?P<body>(?:\n[ \t]+[^\n]*)+)",
)

_WEAK_BODY_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("body is only `pass`", re.compile(r"^\s*pass\s*$")),
    ("body is only `...`", re.compile(r"^\s*\.\.\.\s*$")),
    ("assert True / assert 1", re.compile(r"^\s*assert\s+(?:True|1)\s*(?:#.*)?$")),
    (
        "assert <var> is not None (no comparison)",
        re.compile(r"^\s*assert\s+[A-Za-z_][A-Za-z0-9_.]*\s+is\s+not\s+None\s*(?:#.*)?$"),
    ),
    (
        "assert <var> (truthiness only)",
        re.compile(r"^\s*assert\s+[A-Za-z_][A-Za-z0-9_.]*\s*(?:#.*)?$"),
    ),
)


def _classify_test_body(body: str) -> str | None:
    """Return a label if ``body`` looks like a no-op test, else None.

    ``body`` is the indented block following a ``def test_x():`` header.
    We strip blank/docstring lines and check whether ALL remaining lines
    match a single weak pattern. Multi-line bodies with at least one
    non-trivial assertion are accepted.
    """
    if not body:
        return None
    # Strip leading docstring (single or triple).
    stripped_lines: list[str] = []
    in_docstring = False
    docstring_quote: str | None = None
    for raw in body.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        if in_docstring:
            if docstring_quote and docstring_quote in line:
                in_docstring = False
            continue
        if line.lstrip().startswith(('"""', "'''")):
            opener = '"""' if '"""' in line.lstrip()[:3] else "'''"
            after = line.lstrip()[3:]
            if opener in after:
                # Single-line docstring.
                continue
            in_docstring = True
            docstring_quote = opener
            continue
        if line.lstrip().startswith("#"):
            continue
        stripped_lines.append(line)
    if not stripped_lines:
        return "body is empty"
    if len(stripped_lines) > 1:
        return None  # Multi-line bodies likely have real logic.
    only_line = stripped_lines[0]
    for label, pattern in _WEAK_BODY_PATTERNS:
        if pattern.match(only_line):
            return label
    return None


def _detect_weak_tests_in_payload(text: str) -> list[tuple[str, str]]:
    """Return ``[(test_name, weakness_label)]`` for every weak test_*
    function defined in ``text``."""
    if not text:
        return []
    out: list[tuple[str, str]] = []
    for match in _TEST_FUNC_RE.finditer(text):
        name = match.group("name")
        body = match.group("body") or ""
        label = _classify_test_body(body)
        if label is not None:
            out.append((name, label))
    return out


def _step_introduces_weak_test(step: ReActStep) -> list[tuple[str, str]]:
    """List of ``(test_name, weakness)`` added by this write step.

    Diffs new payload vs old payload so existing weak tests aren't
    repeatedly flagged. Only fires for test paths.
    """
    path = _extract_step_path(step)
    if not path or not _is_test_path(path):
        return []
    if not path.lower().endswith((".py", ".pyi")):
        return []
    new_text, old_text = _extract_step_payloads(step)
    new_weak = set(_detect_weak_tests_in_payload(new_text))
    old_weak = set(_detect_weak_tests_in_payload(old_text))
    return sorted(new_weak - old_weak)


# ──────────────────────────────────────────────────────────────────
# §47 — mock-only test detection
# ──────────────────────────────────────────────────────────────────
# Catch the failure mode where §20 + §42 are both satisfied because
# the new test exists and isn't ``assert True`` — but the assertion
# is purely ``mock.called`` / ``mock.call_count`` with no arg
# verification. A test that proves "the function was called" without
# checking WHAT it was called with proves nothing useful.
#
# Conservative: we only fire when EVERY new test in a file's payload
# uses mock-only assertions and NONE of them have ``assert_called_with``
# / ``call_args`` / ``mock_calls`` introspection. If the file mixes
# proper mock usage with one or two truthiness checks, we let it pass.

_MOCK_ONLY_ASSERTION_RE = re.compile(
    r"^\s*assert\s+[A-Za-z_][A-Za-z0-9_.]*"
    r"\.(?:called|call_count\s*(?:==|>=|>|<=|<|!=)\s*\d+)\s*$",
)
_MOCK_PROPER_INTROSPECTION_RE = re.compile(
    r"\.(?:assert_called_with|assert_called_once_with|assert_any_call|"
    r"assert_has_calls|call_args|call_args_list|mock_calls)\b",
)


def _classify_mock_only_test_body(body: str) -> bool:
    """True when the body's only assertions are mock truthiness checks."""
    if not body:
        return False
    has_mock_only = False
    for raw in body.splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith(('"""', "'''")):
            continue
        if _MOCK_PROPER_INTROSPECTION_RE.search(stripped):
            return False  # Has proper introspection — not mock-only.
        if _MOCK_ONLY_ASSERTION_RE.match(line):
            has_mock_only = True
            continue
        if stripped.startswith("assert "):
            # Some other assertion — could be real.
            return False
    return has_mock_only


def _detect_mock_only_tests_in_payload(text: str) -> list[str]:
    """Return list of test_* function names whose body only asserts
    mock truthiness without checking call arguments."""
    if not text:
        return []
    out: list[str] = []
    for match in _TEST_FUNC_RE.finditer(text):
        body = match.group("body") or ""
        if _classify_mock_only_test_body(body):
            out.append(match.group("name"))
    return out


def _step_introduces_mock_only_test(step: ReActStep) -> list[str]:
    """List of new test functions that are mock-truthiness-only."""
    path = _extract_step_path(step)
    if not path or not _is_test_path(path):
        return []
    if not path.lower().endswith((".py", ".pyi")):
        return []
    new_text, old_text = _extract_step_payloads(step)
    new_hits = set(_detect_mock_only_tests_in_payload(new_text))
    old_hits = set(_detect_mock_only_tests_in_payload(old_text))
    return sorted(new_hits - old_hits)


# ──────────────────────────────────────────────────────────────────
# §48 — pytest.skip without explicit reason detection
# ──────────────────────────────────────────────────────────────────
# Catch the failure mode where the model "fixes" a failing test by
# slapping ``@pytest.mark.skip`` or ``pytest.skip()`` on it. A skip
# with a real reason ("requires GPU", "slow integration test") is
# fine. A skip with no reason or a generic placeholder ("TODO",
# "skip", "fixme") is hiding a bug.

_PYTEST_SKIP_HEAD_RE = re.compile(
    r"@pytest\.mark\.skip\s*(?:\(\s*(?P<args>[^)]*)\))?|"
    r"\bpytest\.skip\s*\(\s*(?P<call>[^)]*)\)",
)
_PLACEHOLDER_REASONS: tuple[str, ...] = (
    "todo",
    "tbd",
    "fixme",
    "skip",
    "broken",
    "fix later",
    "wip",
    "temp",
    "temporary",
    "disabled",
)


def _is_meaningful_skip_reason(args_text: str) -> bool:
    """Whether the skip args contain a string reason longer than a
    placeholder. ``args_text`` is the literal contents between parens.
    Empty args / just whitespace / placeholder string returns False.
    """
    if not args_text or not args_text.strip():
        return False
    # Look for a quoted string. If none, no reason was given.
    string_match = re.search(r'(["\'])([^"\']*)\1', args_text)
    if not string_match:
        # Could be a name=value form like ``reason="..."`` → also matches.
        return False
    reason = string_match.group(2).strip().lower()
    if len(reason) < 8:
        return False
    return not any(reason.startswith(p) or reason == p for p in _PLACEHOLDER_REASONS)


def _payload_has_undocumented_skip(text: str) -> bool:
    if not text:
        return False
    for match in _PYTEST_SKIP_HEAD_RE.finditer(text):
        args_text = match.group("args") or match.group("call") or ""
        if not _is_meaningful_skip_reason(args_text):
            return True
    return False


def _step_introduces_undocumented_skip(step: ReActStep) -> bool:
    """Whether this write step adds a NEW pytest skip without a
    meaningful reason. Only fires for test paths.
    """
    path = _extract_step_path(step)
    if not path or not _is_test_path(path):
        return False
    if not path.lower().endswith((".py", ".pyi")):
        return False
    new_text, old_text = _extract_step_payloads(step)
    return _payload_has_undocumented_skip(new_text) and not _payload_has_undocumented_skip(old_text)


# ──────────────────────────────────────────────────────────────────
# §49 — deleted-test detection
# ──────────────────────────────────────────────────────────────────
# Catch the failure mode where the model "fixes" a failing test by
# deleting the entire test function. We detect:
#   * an edit_file step on a test path where ``old_string`` contains
#     a ``def test_NAME`` and ``new_string`` does NOT contain
#     ``def test_NAME`` (and isn't a rename of the same body).
#   * write_text_file overwriting a test path where the new content
#     drops test functions that existed in the old (caught by the
#     same payload diff via _extract_step_payloads).

_TEST_DEF_NAME_RE = re.compile(r"\bdef\s+(test_[A-Za-z0-9_]+)\s*\(")


def _test_function_names(text: str) -> set[str]:
    if not text:
        return set()
    return set(_TEST_DEF_NAME_RE.findall(text))


def _step_deleted_test_functions(step: ReActStep) -> list[str]:
    """List of ``test_NAME`` functions removed by this write step.

    Only fires for test paths. Uses old_string vs new_string set
    difference: a name in old but not in new → removed.
    """
    path = _extract_step_path(step)
    if not path or not _is_test_path(path):
        return []
    if not path.lower().endswith((".py", ".pyi")):
        return []
    new_text, old_text = _extract_step_payloads(step)
    if not old_text:
        return []  # No prior payload to compare — could be brand-new file.
    new_names = _test_function_names(new_text)
    old_names = _test_function_names(old_text)
    return sorted(old_names - new_names)


# ──────────────────────────────────────────────────────────────────
# §52 — generic test name detection
# ──────────────────────────────────────────────────────────────────
# Catch the failure mode where a test passes §20/§42/§47/§48/§49 but
# the test name is so generic it tells the next reader nothing about
# what the test guards. ``test_basic`` / ``test_works`` / ``test_x``
# / ``test_1`` etc. are placeholder names. A meaningful test name
# describes the BEHAVIOR under test (``test_handles_empty_input``,
# ``test_retries_on_timeout``).

_GENERIC_TEST_STEMS: frozenset[str] = frozenset(
    {
        "basic",
        "simple",
        "works",
        "ok",
        "thing",
        "stuff",
        "function",
        "method",
        "case",
        "example",
        "default",
        "something",
        "anything",
        "test",
        "main",
        "run",
        "execution",
        # Single-letter / numeric placeholders.
        "a",
        "b",
        "c",
        "x",
        "y",
        "z",
        "1",
        "2",
        "3",
        "01",
        "02",
        "first",
        "second",
        "third",
        # Obvious placeholders.
        "todo",
        "tbd",
        "fixme",
        "wip",
        "tmp",
    }
)


def _is_generic_test_name(name: str) -> bool:
    """Whether ``test_NAME`` has a placeholder stem."""
    if not name.startswith("test_"):
        return False
    stem = name[len("test_") :].lower().strip("_")
    if not stem:
        return True  # Just ``test_`` itself.
    return stem in _GENERIC_TEST_STEMS


def _detect_generic_test_names_in_payload(text: str) -> list[str]:
    if not text:
        return []
    return [name for name in _test_function_names(text) if _is_generic_test_name(name)]


def _step_introduces_generic_test_name(step: ReActStep) -> list[str]:
    """List of new test functions with placeholder names."""
    path = _extract_step_path(step)
    if not path or not _is_test_path(path):
        return []
    if not path.lower().endswith((".py", ".pyi")):
        return []
    new_text, old_text = _extract_step_payloads(step)
    new_hits = set(_detect_generic_test_names_in_payload(new_text))
    old_hits = set(_detect_generic_test_names_in_payload(old_text))
    return sorted(new_hits - old_hits)


# ──────────────────────────────────────────────────────────────────
# §54 — no-assertion test detection
# ──────────────────────────────────────────────────────────────────
# Catch the failure mode where the test body has substantive code
# (so it dodges §42's "body is only `pass`/`assert True`" check) but
# contains zero actual assertion. A test that just calls the code
# under test without checking results passes if it doesn't raise —
# which is almost never what the developer meant.
#
# We accept any of: ``assert``, ``assert_called_*``, ``mock.call_args``,
# ``pytest.raises``, ``pytest.warns``, ``assertRaises`` (unittest-style),
# ``self.assertX(...)``.

_ASSERTION_MARKERS_RE = re.compile(
    r"\b(?:"
    r"assert\b|"
    r"assert_called_(?:with|once_with|once|any_call)|"
    r"assert_has_calls|assert_not_called|"
    r"call_args(?:_list)?|mock_calls|"
    r"pytest\.raises|pytest\.warns|"
    r"self\.assert[A-Z][A-Za-z]*"
    r")",
)


def _test_body_has_assertion(body: str) -> bool:
    if not body:
        return False
    return bool(_ASSERTION_MARKERS_RE.search(body))


def _detect_no_assertion_tests_in_payload(text: str) -> list[str]:
    """Return list of test_* names whose body has substantive code
    (more than 1 non-blank, non-docstring line) but no assertion.

    The "more than 1 line" cutoff distinguishes this from §42 which
    catches single-line ``pass`` / ``assert True`` bodies.
    """
    if not text:
        return []
    out: list[str] = []
    for match in _TEST_FUNC_RE.finditer(text):
        name = match.group("name")
        body = match.group("body") or ""
        # Strip docstrings/comments/blanks for the line count.
        substantive_lines = 0
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
                if opener in stripped[3:]:
                    continue
                in_docstring = True
                docstring_quote = opener
                continue
            if stripped.startswith("#"):
                continue
            substantive_lines += 1
        if substantive_lines <= 1:
            continue  # §42's territory.
        if not _test_body_has_assertion(body):
            out.append(name)
    return out


def _step_introduces_no_assertion_test(step: ReActStep) -> list[str]:
    path = _extract_step_path(step)
    if not path or not _is_test_path(path):
        return []
    if not path.lower().endswith((".py", ".pyi")):
        return []
    new_text, old_text = _extract_step_payloads(step)
    new_hits = set(_detect_no_assertion_tests_in_payload(new_text))
    old_hits = set(_detect_no_assertion_tests_in_payload(old_text))
    return sorted(new_hits - old_hits)
