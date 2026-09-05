"""Tentacle Device Contract v1.

This module describes what a physical device can observe and do, together
with limits that must be enforced below the model/prompt layer.  It is kept
transport-neutral so the same manifest can be exposed through MCP, CLI or a
native driver API.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

CONTRACT_VERSION = "1.0"


class ApprovalClass(StrEnum):
    NONE = "none"
    AUDIT = "audit"
    USER = "user"
    OPERATOR = "operator"
    CRITICAL = "critical"


class ConcurrencyMode(StrEnum):
    SHARED = "shared"
    EXCLUSIVE = "exclusive"


@dataclass(frozen=True, slots=True)
class ValueConstraint:
    """Machine-enforceable constraint for one action argument."""

    name: str
    required: bool = False
    minimum: float | None = None
    maximum: float | None = None
    choices: tuple[Any, ...] = ()
    unit: str | None = None

    def validate(self, arguments: Mapping[str, Any]) -> list[str]:
        if self.name not in arguments:
            return [f"missing required argument: {self.name}"] if self.required else []
        value = arguments[self.name]
        errors: list[str] = []
        if self.choices and value not in self.choices:
            errors.append(f"{self.name} must be one of {list(self.choices)!r}")
        if self.minimum is not None or self.maximum is not None:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                errors.append(f"{self.name} must be numeric")
            else:
                if self.minimum is not None and value < self.minimum:
                    errors.append(f"{self.name} must be >= {self.minimum}")
                if self.maximum is not None and value > self.maximum:
                    errors.append(f"{self.name} must be <= {self.maximum}")
        return errors

    def to_dict(self) -> dict[str, Any]:
        return {
            key: value
            for key, value in {
                "name": self.name,
                "required": self.required,
                "minimum": self.minimum,
                "maximum": self.maximum,
                "choices": list(self.choices),
                "unit": self.unit,
            }.items()
            if value not in (None, (), [])
        }


@dataclass(frozen=True, slots=True)
class StateCondition:
    """Machine-readable precondition evaluated by drivers and simulators."""

    key: str
    operator: str
    value: Any

    def evaluate(self, state: Mapping[str, Any]) -> bool:
        if self.key not in state:
            return False
        actual = state[self.key]
        operations = {
            "eq": lambda: actual == self.value,
            "ne": lambda: actual != self.value,
            "gt": lambda: actual > self.value,
            "gte": lambda: actual >= self.value,
            "lt": lambda: actual < self.value,
            "lte": lambda: actual <= self.value,
            "in": lambda: actual in self.value,
        }
        operation = operations.get(self.operator)
        if operation is None:
            raise ValueError(f"unsupported state operator: {self.operator}")
        try:
            return bool(operation())
        except (TypeError, ValueError):
            return False

    def to_dict(self) -> dict[str, Any]:
        return {"key": self.key, "operator": self.operator, "value": self.value}


@dataclass(frozen=True, slots=True)
class StateEffect:
    """Deterministic state transition used for offline simulation."""

    key: str
    operation: str
    value: Any

    def apply(self, state: dict[str, Any]) -> None:
        if self.operation == "set":
            state[self.key] = self.value
        elif self.operation == "increment":
            state[self.key] = state.get(self.key, 0) + self.value
        elif self.operation == "decrement":
            state[self.key] = state.get(self.key, 0) - self.value
        elif self.operation == "delete":
            state.pop(self.key, None)
        else:
            raise ValueError(f"unsupported state effect: {self.operation}")

    def to_dict(self) -> dict[str, Any]:
        return {"key": self.key, "operation": self.operation, "value": self.value}


@dataclass(frozen=True, slots=True)
class ObservationSpec:
    name: str
    unit: str | None = None
    minimum: float | None = None
    maximum: float | None = None
    uncertainty: float | None = None
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            key: value
            for key, value in {
                "name": self.name,
                "unit": self.unit,
                "minimum": self.minimum,
                "maximum": self.maximum,
                "uncertainty": self.uncertainty,
                "description": self.description,
            }.items()
            if value not in (None, "")
        }


@dataclass(frozen=True, slots=True)
class ActionSpec:
    name: str
    arguments: tuple[ValueConstraint, ...] = ()
    description: str = ""
    approval: ApprovalClass = ApprovalClass.NONE
    idempotent: bool = False
    timeout_ms: int = 15_000
    preconditions: tuple[StateCondition, ...] = ()
    effects: tuple[StateEffect, ...] = ()

    def validate(self, arguments: Mapping[str, Any]) -> list[str]:
        errors: list[str] = []
        for constraint in self.arguments:
            errors.extend(constraint.validate(arguments))
        return errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "arguments": [item.to_dict() for item in self.arguments],
            "description": self.description,
            "approval": self.approval.value,
            "idempotent": self.idempotent,
            "timeout_ms": self.timeout_ms,
            "preconditions": [item.to_dict() for item in self.preconditions],
            "effects": [item.to_dict() for item in self.effects],
        }


@dataclass(frozen=True, slots=True)
class SafetySpec:
    """Driver-enforced safety properties, never prompt-only guidance."""

    forbidden_actions: tuple[str, ...] = ()
    interlocks: tuple[str, ...] = ()
    emergency_stop_action: str | None = None
    fail_safe_state: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "forbidden_actions": list(self.forbidden_actions),
            "interlocks": list(self.interlocks),
            "emergency_stop_action": self.emergency_stop_action,
            "fail_safe_state": self.fail_safe_state,
        }


@dataclass(frozen=True, slots=True)
class RuntimeSpec:
    heartbeat_interval_s: float = 30.0
    concurrency: ConcurrencyMode = ConcurrencyMode.EXCLUSIVE
    lease_timeout_s: float = 300.0
    supports_dry_run: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "heartbeat_interval_s": self.heartbeat_interval_s,
            "concurrency": self.concurrency.value,
            "lease_timeout_s": self.lease_timeout_s,
            "supports_dry_run": self.supports_dry_run,
        }


@dataclass(frozen=True, slots=True)
class DeviceManifest:
    device_id: str
    kind: str
    platform: str
    driver_version: str = "unknown"
    contract_version: str = CONTRACT_VERSION
    vendor: str | None = None
    model: str | None = None
    observations: tuple[ObservationSpec, ...] = ()
    actions: tuple[ActionSpec, ...] = ()
    safety: SafetySpec = field(default_factory=SafetySpec)
    runtime: RuntimeSpec = field(default_factory=RuntimeSpec)
    tags: tuple[str, ...] = ()

    def action(self, name: str) -> ActionSpec | None:
        return next((item for item in self.actions if item.name == name), None)

    def validate_action(self, name: str, arguments: Mapping[str, Any]) -> list[str]:
        if name in self.safety.forbidden_actions:
            return [f"action is forbidden by driver safety policy: {name}"]
        action = self.action(name)
        if action is None:
            return [f"action is not declared by device manifest: {name}"]
        return action.validate(arguments)

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "device": {
                "id": self.device_id,
                "kind": self.kind,
                "platform": self.platform,
                "driver_version": self.driver_version,
                "vendor": self.vendor,
                "model": self.model,
                "tags": list(self.tags),
            },
            "observations": [item.to_dict() for item in self.observations],
            "actions": [item.to_dict() for item in self.actions],
            "safety": self.safety.to_dict(),
            "runtime": self.runtime.to_dict(),
        }


def legacy_manifest(
    *,
    device_id: str,
    kind: str,
    platform: str,
    capabilities: list[str] | tuple[str, ...],
    meta: Mapping[str, Any] | None = None,
) -> DeviceManifest:
    """Upgrade an existing string-capability Tentacle without breaking it."""

    metadata = meta or {}
    return DeviceManifest(
        device_id=device_id,
        kind=kind,
        platform=platform,
        vendor=str(metadata.get("brand")) if metadata.get("brand") else None,
        model=str(metadata.get("model")) if metadata.get("model") else None,
        actions=tuple(ActionSpec(name=name) for name in capabilities),
        tags=tuple(dict.fromkeys((kind, platform))),
    )


def manifest_for(tentacle: Any) -> DeviceManifest:
    """Return a native manifest or safely adapt a legacy Tentacle."""

    manifest = getattr(tentacle, "manifest", None)
    if isinstance(manifest, DeviceManifest):
        return manifest
    tentacle_type = getattr(tentacle, "tentacle_type", "unknown")
    kind = getattr(tentacle_type, "value", str(tentacle_type))
    return legacy_manifest(
        device_id=str(tentacle.tentacle_id),
        kind=kind,
        platform=str(tentacle.platform),
        capabilities=list(tentacle.capabilities),
        meta=getattr(tentacle, "meta", None),
    )
