"""Optional side-channel for streaming tool stdout/stderr.

Tool skills (like ``exec_shell``) normally capture output whole and return
it in their result dict. When running inside a react loop that wants to
show output incrementally, the loop binds a ``ToolOutputSink`` via
``push_sink`` around the tool call; the skill then forwards each chunk to
the sink as it arrives. Skills that don't know about the sink just work
as before — the value is optional.

The sink is bound in a ``ContextVar`` so it survives across the
executor/hook plumbing without needing to thread an extra argument
through every layer. Only one sink is active per context.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable, Iterator
from contextvars import ContextVar
from typing import Literal

# ``stream`` is the source (stdout / stderr). ``chunk`` is the raw text.
ToolOutputSink = Callable[[Literal["stdout", "stderr"], str], None]

_current_sink: ContextVar[ToolOutputSink | None] = ContextVar(
    "tool_output_sink", default=None,
)


def current_sink() -> ToolOutputSink | None:
    """Return the sink bound in the current context, or ``None``."""
    return _current_sink.get()


@contextlib.contextmanager
def push_sink(sink: ToolOutputSink) -> Iterator[None]:
    """Bind ``sink`` for the duration of the ``with`` block."""
    token = _current_sink.set(sink)
    try:
        yield
    finally:
        _current_sink.reset(token)


def emit(stream: Literal["stdout", "stderr"], chunk: str) -> None:
    """Forward ``chunk`` to the active sink, if any.

    Safe to call unconditionally from skill code — this is a no-op when
    no sink is bound, and any exception raised by the sink is swallowed
    so a flaky transport doesn't take down the tool call.
    """
    sink = _current_sink.get()
    if sink is None or not chunk:
        return
    with contextlib.suppress(Exception):
        sink(stream, chunk)
