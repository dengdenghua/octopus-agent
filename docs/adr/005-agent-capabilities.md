# ADR-005 · Agent capability flags

Status: Accepted | Date: 2026-05

## Context

``Agent.capabilities`` is a free-form ``dict[str, Any]`` attached
to each registered Agent (see ADR-002 where it was introduced to
gate ``code_mode_unlock`` on the scope resolver). Today it has
exactly one documented key · ``code_mode_unlock`` · on exactly
one agent (``coder``).

It's going to grow. Every time we add a new privileged feature
to some agents but not others — "this agent may spawn
subprocesses", "this agent may call MCP servers exposing secrets",
"this agent may issue web requests to non-allowlisted domains" —
that's a new capability flag.

Without a clear contract two failure modes are certain:

1. **Naming drift.** The first contributor writes
   ``can_run_code``; the second writes ``allow_subprocess``; the
   third writes ``subprocess_enabled``. All three work; none
   search grep-cleanly; backward compat requires checking all
   three spellings forever.
2. **Default-open regression.** ``capabilities.foo`` unset ·
   caller does ``caps.get("foo", True)`` once by mistake · any
   new agent registered tomorrow silently inherits the
   privilege. This is the *opposite* of ADR-002's stated
   invariant (new agents default to the **safest** tier).

This ADR locks the contract before the flags multiply.

## Decision

### Naming

**Format**: ``<subsystem>_<feature>_unlock``

- ``subsystem`` is the pre-existing subsystem name in the
  codebase (``code``, ``scope``, ``mcp``, ``subprocess``,
  ``web``, ``memory``, ...). Not invented here · must already
  exist as a directory, module, or well-known term.
- ``feature`` describes what the flag unlocks. Short · verb or
  noun · preferably 1-2 words.
- ``_unlock`` suffix is **mandatory** · it forces the semantic
  to be "default false = safe; setting to true grants
  something". Prevents the ``*_disabled`` /
  ``*_restricted`` negation trap (``"enabled": False`` vs
  ``"disabled": False`` both mean "don't do it" but read
  opposite — a source of real bugs).

### Default

**Absent key = false = no privilege.** Code that reads a
capability MUST use one of these patterns:

```python
# preferred
if session.agent and session.agent.capabilities.get("code_mode_unlock"):
    ...

# or the explicit helper
from runtime.platform.process.scope import agent_has_capability
if agent_has_capability(session.agent, "code_mode_unlock"):
    ...
```

**Banned patterns**:

```python
caps.get("code_mode_unlock", True)   # default-open · reject in review
caps["code_mode_unlock"]              # KeyError on new agents
```

### Where to declare

Flags live in the agent's ``profile.jsonc`` under
``capabilities``:

```jsonc
{
  "id": "coder",
  ...
  "capabilities": {
    "code_mode_unlock": true
  }
}
```

Not in ``tool-registry.jsonc`` (that's skill whitelist) · not in
``SOUL.md`` (that's LLM-facing persona) · not in Python
dictionaries in ``presets.py`` (those don't survive the reload
path). The JSONC file is reviewable · survives hot-reload
(``watcher.py``) · and travels with the agent folder when one
is cloned to spin up a new persona.

### Registry

Keep the authoritative list in this ADR. Adding a flag = adding
a row here and shipping the code that reads it in the same PR.

| Flag                       | Agents with it set  | Consumer                                    | Effect |
|----------------------------|---------------------|---------------------------------------------|--------|
| ``code_mode_unlock``       | ``coder``           | ``scope.py::resolve_write_scope``           | Enables the ``code`` tier · lets the agent write to ``extra_workspaces`` authorized via the Code-page UI. See ADR-002. |

(That's the only one today. Anyone adding ``*_unlock`` appends
a row + updates the code that reads it.)

### New capability checklist

When proposing a new flag:

1. **Pick the name** per the format above · search grep for
   prior art before inventing.
2. **Pick the consumer** — the function that gates on this
   flag. It must use ``caps.get(name)`` without a default or the
   ``agent_has_capability`` helper.
3. **Pick the agents** that get it. Start with zero and grow
   — never ship a flag that's true-by-default for all agents.
4. **Add a row to the Registry table above.**
5. **Add one test** · parametrize on ``(agent_has_flag: bool,
   expected_behavior: str)`` · covers the gate's two branches.
6. **PR merges** · new agents from that point on default-off.

### Migration

Existing ``profile.jsonc`` files without a ``capabilities``
block: no-op · the loader treats missing field as ``{}`` and
every lookup returns ``None`` → ``False``. Safe.

## Alternatives considered

**A. Boolean fields directly on ``Agent`` (no dict).** Cleaner
types · but ossifies the schema. Every new capability means
migrating ``AgentRegistry`` wire shapes + ``profile.jsonc``
schema validators + frontend types. Dict trades strict typing
for zero-migration velocity. Given capabilities are expected
to churn, dict wins.

**B. Role-based access control (RBAC).** An agent has a role
(``admin`` / ``user`` / ``guest``) · role has permissions.
Rejected for three reasons:
- Roles imply hierarchy; capabilities are orthogonal
  (``web_unlock`` and ``subprocess_unlock`` aren't
  ranked).
- Each new capability requires deciding "which existing role
  gets this" · adds debate-surface for every new flag.
- The two tiers we'd likely collapse to are "has" and "doesn't
  have" · which is literally the dict.

**C. No contract · write capabilities however you want.** What
we have today. Rejected because the failure modes above are
essentially certain without a written rule.

## Consequences

- **Future new capabilities take ~30 lines** — profile.jsonc
  change + one ``caps.get()`` call + one test + one Registry
  row — and ship as a single PR.
- **``capabilities.get(name, True)`` patterns get rejected
  in review.** Forever. Default-closed is what makes "new
  agent added tomorrow" safe.
- **This ADR is the Registry.** Adding a capability without
  updating the table means someone else has to archaeologize
  why a flag exists. If the table grows past ~15 rows we
  split it to ``docs/agent-capabilities.md`` but keep this
  ADR as the decision record.
- **Frontend code that branches on capabilities** reads from
  ``agent.capabilities`` in the ``/api/agents`` wire (already
  exposed as ``Record<string, unknown>`` — see
  ``frontend/src/core/agents/types.ts``). Adding a typed
  access helper there is follow-up work that can wait until
  we have ≥3 flags.
