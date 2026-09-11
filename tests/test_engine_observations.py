from types import SimpleNamespace

from runtime.execution import engine_observations as checks
from runtime.execution import request


def test_actual_evidence_is_principal_scoped_expires_and_never_contains_payload(monkeypatch):
    checks._records.clear()
    task = SimpleNamespace(tenant_id="org", actor_id="alice", execution_engine="opencode")
    monkeypatch.setattr(request, "current_execution_request", lambda: SimpleNamespace(task=task))
    event = {"type": "tool_end", "tool_name": "opencode.websearch", "success": True,
             "output_preview": "private payload"}
    result = checks.observe_engine_event(event, "opencode", "model-a")
    assert result["tool_name"] == "web_search"
    assert result["native_tool_name"] == "opencode.websearch"
    snapshot = checks.engine_observations(task, "opencode")
    assert snapshot["capability_checks"]["web_search"]["state"] == "verified"
    assert "private payload" not in str(snapshot)
    other = SimpleNamespace(tenant_id="org", actor_id="bob")
    assert checks.engine_observations(other, "opencode")["capability_checks"]["web_search"]["state"] == "untested"
    monkeypatch.setattr(checks.time, "monotonic", lambda: float("inf"))
    assert checks.engine_observations(task, "opencode")["capability_checks"]["web_search"]["state"] == "untested"


def test_failure_replaces_success_but_cancellation_is_not_a_provider_failure(monkeypatch):
    checks._records.clear()
    task = SimpleNamespace(tenant_id="org", actor_id="alice", execution_engine="codex")
    monkeypatch.setattr(request, "current_execution_request", lambda: SimpleNamespace(task=task))
    checks.observe_engine_event({"type": "react_completed", "success": True}, "codex")
    checks.observe_engine_event({"type": "react_cancelled"}, "codex")
    assert checks.engine_observations(task, "codex")["capability_checks"]["chat"]["state"] == "verified"
    checks.observe_engine_event({"type": "react_completed", "success": False}, "codex")
    assert checks.engine_observations(task, "codex")["capability_checks"]["chat"]["state"] == "failed"


def test_foreign_engine_cannot_record_success(monkeypatch):
    checks._records.clear()
    task = SimpleNamespace(tenant_id="org", actor_id="alice", execution_engine="opencode")
    monkeypatch.setattr(request, "current_execution_request", lambda: SimpleNamespace(task=task))
    checks.observe_engine_event({"type": "react_completed", "success": True}, "codex")
    assert checks.engine_observations(task, "codex")["capability_checks"]["chat"]["state"] == "untested"


def test_codex_status_contract_and_denied_tools_are_not_provider_failures(monkeypatch):
    checks._records.clear()
    task = SimpleNamespace(tenant_id="org", actor_id="alice", execution_engine="codex")
    monkeypatch.setattr(request, "current_execution_request", lambda: SimpleNamespace(task=task))
    for status in ("success", "rejected", "cancelled"):
        checks.observe_engine_event({"type": "tool_end", "tool_name": "web_search", "status": status}, "codex")
        assert checks.engine_observations(task, "codex")["capability_checks"]["web_search"]["state"] == "verified"
