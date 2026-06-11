# ADR-008 · Constitution enforcement profiles

Status: Accepted | Date: 2026-04

## Context

The constitution gate ([docs/constitution.md](../constitution.md))
defines five principle categories (PRIV / LAWF / DGNT / SELF /
EXFIL) and three enforcement layers (Rule regex · LLM-Judge ·
Human-Gate). The same runtime ships to very different deployments:

* A hosted multi-tenant service where every outbound to a channel
  is untrusted and must be scrubbed aggressively.
* A developer running agents locally against their own IDE, where
  a false-positive on PII rewrite is an annoyance (own email
  address in own IDE isn't a leak).
* An air-gapped / internal deployment where operators explicitly
  accept the risk profile and want audit-only behavior to preserve
  flow.

One enforcement level fits none of these well. Section 8 of the
constitution spec already sketched three profiles — strict /
normal / lax — but no code enforced them. Every decision was
hard-coded `strict`.

## Decision

Add a process-level profile setting at
`runtime.safety.validation.profiles`:

```python
from runtime.safety.validation import set_profile, get_profile

set_profile("strict")   # default
set_profile("normal")
set_profile("lax")
```

The gate consults **policy flags** (not the profile name
directly), so adding a new profile only means flipping bits in
`profiles.py`:

* `enforces_pii_rewrite()` → `True` in strict/normal, `False` in lax
* `enforces_judge_verdict()` → `True` in strict, `False` otherwise
* `enforces_secrets_block()` → `True` always (hard floor)

| Behavior                       | strict           | normal           | lax              |
|--------------------------------|------------------|------------------|------------------|
| PII rewrite on external dest   | yes              | yes              | no (audit log)   |
| Secret pattern                 | **block**        | **block**        | **block**        |
| LLM judge `block`              | authoritative    | audit-only       | audit-only       |
| LLM judge `human_gate`         | authoritative    | audit-only       | audit-only       |
| Owner destination PII bypass   | yes              | yes              | yes              |

When a decision is downgraded, the `reason` string carries an
`audit_only_*` prefix so log pipelines can still surface the
would-be-block for human review.

## Alternatives considered

* **Per-agent profile override.** Let each agent set its own
  profile in `profile.jsonc`. Rejected for now — introduces
  ambiguity when agents collaborate (whose profile wins on a
  shared channel?). Can layer on later with a `profile` kwarg
  on `check_outbound` · the gate already accepts one for
  testability.

* **Per-destination profile (channel-level).** E.g. strict for
  `channels:discord:*`, lax for `channels:internal_slack:*`.
  Deferred · the cross-product of profiles × destinations
  explodes the config surface and we don't have the use-case
  signal yet.

* **No profiles · only per-rule overrides.** `DGNT-4: journal`
  style. Still a reasonable complement (documented in
  `constitution.md §8`) but doesn't replace profiles — operators
  want a one-dial "how aggressive" knob before they reach for
  clause-level tuning.

## Consequences

**Positive**

* The runtime now matches the documented profile spec — no
  surprise where code behavior diverges from the doc.
* New profiles are mechanical additions (flip flags, add a name
  to the `_VALID_PROFILES` tuple, bump tests).
* Secrets staying hard-blocked across all profiles is now
  explicit in code (`enforces_secrets_block` returns `True`
  unconditionally) rather than implicit from "no profile
  touches the secret path".

**Negative**

* One more global knob. Tests must `reset_profile_for_tests()`
  in fixtures to avoid cross-contamination. Wrapped into the
  `test_constitution_profiles.py` autouse fixture.

**Neutral**

* The profile is process-global. A future multi-tenant
  deployment that wants per-tenant profiles will need to add
  a profile argument to `check_outbound` and thread it through
  callers. The flag abstraction makes that retrofit cheap.

## References

* Spec: [`docs/constitution.md §8`](../constitution.md) · the
  profile definitions this code implements.
* Implementation: `runtime/safety/constitution/profiles.py`
* Gate integration: `runtime/safety/constitution/gate.py`
  (PII pass + judge pass consult the flags).
* Tests: `tests/test_constitution_profiles.py` (14 cases across
  profile basics / PII / judge / hard floor / owner bypass).
