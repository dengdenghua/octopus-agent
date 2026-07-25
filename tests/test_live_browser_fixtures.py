from __future__ import annotations

from pathlib import Path
from urllib.request import urlopen

from playwright.sync_api import expect, sync_playwright

from benchmarks.eval_harness import Trajectory
from benchmarks.fixed_suite_fixtures import prepare_fixture_suite
from benchmarks.fixture_grading import LiveIsolatedFixture

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_frontend_fixtures_have_isolated_live_previews(tmp_path) -> None:
    case_ids = {
        "frontend.responsive-settings",
        "frontend.async-form-recovery",
    }
    prepared = prepare_fixture_suite(
        repo_root=REPO_ROOT,
        runs_root=tmp_path / "runs",
        case_ids=case_ids,
    )

    for case in prepared.cases:
        fixture = prepared.fixtures[case.id]
        assert isinstance(fixture, LiveIsolatedFixture)
        assert case.setup is not None and case.teardown is not None
        case.setup()
        try:
            url = fixture.url()
            assert url.startswith("http://127.0.0.1:")
            with urlopen(url, timeout=2) as response:  # noqa: S310 - trusted loopback fixture
                html = response.read().decode("utf-8")
            assert '<meta name="eval-session"' in html
            assert "<!doctype html" in html.lower()
        finally:
            case.teardown()


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
    trajectory = Trajectory(trial_id="test", case_id=case.id)
    case.setup()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(fixture.url())
            trajectory.append("tool_start", tool_name="browser_navigate")
            page.locator("#name").fill("Acme Labs")
            trajectory.append("tool_start", tool_name="browser_type")
            page.locator("#plan").select_option(label="Starter")
            trajectory.append("tool_start", tool_name="browser_type")
            page.get_by_role("button", name="Create").click()
            trajectory.append("tool_start", tool_name="browser_click")
            row = page.locator('[data-customer-id="customer-1"]')
            row.wait_for()
            row.locator("[data-edit-plan]").select_option(label="Enterprise")
            trajectory.append("tool_start", tool_name="browser_type")
            row.locator("[data-save]").click()
            trajectory.append("tool_start", tool_name="browser_click")
            expect(page.locator('[data-customer-id="customer-1"] [data-plan]')).to_have_text(
                "Enterprise"
            )
            trajectory.append("tool_start", tool_name="browser_get")
            page.locator('[data-customer-id="customer-1"] [data-verify]').click()
            trajectory.append("tool_start", tool_name="browser_click")
            page.wait_for_timeout(80)
            page.locator('[data-customer-id="customer-1"] [data-delete]').click()
            trajectory.append("tool_start", tool_name="browser_click")
            page.locator('[data-customer-id="customer-1"]').wait_for(state="detached")
            browser.close()
        verdict = case.grader(trajectory)
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
    trajectory = Trajectory(trial_id="test", case_id=case.id)
    case.setup()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(fixture.url())
            trajectory.append("tool_start", tool_name="browser_navigate")
            page.locator("#role").select_option(label="Administrator")
            trajectory.append("tool_start", tool_name="browser_type")
            page.locator("#bio").fill("Building reliable agents.")
            trajectory.append("tool_start", tool_name="browser_type")
            page.locator("#avatar").set_input_files(fixture.workspace() / "profile.txt")
            trajectory.append("tool_start", tool_name="browser_upload")
            page.locator("#submit").click()
            trajectory.append("tool_start", tool_name="browser_click")
            frame = page.frame_locator("#confirmation")
            frame.locator("#confirmed").wait_for()
            trajectory.append("tool_start", tool_name="browser_wait")
            browser.close()
        verdict = case.grader(trajectory)
    finally:
        case.teardown()

    assert verdict.passed is True, verdict.reason
