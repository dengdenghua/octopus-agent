# ADR-001 · Bionic naming + dual-track contracts

Status: Accepted | Date: 2026-04

## Context

The project's public architecture is described in biology: brain
(Cerebrum), arms, suckers, beak, mantle, hearts, nerves, genome,
ink sac, skin, chromatophore. These names are evocative and they
structure the whole README, the biomimetic docs, and the
high-level design conversations. They're not decorative — a
reviewer saying "the arm should hold its own affinity" maps to a
real invariant (SWM-3) and a real code path.

But biology names alone break at the implementation boundary:

- `Cerebrum.plan()` is perfect for a diagram. In day-to-day code
  review, "the planner messed up the task graph" is how we
  actually talk. Forcing `cerebrum` into variable names makes
  `planner.plan_count` read as `cerebrum.plan_count` — a fight
  against Python's own norms for object naming.
- External contributors from other agent frameworks
  have planner / executor / scheduler / tool-call vocabulary
  burned in. Forcing them to learn "arm ≈ agent" and "sucker ≈
  skill" before they can grep is a real tax.
- Some biology names simply have no clean one-word engineering
  equivalent (chromatophore ≈ "prompt A/B mimicry module"?). If
  we pick a bad engineering name we make the code *worse*, not
  better.

Two failure modes we've actually hit in this codebase:

1. **Half-migration drift.** Early files used `suckers` as a
   package name AND `skill` as a class name for the same concept.
   Grep became unreliable. New code drifted toward whichever name
   happened to appear nearest.
2. **Docs-code mismatch.** The architecture doc said "arms are
   semi-autonomous" but the implementation file was named
   `executor.py` with no mention of arms — so the invariants
   described in biology couldn't be cross-referenced to code
   without the docs author's mental map.

## Decision

We keep **both** vocabularies and bind them at explicit seams.

**Public names in code use engineering terms:**
- `class LLMPlanner` — not `Cerebrum`
- `SkillRegistry` — not `SuckerRegistry`
- `ArmPool`, `Agent` — both engineering terms
- Function / variable names stay engineering

**Biology names live in:**
- **Package paths** — `runtime/core/cerebrum/`, `runtime/execution/suckers/`,
  `runtime/core/hearts/`. The filesystem is where the architecture
  map lives, one level above specific classes.
- **Import aliases** for the architecture-aware reader:
  ```python
  from runtime.core.cerebrum import LLMPlanner as Cerebrum  # allowed
  ```
  The aliased form is fine in docs and tutorial scripts; it's
  discouraged in the runtime itself.
- **Docstrings and comments** describing the "why". A class called
  `SpinalCord` whose docstring says "this is the reflex fast path
  that short-circuits the planner for sub-50ms tasks" costs no
  engineering readability while preserving the concept.
- **Documentation** (`docs/vision/biomimetic-architecture.md`, `docs/invariants.md`).
  Anywhere we're talking *about* the system, biology wins.

## Alternatives considered

**A. Biology-only in code.** Rejected: fights Python conventions,
   confuses every external reader, makes stack traces hostile
   ("Sucker.execute took 500ms" — what?).

**B. Engineering-only in code AND docs.** Rejected: loses the
   organizing metaphor. We'd end up with
   `planner`/`executor`/`scheduler`/`budget`/`safety` — same as
   every other Agent framework, with no way to explain why *our*
   version has a reflex path, three hearts, or an immune system.
   The biology isn't decoration; it drives architectural
   decisions we'd have to re-justify every time.

**C. A single "glossary" that maps biology ↔ engineering and
   leaves it to the reader.** Rejected: relies on the reader
   consulting a separate doc mid-read. Dual-track with aliases
   makes the mapping available at the import site.

## Consequences

- **Grep still works** for the engineering names, which is what
  developers actually grep for.
- **Every new concept needs two names decided up front.** For a
  while we added biology names post-hoc and they felt contrived
  (what's the biology for "fitness evaluator"?). Now we pick
  both at the time of introduction or pick "no biology name"
  explicitly (`safety/regeneration/` has no clean biological
  twin — fine, it keeps the engineering name only).
- **The aliasing in imports is a one-way contract.** You can
  write `LLMPlanner as Cerebrum` to enrich a demo; you must NOT
  write `Cerebrum` in a class name, type annotation, or public
  API that external callers import. The grep failure mode (1)
  above is what happens when you relax this rule.
- **`docs/naming.md` is the source of truth** for the mapping.
  Adding a new organ without updating it is a lint failure
  (pending — not yet enforced).
