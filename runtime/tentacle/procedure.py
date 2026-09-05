"""Deterministic, resumable procedures for physical Tentacle devices."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from runtime.platform.io import atomic_write_json

from .base import Tentacle, ToolCall, ToolResult
from .contract import manifest_for
from .execution import ApprovalEnvelope, DeviceActionExecutor


class ProcedureStatus(StrEnum):
    DRAFT = "draft"
    RUNNING = "running"
    PAUSED = "paused"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EMERGENCY_STOPPED = "emergency_stopped"


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_attempts: int = 1
    backoff_s: float = 0.0

    def __post_init__(self) -> None:
        if self.max_attempts <= 0:
            raise ValueError("max_attempts must be positive")
        if self.backoff_s < 0:
            raise ValueError("backoff_s must not be negative")


@dataclass(frozen=True, slots=True)
class ProcedureStep:
    step_id: str
    action: str
    arguments: dict[str, Any] = field(default_factory=dict)
    retry: RetryPolicy = field(default_factory=RetryPolicy)


@dataclass(slots=True)
class Procedure:
    procedure_id: str
    device_id: str
    steps: tuple[ProcedureStep, ...]
    expected_contract_version: str | None = None
    expected_driver_version: str | None = None
    status: ProcedureStatus = ProcedureStatus.DRAFT
    current_step: int = 0
    attempts: dict[str, int] = field(default_factory=dict)
    receipt_ids: list[str] = field(default_factory=list)
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    @property
    def complete(self) -> bool:
        return self.status in {
            ProcedureStatus.SUCCEEDED,
            ProcedureStatus.FAILED,
            ProcedureStatus.CANCELLED,
            ProcedureStatus.EMERGENCY_STOPPED,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "procedure_id": self.procedure_id,
            "device_id": self.device_id,
            "steps": [
                {
                    "step_id": step.step_id,
                    "action": step.action,
                    "arguments": step.arguments,
                    "retry": asdict(step.retry),
                }
                for step in self.steps
            ],
            "expected_contract_version": self.expected_contract_version,
            "expected_driver_version": self.expected_driver_version,
            "status": self.status.value,
            "current_step": self.current_step,
            "attempts": dict(self.attempts),
            "receipt_ids": list(self.receipt_ids),
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Procedure:
        return cls(
            procedure_id=str(payload["procedure_id"]),
            device_id=str(payload["device_id"]),
            steps=tuple(
                ProcedureStep(
                    step_id=str(step["step_id"]),
                    action=str(step["action"]),
                    arguments=dict(step.get("arguments") or {}),
                    retry=RetryPolicy(**dict(step.get("retry") or {})),
                )
                for step in payload.get("steps", [])
            ),
            expected_contract_version=payload.get("expected_contract_version"),
            expected_driver_version=payload.get("expected_driver_version"),
            status=ProcedureStatus(payload.get("status", ProcedureStatus.DRAFT.value)),
            current_step=int(payload.get("current_step", 0)),
            attempts={str(k): int(v) for k, v in dict(payload.get("attempts") or {}).items()},
            receipt_ids=[str(item) for item in payload.get("receipt_ids", [])],
            error=payload.get("error"),
            created_at=float(payload.get("created_at", time.time())),
            updated_at=float(payload.get("updated_at", time.time())),
        )


class ProcedureCheckpointStore:
    """One atomic JSON checkpoint per procedure."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def path_for(self, procedure_id: str) -> Path:
        safe_id = "".join(char for char in procedure_id if char.isalnum() or char in "-_")
        if not safe_id or safe_id != procedure_id:
            raise ValueError("procedure_id contains unsafe path characters")
        return self.root / f"{safe_id}.json"

    def save(self, procedure: Procedure) -> None:
        destination = self.path_for(procedure.procedure_id)
        destination.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(destination, procedure.to_dict(), mode=0o600)

    def load(self, procedure_id: str) -> Procedure | None:
        path = self.path_for(procedure_id)
        if not path.exists():
            return None
        import json

        payload = json.loads(path.read_text(encoding="utf-8"))
        return Procedure.from_dict(payload)

    def load_all(self) -> list[Procedure]:
        if not self.root.exists():
            return []
        procedures: list[Procedure] = []
        for path in sorted(self.root.glob("*.json")):
            try:
                loaded = self.load(path.stem)
            except (OSError, ValueError, KeyError):
                continue
            if loaded is not None:
                procedures.append(loaded)
        return procedures


class ProcedureExecutor:
    """Runs validated steps without asking a model to drive every transition."""

    def __init__(
        self,
        action_executor: DeviceActionExecutor,
        checkpoint_store: ProcedureCheckpointStore | None = None,
        event_sink: Callable[[str, str, dict[str, Any]], None] | None = None,
    ) -> None:
        self.action_executor = action_executor
        self.checkpoint_store = checkpoint_store
        self.event_sink = event_sink

    def _checkpoint(self, procedure: Procedure) -> None:
        procedure.updated_at = time.time()
        if self.checkpoint_store is not None:
            self.checkpoint_store.save(procedure)
        if self.event_sink is not None:
            self.event_sink("procedure.updated", procedure.device_id, procedure.to_dict())

    def pause(self, procedure: Procedure) -> None:
        if procedure.status in {ProcedureStatus.DRAFT, ProcedureStatus.RUNNING}:
            procedure.status = ProcedureStatus.PAUSED
            self._checkpoint(procedure)

    def resume(self, procedure: Procedure) -> None:
        if procedure.status == ProcedureStatus.PAUSED:
            procedure.status = ProcedureStatus.DRAFT
            procedure.error = None
            self._checkpoint(procedure)

    def cancel(self, procedure: Procedure) -> None:
        if not procedure.complete:
            procedure.status = ProcedureStatus.CANCELLED
            self._checkpoint(procedure)

    @staticmethod
    def validate(procedure: Procedure, device: Tentacle) -> list[str]:
        """Compile-time validation of every remaining step."""
        manifest = manifest_for(device)
        errors: list[str] = []
        seen: set[str] = set()
        for index, step in enumerate(procedure.steps):
            if step.step_id in seen:
                errors.append(f"duplicate step_id: {step.step_id}")
            seen.add(step.step_id)
            action = manifest.action(step.action)
            step_errors = manifest.validate_action(step.action, step.arguments)
            errors.extend(f"step {index} ({step.step_id}): {error}" for error in step_errors)
            if step.retry.max_attempts > 1 and action is not None and not action.idempotent:
                errors.append(
                    f"step {index} ({step.step_id}): retries require an idempotent action"
                )
        return errors

    async def run(
        self,
        procedure: Procedure,
        device: Tentacle,
        *,
        envelope: ApprovalEnvelope | None = None,
        owner: str | None = None,
    ) -> Procedure:
        if procedure.device_id != device.tentacle_id:
            raise ValueError("procedure device_id does not match selected device")
        if procedure.complete or procedure.status == ProcedureStatus.PAUSED:
            return procedure
        manifest = manifest_for(device)
        if (
            procedure.expected_contract_version is not None
            and procedure.expected_contract_version != manifest.contract_version
        ) or (
            procedure.expected_driver_version is not None
            and procedure.expected_driver_version != manifest.driver_version
        ):
            procedure.status = ProcedureStatus.PAUSED
            procedure.error = (
                "device contract or driver version changed; procedure must be reviewed"
            )
            self._checkpoint(procedure)
            return procedure
        validation_errors = self.validate(procedure, device)
        if validation_errors:
            procedure.status = ProcedureStatus.FAILED
            procedure.error = "; ".join(validation_errors)
            self._checkpoint(procedure)
            return procedure
        if procedure.expected_contract_version is None:
            procedure.expected_contract_version = manifest.contract_version
        if procedure.expected_driver_version is None:
            procedure.expected_driver_version = manifest.driver_version
        self._checkpoint(procedure)
        owner = owner or f"procedure:{procedure.procedure_id}"
        lease_timeout = max(1, int(manifest.runtime.lease_timeout_s))
        acquired = await self.action_executor.pool.acquire_lock(
            device.tentacle_id, owner, procedure.procedure_id, timeout_s=lease_timeout
        )
        if not acquired:
            procedure.status = ProcedureStatus.PAUSED
            procedure.error = "device lease is held by another task"
            self._checkpoint(procedure)
            return procedure

        procedure.status = ProcedureStatus.RUNNING
        procedure.error = None
        self._checkpoint(procedure)
        try:
            while procedure.current_step < len(procedure.steps):
                if procedure.status != ProcedureStatus.RUNNING:
                    break
                step = procedure.steps[procedure.current_step]
                action_spec = manifest_for(device).action(step.action)
                max_attempts = (
                    step.retry.max_attempts if action_spec and action_spec.idempotent else 1
                )
                result: ToolResult | None = None
                while procedure.attempts.get(step.step_id, 0) < max_attempts:
                    if procedure.status != ProcedureStatus.RUNNING:
                        break
                    if not await self.action_executor.pool.renew_lock(device.tentacle_id, owner):
                        procedure.status = ProcedureStatus.PAUSED
                        procedure.error = "device lease expired"
                        self._checkpoint(procedure)
                        break
                    attempt = procedure.attempts.get(step.step_id, 0) + 1
                    procedure.attempts[step.step_id] = attempt
                    call = ToolCall(
                        call_id=f"{procedure.procedure_id}:{step.step_id}:{attempt}",
                        tentacle_id=device.tentacle_id,
                        tool=step.action,
                        args=dict(step.arguments),
                        trace_id=procedure.procedure_id,
                    )
                    result = await self.action_executor.execute(
                        device, call, envelope=envelope, lease_owner=owner
                    )
                    receipt_id = result.extra.get("execution_receipt_id")
                    if receipt_id:
                        procedure.receipt_ids.append(str(receipt_id))
                    self._checkpoint(procedure)
                    if result.success:
                        break
                    if attempt < max_attempts and step.retry.backoff_s:
                        await asyncio.sleep(step.retry.backoff_s)

                if procedure.status != ProcedureStatus.RUNNING:
                    break
                if result is None or not result.success:
                    procedure.status = ProcedureStatus.FAILED
                    procedure.error = result.error_message if result else "step did not execute"
                    self._checkpoint(procedure)
                    break
                procedure.current_step += 1
                self._checkpoint(procedure)

            if procedure.status == ProcedureStatus.RUNNING:
                procedure.status = ProcedureStatus.SUCCEEDED
                self._checkpoint(procedure)
            return procedure
        finally:
            await self.action_executor.pool.release_lock(device.tentacle_id, owner)

    async def emergency_stop(
        self,
        procedure: Procedure,
        device: Tentacle,
        *,
        owner: str | None = None,
    ) -> Procedure:
        manifest = manifest_for(device)
        stop_action = manifest.safety.emergency_stop_action
        if not stop_action:
            procedure.status = ProcedureStatus.PAUSED
            procedure.error = "device does not declare an emergency stop action"
            self._checkpoint(procedure)
            return procedure
        owner = owner or f"procedure:{procedure.procedure_id}:emergency"
        # Emergency stop may preempt the lease held by this same procedure, but
        # never an unrelated task's active lease.
        existing_lease = self.action_executor.pool.lock_holder(device.tentacle_id)
        if existing_lease is not None and existing_lease.task_id == procedure.procedure_id:
            await self.action_executor.pool.release_lock(device.tentacle_id, existing_lease.owner)
        acquired = await self.action_executor.pool.acquire_lock(
            device.tentacle_id, owner, procedure.procedure_id, timeout_s=30
        )
        if not acquired:
            procedure.status = ProcedureStatus.PAUSED
            procedure.error = "emergency stop blocked by an active foreign lease"
            self._checkpoint(procedure)
            return procedure
        try:
            call = ToolCall(
                call_id=f"{procedure.procedure_id}:emergency-stop",
                tentacle_id=device.tentacle_id,
                tool=stop_action,
                trace_id=procedure.procedure_id,
            )
            result = await self.action_executor.execute(device, call, lease_owner=owner)
            receipt_id = result.extra.get("execution_receipt_id")
            if receipt_id:
                procedure.receipt_ids.append(str(receipt_id))
            procedure.status = (
                ProcedureStatus.EMERGENCY_STOPPED if result.success else ProcedureStatus.FAILED
            )
            procedure.error = None if result.success else result.error_message
            self._checkpoint(procedure)
            return procedure
        finally:
            await self.action_executor.pool.release_lock(device.tentacle_id, owner)
