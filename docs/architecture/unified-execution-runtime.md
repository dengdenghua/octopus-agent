# Unified execution runtime

Status: implementation in progress. This document records the target and the
acceptance evidence; an unchecked item is not an implemented capability.

## Target

Octopus owns projects, identity, permission policy, task lifecycle, budgets,
context and durable results. Native Octopus and Codex are execution backends.
Engine selection, model selection and persona selection are separate decisions.
An engine's internal planning loop remains its own responsibility.

Biomimetic concepts retain their engineering purpose: reflexes are deterministic
fast paths, arms are scoped workers, hearts supervise liveness and isolate
dependencies, immunity constrains effects, and regeneration proposes evaluated
changes. Organ counts do not set process counts or require extra planning layers.

## Migration and acceptance

### 1. Shared execution ownership

- [x] Resolve the primary execution route once, before invoking an engine.
- [x] Use the same engine for steering, verification and repair in that turn.
- [x] Reject overlapping engine calls and stop admitting calls after cancellation.
- [x] Persist the actual engine and invocation phase before execution; preserve
      this information on replay and expose it to the frontend.
- [x] Retain existing permission brokers, workspace authority, outcome checks
      and cancellation propagation. Do not recreate these inside a new engine loop.
- [x] Verify native and Codex routing, errors, interruptions, late steering and
      code-verification continuations using the real gateway and controlled drivers.

### 2. Explicit engine policy and usable controls

- [x] Decouple a role's identity from its preferred execution backend.
- [x] Support explicit per-task engine selection and a conservative default:
      coding tasks prefer Codex; business tools and fixed workflows prefer native.
      Engine availability and required capabilities must be checked before execution.
- [x] Present the actual engine and unavailable capabilities without asking users
      to select an engine for every ordinary task.
- [x] Never transfer a task with possible side effects to a different engine
      without reconciling its execution record and an explicit handoff decision.

### 3. Shared context and scoped workers

- [x] Pass task goals, approved project context, permissions and budgets through
      an engine-neutral request. Keep engine-private state opaque and scoped.
- [ ] Give child tasks explicit inputs, outputs, ownership and cancellation.
      Isolate concurrent writers with existing worktrees or write leases.
- [x] Validate a sequential native -> Codex -> native artifact handoff before
      enabling automatic parallel engine cooperation.

### 4. Focused delivery and evaluated learning

- [ ] Establish one coding scenario and one office/tool scenario with recorded
      success, latency, cost and human intervention. Controlled tests establish
      contracts; they do not count as live model performance evidence.
- [ ] Separate factual execution records, project knowledge, user preferences
      and unverified model summaries at the memory boundary.
- [ ] Load optional business plugins only when needed while keeping the local
      desktop installation reproducible.
- [ ] Keep shadow review and learning opt-in; changes require validation,
      versioning and rollback before promotion. No autonomous permission expansion.

## Ownership rules

The existing turn lifecycle remains the authority for status and finalization.
The execution supervisor owns only admission and engine binding for its calls;
it has no independent task database or second outcome state machine. The event
log remains authoritative for observable execution records. Model requests do
not carry credentials or unvalidated workspace grants between engines.

The first migration extracts route selection and engine dispatch from the
realtime gateway, retaining the current project/group/topology precedence.
Existing engine-specific security boundaries remain active. Subsequent changes
can replace adapters without changing the task lifecycle or public result model.

## Foundation acceptance evidence

Implemented on `codex/unified-execution-runtime`:

- `runtime/execution/engines.py` binds a single adapter and guards invocation
  admission. The realtime host retains authoritative status and finalization.
- `runtime/sensing/gateway/realtime_execution.py` adapts the existing native
  drivers and Codex App Server. Every invocation is journaled durably before
  dispatch; a failed journal write prevents effects.
- `turn/execution/updated` and the persisted `turn_updated.execution` field
  carry actual engine/phase evidence through Python replay, client replay and
  message metadata. Old turns remain readable without inferred engine evidence.
- Existing verification continuations now use their turn's bound engine.
  No secondary planner or automatic cross-engine recovery was introduced.
- Real Windows cancellation testing exposed an existing claim-reader defect:
  reading the mandatory-locked sentinel byte concealed the active turn id and
  made Stop return false. Metadata reads now begin after that byte, preserving
  lock authority. The existing real subprocess interrupt test passes, along
  with the cross-worker interrupt and process-claim tests.

Contract coverage lives in `tests/test_execution_engines.py`,
`tests/test_realtime_execution.py`, the Codex lifecycle cases in
`tests/test_realtime_cerebrum.py`, and
`frontend/src/core/realtime/execution.test.ts`. These use controlled engine
responses and real local persistence/gateway code; they do not establish live
model quality, latency or cost. Project/team orchestration still belongs to the
host; phase 2 adds an independent preference for its individual tasks.

Local validation on Windows (2026-09-05): 199 backend tests passed across
execution admission, gateway lifecycle, Codex adapter/approvals, durable event
logs, process claims and cross-worker interruption. The four affected frontend
test files passed all 154 tests; TypeScript and the production Vite build passed.
Ruff, invariant lint, protocol-method parity and generated-enum parity passed;
the two new runtime modules also passed mypy. No live model call was made.

## Engine policy and controls

`turn/start.executionEngine` accepts `auto`, `octopus`, or `codex`. The server
validates it independently of display metadata and a role's preferred backend.
The composer remembers the choice per principal and task, including the id
assigned to a newly created task. Roles retain their persona and allowed skills.
Codex model selection uses its principal-scoped profile or a trusted server
override, not a native persona's model hint.

Automatic selection supports the upstream unified General/Design modes. Their
labels and directory scope do not imply a coding task: parsed debug/refactor
intent and deterministic coding-purpose signals prefer Codex, while ambiguous
and office requests default to Native. Old build/general/research payloads remain
compatible. This policy adds no model call. A configured Codex role retains its
existing default; explicit task selection overrides that preference.
Project/team coordination remains native, with Codex available to member tasks.
The upstream focused/fanout/presence strategy stays authoritative; coordinated
delivery repair also passes through the bound supervisor and its durable receipt.

Before dispatch, Codex checks configuration enablement, executable availability,
the trusted workspace/principal, model compatibility, shared tool readiness and
the required local auth source. These checks do not refresh credentials or call
a model. Runtime permission, sandbox, provider and account validation still apply.
An automatically routed coding task may choose native before any effects when
Codex is unavailable; the receipt records the reason. An explicit Codex choice
or configured Codex role instead returns `execution_unavailable` before an engine
receipt is created. After execution starts, no automatic engine transfer exists.

The model-profile API exposes configuration availability and a reason code. The
composer explains unavailable options, and history badges read actual engine
receipts. Old history without receipts receives no inferred engine badge.

Validation on Windows (2026-09-05): the engine/gateway/role/account/approval batch
passed 243 tests; the WebSocket and cross-surface role batch passed 50 tests
(these batches share some role cases). All 366 tests in 12 affected frontend
files passed. The regenerated OpenAPI snapshot passed all three checks and its
TypeScript diff contains only the two added availability fields. Ruff, mypy,
invariant lint and protocol parity checks passed. Browser checks at 1360px and
390px verified preference persistence, a real `model_incompatible` response and
no horizontal overflow or page errors. No live model call was made.

The final native-fast-path regression batch passed 160 tests. TypeScript and
the production Vite build passed (26.06s). Real authenticated WebSocket probes
passed all three transports: direct Bearer header, direct browser subprotocol,
and browser subprotocol through the Vite proxy. The real UI model-profile and
account endpoints returned 200; configuration availability correctly remains
false for the current incompatible system-model profile.

Two local-runtime defects were also exposed by exercising the real installation:
Windows long-path support was disabled (now enabled and documented in
`LOCAL-RUN.md`), and Uvicorn SansIO coalesces WebSocket protocol header entries.
Auth parsing now accepts both coalesced and split representations while still
validating the credential and echoing only the non-secret protocol marker.

## Shared task context and child boundaries (in progress)

The realtime adapters now install an engine-neutral `ExecutionRequest` with a
frozen host task identity, original goal, approved filesystem scope and resource
policy. Continuations supply a new instruction while retaining the same task.
The request is a Python object, outside transport JSON and engine-private
conversation state. The host builds it from the authenticated turn and the
gateway's flat, validated context; nested client metadata cannot override those
grants. Codex materialization carries the same request and the native producer
uses its token/USD targets.

The host enforces one absolute deadline across primary execution, steering,
verification and repair. Existing native wall-time settings and Codex's operator
timeout remain in effect; continuation does not renew them. Token and dollar
targets preserve existing elastic-budget semantics. This implementation does
not claim a hard cross-engine spending cap or turn unknown Codex account cost
into zero cost.

`ExecutionScope` remains the filesystem authority. A Python-only ceiling is
intersected with each tool Session's current scope, including the legacy write
scope resolver. Nested requests can narrow the ceiling; reads remain available
when writes are denied. Codex built-ins use a read-only sandbox when the whole
resolved workspace is not writable; Octopus tools retain their own narrower
write scope and existing approval checks.

The existing subagent bridge now gives each scoped child a distinct execution
identity, parent coordinate and inherited deadline. Its existing cancellation
monitor enforces the remaining parent time. Codex's synchronous adapter retains
ContextVars when it needs a helper thread, and delegated Codex calls observe the
parent cancellation token. Private Codex child thread/turn coordinates are
separate even when public events share the parent's workbench lane.

Write lease and read-snapshot tables persist across native continuation threads
and child Session copies. Lease ownership identifies the task, not the shared
user account. This detects conflicting writes through the Octopus executor;
it is not an OS sandbox for arbitrary shell or built-in Codex writes. The
explicit artifact handoff section below records subsequent implementation of
manifests and verified ownership transfer. The isolated-worker section records
the new worktree integration. Completing the remaining orchestration surfaces
and reviewed application of partial/candidate outputs remains open for phase 3.

Validation on Windows: 287 tests passed across request/scope contracts, the
gateway, Codex routing, stack workers, child timeout/threading/schema/slot
isolation and real subprocess cancellation. The new gateway deadline test runs
a real Python subprocess and verifies it is cancelled before it can complete.
Child bridge tests use real worker threads to check distinct ownership, retained
scope and parent cancellation. Ruff, mypy for the three new runtime modules and
invariant lint passed. These are controlled driver tests, not live model quality
or cost evidence; phase 3 and phase 4 acceptance items remain open.

The follow-up batch passed 89 tests for nested-metadata rejection, tool bridge
scope, Codex dynamic tools/role context and file leases (some request cases
overlap the earlier batch). The local backend was restarted with these changes;
backend health and Vite returned 200, and authenticated WebSocket probes passed
direct header, direct browser subprotocol and Vite-proxied subprotocol transport.

## Explicit artifact handoff

`call_agent` and `call_subagent` accept `input_files` and `output_files`. The
host resolves these files inside the parent task's approved read/write roots,
snapshots input SHA-256 hashes and output baselines, and places the resulting
immutable artifact contract on the child execution request. The contract is
bounded to 64 inputs and 64 outputs, each at most 32 MiB. Relative input/output
paths use the approved primary read/write root respectively.

Before the child starts, all output lease owners and file baselines must match.
The host writes an `execution_handoff` assignment record durably and transfers
the declared leases as one operation. Acceptance waits for a completed child,
checks the result schema when requested, verifies unchanged inputs (apart from
explicit input/output edits), hashes every required output, and rejects missing
or unstable files and undeclared writes observed by the file-tool executor.
Another durable record precedes returning ownership to the parent. These log
records survive event coalescing. The result exposes verified artifact paths,
hashes, sizes and producer task identity; model-authored hashes are not used.

Artifact handoffs disable transient, round-limit and schema auto-retries.
Cancellation, missing outputs, ownership conflicts and failed journal writes
cannot silently grant another worker access. Partial or failed outputs remain
unaccepted. Once the child runner has unwound, a failed handoff can return its
leases only if every declared file still matches its pre-dispatch baseline and
the child owns no undeclared file-tool leases. A durable `aborted` receipt with
reason `outputs_unchanged` precedes this atomic transfer. This cleanup can run
after the parent's deadline; it does not accept artifacts or enable an automatic
retry. Timed-out workers keep their leases until their future finishes. Changed
outputs and journal failures retain child ownership for explicit reconciliation.
Reviewed partial-output reconciliation and lifecycle-managed worktree cleanup
still need to be wired for the full parallel-worker acceptance item. Legacy
callers without an artifact contract retain their existing interface.

`tests/test_artifact_handoff.py` exercises native preparation, a dispatched
Codex-role child and native verification through the actual supervisor,
subagent bridge, tool executor, file leases and disk journal. The child produces
a Python function; the native step checks its result and creates a verification
artifact after ownership returns. This proves the sequential handoff contract
using a controlled Codex response. It does not establish live App Server/model
quality or filesystem isolation for arbitrary shell/built-in Codex writes.

The handoff/delegation/journal regression batch passed 93 tests on Windows.
It includes journal failures before assignment and acceptance, changing inputs,
edits during acceptance, required-output absence, schema failure, timeout/late
completion, existing-file updates, ownership conflicts, resource bounds and
prevention of a retry that would drop the artifact contract. Phase 3 remains
open for concurrent writer isolation and integration across orchestration
surfaces; all phase 4 acceptance requirements remain open.

The failure-reconciliation follow-up passed 265 tests on Windows, covering the
handoff and delegation batches above plus OpenAPI parity, the realtime gateway,
Codex dynamic tools, file leases and child threading. The 24 artifact tests
include unchanged existing/missing outputs after runner failure, recovery after
the parent deadline, failed cleanup journals, undeclared leases and a real worker
thread that remains active after timeout. That worker's leases become available
only after it unwinds; its late result is never accepted. Ruff, mypy for five
shared-context modules and invariant lint passed. This remains controlled-driver
evidence; it does not close the concurrent-isolation or live-model requirements.

## Scoped isolated workers (in progress)

`call_subagent` and `call_agent` now accept `isolate=true`. The bridge owns the
worktree on the actual child worker thread, covering preparation, engine
execution, schema checks, durable export and cleanup. A caller timing out or
being cancelled cannot delete files underneath a still-running child. After
that child unwinds, its partial patch is exported with `contract_valid=false`;
its late model result never becomes a parent success. A failed export retains
the checkout, identified by its durable assignment record and, when the call
is still awaiting a result, `retained_workspace`.

The source directory comes from the host Session's approved project, not the
backend's current directory or model context. Worktrees are created beneath
an existing approved output root. Child requests retain identity lineage,
deadline and policy while their write ceiling narrows to their own checkout.
The native and Codex role adapters receive that checkout as their workspace.
This is Git checkout isolation with the existing engine permission mechanisms;
it does not turn unrestricted native shell execution into an OS sandbox.

Preparation uses a private Git index to snapshot current working files,
including staged/unstaged edits, deletions and non-ignored untracked files.
The source HEAD and index stay unchanged. Two matching tree snapshots and an
unchanged HEAD are required before dispatch. Runtime storage is excluded from
the snapshot; ignored dependencies are not copied. Git hooks and fsmonitor are
disabled for host bookkeeping and Windows long paths are enabled per command.

The host exports a complete binary-capable `changes.patch`, bounded by the
existing 32 MiB artifact limit, and returns its SHA-256/size/producer coordinate
plus a bounded preview. The base snapshot remains reachable through a
`refs/octopus/execution-snapshots/...` reference after the temporary worktree
branch is removed. The receipt explicitly says `applied=false`. Declared input
versions and required outputs are checked; when an output list was supplied,
undeclared changed files make the candidate invalid. This checks the artifact
contract, not task quality. Failed candidates retain their patch for review.
Export pins the exact original worktree gitdir: a rewritten `.git` pointer,
including one aimed at the main repository index, cannot redirect host staging.

The parallel, graph and pipeline delegation surfaces forward isolation and file
contracts and retain artifact/patch records in their result projections. Parallel
fan-out copies the parent's cancellation context, and file-contract/isolated
attempts disable transient retries. Graph resume does not replay file ownership
from cached prose. The remaining acceptance work includes reviewed application
and reconciliation of candidate/partial outputs, consistent writer admission,
and the older tournament/CLI and project/team orchestration entrypoints. Phase 3
remains open, as do all phase 4 requirements.

Validation on Windows: 287 tests passed in 81.83s across isolated workers,
worktree lifecycle, graph/pipeline/parallel delegation, contracts, budgets,
timeouts, tool bridges, orchestration, stack workers, realtime execution and
OpenAPI parity. The 12 isolated-worker cases use real Git repositories, real
worker threads and disk journals, including concurrent edits to the same file,
parent cancellation reaching both children, retained partial patches, dirty
starting states, binary patch application checks, invalid output contracts,
failed journals, scope rejection and a tampered gitdir aimed at the parent
index. Codex role responses remain controlled; these are not live model metrics.
Ruff, mypy for the two worktree modules and invariant lint passed. The local
backend was restarted with these changes; backend health and Vite returned 200,
and all three authenticated WebSocket connection probes passed (direct header,
direct browser subprotocol and Vite-proxied browser subprotocol).

## Tournament integration checkpoint

The host-facing tournament now uses the existing parallel subagent bridge for
its producers. It requires an authenticated host task and journal; an optional
`repo_root` must match the approved project. It forwards the file contract and
isolates each producer's working files. Producer and reviewer spawns share one
bounded budget, including an already active enclosing orchestration budget.
The parallel bridge honors a bounded worker count and accounts for queued
waves in its batch timeout; the original parent deadline is still authoritative.

Voting narrows a host task's filesystem write ceiling to empty while retaining
its identity, approved reads and resource policy. A legacy workspace coordinate
cannot restore reviewer write permissions. Candidate selection checks the
host-exported patch's size and SHA-256 before review and before returning the
winner, and appends a durable `worktree_selected` receipt with `applied=false`.
Cancellation, changed patch contents and failed selection journals preserve
candidate coordinates without returning a winner. The reported judgment
remains distinguishable from a single surviving candidate or an abstaining
panel; selection alone is not verification or permission to apply a patch.

An explicit `asyncio.CancelledError` from an isolated runner now exports its
partial changes as an invalid candidate before removing the temporary checkout.
This complements linked cancellation and timeout handling; interrupted work is
never promoted into a successful artifact contract.

Before the concurrent upstream merge began, the tournament, vote, isolated
worker and child-context batch passed 51 tests in 56.43s. It exercised real Git,
worker threads, the bridge, builtin reviewer dispatch and disk journals with
controlled model responses. The tested changes are captured in local checkpoint
`a4f1c931`. The subsequent upstream merge introduced conflicts in shared runtime
files, so these results do not validate the merged checkout. Type checking,
the wider regression batch and local runtime restart must be repeated after
that merge settles. Phase 3 and phase 4 acceptance remain open.
