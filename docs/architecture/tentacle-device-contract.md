# Tentacle Device Contract v1

The Tentacle Device Contract is Octopus's transport-neutral description of a
physical device. It complements MCP: MCP transports tool calls, while this
contract describes device semantics and the limits a driver must enforce.

## Safety boundary

Models and prompts may plan an action, but they are not the safety boundary.
Every real driver must validate the requested action against its
`DeviceManifest` before it reaches hardware. A rejected action must not be
forwarded to the device.

The v1 manifest contains:

- stable device identity, driver and contract versions;
- typed observations, units, ranges and uncertainty;
- declared actions, argument constraints and approval class;
- forbidden actions, interlocks, emergency stop and fail-safe state;
- heartbeat, concurrency, lease and dry-run properties.

## Compatibility

Existing Tentacles can keep reporting `capabilities: list[str]`.
`manifest_for(tentacle)` upgrades that list to a basic manifest, allowing a
gradual migration. New hardware drivers should provide a native manifest with
machine-enforceable argument limits rather than relying on the legacy adapter.

## Execution contract

The intended device path is:

1. discover and select a device through `TentaclePool`;
2. validate the action and arguments against the manifest;
3. acquire the device lease and any required approval;
4. execute through MCP, CLI or the native API;
5. record the command, result and before/after observations;
6. move to the declared fail-safe state on an unrecoverable failure.

The implementation provides the schema, legacy discovery, pool lookup and
Android driver-side validation. Model-planned coordinator, team and MCP actions
also run through renewable leases, scoped approval envelopes and bounded
before/after execution receipts. Durable receipt storage remains a subsequent
phase.

## Deterministic procedures

Validated device actions can be compiled into a `Procedure`. A procedure pins
the device contract and driver versions, validates every step before the first
physical action, and checkpoints after every attempt and state transition.
Only idempotent actions may retry. Procedures can pause, resume, cancel or call
the driver's declared emergency-stop action without returning control to a
model between steps.

## Telemetry and physical fault visibility

`TelemetryHub` keeps bounded per-device time series for heartbeats, action
latency and outcomes. It derives a health score from connectivity freshness,
recent failures and critical battery state. Failures are classified as
connectivity, contention, safety, sensor, physical, software or unknown so a
physical condition is not automatically misdiagnosed as a model/software bug.

The control plane exposes health snapshots, filtered telemetry, fault history
and an SSE event stream. Slow event consumers have bounded queues with
drop-oldest behavior; observability therefore cannot back-pressure physical
device execution.

## Offline simulation

Actions may declare machine-readable state preconditions and deterministic
effects. `ProcedureSimulator` evaluates the complete procedure against those
rules without acquiring a lease or calling the device. It supports initial
state and per-step fault injection, stops at the first invalid transition and
reports every simulated before/after state. Contract or driver version drift
fails before the first simulated step. Actions without state effects remain
valid but are explicitly reported as lower-fidelity simulation warnings.
