
from __future__ import annotations

import contextlib
import hashlib
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from runtime.core.nerves.hooks import HookManager

from runtime.adapters.instrumentation import trace_stage
from runtime.execution.misc.file_write_leases import (
    FileWriteLeaseConflict,
    acquire_file_write_lease,
)
from runtime.execution.suckers import Skill, SkillRegistry
from runtime.execution.tool_engine.skill_gate import (
    antigen_for,
    canonical_tool_path,
    file_safety_target,
    use_trust_engine,
)
from runtime.memory.journal import InMemoryJournal, Journal
from runtime.platform.models import (
    ArmId,
    Budget,
    CostEntry,
    ExecutionResult,
    ExecutionStatus,
    InsufficientBudget,
    SkillId,
    Step,
    TaskId,
    ToolCall,
)
from runtime.platform.process.utils import safe_repr as _safe_repr
from runtime.safety.approval.approval_gate import injection_taint_block
from runtime.safety.auth import (
    TrustEngine,
    check_file_write,
    strip_model_controlled_overrides,
)
from runtime.safety.validation.prompt_injection import (
    is_untrusted_tool,
    mark_injection_taint,
    scan_for_injection,
)

_READ_BEFORE_WRITE_TOOLS = frozenset({
    "write_text_file",
    "edit_text_file",
    "edit_file",
    "multi_edit_file",
})
_READ_TRACKING_KEY = "_read_file_paths_this_turn"
_TRANSIENT_ERROR_NAME_HINTS = (
    "Timeout",
    "Connection",
    "Network",
    "RateLimit",
    "Retry",
    "Temporary",
    "Transient",
)


def _validate_output(output: dict, schema: dict) -> None:
    required = schema.get("required", [])
    properties = schema.get("properties", {})
    for key in required:
        if key not in output:
            raise ValueError(f"missing required field: {key}")
    for key, prop in properties.items():
        if key not in output:
            continue
        expected_type = prop.get("type")
        val = output[key]
        if expected_type == "string" and not isinstance(val, str):
            raise ValueError(f"field {key}: expected string, got {type(val).__name__}")
        if expected_type == "number" and not isinstance(val, (int, float)):
            raise ValueError(f"field {key}: expected number, got {type(val).__name__}")
        if expected_type == "boolean" and not isinstance(val, bool):
            raise ValueError(f"field {key}: expected boolean, got {type(val).__name__}")
        if expected_type == "array" and not isinstance(val, list):
            raise ValueError(f"field {key}: expected array, got {type(val).__name__}")
        if expected_type == "object" and not isinstance(val, dict):
            raise ValueError(f"field {key}: expected object, got {type(val).__name__}")


def _is_transient_tool_exception(exc: BaseException) -> bool:
    if isinstance(exc, (TimeoutError, ConnectionError)):
        return True
    name = type(exc).__name__
    return any(hint in name for hint in _TRANSIENT_ERROR_NAME_HINTS)


def _call_handler_with_transient_retry(
    handler: Any,
    args: dict[str, Any],
) -> tuple[Any, list[str]]:
    try:
        return handler(**args), []
    except Exception as exc:  # noqa: BLE001 - retry classifier needs arbitrary skill exceptions
        if not _is_transient_tool_exception(exc):
            raise
        retry_tag = f"transient_retry:{type(exc).__name__}"
        return handler(**args), [retry_tag]


class StepExecutionError(RuntimeError):
    pass


class ReadBeforeWriteRequired(RuntimeError):
    pass


class ToolExecutor:
    """Skill-step executor with read-before-write + diff/rollback wiring.

    ╔════════════════════════════════════════════════════════════════════╗
    ║ executor.py · navigation map (1348 lines).                         ║
    ║                                                                    ║
    ║   §1 helpers (_validate_output, retry classifier)  ~L54            ║
    ║   §2 ToolExecutor (the main class, ~775 lines)     ~L105           ║
    ║   §3 token usage extraction                        ~L880           ║
    ║   §4 read-before-write enforcement                 ~L920           ║
    ║   §5 file-write lease tracking                     ~L950           ║
    ║   §6 path canonicalisation + workspace resolve     ~L996           ║
    ║   §7 reject-step builders + capability check       ~L1043          ║
    ║   §8 output hashing + path extraction              ~L1076          ║
    ║   §9 diff computation + rollback payload           ~L1151          ║
    ║   §10 file_op event emission                       ~L1261          ║
    ╚════════════════════════════════════════════════════════════════════╝
    """

    def __init__(
        self,
        registry: SkillRegistry,
        immunity: TrustEngine,
        journal: Journal | None = None,
        *,
        hooks: HookManager | None = None,
        budget_tracker: Any = None,
    ) -> None:
        self.registry = registry
        self.immunity = immunity
        self.journal = journal if journal is not None else InMemoryJournal()
        self.hooks = hooks  # Implementation note.
        # Session-level cumulative budget tracker (Round 18 primitive).
        # When provided, every successful step's cost is recorded into
        # the per-session ledger keyed off ``current_session().session_id``.
        # ``None`` (default) preserves prior behaviour — no session-level
        # tracking, only per-task ``Budget`` accounting.
        self._budget_tracker = budget_tracker


    def execute_step(
        self,
        step_id: int,
        node_id: str,
        sucker_id: SkillId,
        args: dict[str, Any],
        *,
        caller: str,
        task_id: TaskId,
        arm_id: ArmId,
        budget: Budget,
        predicted_cost: CostEntry | None = None,
        actor: str | None = None,
    ) -> Step:
        with trace_stage(
            "beak.execute_step",
            stage="execute",
            task_id=str(task_id),
            arm_id=arm_id,
        ) as span:
            span.set_attribute("octopus.sucker_id", sucker_id)
            span.set_attribute("octopus.node_id", node_id)
            if actor:
                span.set_attribute("octopus.actor", actor)

            # Drop model-controllable privilege-escalation flags before the
            # args reach the ToolCall record, the journal, or
            # ``handler(**args)``. The published tool schema hides
            # ``allow_sensitive`` but is ``additionalProperties: True``, so a
            # model — or an indirect prompt injection in tool output — could
            # otherwise smuggle ``allow_sensitive`` / ``allow_private`` in to
            # defeat the sensitive-file / SSRF guards. Trusted internal callers
            # set these by invoking handlers directly, never via execute_step.
            args, _stripped_overrides = strip_model_controlled_overrides(args)
            if _stripped_overrides:
                span.set_attribute(
                    "octopus.args.stripped_overrides",
                    ",".join(_stripped_overrides),
                )

            skill = self.registry.get(sucker_id)
            if not self.registry.is_enabled(sucker_id):
                call = ToolCall(
                    caller=caller,
                    sucker_id=sucker_id,
                    args=args,
                    predicted_cost=predicted_cost,
                )
                step = _make_reject_step(
                    step_id,
                    node_id,
                    call,
                    "failed",
                    f"skill disabled: {sucker_id}",
                )
                self.journal.write_step(task_id, arm_id, step, actor=actor)
                span.set_attribute("octopus.skill.disabled", True)
                return step

            # Auto-fill predicted_cost from adaptive immunity baseline when
            # the caller doesn't supply one. This activates the pre-execute
            # anomaly detection path in TrustEngine.check() — without it,
            # compute_risk() sees zero predictions and stays in cold-start.
            if predicted_cost is None and self.immunity.adaptive is not None:
                predicted_cost = self.immunity.adaptive.predict(str(sucker_id))

            call = ToolCall(
                caller=caller,
                sucker_id=sucker_id,
                args=args,
                predicted_cost=predicted_cost,
            )
            sig = antigen_for(skill)

            allowed_by_capability, capability_reason = _check_capability_permission(
                sucker_id,
            )
            if not allowed_by_capability:
                self.journal.write_immune(
                    verdict="reject",
                    signature=sig,
                    task_id=task_id,
                    arm_id=arm_id,
                    actor=actor,
                    reason=capability_reason or "capability disabled",
                )
                span.set_attribute("octopus.immunity.verdict", "reject")
                span.set_attribute(
                    "octopus.capability.blocked",
                    capability_reason or "capability disabled",
                )
                step = _make_reject_step(
                    step_id,
                    node_id,
                    call,
                    "immune_reject",
                    capability_reason or "capability disabled",
                )
                self.journal.write_step(task_id, arm_id, step, actor=actor)
                return step

            # Indirect prompt-injection taint gate (chokepoint). Every
            # execution path crosses execute_step, so enforcing here closes
            # the paths (parallel dispatch, agentic-fallback, subagents)
            # that don't run their own approval gate: a risky tool can't
            # run after untrusted content carried injection markers into the
            # turn, unless an approval-capable loop already reviewed it.
            _inj_block = injection_taint_block(str(sucker_id), str(args)[:500])
            if _inj_block is not None:
                span.set_attribute("octopus.injection.blocked", _inj_block)
                step = _make_reject_step(
                    step_id, node_id, call, "immune_reject",
                    f"injection_taint_block: {_inj_block}",
                )
                self.journal.write_step(task_id, arm_id, step, actor=actor)
                return step

            report = self.immunity.check(call, sig)
            self.journal.write_immune(
                verdict=report.verdict,
                signature=sig,
                task_id=task_id,
                arm_id=arm_id,
                actor=actor,
                reason=report.reason,
            )
            span.set_attribute("octopus.immunity.verdict", report.verdict)

            if report.verdict == "reject":
                step = _make_reject_step(step_id, node_id, call, "immune_reject")
                self.journal.write_step(task_id, arm_id, step, actor=actor)
                # Notify monitoring · immune system blocked a call.
                # Best-effort · cannot rail the reject path.
                try:
                    from runtime.platform.process.session import (
                        current_session as _cs_im,
                    )
                    from runtime.safety.hooks.runner import (
                        dispatch_notification,
                    )
                    dispatch_notification(
                        kind="immune_reject",
                        details={
                            "task_id": str(task_id),
                            "arm_id": str(arm_id),
                            "sucker_id": str(sucker_id),
                            "trusted_source": skill.trusted_source,
                            "reason": report.reason or "",
                        },
                        session=_cs_im(),
                    )
                except (TypeError, ValueError, AttributeError):  # noqa: BLE001
                    pass
                return step

            est = predicted_cost or CostEntry(tokens_in=100, tokens_out=100, usd=0.001)
            try:
                reservation = budget.reserve(est)
            except InsufficientBudget as e:
                step = _make_reject_step(step_id, node_id, call, "circuit_broken", str(e))
                self.journal.write_step(task_id, arm_id, step, actor=actor)
                self.journal.write_budget(
                    "budget_squirt",
                    task_id=task_id,
                    actor=actor,
                    reason=str(e),
                )
                # Community hook notification · circuit-breaker fired.
                # Monitoring / alerting subscribers pick this up to
                # ring pages without having to tail the journal.
                try:
                    from runtime.platform.process.session import (
                        current_session as _cs_sq,
                    )
                    from runtime.safety.hooks.runner import (
                        dispatch_notification,
                    )
                    dispatch_notification(
                        kind="budget_squirt",
                        details={
                            "task_id": str(task_id),
                            "arm_id": str(arm_id),
                            "sucker_id": str(sucker_id),
                            "reason": str(e),
                            "usd_spent": budget.usd_spent,
                            "tokens_spent": budget.tokens_spent,
                        },
                        session=_cs_sq(),
                    )
                except (TypeError, ValueError, AttributeError):  # noqa: BLE001
                    pass
                return step

            pre_result: ExecutionResult | None = None
            if self.hooks is not None:
                from runtime.core.nerves.hooks import HookContext, HookError

                pre_ctx = HookContext(
                    phase="pre", task_id=task_id, arm_id=arm_id,
                    sucker_id=sucker_id, node_id=node_id, step_id=step_id,
                    call=call, result=None,
                )
                try:
                    pre_out = self.hooks.run_pre(pre_ctx)
                    if pre_out is not None and pre_out.replace_with is not None:
                        pre_result = pre_out.replace_with
                except HookError as he:
                    budget.commit(reservation, CostEntry())
                    self.journal.write_budget("budget_commit", task_id=task_id, actor=actor)
                    step = _make_reject_step(
                        step_id, node_id, call, "failed",
                        reason=f"hook_block: {he.reason}",
                    )
                    self.journal.write_step(task_id, arm_id, step, actor=actor)
                    span.set_attribute("octopus.hook.blocked", he.reason)
                    return step

            pre_content: str | None = None
            pre_exists = False
            if "file" in (skill.affinity or []):
                _pre_path = _extract_path(args, None)
                if _pre_path:
                    with contextlib.suppress(OSError, ValueError):
                        pre_exists = Path(_pre_path).is_file()
                pre_content = _try_read_pre_content(_pre_path)
            t0 = time.monotonic()

            # 6a. PUBLIC PreToolUse hook · pre/post tool lifecycle
            # event · community handlers can cancel or rewrite args here.
            # Runs BEFORE legacy self.hooks pre_result branch so a
            # community hook can still override · returns None if no
            # handler registered (cheap no-op).
            hook_cancel: str | None = None
            try:
                from runtime.platform.process.session import current_session as _cs
                from runtime.safety.hooks.runner import dispatch_pre_tool
                pre_decision = dispatch_pre_tool(
                    sucker_id=str(sucker_id),
                    args=args,
                    caller=caller,
                    session=_cs(),
                )
                if pre_decision.cancelled:
                    hook_cancel = pre_decision.reason or "pre_tool_hook_cancelled"
                elif pre_decision.modified_args is not None:
                    args = pre_decision.modified_args
            except (TypeError, ValueError, RuntimeError):  # noqa: BLE001 — pre-tool hook best-effort
                pass

            if hook_cancel is not None:
                budget.commit(reservation, CostEntry())
                self.journal.write_budget(
                    "budget_commit", task_id=task_id, actor=actor,
                )
                step = _make_reject_step(
                    step_id, node_id, call, "failed",
                    reason=f"hook_cancel: {hook_cancel}",
                )
                self.journal.write_step(task_id, arm_id, step, actor=actor)
                span.set_attribute("octopus.hook.cancelled", hook_cancel)
                return step

            if pre_result is not None:
                output = pre_result.output
                status = pre_result.status
                error_type = pre_result.error_type
                stderr_tags = list(pre_result.stderr_tags) + ["pre_hook_replaced"]
            else:
                try:
                    # Opt-in Session injection · if a skill handler
                    # declares a `session` parameter, pass the current
                    # Session to it (spares the handler an inline
                    # `current_session()` lookup). Old handlers without
                    # the param keep working — we detect via inspect.
                    import inspect as _inspect
                    handler_params: dict[str, Any] = {}
                    try:
                        sig = _inspect.signature(skill.handler)
                        handler_params = dict(sig.parameters)
                    except (TypeError, ValueError):
                        handler_params = {}

                    if (
                        "session" in handler_params
                        and "session" not in args
                    ):
                        from runtime.platform.process.session import current_session
                        args = {**args, "session": current_session()}

                    # Mode-gated sandbox injection / enforcement.
                    # Any skill whose handler declares ``sandbox_dir``
                    # participates in the permission domain: if the LLM
                    # didn't pass one, fill in the scope's primary root
                    # (per-agent/per-thread workspace) · if it DID pass
                    # one, reject the call when the path escapes the
                    # scope's allowed roots.
                    # Same gate covers chat/team/code — the scope
                    # resolver itself encodes which tier the turn has
                    # · so this block stays mode-agnostic.
                    # Directory-base parameter names that mean "where
                    # to start scanning / listing / globbing". When the
                    # LLM omits them (or passes ``"."``), we want them
                    # to default to the user's selected workspace, not
                    # to whatever cwd uvicorn happened to start from.
                    # This is what makes "analyze the code in this
                    # folder" actually scan the folder the user picked
                    # in the WorkDirSelector, instead of hitting the
                    # project root by accident.
                    _root_params = (
                        "root", "cwd", "working_dir", "directory", "base_dir",
                        "repo_dir",
                    )
                    # Parameters that carry a file/directory path (not a
                    # directory-base). When the LLM passes a relative path
                    # like "src/main.py" or just ".", we resolve it against
                    # scope.primary so it lands in the user's workspace
                    # instead of the process CWD (which is typically the
                    # octopus-agent project root — the exact bug where
                    # "analyze this project" scanned octopus-agent itself).
                    _path_params = ("path", "filepath", "file_path", "filename")
                    has_sandbox = "sandbox_dir" in handler_params
                    has_root_param = any(
                        p in handler_params for p in _root_params
                    )
                    has_path_param = any(
                        p in handler_params for p in _path_params
                    )

                    if has_sandbox or has_root_param or has_path_param:
                        from runtime.platform.process.session import (
                            current_session,
                        )
                        _sess = current_session()
                        # Scope is only enforced when a Session is
                        # bound. Direct callers (tests, programmatic
                        # runtime use without the compat router)
                        # bypass the mode ladder — the Session is what
                        # carries mode/agent/team_id/extras, and
                        # without it we have no tier to gate against.
                        # The old "LLM chooses sandbox_dir" contract
                        # still applies on that path.
                        if _sess is not None:
                            from runtime.platform.process.scope import (
                                resolve_execution_scope,
                            )
                            scope = resolve_execution_scope(_sess)
                            read_primary = scope.primary_read
                            _mutates_files = bool(
                                set(skill.affinity or [])
                                & {"write", "edit", "exec", "dangerous"}
                            )
                            arg_primary = (
                                scope.primary_write if _mutates_files else read_primary
                            )
                            # Read-side root injection · only fires
                            # for skills that accept a directory-base
                            # parameter. Symmetric with the write-side
                            # ``sandbox_dir`` defaulting below: if the
                            # LLM didn't supply the root (or supplied
                            # the meaningless ``"."``), inject
                            # ``scope.primary`` so the read scans the
                            # user's selected folder.
                            if has_root_param and arg_primary is not None:
                                for _rp in _root_params:
                                    if _rp not in handler_params:
                                        continue
                                    _supplied = args.get(_rp)
                                    if _supplied in (None, "", ".", "./"):
                                        args = {
                                            **args,
                                            _rp: str(arg_primary),
                                        }
                                        break

                            # Path-param injection · for skills where
                            # the param name is "path" (not "root").
                            # When the LLM passes a relative path, resolve
                            # it against scope.primary so the skill reads
                            # from the user's workspace, not the process CWD.
                            if has_path_param and arg_primary is not None:
                                for _pp in _path_params:
                                    if _pp not in handler_params:
                                        continue
                                    _supplied = args.get(_pp)
                                    if _supplied is None or _supplied == "":
                                        continue
                                    if _supplied == "." or _supplied == "./":
                                        args = {**args, _pp: str(arg_primary)}
                                        break
                                    _supplied_str = str(_supplied)
                                    if not Path(_supplied_str).is_absolute():
                                        args = {
                                            **args,
                                            _pp: str(arg_primary / _supplied_str),
                                        }
                                        break

                            # Write-side · only relevant for skills
                            # whose handler accepts ``sandbox_dir``.
                            if has_sandbox:
                                # Plan mode · empty roots · EVERY write
                                # call rejected. Caller must transition
                                # out via ``exit_plan_mode`` skill.
                                if scope.primary_write is None:
                                    raise PermissionError(
                                        f"write skill {sucker_id!r} blocked: "
                                        f"thread is in '{scope.mode}' mode "
                                        "(no write scope). Call "
                                        "'exit_plan_mode' first with a confirmed "
                                        "plan summary to transition to chat / "
                                        "team / code mode."
                                    )
                                supplied = args.get("sandbox_dir")
                                default_sandbox = (
                                    scope.primary_write if _mutates_files else read_primary
                                )
                                if not supplied:
                                    # Lazily create the primary root so
                                    # the skill can open files there
                                    # without having to mkdir itself.
                                    if _mutates_files:
                                        with contextlib.suppress(OSError):
                                            scope.primary_write.mkdir(
                                                parents=True, exist_ok=True,
                                            )
                                    args = {
                                        **args,
                                        "sandbox_dir": str(default_sandbox),
                                    }
                                elif not (
                                    scope.allows_write(supplied)
                                    if _mutates_files
                                    else scope.allows_read(supplied)
                                ):
                                    raise PermissionError(
                                        f"sandbox_dir {supplied!r} escapes "
                                        f"write scope (mode={scope.mode}, "
                                        f"requested_mode={scope.requested_mode}, "
                                        f"writable_roots="
                                        f"{[str(r) for r in scope.writable_roots]}, "
                                        f"readable_roots="
                                        f"{[str(r) for r in scope.readable_roots]}, "
                                        f"workspace_path="
                                        f"{(_sess.metadata or {}).get('workspace_path', 'NOT SET')}"
                                        "). If workspace_path is NOT SET, "
                                        "the session lost its code-mode context. "
                                        "Try opening a new code thread "
                                        "with the correct workspace selected."
                                    )
                    _read_guard_reason = _read_before_write_violation(
                        str(sucker_id),
                        args,
                    )
                    if _read_guard_reason is not None:
                        raise ReadBeforeWriteRequired(_read_guard_reason)
                    # Credential-file denylist. Write scope decides
                    # *where* a skill may write; this decides *what it may
                    # never name* — .env, id_rsa, ~/.ssh/*, /etc/shadow,
                    # etc. — regardless of scope. A sandbox-scoped write to
                    # a `.env` is in-scope yet still a credential write, so
                    # this layer is complementary, not redundant.
                    _fs_target = file_safety_target(skill, args)
                    if _fs_target is not None:
                        _fs_verdict = check_file_write(_fs_target)
                        if not _fs_verdict.allow:
                            raise PermissionError(
                                f"write skill {sucker_id!r} blocked by "
                                f"file-safety: {_fs_verdict.reason}"
                            )
                    _lease_target = _file_write_lease_target(skill, args)
                    if _lease_target is not None:
                        from runtime.platform.process.session import current_session
                        acquire_file_write_lease(
                            current_session(),
                            _lease_target,
                            owner=_file_write_lease_owner(
                                actor=actor,
                                arm_id=arm_id,
                                caller=caller,
                            ),
                        )
                    # Bind the runtime TrustEngine as the ambient engine for
                    # the handler call. A meta-skill (use_capability / forged
                    # composite) dispatches to an inner handler DIRECTLY,
                    # bypassing this execute_step; binding here lets that
                    # nested dispatch run the SAME immunity policy via
                    # skill_gate.gate_inner_dispatch.
                    with use_trust_engine(self.immunity):
                        output, retry_tags = _call_handler_with_transient_retry(
                            skill.handler,
                            args,
                        )
                    status: ExecutionStatus = "success"
                    error_type: str | None = None
                    stderr_tags: list[str] = retry_tags
                    _record_successful_read(str(sucker_id), args, output)
                    # Taint the turn (chokepoint) if this tool's output is
                    # external/untrusted and carries injection markers, so a
                    # LATER risky tool on ANY path is gated. Setting it here
                    # (not only in react_loop) covers the agentic-fallback
                    # and subagent paths that never reach react_loop's
                    # observation-wrap sites.
                    if is_untrusted_tool(
                        str(sucker_id),
                        list(skill.affinity or []),
                        args if isinstance(args, dict) else None,
                    ):
                        _inj_scan = scan_for_injection(str(output))
                        if _inj_scan.flagged:
                            mark_injection_taint(_inj_scan.severity)
                    # ── Structured output validation ──────
                    _output_schema = getattr(skill, "output_schema", None)
                    if (
                        _output_schema
                        and isinstance(_output_schema, dict)
                        and isinstance(output, dict)
                        and status == "success"
                    ):
                        try:
                            _validate_output(output, _output_schema)
                        except ValueError as ve:
                            stderr_tags.append("schema_mismatch")
                            span.set_attribute(
                                "octopus.output_schema.error", str(ve),
                            )
                except ReadBeforeWriteRequired as e:
                    output = {"error": str(e)}
                    status = "failed"
                    error_type = "read_before_write_required"
                    stderr_tags = [error_type, str(e)]
                except FileWriteLeaseConflict as e:
                    output = {"error": str(e)}
                    status = "failed"
                    error_type = "FileWriteLeaseConflict"
                    stderr_tags = ["file_write_lease_conflict", str(e)]
                except TimeoutError:
                    output = None
                    status = "timeout"
                    error_type = "timeout"
                    stderr_tags = []
                except PermissionError as e:
                    # Write-scope escapes and file-safety denials both
                    # surface here. Preserve the reason in output/tags so
                    # the block is attributable (the catch-all below would
                    # drop the message, keeping only the type name).
                    output = {"error": str(e)}
                    status = "failed"
                    error_type = "PermissionError"
                    stderr_tags = ["permission_denied", str(e)]
                except Exception as e:  # noqa: BLE001 - we want to capture arbitrary handler errors
                    output = None
                    status = "failed"
                    error_type = type(e).__name__
                    stderr_tags = [error_type]

            latency_ms = (time.monotonic() - t0) * 1000

            #
            # Real tokens take priority over the ``est`` placeholder when
            # the skill output surfaces them. Convention: an LLM-coupled
            # skill returns a dict with ``"cost": {input_tokens, output_tokens}``
            # (e.g. ``deep_evolve``) OR ``"meta": {input_tokens, output_tokens}``
            # (e.g. ``deep_reflect`` / ``learn_skill_from_text``). If
            # neither key is present (atomic skills · tool_use handlers
            # that don't call LLMs) we fall back to the ``est`` values,
            # which for atomic skills are close to zero anyway.
            _real_in, _real_out = _extract_token_usage(output)
            if _real_in > 0 or _real_out > 0:
                actual_cost = CostEntry(
                    tokens_in=_real_in,
                    tokens_out=_real_out,
                    usd=est.usd,  # usd estimation still from predicted_cost
                    latency_ms=latency_ms,
                )
            else:
                actual_cost = CostEntry(
                    tokens_in=est.tokens_in,
                    tokens_out=est.tokens_out,
                    usd=est.usd,
                    latency_ms=latency_ms,
                )
            budget.commit(reservation, actual_cost)
            # Feed the adaptive-immunity baseline (protocols/immunity.md
            # Execute-time learning loop). No-op unless the adaptive tier
            # is enabled; builds the per-sucker latency/token baseline
            # from observed cost. Best-effort — must never break a
            # successful tool result.
            learn = getattr(self.immunity, "learn", None)
            if callable(learn):
                with contextlib.suppress(Exception):
                    learn(
                        call,
                        latency_ms=latency_ms,
                        tokens=float(actual_cost.tokens_in + actual_cost.tokens_out),
                    )
            self.journal.write_budget(
                "budget_commit",
                task_id=task_id,
                actor=actor,
                cost=actual_cost,
            )

            # Notify community hooks when the budget crosses 80% / 95%
            # utilization · at most once per level per Budget. Best-
            # effort · dispatch exceptions can't rail the commit path.
            try:
                crossings = budget.check_warn_crossing()
                if crossings:
                    from runtime.platform.process.session import (
                        current_session as _cs_warn,
                    )
                    from runtime.safety.hooks.runner import (
                        dispatch_notification,
                    )
                    for level in crossings:
                        dispatch_notification(
                            kind="budget_warn",
                            details={
                                "level_pct": level,
                                "task_id": str(task_id),
                                "arm_id": str(arm_id),
                                "utilization": budget.utilization,
                                "usd_spent": budget.usd_spent,
                                "tokens_spent": budget.tokens_spent,
                                "usd_limit": budget.limits.usd,
                                "tokens_limit": budget.limits.tokens,
                            },
                            session=_cs_warn(),
                        )
            except (TypeError, ValueError, RuntimeError):  # noqa: BLE001
                pass

            result = ExecutionResult(
                call_id=call.call_id,
                status=status,
                output=_safe_repr(output),
                output_hash=_hash_output(output),
                error_type=error_type,
                stderr_tags=stderr_tags,
                cost=actual_cost,
            )

            # 8a. PUBLIC PostToolUse hook · community handlers can
            # rewrite the output (e.g. scrub secrets before it reaches
            # the planner). Cancel is not meaningful post-hoc · any
            # side effect already happened · we honor modified_output
            # only.
            try:
                from runtime.platform.process.session import current_session as _cs2
                from runtime.safety.hooks.runner import dispatch_post_tool
                post_decision = dispatch_post_tool(
                    sucker_id=str(sucker_id),
                    args=args,
                    output=output,
                    success=(status == "success"),
                    session=_cs2(),
                )
                if post_decision.modified_output is not None:
                    # re-hash · keep ExecutionResult self-consistent
                    result = ExecutionResult(
                        call_id=call.call_id,
                        status=status,
                        output=_safe_repr(post_decision.modified_output),
                        output_hash=_hash_output(post_decision.modified_output),
                        error_type=error_type,
                        stderr_tags=stderr_tags + ["post_hook_rewrote"],
                        cost=actual_cost,
                    )
            except (TypeError, ValueError, RuntimeError):  # noqa: BLE001
                pass

            # 8b. Post-write diagnostics · auto-trigger ruff/eslint and
            # attach a targeted regression matrix after successful writes.
            # Output is appended to ``result.output`` (frozen model ·
            # re-built via ``model_copy``) so the model sees lint feedback
            # and knows which verification commands fit the changed file.
            # Best-effort · hook helpers never raise into the executor.
            if status == "success" and str(sucker_id) in _READ_BEFORE_WRITE_TOOLS | {
                "append_text_file",
            }:
                try:
                    from runtime.safety.hooks.tool_edge_hooks import (
                        post_write_diagnostics,
                        post_write_regression_matrix,
                    )
                    workspace_path = _resolve_workspace_for_diagnostics(args)
                    if workspace_path is not None:
                        diag = post_write_diagnostics(
                            str(sucker_id),
                            args,
                            output if isinstance(output, dict) else {"path": _extract_path(args, output)},
                            workspace_path=workspace_path,
                        )
                        matrix = post_write_regression_matrix(
                            str(sucker_id),
                            args,
                            output if isinstance(output, dict) else {"path": _extract_path(args, output)},
                            workspace_path=workspace_path,
                        )
                        if diag:
                            new_output_text = (
                                (result.output or "")
                                + ("\n\n" if result.output else "")
                                + "[post-write diagnostics]\n"
                                + diag
                            )
                            result = result.model_copy(
                                update={
                                    "output": new_output_text,
                                    "stderr_tags": list(result.stderr_tags)
                                    + ["post_diagnostics"],
                                }
                            )
                        if matrix:
                            new_output_text = (
                                (result.output or "")
                                + ("\n\n" if result.output else "")
                                + "[regression matrix]\n"
                                + matrix
                            )
                            result = result.model_copy(
                                update={
                                    "output": new_output_text,
                                    "stderr_tags": list(result.stderr_tags)
                                    + ["regression_matrix"],
                                }
                            )
                except (TypeError, ValueError, RuntimeError):  # noqa: BLE001
                    pass

            if self.hooks is not None:
                from runtime.core.nerves.hooks import HookContext

                post_ctx = HookContext(
                    phase="post", task_id=task_id, arm_id=arm_id,
                    sucker_id=sucker_id, node_id=node_id, step_id=step_id,
                    call=call, result=result,
                )
                post_out = self.hooks.run_post(post_ctx)
                if post_out is not None and post_out.replace_with is not None:
                    result = post_out.replace_with
            step = Step(
                step_id=step_id,
                node_id=node_id,
                action=call,
                result=result,
                immune_verdict=report.verdict,
            )

            # Beak-level metrics. Increment counters + record latency
            # so the /metrics endpoint reflects skill-execution shape
            # without requiring a separate emitter on every call site.
            # Best-effort: a metrics-registry import failure must NOT
            # break execution.
            try:
                from runtime.platform.observability.metrics import get_registry as _mr
                _reg = _mr()
                _calls = _reg.counter(
                    "octopus_skill_calls_total",
                    "Total skill invocations",
                    labels=["sucker_id", "status"],
                )
                _calls.inc(labels={"sucker_id": str(sucker_id), "status": str(status)})
                _lat = _reg.histogram(
                    "octopus_skill_latency_seconds",
                    "Skill invocation latency (seconds)",
                    labels=["sucker_id"],
                )
                _lat.observe(
                    latency_ms / 1000.0,
                    labels={"sucker_id": str(sucker_id)},
                )
                if status != "success":
                    _errs = _reg.counter(
                        "octopus_skill_errors_total",
                        "Skill invocations that did not return success",
                        labels=["sucker_id", "error_type"],
                    )
                    _errs.inc(labels={
                        "sucker_id": str(sucker_id),
                        "error_type": str(error_type or "unknown"),
                    })
            except (TypeError, ValueError, RuntimeError):  # noqa: BLE001
                pass

            # Session-level cumulative budget tracking. Records the
            # actual cost of this step against the active session's
            # ledger so cross-task / cross-arm aggregates are visible
            # at /api/budget/sessions and warning callbacks fire at
            # 80% / 95% of the configured ceiling.
            #
            # ``Session.thread_id`` is the canonical per-chat key.
            # Fall back to ``turn_id`` so anonymous / legacy flows
            # still bucket coherently.
            #
            # Best-effort: any failure (no active session, no tracker
            # configured, BudgetExceeded raised by ceiling enforcement)
            # propagates only when ``BudgetExceeded`` was specifically
            # raised; otherwise we swallow so a misconfigured ledger
            # can't break execution.
            if self._budget_tracker is not None:
                try:
                    from runtime.platform.process.session import current_session as _cs_bt
                    _sess = _cs_bt()
                    _sid: str | None = None
                    if _sess is not None:
                        _sid = (
                            getattr(_sess, "thread_id", None)
                            or getattr(_sess, "conversation_id", None)
                            or getattr(_sess, "turn_id", None)
                        )
                    if _sid:
                        self._budget_tracker.record(_sid, actual_cost)
                except Exception as _bt_exc:  # noqa: BLE001
                    # Re-raise BudgetExceeded so the caller can stop;
                    # swallow everything else.
                    if type(_bt_exc).__name__ == "BudgetExceeded":
                        raise

            if status == "success" and "file" in (skill.affinity or []):
                with contextlib.suppress(Exception):
                    _emit_file_op_from_step(
                        journal=self.journal,
                        skill=skill,
                        args=args,
                        output=output,
                        task_id=task_id,
                        arm_id=arm_id,
                        actor=actor,
                        pre_content=pre_content,
                        pre_exists=pre_exists,
                    )
                    if isinstance(output, dict) and output.get("diff_preview"):
                        result = result.model_copy(
                            update={
                                "output": _safe_repr(output),
                                "output_hash": _hash_output(output),
                            }
                        )
                        step = step.model_copy(update={"result": result})

            self.journal.write_step(task_id, arm_id, step, actor=actor)

            span.set_attribute("octopus.execution.status", status)
            span.set_attribute("octopus.execution.latency_ms", latency_ms)
            return step


# ═══════════════════════════════════════════════════════════
# helpers
# ═══════════════════════════════════════════════════════════


def _extract_token_usage(output: Any) -> tuple[int, int]:
    """Pull real LLM token usage out of a skill's return value.

    Recognized conventions (first match wins):
      * ``output["cost"]["input_tokens"]`` / ``output["cost"]["output_tokens"]``
        (used by ``deep_evolve`` aggregating multiple inner LLM calls)
      * ``output["meta"]["input_tokens"]`` / ``output["meta"]["output_tokens"]``
        (used by ``deep_reflect``, ``learn_skill_from_text``,
        ``apply_skill`` — single-LLM-call skills)
      * top-level ``output["input_tokens"]`` / ``output["output_tokens"]``

    Returns ``(0, 0)`` if no usage info is present · falls back to the
    executor's estimate (close to zero for atomic skills).

    Defensive · never raises. An LLM-coupled skill that forgets to
    report tokens just under-charges its own budget slot; a malformed
    dict doesn't break the commit path.
    """
    if not isinstance(output, dict):
        return 0, 0
    for section in ("cost", "meta"):
        blk = output.get(section)
        if isinstance(blk, dict):
            _in = blk.get("input_tokens")
            _out = blk.get("output_tokens")
            if _in or _out:
                try:
                    return int(_in or 0), int(_out or 0)
                except (TypeError, ValueError):
                    continue
    _in = output.get("input_tokens")
    _out = output.get("output_tokens")
    if _in or _out:
        try:
            return int(_in or 0), int(_out or 0)
        except (TypeError, ValueError):  # noqa: BLE001 — token coercion fallthrough
            pass
    return 0, 0


def _read_before_write_violation(
    skill_name: str,
    args: dict[str, Any],
) -> str | None:
    if skill_name not in _READ_BEFORE_WRITE_TOOLS:
        return None
    target = canonical_tool_path(args)
    if target is None or not target.exists():
        return None

    try:
        from runtime.platform.process.session import current_session
        session = current_session()
    except (ImportError, AttributeError, RuntimeError):
        session = None
    if session is None:
        return None

    read_paths = session.metadata.get(_READ_TRACKING_KEY)
    if not isinstance(read_paths, list):
        read_paths = []
    target_key = _path_key(target)
    if target_key in set(str(p) for p in read_paths):
        return None
    return (
        f"refuse: must read_file('{target}') in this turn before writing "
        "to an existing file"
    )


def _file_write_lease_target(skill: Skill, args: dict[str, Any]) -> Path | None:
    affinity = set(skill.affinity or [])
    if "file" not in affinity:
        return None
    if not (affinity & {"write", "edit", "delete", "dangerous"}):
        return None
    return canonical_tool_path(args)


def _file_write_lease_owner(
    *,
    actor: str | None,
    arm_id: ArmId,
    caller: str,
) -> str:
    return str(actor or arm_id or caller or "unknown")


def _record_successful_read(
    skill_name: str,
    args: dict[str, Any],
    output: Any,
) -> None:
    if skill_name != "read_file":
        return
    if isinstance(output, dict) and output.get("error"):
        return
    path = canonical_tool_path(args)
    if path is None:
        return
    try:
        from runtime.platform.process.session import current_session
        session = current_session()
    except (ImportError, AttributeError, RuntimeError):
        session = None
    if session is None:
        return
    key = _path_key(path)
    read_paths = session.metadata.get(_READ_TRACKING_KEY)
    if not isinstance(read_paths, list):
        read_paths = []
        session.metadata[_READ_TRACKING_KEY] = read_paths
    if key not in set(str(p) for p in read_paths):
        read_paths.append(key)


def _path_key(path: Path) -> str:
    return str(path.resolve(strict=False)).casefold()


def _resolve_workspace_for_diagnostics(args: dict[str, Any]) -> str | None:
    """Pick a workspace root for ``post_write_diagnostics``.

    Prefers the active session's ``workspace_path`` (carried in
    ``Session.metadata`` for code-mode threads). Falls back to the
    write call's ``sandbox_dir`` / ``cwd``. Returns ``None`` when no
    plausible root is available — diagnostics simply skip in that
    case rather than scanning the process CWD.
    """
    try:
        from runtime.platform.process.session import current_session
        session = current_session()
    except (ImportError, AttributeError, RuntimeError):
        session = None
    if session is not None:
        try:
            wp = (session.metadata or {}).get("workspace_path")
        except AttributeError:
            wp = None
        if isinstance(wp, str) and wp.strip() and Path(wp).is_dir():
            return wp
    for key in ("sandbox_dir", "cwd"):
        cand = args.get(key)
        if isinstance(cand, str) and cand.strip() and Path(cand).is_dir():
            return cand
    return None


def _make_reject_step(
    step_id: int,
    node_id: str,
    call: ToolCall,
    status: ExecutionStatus,
    reason: str = "",
) -> Step:
    return Step(
        step_id=step_id,
        node_id=node_id,
        action=call,
        result=ExecutionResult(
            call_id=call.call_id,
            status=status,
            output=None,
            error_type=status,
            stderr_tags=[status] + ([reason] if reason else []),
        ),
        immune_verdict=status if status == "immune_reject" else None,
    )


def _check_capability_permission(skill_id: SkillId) -> tuple[bool, str | None]:
    try:
        from runtime.execution.misc.capability_permissions import is_skill_allowed

        return is_skill_allowed(str(skill_id))
    except (ImportError, AttributeError, TypeError, RuntimeError):  # noqa: BLE001 - permission layer must fail closed
        return False, "capability permission check failed"




def _hash_output(obj: Any) -> str | None:
    if obj is None:
        return None
    try:
        return hashlib.blake2b(repr(obj).encode("utf-8"), digest_size=8).hexdigest()
    except (TypeError, ValueError, RecursionError, UnicodeEncodeError):
        # Same tolerance as _safe_repr · an object we can't repr or
        # encode still shouldn't crash the step. None means "no
        # content hash for this step" · downstream dedup just skips.
        return None


# ═══════════════════════════════════════════════════════════
# FileOp extraction
# ═══════════════════════════════════════════════════════════


_ACTION_PRIORITY: list[tuple[str, str]] = [
    ("delete", "delete"),
    ("rename", "rename"),
    ("create", "create"),
    ("edit", "edit"),
    ("write", "write"),
]


def _infer_action(affinity: list[str], sucker_id: str) -> str:
    names = set(affinity or [])
    for tag, action in _ACTION_PRIORITY:
        if tag in names:
            return action
    # Fall back to sucker_id substring match
    low = sucker_id.lower()
    for tag, action in _ACTION_PRIORITY:
        if tag in low:
            return action
    return "write"


def _extract_path(args: dict[str, Any], output: Any) -> str:
    for key in ("path", "filepath", "file_path", "file", "target", "dest", "dest_path"):
        val = args.get(key)
        if isinstance(val, str) and val:
            return val
    if isinstance(output, dict):
        for key in ("path", "filepath", "file", "written"):
            val = output.get(key)
            if isinstance(val, str) and val:
                return val
    return ""


_FILE_DIFF_PRE_READ_LIMIT = 100_000   # Implementation note.
_FILE_DIFF_OUTPUT_LIMIT = 20_000      # Implementation note.
_FILE_DIFF_CONTEXT_LINES = 3          # Implementation note.
_FILE_ROLLBACK_CONTENT_LIMIT = 100_000


def _try_read_pre_content(path: str) -> str | None:
    if not path:
        return None
    import os
    try:
        if not os.path.isfile(path):
            return None
        size = os.path.getsize(path)
        if size > _FILE_DIFF_PRE_READ_LIMIT:
            return None
        with open(path, "rb") as fh:
            blob = fh.read(_FILE_DIFF_PRE_READ_LIMIT)
        return blob.decode("utf-8", errors="strict").replace("\r\n", "\n")
    except (OSError, ValueError):  # Implementation note.
        return None


def _compute_unified_diff(
    old: str, new: str, path: str,
) -> str | None:
    old_n = old.replace("\r\n", "\n")
    new_n = new.replace("\r\n", "\n")
    if old_n == new_n:
        return None
    old, new = old_n, new_n
    import difflib
    lines = list(difflib.unified_diff(
        old.splitlines(keepends=True),
        new.splitlines(keepends=True),
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
        n=_FILE_DIFF_CONTEXT_LINES,
    ))
    if not lines:
        return None
    diff = "".join(lines)
    if len(diff) > _FILE_DIFF_OUTPUT_LIMIT:
        head = diff[:_FILE_DIFF_OUTPUT_LIMIT]
        omitted = len(diff) - len(head)
        # Marker format is a wire contract: runtime/protocol/items.py
        # ``diff_is_truncated`` matches it to set FileChange.diff_truncated
        # downstream. Change both together.
        return head + f"\n... (truncated {omitted} bytes)\n"
    return diff


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _rollback_payload(
    *,
    path: str,
    action: str,
    pre_exists: bool,
    pre_content: str | None,
    new_content: str | None,
) -> dict[str, Any] | None:
    if action == "rename":
        return {
            "reversible": False,
            "reason": "rename_rollback_not_supported",
            "path": path,
        }
    if pre_exists and pre_content is None:
        return {
            "reversible": False,
            "reason": "previous_content_unavailable",
            "path": path,
        }
    if new_content is not None and len(new_content.encode("utf-8")) > _FILE_ROLLBACK_CONTENT_LIMIT:
        return {
            "reversible": False,
            "reason": "new_content_too_large",
            "path": path,
        }
    if pre_content is not None and len(pre_content.encode("utf-8")) > _FILE_ROLLBACK_CONTENT_LIMIT:
        return {
            "reversible": False,
            "reason": "previous_content_too_large",
            "path": path,
        }
    if action == "delete":
        if pre_content is None:
            return {
                "reversible": False,
                "reason": "deleted_content_unavailable",
                "path": path,
            }
        return {
            "reversible": True,
            "action": "write",
            "path": path,
            "content": pre_content,
            "expected_current_sha256": "",
            "before_sha256": _sha256_text(pre_content),
            "after_sha256": "",
        }
    if not pre_exists:
        if new_content is None:
            return {
                "reversible": False,
                "reason": "new_content_unavailable",
                "path": path,
            }
        return {
            "reversible": True,
            "action": "delete",
            "path": path,
            "expected_current_sha256": _sha256_text(new_content),
            "before_sha256": "",
            "after_sha256": _sha256_text(new_content),
        }
    if pre_content is None or new_content is None:
        return {
            "reversible": False,
            "reason": "content_unavailable",
            "path": path,
        }
    return {
        "reversible": True,
        "action": "write",
        "path": path,
        "content": pre_content,
        "expected_current_sha256": _sha256_text(new_content),
        "before_sha256": _sha256_text(pre_content),
        "after_sha256": _sha256_text(new_content),
    }


def _emit_file_op_from_step(
    *,
    journal: Journal,
    skill: Skill,
    args: dict[str, Any],
    output: Any,
    task_id: TaskId,
    arm_id: ArmId,
    actor: str | None,
    pre_content: str | None = None,
    pre_exists: bool = False,
) -> None:
    path = _extract_path(args, output)
    if not path:
        return  # Implementation note.
    action = _infer_action(list(skill.affinity), skill.name)

    new_size: int | None = None
    new_content: str | None = None
    if isinstance(output, dict):
        for key in ("bytes_written", "size", "new_size"):
            v = output.get(key)
            if isinstance(v, int):
                new_size = v
                break
        for key in ("content", "new_content", "written_content"):
            v = output.get(key)
            if isinstance(v, str):
                new_content = v
                break
    if new_content is None:
        raw = args.get("content") or args.get("text")
        if isinstance(raw, str):
            new_content = raw
    if new_size is None and new_content is not None:
        new_size = len(new_content.encode("utf-8"))

    diff: str | None = None
    readback_path = path
    if isinstance(output, dict):
        for key in ("path", "filepath", "file", "written"):
            val = output.get(key)
            if isinstance(val, str) and val:
                readback_path = val
                break
    if new_content is None and action != "delete":
        new_content = _try_read_pre_content(readback_path)
        if new_size is None and new_content is not None:
            new_size = len(new_content.encode("utf-8"))
    if new_content is not None and action != "delete":
        diff = _compute_unified_diff(
            pre_content or "", new_content, path,
        )
    elif action == "delete" and pre_content is not None:
        diff = _compute_unified_diff(pre_content, "", path)

    # Inline diff preview for chat tool-result bubbles. The frontend
    # message bubble already knows how to render ``result.diff_preview``
    # for write/edit tool calls; we just never populated it. Best-effort
    # only · never let preview generation break the main tool result.
    if diff and isinstance(output, dict) and "diff_preview" not in output:
        output["diff_preview"] = diff[:4000]

    old_size: int | None = None
    if pre_content is not None:
        old_size = len(pre_content.encode("utf-8"))
    rollback = _rollback_payload(
        path=path,
        action=action,
        pre_exists=pre_exists,
        pre_content=pre_content,
        new_content=new_content,
    )

    if not hasattr(journal, "write_file_op"):
        return
    journal.write_file_op(
        path=path,
        action=action,
        sucker_id=str(skill.name),
        task_id=task_id,
        arm_id=arm_id,
        actor=actor,
        old_size=old_size,
        new_size=new_size,
        diff=diff,
        rollback=rollback,
    )
