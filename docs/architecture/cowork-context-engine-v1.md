# Cowork Context Engine v1

`octopus.cowork_context_engine.v1` is the versioned extension contract for
multi-member context assembly. It is used by the real realtime group-fanout
path, not only by an offline evaluator.

## Registration

Publish an entry point in the `octopus.cowork_context_engines` group and select
it explicitly with `OCTOPUS_COWORK_CONTEXT_ENGINE=<entry-point-name>`.
Installing a package does not activate it. Unknown names, malformed names and
unsupported API versions fail before a realtime turn starts.

An engine declares:

```python
class MyEngine:
    name = "my-engine"
    api_version = "1"
    capabilities = {"assemble", "compact", "commit_turn"}
```

`api_version = "octopus.cowork_context_engine.v1"` is also accepted. Engines
without a version remain supported through the legacy `select_context`
adapter. New engines should implement `assemble`.

## Lifecycle

The host recognizes these hooks:

| Hook | When it runs | Data boundary |
|---|---|---|
| `bootstrap` | Once per live host/session pair | Session id and API version only |
| `ingest` | Before context assembly | Current user message and stable session/turn ids |
| `assemble` | Once per non-empty authorized candidate section | Current message, member metadata, authorized candidates, hard token budget and stable ids |
| `compact` | When a long-project plan crosses the host tier | Counts and token statistics only; maintains engine-owned state |
| `on_member_start` | Immediately before a member model run | Member id and body-free projection epoch |
| `on_member_end` | After the member run settles | Member id, status and result SHA-256 only |
| `commit_turn` | Only after the host lifecycle ledger atomically settles an accepted turn | Advancement key, body-free context receipt and member result hashes |
| `maintain` | After commit, or after an aborted group run | Aggregate outcome only |

All hooks are keyword-only by convention. Lifecycle hooks may persist or
maintain plugin-owned state, but their return values never enter a model
prompt. `assemble` is the only hook allowed to influence selection.

## Assemble result

`assemble` returns either a sequence of source ids or:

```python
{"selected_source_ids": ["ctx_..."]}
```

The host has already applied each member's ContextGrant before candidates are
exposed. It then discards unknown and duplicate ids, reapplies the token budget
and renders selected facts in stable source order. An engine cannot widen
visibility or inject arbitrary prompt text.

## Failure and isolation contract

- Every plugin call is bounded by
  `OCTOPUS_COWORK_CONTEXT_ENGINE_TIMEOUT_SECONDS` (default 2 seconds, accepted
  range 0.01–30 seconds).
- Three consecutive failures or timeouts quarantine the engine for the live
  process. Selection then falls back to the deterministic host policy.
- Diagnostics contain only engine name, API version, capabilities, call/error
  counts, duration and exception type. Exception messages, request bodies,
  candidate bodies and result bodies are never copied into lifecycle traces.
- The host's SQLite context ledger remains authoritative. A plugin failure
  cannot turn an aborted member into a committed one or make a committed group
  appear rolled back.

## Minimal implementation

```python
class ProjectRecallEngine:
    name = "project-recall"
    api_version = "1"
    capabilities = {"assemble"}

    def assemble(self, *, candidates, budget_tokens, **_scope):
        remaining = budget_tokens
        selected = []
        for item in sorted(candidates, key=lambda row: (-row.score, row.order)):
            if item.estimated_tokens <= remaining:
                selected.append(item.source_id)
                remaining -= item.estimated_tokens
        return {"selected_source_ids": selected}
```

The fixed release benchmark verifies version negotiation, every lifecycle
hook, legacy compatibility, authorized-id enforcement, budget enforcement,
timeout quarantine and body-free diagnostics.
