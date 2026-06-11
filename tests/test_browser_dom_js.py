"""Shared browser DOM perception JS (browser_dom_js).

The snippet runs inside the page, so Python tests pin its structure
and — when Node is available — validate the syntax for real. The two
consumers (Electron bridge IIFE, Playwright evaluate function) must
both embed the same helpers.
"""

import shutil
import subprocess

import pytest

from runtime.execution.suckers.browser_dom_js import (
    DOM_HELPERS_JS,
    dom_snapshot_function_js,
    dom_state_iife_js,
)


class TestSelectorGeneration:
    def test_priority_candidates_present(self):
        # data-testid outranks id outranks aria-label outranks name —
        # measured within selectorFor's candidate section only (textOf
        # above it also mentions aria-label).
        body = DOM_HELPERS_JS[DOM_HELPERS_JS.index("const selectorFor") :]
        order = [
            body.index("data-testid"),
            body.index("CSS.escape(el.id)"),
            body.index("aria-label"),
            body.index("'name'"),
        ]
        assert order == sorted(order)

    def test_uniqueness_is_verified_not_assumed(self):
        assert "uniqueMatch" in DOM_HELPERS_JS
        assert "querySelectorAll" in DOM_HELPERS_JS
        # Structural fallback exists for pages without stable hooks.
        assert "nth-of-type" in DOM_HELPERS_JS


class TestPerceptionFields:
    def test_interaction_state_is_exposed(self):
        for field in ("disabled", "checked", "role", "ariaLabel", "value"):
            assert f"{field}:" in DOM_HELPERS_JS

    def test_password_values_never_echo(self):
        # The value field must be gated on type !== 'password'.
        assert "password" in DOM_HELPERS_JS
        value_line = next(
            line for line in DOM_HELPERS_JS.splitlines() if "value:" in line
        )
        assert "password" in value_line


class TestWrappers:
    def test_iife_carries_limit_and_page_meta(self):
        code = dom_state_iife_js(25)
        assert "const limit = 25;" in code
        assert "location.href" in code
        assert code.startswith("(() => {") and code.endswith("})()")

    def test_iife_clamps_to_int(self):
        assert "const limit = 7;" in dom_state_iife_js(7)

    def test_playwright_function_takes_limit_param(self):
        code = dom_snapshot_function_js()
        assert code.startswith("(limit) => {")
        assert "pickElements" in code

    def test_both_wrappers_embed_the_same_helpers(self):
        iife = dom_state_iife_js(10)
        fn = dom_snapshot_function_js()
        for marker in ("uniqueMatch", "selectorFor", "describe", "pickElements"):
            assert marker in iife
            assert marker in fn


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
class TestJsSyntax:
    def _check(self, code: str) -> None:
        proc = subprocess.run(
            ["node", "-e", "new Function(process.argv[1]); console.log('ok')", code],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert proc.returncode == 0, proc.stderr

    def test_iife_parses(self):
        self._check(dom_state_iife_js(30))

    def test_playwright_function_parses(self):
        self._check("(" + dom_snapshot_function_js() + ")(10)")
