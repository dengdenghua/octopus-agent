
from __future__ import annotations

import fnmatch
from typing import Literal

from runtime.platform.models import AntigenSignature, ImmuneReport, ImmuneVerdict, ToolCall

UnknownPolicy = Literal["quarantine", "reject", "allow"]


class TrustEngine:

    def __init__(
        self,
        trusted_sources: list[str] | None = None,
        self_whitelist: list[str] | None = None,
        unknown_policy: UnknownPolicy = "quarantine",
    ) -> None:
        # Default trust roster — keep these in sync with the
        # ``ImmunityConfig`` defaults in
        # ``runtime/platform/config/schema.py``. Same exact defaults
        # ensure the in-process construction (via _build_stack in cli)
        # matches the yaml-driven construction.
        #
        # SECURITY: ``mcp://*`` is intentionally REMOVED from defaults.
        # MCP servers must be explicitly whitelisted in config to be
        # trusted. This prevents malicious MCP servers from bypassing
        # trust checks out of the box.
        self.trusted_sources = (
            trusted_sources if trusted_sources is not None
            else ["skill://public/*"]
        )
        self.self_whitelist = (
            self_whitelist if self_whitelist is not None
            else [
                "cerebrum", "ganglia", "arms/*",
                "react_loop", "react_arm",
                "intel_collector/*",
            ]
        )
        self.unknown_policy = unknown_policy


    def check(self, call: ToolCall, signature: AntigenSignature) -> ImmuneReport:
        if self._is_self(call):
            return ImmuneReport(
                verdict="allow",
                signature=signature,
                strategy_used="tolerance",
                reason="self-whitelisted caller",
            )

        if self._is_trusted(signature.entity_id):
            return ImmuneReport(
                verdict="allow",
                signature=signature,
                strategy_used="innate",
                reason="matched trusted_sources",
            )

        verdict: ImmuneVerdict
        if self.unknown_policy == "reject":
            verdict = "reject"
            reason = "unknown source, policy=reject"
        elif self.unknown_policy == "allow":
            verdict = "allow"
            reason = "unknown source, policy=allow (risky)"
        else:
            verdict = "quarantine"
            reason = "unknown source, policy=quarantine"

        return ImmuneReport(
            verdict=verdict,
            signature=signature,
            strategy_used="innate",
            reason=reason,
        )


    def _is_self(self, call: ToolCall) -> bool:
        return any(fnmatch.fnmatch(call.caller, pattern) for pattern in self.self_whitelist)

    def _is_trusted(self, entity_id: str) -> bool:
        return any(fnmatch.fnmatch(entity_id, pattern) for pattern in self.trusted_sources)
