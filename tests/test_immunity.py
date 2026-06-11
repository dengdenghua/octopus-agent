"""Implementation note."""

from __future__ import annotations

from runtime.platform.models import AntigenSignature, ToolCall
from runtime.safety.auth import TrustEngine


def _sig(entity_id: str) -> AntigenSignature:
    return AntigenSignature(
        entity_id=entity_id,
        entity_type="skill",
        content_hash="h",
    )


class TestTolerance:
    """Implementation note."""

    def test_cerebrum_caller_allowed(self):
        t = TrustEngine()
        call = ToolCall(caller="cerebrum", sucker_id="x", args={})
        report = t.check(call, _sig("external://unknown/stuff"))
        assert report.verdict == "allow"
        assert report.strategy_used == "tolerance"

    def test_arms_glob_allowed(self):
        t = TrustEngine()
        call = ToolCall(caller="arms/code_arm", sucker_id="x", args={})
        report = t.check(call, _sig("external://unknown/stuff"))
        assert report.verdict == "allow"
        assert report.strategy_used == "tolerance"


class TestInnate:
    def test_trusted_source_allowed(self):
        t = TrustEngine(trusted_sources=["skill://public/*"])
        call = ToolCall(caller="external-caller", sucker_id="x", args={})
        report = t.check(call, _sig("skill://public/run_pytest"))
        assert report.verdict == "allow"
        assert report.strategy_used == "innate"

    def test_glob_pattern(self):
        t = TrustEngine(trusted_sources=["mcp://anthropic/*"])
        call = ToolCall(caller="external-caller", sucker_id="x", args={})
        report = t.check(call, _sig("mcp://anthropic/filesystem"))
        assert report.verdict == "allow"


class TestUnknownPolicy:
    def test_quarantine_default(self):
        t = TrustEngine(trusted_sources=[])
        call = ToolCall(caller="external-caller", sucker_id="x", args={})
        report = t.check(call, _sig("rogue://source"))
        assert report.verdict == "quarantine"

    def test_reject_policy(self):
        t = TrustEngine(trusted_sources=[], unknown_policy="reject")
        call = ToolCall(caller="external-caller", sucker_id="x", args={})
        report = t.check(call, _sig("rogue://source"))
        assert report.verdict == "reject"

    def test_allow_policy_risky(self):
        t = TrustEngine(trusted_sources=[], unknown_policy="allow")
        call = ToolCall(caller="external-caller", sucker_id="x", args={})
        report = t.check(call, _sig("rogue://source"))
        assert report.verdict == "allow"
