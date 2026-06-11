
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

_AGENT_ID: ContextVar[str | None] = ContextVar("octopus_journal_agent_id", default=None)
_CONVERSATION_ID: ContextVar[str | None] = ContextVar(
    "octopus_journal_conversation_id", default=None,
)


def current_agent_id() -> str | None:
    return _AGENT_ID.get()


def current_conversation_id() -> str | None:
    return _CONVERSATION_ID.get()


@contextmanager
def journal_context(
    *,
    agent_id: str | None = None,
    conversation_id: str | None = None,
) -> Iterator[None]:
    token_a = _AGENT_ID.set(agent_id)
    token_c = _CONVERSATION_ID.set(conversation_id)
    try:
        yield
    finally:
        _AGENT_ID.reset(token_a)
        _CONVERSATION_ID.reset(token_c)
