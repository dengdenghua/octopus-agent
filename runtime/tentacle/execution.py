"""Guarded Tentacle execution with leases, approval envelopes and receipts."""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from fnmatch import fnmatch
from typing import Any

from .base import Heartbeat, Tentacle, ToolCall, ToolResult
from .contract import ApprovalClass, ValueConstraint, manifest_for
from .pool import TentaclePool


@dataclass(frozen=True, slots=True)
class ActionGrant:
    """A pre-approved action range, narrower than the driver hard limits."""

    action: str
    constraints: tuple[ValueConstraint, ...] = ()

    def allows(self, action: str, arguments: dict[str, Any]) -> bool:
        return fnmatch(action, self.action) and not any(
            constraint.validate(arguments) for constraint in self.constraints
        )


@dataclass(frozen=True, slots=True)
class ApprovalEnvelope:
    envelope_id: str
    actor_id: str
    device_id: str
    grants: tuple[ActionGrant, ...]
    expires_at: float
    task_id: str | None = None

    @property
    def expired(self) -> bool:
        return time.time() >= self.expires_at

    def allows(self, device_id: str, action: str, arguments: dict[str, Any]) -> bool:
        if self.expired or self.device_id not in {device_id, "*"}:
            return False
        return any(grant.allows(action, arguments) for grant in self.grants)


@dataclass(frozen=True, slots=True)
class ExecutionReceipt:
    receipt_id: str
    call_id: str
    trace_id: str | None
    device_id: str
    action: str
    arguments: dict[str, Any]
    safety_errors: tuple[str, ...]
    approval_class: str
    envelope_id: str | None
    lease_id: str | None
    started_at: float
    finished_at: float
    success: bool
    error_code: int | None
    error_message: str | None
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {field_name: getattr(self, field_name) for field_name in self.__dataclass_fields__}


class ExecutionReceiptLedger:
    """Bounded in-memory ledger; durable sinks can consume ``append`` later."""

    def __init__(self, max_receipts: int = 2_000, on_append: Any = None) -> None:
        if max_receipts <= 0:
            raise ValueError("max_receipts must be positive")
        self._receipts: deque[ExecutionReceipt] = deque(maxlen=max_receipts)
        self._on_append = on_append

    def append(self, receipt: ExecutionReceipt) -> None:
        self._receipts.append(receipt)
        if self._on_append is not None:
            self._on_append(receipt)

    def list(self, *, device_id: str | None = None, limit: int = 100) -> list[ExecutionReceipt]:
        items = reversed(self._receipts)
        selected = (item for item in items if device_id is None or item.device_id == device_id)
        return list(selected)[: max(0, limit)]


async def _heartbeat_dict(device: Tentacle) -> dict[str, Any] | None:
    try:
        heartbeat: Heartbeat = await device.heartbeat()
        return heartbeat.to_dict()
    except Exception:  # noqa: BLE001 — telemetry must never mask action outcome
        return None


class DeviceActionExecutor:
    """The single guarded path for model-planned physical actions."""

    def __init__(self, pool: TentaclePool, ledger: ExecutionReceiptLedger | None = None) -> None:
        self.pool = pool
        self.ledger = ledger or ExecutionReceiptLedger()

    async def execute(
        self,
        device: Tentacle,
        call: ToolCall,
        *,
        envelope: ApprovalEnvelope | None = None,
        lease_owner: str | None = None,
    ) -> ToolResult:
        manifest = manifest_for(device)
        action = manifest.action(call.tool)
        safety_errors = manifest.validate_action(call.tool, call.args)
        approval = action.approval if action is not None else ApprovalClass.CRITICAL
        is_emergency_stop = call.tool == manifest.safety.emergency_stop_action
        if (
            not safety_errors
            and not is_emergency_stop
            and approval not in {ApprovalClass.NONE, ApprovalClass.AUDIT}
            and (envelope is None or not envelope.allows(device.tentacle_id, call.tool, call.args))
        ):
            safety_errors.append(f"action requires {approval.value} approval envelope")

        started_at = time.time()
        before = await _heartbeat_dict(device)
        if safety_errors:
            result = ToolResult.fail(call.call_id, -32004, "; ".join(safety_errors), 0)
        else:
            result = await device.execute(call)
        after = await _heartbeat_dict(device)
        finished_at = time.time()
        lease = self.pool.lock_holder(device.tentacle_id)
        receipt = ExecutionReceipt(
            receipt_id=f"device-{call.call_id}",
            call_id=call.call_id,
            trace_id=call.trace_id,
            device_id=device.tentacle_id,
            action=call.tool,
            arguments=dict(call.args),
            safety_errors=tuple(safety_errors),
            approval_class=approval.value,
            envelope_id=envelope.envelope_id if envelope else None,
            lease_id=lease.lease_id if lease and lease.owner == lease_owner else None,
            started_at=started_at,
            finished_at=finished_at,
            success=result.success,
            error_code=result.error_code,
            error_message=result.error_message,
            before=before,
            after=after,
        )
        self.ledger.append(receipt)
        result.extra.setdefault("execution_receipt_id", receipt.receipt_id)
        return result

    async def execute_sequence(
        self,
        device: Tentacle,
        calls: list[ToolCall],
        *,
        owner: str,
        task_id: str,
        envelope: ApprovalEnvelope | None = None,
        lease_timeout_s: int = 300,
    ) -> list[ToolResult]:
        acquired = await self.pool.acquire_lock(
            device.tentacle_id, owner, task_id, timeout_s=lease_timeout_s
        )
        if not acquired:
            call_id = calls[0].call_id if calls else task_id
            return [ToolResult.fail(call_id, -32016, "Device lease is held by another task", 0)]
        results: list[ToolResult] = []
        try:
            for call in calls:
                if not await self.pool.renew_lock(device.tentacle_id, owner):
                    results.append(ToolResult.fail(call.call_id, -32017, "Device lease expired", 0))
                    break
                result = await self.execute(device, call, envelope=envelope, lease_owner=owner)
                results.append(result)
                if not result.success:
                    break
            return results
        finally:
            await self.pool.release_lock(device.tentacle_id, owner)
