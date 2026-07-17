from __future__ import annotations

from pathlib import Path

from playwright.sync_api import expect, sync_playwright

from benchmarks.eval_harness import Trajectory
from benchmarks.fixed_suite_fixtures import prepare_fixture_suite
from benchmarks.fixture_grading import LiveIsolatedFixture

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_dynamic_crud_fixture_is_live_and_satisfiable(tmp_path) -> None:
    prepared = prepare_fixture_suite(
        repo_root=REPO_ROOT,
        runs_root=tmp_path / "runs",
        case_ids={"browser.dynamic-crud"},
    )
    case = prepared.cases[0]
    fixture = prepared.fixtures[case.id]
    assert isinstance(fixture, LiveIsolatedFixture)
    assert case.setup is not None and case.teardown is not None
    case.setup()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(fixture.url())
            page.locator("#name").fill("Acme Labs")
            page.locator("#plan").select_option(label="Starter")
            page.get_by_role("button", name="Create").click()
            row = page.locator('[data-customer-id="customer-1"]')
            row.wait_for()
            row.locator("[data-edit-plan]").select_option(label="Enterprise")
            row.locator("[data-save]").click()
            expect(page.locator('[data-customer-id="customer-1"] [data-plan]')).to_have_text(
                "Enterprise"
            )
            page.locator('[data-customer-id="customer-1"] [data-verify]').click()
            page.wait_for_timeout(80)
            page.locator('[data-customer-id="customer-1"] [data-delete]').click()
            page.locator('[data-customer-id="customer-1"]').wait_for(state="detached")
            browser.close()
        verdict = case.grader(Trajectory(trial_id="test", case_id=case.id))
    finally:
        case.teardown()

    assert verdict.passed is True, verdict.reason


def test_rich_editor_upload_fixture_is_live_and_satisfiable(tmp_path) -> None:
    prepared = prepare_fixture_suite(
        repo_root=REPO_ROOT,
        runs_root=tmp_path / "runs",
        case_ids={"browser.rich-editor-upload"},
    )
    case = prepared.cases[0]
    fixture = prepared.fixtures[case.id]
    assert isinstance(fixture, LiveIsolatedFixture)
    assert case.setup is not None and case.teardown is not None
    case.setup()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(fixture.url())
            page.locator("#role").select_option(label="Administrator")
            page.locator("#bio").fill("Building reliable agents.")
            page.locator("#avatar").set_input_files(fixture.workspace() / "profile.txt")
            page.locator("#submit").click()
            frame = page.frame_locator("#confirmation")
            frame.locator("#confirmed").wait_for()
            browser.close()
        verdict = case.grader(Trajectory(trial_id="test", case_id=case.id))
    finally:
        case.teardown()

    assert verdict.passed is True, verdict.reason
