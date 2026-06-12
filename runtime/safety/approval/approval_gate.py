"""Tool-approval provider — pluggable, transport-agnostic.

The previous implementation kept a process-wide ``dict[str, threading.Event]``
and exposed ``request_approval``/``wait_for_approval``/``submit_decision``
free functions. That design forced the SSE+POST flow, deadlocked under
multi-worker uvicorn, and could not be unit-tested without monkey-patching
the global state.

This module replaces that with an :class:`ApprovalProvider` interface plus
two implementations:

  * :class:`AutoApproveProvider` — always grants. Useful in tests, in
    ``approvalPolicy="never"`` paths, and for headless batch jobs.
  * :class:`AutoDenyProvider`    — always denies. The default when no
    provider is wired, so a missing wiring fails closed rather than
    silently auto-accepting destructive tools.

Live UIs supply their own provider — for the realtime gateway, the
emitter is the provider (see :class:`RpcConnection.request_approval`).
"""

from __future__ import annotations

import fnmatch
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Literal

_logger = logging.getLogger(__name__)

ApprovalRiskLevel = Literal["low", "medium", "high", "critical"]
ApprovalRiskAction = Literal["allow", "audit", "ask", "confirm", "deny"]


@dataclass(frozen=True, slots=True)
class ApprovalRisk:
    level: ApprovalRiskLevel
    categories: tuple[str, ...] = ()
    reason: str = ""

    @property
    def requires_approval(self) -> bool:
        return self.level in {"medium", "high", "critical"}

    def with_injection_taint(self) -> ApprovalRisk:
        """Annotate that this approval was forced by prompt-injection
        taint in the turn (untrusted content carried injection markers),
        so the UI / audit log shows *why* a normally-auto tool is asking."""
        if "prompt_injection_taint" in self.categories:
            return self
        return ApprovalRisk(
            level=self.level,
            categories=(*self.categories, "prompt_injection_taint"),
            reason=(
                f"{self.reason}; forced approval — untrusted content with "
                "injection markers entered this turn"
            ).lstrip("; "),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "level": self.level,
            "categories": list(self.categories),
            "reason": self.reason,
            "requires_approval": self.requires_approval,
        }


@dataclass(frozen=True, slots=True)
class ApprovalRiskPolicy:
    """Risk-level policy matrix for tool approval routing."""

    low: ApprovalRiskAction = "allow"
    medium: ApprovalRiskAction = "ask"
    high: ApprovalRiskAction = "ask"
    critical: ApprovalRiskAction = "confirm"

    def action_for(self, risk: ApprovalRisk) -> ApprovalRiskAction:
        return getattr(self, risk.level)

    @classmethod
    def from_mapping(cls, value: object) -> ApprovalRiskPolicy:
        if not isinstance(value, dict):
            return cls()
        allowed = {"allow", "audit", "ask", "confirm", "deny"}
        data: dict[str, ApprovalRiskAction] = {}
        for level in ("low", "medium", "high", "critical"):
            raw = value.get(level)
            if isinstance(raw, str) and raw in allowed:
                data[level] = raw  # type: ignore[assignment]
        return cls(**data)

    def to_dict(self) -> dict[str, ApprovalRiskAction]:
        return {
            "low": self.low,
            "medium": self.medium,
            "high": self.high,
            "critical": self.critical,
        }


# Heuristic catalog of tool names that require explicit approval when no
# more specific policy is supplied. Mirrors the original ``approval_gate``
# defaults; centralizing here keeps the rule set in one place.
DANGEROUS_TOOLS: frozenset[str] = frozenset(
    {
        "exec_shell",
        "write_text_file",
        "append_text_file",
        "edit_text_file",
        "edit_code",
        "delete_file",
        "git_commit",
        "git_push",
        "git_checkout",
        "git_create_pr",
        "git_merge",
        "git_reset",
        # Computer-automation API surface (preview-confirm-execute) ·
        # ``computer_observe`` and ``computer_preview_action`` are
        # deliberately omitted: the former is read-only status and a
        # screenshot, the latter only queues a token without executing.
        # ``computer_plan_next`` is included because it ships a fresh
        # screenshot to a vision model (egress) before any user
        # confirmation, and ``computer_execute_token`` is the one that
        # actually moves the mouse / keyboard via the queued token.
        "computer_plan_next",
        "computer_execute_token",
    }
)

DANGEROUS_PREFIXES: tuple[str, ...] = (
    "exec_shell",
    "write_",
    "edit_",
    "delete_",
    "git_",
    "send_",
    "http_",
    "fetch_",
    "email_",
    "slack_",
    # Desktop GUI control · pyautogui-driven mouse / keyboard / screen
    # primitives. Screen capture is included (not just input) because
    # whatever's on screen — open password managers, draft emails,
    # private chat — leaves the host the moment the screenshot lands
    # in a tool observation. Treat it as data egress.
    "mouse_",
    "keyboard_",
    "screen_",
    # Browser automation · both the headless Playwright pool
    # (``browser_*``) and the live bridge into the desktop Electron
    # webview (``live_browser_*``). The latter operates the user's
    # real, logged-in browser, so it is at least as sensitive as the
    # former. Gating both at the prefix level avoids per-skill drift
    # as new browser primitives get added.
    "browser_",
    "live_browser_",
    # Mobile/Tentacle device control. These names appear as canonical
    # Android skill ids (``android.tap``) and MCP-safe tool ids
    # (``android_tap``).
    "android.",
    "android_",
)


def is_dangerous_tool(tool_name: str) -> bool:
    """Return True iff ``tool_name`` should default to needing approval.

    Pure function; safe to call from anywhere. Decisions about whether
    to *consult* the user (vs. an auto-approve override) belong to the
    caller — typically the ``approval_policy`` resolution layer.
    """
    if tool_name in DANGEROUS_TOOLS:
        return True
    return any(tool_name.startswith(prefix) for prefix in DANGEROUS_PREFIXES)


def assess_approval_risk(
    tool_name: str,
    args_preview: str = "",
) -> ApprovalRisk:
    """Classify a tool call by capability risk, independent of UI policy."""

    name = (tool_name or "").strip()
    preview = (args_preview or "").lower()
    categories: list[str] = []
    level: ApprovalRiskLevel = "low"

    def bump(next_level: ApprovalRiskLevel, category: str) -> None:
        nonlocal level
        order = {"low": 0, "medium": 1, "high": 2, "critical": 3}
        if order[next_level] > order[level]:
            level = next_level
        if category not in categories:
            categories.append(category)

    if name.startswith(("read_", "list_", "glob_", "grep_", "file_stats")):
        bump("low", "local_read")
    if name.startswith((
        "fetch_", "http_", "send_", "email_", "slack_",
        "upload_", "publish_", "post_", "webhook_", "deploy_",
    )):
        bump("medium", "network_or_egress")
    if name.startswith(("write_", "append_", "edit_", "delete_")) or name in DANGEROUS_TOOLS:
        bump("high", "filesystem_write")
    if name.startswith(("browser_", "live_browser_", "mouse_", "keyboard_", "screen_", "computer_")):
        bump("high", "interactive_control")
    if name.startswith(("android.", "android_")):
        bump("high", "mobile_device_control")
    if name.startswith("git_"):
        bump("high", "vcs_mutation")
    # Command execution — incl. background / renamed aliases that the
    # bare ``exec_shell`` check missed (a prompt-injected agent can route
    # a shell through any of these).
    if (
        name in {
            "exec_shell", "shell_command", "bash", "background_exec",
            "run_command", "exec_command", "run_python", "python_exec",
            "run_code", "subprocess_run",
        }
        or name.startswith(("exec_shell", "background_exec", "run_command"))
    ):
        bump("high", "shell_execution")
        destructive_markers = (
            "rm -rf", "del /", "remove-item", "format ", "drop database",
            "truncate table", "git reset --hard", "git clean -fd",
            "push --force", "--force-with-lease", "chmod 777",
        )
        if any(marker in preview for marker in destructive_markers):
            bump("critical", "destructive_command")
    # MCP / remote tools: their output is attacker-influenceable and their
    # tool NAME is freeform, so the prefix rules above don't see the
    # capability. Treat any mcp_* tool as at least medium, and infer a
    # dangerous capability from danger keywords in the name (e.g.
    # ``mcp_<server>_exec_shell`` / ``..._write_file`` / ``..._upload``).
    if name.startswith(("mcp_", "mcp__")):
        bump("medium", "external_mcp")
        _low = name.lower()
        if any(k in _low for k in (
            "exec", "shell", "bash", "subprocess", "run_command", "run_code",
        )):
            bump("high", "shell_execution")
        elif any(k in _low for k in (
            "write", "delete", "remove", "edit_", "upload", "publish", "deploy",
        )):
            bump("high", "filesystem_write")
    if "api_key" in preview or "secret" in preview or "token" in preview:
        bump("high", "secret_material")
    if level == "low" and is_dangerous_tool(name):
        bump("medium", "dangerous_tool_catalog")

    return ApprovalRisk(
        level=level,
        categories=tuple(categories),
        reason=", ".join(categories) or "no elevated risk detected",
    )


def injection_taint_block(tool_name: str, args_preview: str = "") -> str | None:
    """The single, path-independent enforcement point for prompt-injection
    taint, called by the executor before every tool runs.

    Returns a block reason when: the turn is injection-tainted (untrusted
    content with injection markers entered it), this tool is risky
    (medium+), and no approval-capable loop has reviewed this specific call
    — i.e. it reached the executor via the parallel dispatch, the
    agentic-fallback loop, or a subagent, none of which can ask a human.
    Returns ``None`` to allow (clean turn, low-risk tool, or already
    reviewed by the single-action approval gate). Fail-closed: when in
    doubt after taint, a risky tool is blocked rather than auto-run."""
    from runtime.safety.validation.prompt_injection import (
        injection_gate_already_handled,
        injection_taint_gates,
    )
    if not injection_taint_gates() or injection_gate_already_handled():
        return None
    risk = assess_approval_risk(tool_name, args_preview)
    if risk.level in {"medium", "high", "critical"}:
        return (
            f"{tool_name} (risk={risk.level}: {risk.reason}) blocked — "
            "untrusted content with prompt-injection markers entered this "
            "turn and this execution path cannot request human approval"
        )
    return None


def needs_approval(tool_name: str, auto_approve: bool = False) -> bool:
    """Backwards-compatible helper. Prefer ``is_dangerous_tool``."""
    if auto_approve:
        return False
    return assess_approval_risk(tool_name).requires_approval


def needs_approval_for_chain(tool_names: list[str], auto_approve: bool = False) -> bool:
    if auto_approve:
        return False
    return any(assess_approval_risk(name).requires_approval for name in tool_names)


def approval_action_for_tool(
    tool_name: str,
    args_preview: str = "",
    *,
    policy: ApprovalRiskPolicy | dict[str, str] | None = None,
) -> tuple[ApprovalRisk, ApprovalRiskAction, ApprovalRiskPolicy]:
    risk = assess_approval_risk(tool_name, args_preview)
    resolved_policy = (
        policy if isinstance(policy, ApprovalRiskPolicy)
        else ApprovalRiskPolicy.from_mapping(policy)
    )
    return risk, resolved_policy.action_for(risk), resolved_policy


# ── Provider protocol ────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class ApprovalRequest:
    """All the context an approval decision could possibly need."""

    thread_id: str
    tool_name: str
    tool_call_id: str
    args_preview: str = ""
    detail: str = ""


@dataclass(frozen=True, slots=True)
class ApprovalDecision:
    approved: bool
    reason: str | None = None


class ApprovalProvider(ABC):
    """Adapter between a planner's "needs human consent" event and a
    transport (web UI, CLI prompt, Slack, auto-deny, …).

    Implementations must be thread-safe — the same provider may be
    invoked from any worker thread the executor places ReAct on.
    """

    @abstractmethod
    def request(self, req: ApprovalRequest, *, timeout: float = 120.0) -> ApprovalDecision:
        """Block the calling thread until the user decides or timeout.

        Implementations may raise on transport failure; callers should
        treat exceptions as denial unless they have a more specific
        policy.
        """


class AutoApproveProvider(ApprovalProvider):
    """Always grants. Convenient for tests and non-interactive runs."""

    def request(self, req: ApprovalRequest, *, timeout: float = 120.0) -> ApprovalDecision:
        return ApprovalDecision(approved=True, reason="auto-approve")


class AutoDenyProvider(ApprovalProvider):
    """Default fail-closed provider.

    When no UI is wired, the safe behavior is to refuse rather than
    silently auto-accepting whatever the planner proposes. The reason
    string is surfaced to the planner so it can adjust its plan.
    """

    def request(self, req: ApprovalRequest, *, timeout: float = 120.0) -> ApprovalDecision:
        _logger.info(
            "AutoDenyProvider rejecting %s (no interactive UI wired)",
            req.tool_name,
        )
        return ApprovalDecision(
            approved=False,
            reason="no interactive approval UI is wired in this runtime",
        )


# ── Rule-based provider (static policy → cheap) ───────────────
#
# Two-layer permission: static rules absorb the bulk
# of routine tool calls (no human round-trip), and an underlying
# provider handles whatever the rules do not decide. This drops
# approval UI traffic dramatically for sessions where the user has
# pre-declared trusted operations (e.g. "always allow reads",
# "never allow rm -rf").


@dataclass(frozen=True, slots=True)
class ApprovalRule:
    """A single allow/deny rule.

    ``tool`` is matched with ``fnmatch`` against ``ApprovalRequest.tool_name``
    (``"*"`` = any). ``args_contains``, if non-empty, requires the
    substring to appear in ``args_preview`` (cheap containment check —
    deliberately not a regex, the rule set is expected to stay small
    and auditable).
    """

    effect: Literal["allow", "deny"]
    tool: str = "*"
    args_contains: str = ""
    reason: str = ""

    def matches(self, req: ApprovalRequest) -> bool:
        if not fnmatch.fnmatchcase(req.tool_name, self.tool):
            return False
        if self.args_contains and self.args_contains not in req.args_preview:  # noqa: SIM103 — early-return guards read better
            return False
        return True


@dataclass(frozen=True, slots=True)
class ApprovalPolicy:
    """Ordered rule list. First match wins; miss → fallback provider."""

    rules: tuple[ApprovalRule, ...] = field(default_factory=tuple)

    def decide(self, req: ApprovalRequest) -> ApprovalDecision | None:
        for rule in self.rules:
            if rule.matches(req):
                return ApprovalDecision(
                    approved=(rule.effect == "allow"),
                    reason=rule.reason or f"rule:{rule.effect}:{rule.tool}",
                )
        return None


class RuleBasedProvider(ApprovalProvider):
    """Decorator that consults a static policy before delegating.

    A hit on the policy short-circuits; a miss falls through to
    ``fallback`` (typically a UI-backed provider or AutoDeny).
    """

    def __init__(self, policy: ApprovalPolicy, fallback: ApprovalProvider) -> None:
        self._policy = policy
        self._fallback = fallback

    def request(self, req: ApprovalRequest, *, timeout: float = 120.0) -> ApprovalDecision:
        decision = self._policy.decide(req)
        if decision is not None:
            _logger.debug(
                "RuleBasedProvider short-circuit: %s → %s (%s)",
                req.tool_name,
                "allow" if decision.approved else "deny",
                decision.reason,
            )
            return decision
        return self._fallback.request(req, timeout=timeout)


__all__ = [
    "ApprovalDecision",
    "ApprovalPolicy",
    "ApprovalProvider",
    "ApprovalRisk",
    "ApprovalRiskAction",
    "ApprovalRiskLevel",
    "ApprovalRiskPolicy",
    "ApprovalRequest",
    "ApprovalRule",
    "AutoApproveProvider",
    "AutoDenyProvider",
    "DANGEROUS_PREFIXES",
    "DANGEROUS_TOOLS",
    "RuleBasedProvider",
    "approval_action_for_tool",
    "assess_approval_risk",
    "is_dangerous_tool",
    "needs_approval",
    "needs_approval_for_chain",
]
