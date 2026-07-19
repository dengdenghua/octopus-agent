from types import SimpleNamespace

from runtime.core.cerebrum import react_parallel_dispatch
from runtime.core.cerebrum.react_execution import _has_unrecovered_beak_failure


def _beak_step(name: str, *, status: str = "success") -> SimpleNamespace:
    return SimpleNamespace(
        action=SimpleNamespace(name=name),
        result=SimpleNamespace(status=status, output={}),
    )


def _drain(generator):
    events = []
    while True:
        try:
            events.append(next(generator))
        except StopIteration as stopped:
            return events, stopped.value


def test_parallel_success_recovers_an_earlier_tool_failure(monkeypatch) -> None:
    successful_steps = []
    executor = SimpleNamespace(
        registry=SimpleNamespace(
            has=lambda name: name == "read_file",
            get=lambda _name: SimpleNamespace(affinity=[]),
        )
    )

    monkeypatch.setattr(
        react_parallel_dispatch,
        "_execute_action_via_beak",
        lambda _stack, action, **_kwargs: ("read succeeded", _beak_step("read_file")),
    )
    monkeypatch.setattr(
        react_parallel_dispatch,
        "_tool_event_extras_from_beak_step",
        lambda _step, _name: {},
    )

    _events, (_observation, results) = _drain(
        react_parallel_dispatch._dispatch_parallel_actions(
            [
                'read_file({"path": "a.py"})',
                'read_file({"path": "b.py"})',
            ],
            stack=SimpleNamespace(),
            executor=executor,
            iteration=2,
            react_task_id="task",
            agent=None,
            intent=SimpleNamespace(),
            beak_step_sink=successful_steps,
        )
    )

    assert [result["ok"] for result in results] == [True, True]
    assert len(successful_steps) == 2
    assert not _has_unrecovered_beak_failure(
        [_beak_step("grep_text", status="failed"), *successful_steps]
    )
