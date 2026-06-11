
from __future__ import annotations

import fnmatch
from typing import Literal

from runtime.platform.models import AntigenSignature, ImmuneReport, ImmuneVerdict, ToolCall
from runtime.safety.auth.attack_memory import AttackMemory

UnknownPolicy = Literal["quarantine", "reject", "allow"]


class TrustEngine:

    def __init__(
        self,
        trusted_sources: list[str] | None = None,
        self_whitelist: list[str] | None = None,
        unknown_policy: UnknownPolicy = "quarantine",
        attack_memory: AttackMemory | None = None,
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
        # Memory tier (protocols/immunity.md): known attackers are
        # rejected before the trusted_sources allow — a compromised
        # entity inside a trusted glob must not keep its free pass.
        self.attack_memory = attack_memory if attack_memory is not None else AttackMemory()


    def check(self, call: ToolCall, signature: AntigenSignature) -> ImmuneReport:
        if self._is_self(call):
            return ImmuneReport(
                verdict="allow",
                signature=signature,
                strategy_used="tolerance",
                reason="self-whitelisted caller",
            )

        pattern = self.attack_memory.match(signature.entity_id)
        if pattern is not None:
            return ImmuneReport(
                verdict="reject",
                signature=signature,
                strategy_used="memory",
                reason=(
                    f"known attack pattern (hits={pattern.hit_count}): "
                    f"{pattern.reason}"
                ),
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
            # Crystallization input: repeated hard rejections of the
            # same source become an antibody, so the source stays
            # rejected even if the policy is later relaxed.
            self.attack_memory.record_violation(
                signature.entity_id, reason="repeated innate rejections",
            )
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
