from __future__ import annotations

from runtime.core.cerebrum.react_guards import GuardContext, evaluate_guards
from runtime.core.cerebrum.react_types import ReActStep


GOAL = (
    "Using the browser UI, complete onboarding with a native select, a rich-text "
    "editor, and an upload. Submit once and verify the delayed iframe confirmation."
)


def _step(iteration: int, action: str, observation: str) -> ReActStep:
    return ReActStep(
        iteration=iteration,
        action=action,
        actions=[action],
        observation=observation,
        action_results=[{"ok": True}],
    )


def _context(steps: list[ReActStep]) -> GuardContext:
    return GuardContext(
        steps=steps,
        final_answer="Done.",
        goal=GOAL,
        browser_operation_mode=True,
        tools_active=True,
        is_code_mode=False,
    )


def test_browser_completion_guard_blocks_file_inspection_only() -> None:
    ctx = _context([_step(1, 'read_file({"path":"EVAL_URL.txt"})', "http://localhost")])

    hit = evaluate_guards(ctx)

    assert hit is not None
    assert hit[0] == "browser-completion guard"
    assert "browser_upload receipt" in hit[1]
    assert "iframe confirmation" in hit[1]


def test_browser_completion_guard_accepts_executed_form_and_frame_evidence() -> None:
    ctx = _context(
        [
            _step(1, 'browser_type({"selector":"#role","value":"Administrator"})', "selected"),
            _step(2, 'browser_type({"selector":"#bio","value":"Building reliable agents."})', "typed"),
            _step(3, 'browser_upload({"selector":"#avatar","path":"profile.txt"})', "uploaded"),
            _step(4, 'browser_click({"selector":"#submit"})', "clicked"),
            _step(
                5,
                'browser_get({"wait_ms":300})',
                '{"frames":[{"url":"/confirmation.html","content":"Onboarding complete"}]}',
            ),
        ]
    )

    assert evaluate_guards(ctx) is None


def test_browser_completion_guard_never_requests_second_submit() -> None:
    ctx = _context(
        [
            _step(1, 'browser_click({"selector":"#submit"})', "clicked"),
        ]
    )

    hit = evaluate_guards(ctx)

    assert hit is not None
    assert "do not click Submit again" in hit[1]
    assert "browser_get(wait_ms=300)" in hit[1]
