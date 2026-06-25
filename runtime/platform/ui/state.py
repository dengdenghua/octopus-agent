"""Shared UI app state."""
from __future__ import annotations

from pathlib import Path

from runtime.execution.suckers import SkillRegistry
from runtime.memory.journal import InMemoryJournal, Journal, JSONLJournal
from runtime.platform.observability.redactor import Redactor
from runtime.sensing.gateway import StreamingJournal


class AppState:
    """Runtime state shared by UI routers."""

    def __init__(
        self,
        journal_path: Path | None = None,
        *,
        journal: Journal | None = None,
        registry: SkillRegistry | None = None,
        trace_store_path: Path | None = None,
    ) -> None:
        self.journal_path = journal_path
        self.trace_store_path = trace_store_path
        if registry is not None:
            self.registry = registry
        else:
            self.registry = SkillRegistry()
            self.registry.set_state_file(Path("data/skill_state.json"))
            from runtime.execution.suckers.builtins import register_all

            register_all(self.registry)
        try:
            from runtime.execution.suckers import load_forged_skills_from_dir

            load_forged_skills_from_dir(Path("data/forged_skills"), self.registry)
        except Exception:  # noqa: BLE001
            pass

        trace_store = None
        if trace_store_path is not None and (
            (journal is None and journal_path)
            or isinstance(journal, JSONLJournal)
        ):
            from runtime.memory.diagnostics.trace_store import AgentTraceStore

            trace_store = AgentTraceStore(trace_store_path)
            if isinstance(journal, JSONLJournal):
                journal.attach_trace_store(trace_store)
        self.trace_store = trace_store

        base_journal = journal if journal is not None else (
            JSONLJournal(journal_path, trace_store=trace_store, redactor=Redactor())
            if journal_path
            else InMemoryJournal()
        )
        if isinstance(base_journal, StreamingJournal):
            self.journal = base_journal
        else:
            self.journal = StreamingJournal(base_journal)
