"""Implementation note."""

from __future__ import annotations

from pathlib import Path

from tools.lint.invariant_check import (
    ALL_RULES,
    lint_tree,
)

FIXTURES = Path(__file__).parent.parent / "tools" / "lint" / "fixtures"


class TestFixturesTriggerExpectedRules:
    def test_good_fixture_has_no_issues(self):
        issues = lint_tree(FIXTURES / "good.py", ALL_RULES)
        # Implementation note.
        errors = [i for i in issues if i.severity == "error"]
        assert errors == [], f"good.py should have no errors, got: {errors}"

    def test_bad_bio_name_triggers_lint_03(self):
        issues = lint_tree(FIXTURES / "bad_bio_name.py", ALL_RULES)
        rule_ids = {i.rule_id for i in issues}
        assert "LINT-03" in rule_ids

    def test_bad_raw_llm_triggers_lint_04(self):
        issues = lint_tree(FIXTURES / "bad_raw_llm.py", ALL_RULES)
        rule_ids = {i.rule_id for i in issues}
        assert "LINT-04" in rule_ids

    def test_bad_task_no_budget_triggers_lint_05(self):
        issues = lint_tree(FIXTURES / "bad_task_no_budget.py", ALL_RULES)
        rule_ids = {i.rule_id for i in issues}
        assert "LINT-05" in rule_ids


class TestSelfLint:
    """Implementation note."""

    def test_package_is_clean(self):
        pkg = Path(__file__).parent.parent / "runtime"
        assert pkg.is_dir()
        issues = lint_tree(pkg, ALL_RULES)
        errors = [i for i in issues if i.severity == "error"]
        assert errors == [], (
            "runtime/ must pass its own lint. Found: "
            + "\n".join(i.format() for i in errors)
        )
