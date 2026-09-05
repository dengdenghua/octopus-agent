# ADR-003 · Session object replaces scattered ContextVars

Status: Accepted | Date: 2026-04

## Context

Before this decision, per-turn context was carried through the
runtime as a **collection of independent ContextVars**:

- `model_router.actor_context.current_actor` — who the user is (billing, audit)
- `process.session.current_agent_id` — which persona is answering
- `journal_context.current_conversation_id` — thread tag on journal events
- implicit globals: `TaskId` / `TurnId` generated per entry point
- `raw_identity` override: a flag on request body read by filter
  layer, not propagated anywhere

Each value had its own setter, its own ContextVar default, its
own code path for "what happens if this isn't set". The Starlette
threadpool made this worse — a request handler that spawned an
SSE generator thread had to **manually re-propagate** every
ContextVar onto the child thread, because ContextVars don't cross
thread boundaries by default.

The failure modes were real, not theoretical:

1. **`no current_actor set` errors in production.** When the
   planner ran in the SSE generator's thread, `_set_actor_ctx` got
   called on the request handler thread (where the request came
   in) but not on the generator thread (where the planner actually
   ran). Any skill that touched the account bridge crashed.

2. **Memory skills couldn't tell which agent was active.** The
   `remember` / `recall` / `note_user` / `diary_write` skills need
   to know "store under which agent's MEMORY.md". Reading the
   agent via `current_agent_id.get()` worked when the
   compat-router set it, worked most of the time for the OpenAI
   gateway, failed silently for channel adapters that had their
   own code path.

3. **Journal events missed `agent_id` / `conversation_id` tags.**
   Different journal helpers had different fallback conventions.
   Post-hoc analysis required correlating journal events to
   threads by timestamp, which was brittle.

4. **Adding `raw_identity` override required four places.** The
   request body carried it; `thread_compat_router` had to extract
   it; identity_filter had to check for it; and the SSE generator
   had to propagate the "is this in raw mode" flag across thread
   boundaries. Each of those touched a different ContextVar or
   dict lookup.

## Decision

Introduce a single `Session` dataclass that owns **all** per-turn
context, activate it via `session_scope()` once per entry point,
and make downstream callers read from it:

```python
@dataclass(slots=True)
class Session:
    actor: str | None = None
    agent: "Agent | None" = None
    thread_id: str | None = None
    conversation_id: str | None = None
    turn_id: str = field(default_factory=lambda: uuid4().hex)
    started_at: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)
```

Semantics:

- **One master ContextVar** (`_current_session`) carries the
  Session. `current_session()` returns it or None.
- **Legacy ContextVars are mirrored, not replaced.** On
  `session_scope()` entry, we set the Session *and* the old
  provider-neutral `current_actor` / `current_agent_id` variables
  — pre-session code keeps working during migration.
- **`metadata` is the extension point.** Per-turn overrides that
  don't fit the core fields (`raw_identity`, `mode`, `team_id`,
  `extra_workspaces`) live in the dict. Callers agree on string
  keys; no new ContextVar needed per feature.
- **Thread-spawning routers bind explicitly.** The compat router's
  SSE generator calls `bind_thread_session()` as the first thing
  in the `_gen()` function. Without it, the Session is invisible
  to the generator's thread — the same failure we had with the
  ad-hoc ContextVars, but now there's **one** explicit line to
  review instead of five.

The scope resolver (ADR-002), memory skills (remember/recall),
identity filter (`/raw` override), and journal tagging all read
from `current_session()` now.

## Alternatives considered

**A. Keep individual ContextVars, fix propagation per-feature.**
Rejected. That's what we had. The maintenance tax is paid every
time a new per-turn flag is added.

**B. Thread the Session through every function signature.** Too
invasive — skill handlers in particular take `**kwargs` from the
LLM's JSON and don't have a place to put a positional Session.
We do it for handlers that **opt in** (declare `session` in their
signature; the executor inspects and injects), but not as a
universal requirement.

**C. Make Session a singleton / module-level variable.** Obviously
broken under concurrency. Rejected immediately.

**D. Adopt `contextvars.copy_context()` at every thread boundary.**
Would solve propagation but leaves every other pain point (no
single shape, no typed access, no extension point). `copy_context`
treats the problem as "inherit all the vars", this ADR treats it
as "there should be fewer vars in the first place".

## Consequences

- **Skill handlers can opt-in by declaring a `session` parameter.**
  The executor's `inspect.signature` check fills it in from
  `current_session()`. Handlers without the param stay unchanged.
  This is how `remember` / `recall` get the active agent without
  each handler duplicating a ContextVar read.

- **The legacy ContextVar mirror is a migration aid, not the
  contract.** New code reads `current_session()`. Old code
  reading `current_actor()` keeps working. Deleting the mirror
  someday requires migrating any remaining legacy reader — grep
  for `current_actor` / `current_agent_id` to find
  the deletion cost.

- **Test isolation got tighter.** The Session is set via
  `session_scope()` as a context manager, which `reset()`s on
  exit. Bare-handed ContextVar.set() had leaked state between
  tests in the past (identity_filter `_RUNTIME_OVERRIDE` was a
  canary). Running a turn in a `with session_scope(s):` block
  guarantees cleanup even on exception.

- **`metadata` is unkeyed.** Anyone can stuff anything in it. The
  keys we've committed to so far (`mode`, `team_id`,
  `extra_workspaces`, `identity_lock_override`, `raw_identity`)
  are documented in the Session docstring and in the ADRs that
  introduced them. A future ADR may promote commonly-used keys to
  typed fields if the churn warrants.

- **ContextVar propagation is a property of `bind_thread_session`
  / `session_scope` and nothing else.** If a new code path spawns
  threads, it must call one of these two as the first action in
  the child thread. Forgetting is still possible — but now it's
  one call forgotten instead of five.
