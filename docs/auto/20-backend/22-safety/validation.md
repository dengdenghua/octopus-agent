---
type: "SafetySubsystem"
title: "Safety · Validation"
description: "宪法层 · PRIV/LAWF/DGNT/SELF/EXFIL 五类 · rule gate + LLM judge + profile 降级。"
tags: ["backend", "safety"]
tier: "core"
---
# Safety · Validation

> 宪法层 · PRIV/LAWF/DGNT/SELF/EXFIL 五类 · rule gate + LLM judge + profile 降级。

**Source**: `runtime/safety/validation/`

## Exports

- `CONSTITUTION_SUMMARY`
- `ConstitutionViolationEvent`
- `Judge`
- `JudgeVerdict`
- `ProfileName`
- `Verdict`
- `build_judge_from_llm_fn`
- `build_judge_from_router`
- `check_outbound`
- `get_constitution_summary`
- `get_judge`
- `get_profile`
- `null_judge`
- `reset_profile_for_tests`
- `scan_pii`
- `scrub_pii`
- `set_judge`
- `set_profile`

## Modules

| Module | Summary |
| --- | --- |
| `bootstrap.py` | Bootstrap wiring for the constitution's LLM-judge tier. |
| `events.py` | Journal event types for constitution violations. |
| `gate.py` | The constitution gate · the single entry point channel adapters and outbound-path code call before sending anything externally. |
| `judge.py` | LLM-judge layer · semantic gate for cases regex can't catch. |
| `llm_judge.py` | Production LLM judge wiring · bridges ``constitution.judge`` to the runtime's ``ModelRouter`` abstraction. |
| `profiles.py` | Constitution profiles · strict / normal / lax. |
| `prompt_injection.py` | Indirect prompt-injection defense for untrusted tool output. |
| `rules.py` | Rule-layer checks · regex-based PII + keyword-based hazard detection. |
| `soul.py` | Constitution internalization · compress the policy into a compact prompt section for injection into agent system prompts. |
| `trust_signal.py` | Trust signal — bridges P1 guard telemetry into P0 constitution decisions. |

## Key classes & functions

> AST 自动提取 · 仅列公开顶层 class / function · 签名与真实代码一致。

### `bootstrap.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def llm_judge_enabled(explicit, config_value)` | Resolve the judge opt-in. Precedence, highest first: 1. ``explicit`` kwarg (tests). 2. ``OCTOPUS_ENABLE_LLM_JUDGE`` env var (emergency overr |
| func | `def maybe_register_llm_judge(router, enabled, config_value, model)` | Register the LLM judge when enabled and a router is available. |

### `events.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class ConstitutionViolationEvent(JournalEvent)` | A gate call that detected one or more constitution clauses being violated. Recorded regardless of action (block / rewrite / audit) so downst |

### `gate.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class Verdict` | Result of a ``check_outbound`` call. |
| func | `def check_outbound(message, destination, session, owner_destinations, overrides, enable_trust_signal)` | Apply the rule-layer gate to ``message``. |

### `judge.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class JudgeVerdict` |  |
| func | `def null_judge(message, destination, session)` | Default · never blocks. Suitable when no LLM is available or the deployment doesn't want the latency cost. |
| func | `def set_judge(judge)` | Install a judge · ``None`` resets to the null judge. |
| func | `def get_judge()` |  |
| func | `def build_judge_from_llm_fn(llm_call, prompt_template)` | Helper · wrap a raw "prompt → response" LLM callable into a Judge. ``llm_call`` takes a prompt string · returns the raw model reply. Parsing |

### `llm_judge.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def build_judge_from_router(router, model, system_provider, max_tokens, temperature, cache_ttl_s, cache_max_size, prompt_template)` | Build a judge that calls ``router.call()`` per outbound message (modulo cache hits). |

### `profiles.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def set_profile(name)` | Install the global profile. Raises ``ValueError`` on unknown names · callers should surface that to the user rather than silently fall back. |
| func | `def get_profile()` |  |
| func | `def reset_profile_for_tests()` | Back to the default. Test fixtures call this between cases. |
| func | `def enforces_pii_rewrite(profile)` | True if the gate should rewrite PII to placeholders. False means PII passes through (still logged via violations list · just not mutated). |
| func | `def enforces_judge_verdict(profile)` | True if the LLM judge's ``block`` / ``human_gate`` actions are authoritative. False means judge decisions degrade to ``allow`` but the reaso |
| func | `def enforces_secrets_block(profile)` | Secrets always block · even in lax. This is the hard floor · once a credential is on the wire the attacker owns it. Kept as a flag so the co |

### `prompt_injection.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class InjectionScan` | Result of scanning a blob of untrusted text. |
| func | `def scan_for_injection(text, max_chars)` | Flag known prompt-injection markers in ``text`` (first ``max_chars``). |
| func | `def is_untrusted_tool(name, affinity, args)` | Whether a tool's output should be treated as external/untrusted. |
| func | `def wrap_untrusted_observation(text, source, scan)` | Fence ``text`` as untrusted data with an instruction-boundary header. |
| func | `def reset_injection_taint()` | Clear taint at the start of a turn. |
| func | `def mark_injection_taint(severity)` | Raise the turn's taint to at least ``severity`` (monotonic). |
| func | `def current_injection_taint()` | Current taint severity for this turn (``"none"`` when clean). |
| func | `def injection_taint_gates(threshold)` | Whether the turn is tainted at/above ``threshold`` — i.e. a high-risk tool should be forced through human approval. |
| func | `def set_injection_gate_handled(value)` |  |
| func | `def injection_gate_already_handled()` |  |

### `rules.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class RuleHit` | One match from a rule pattern · what and where. |
| func | `def scan_pii(text)` | Return every PII pattern hit in ``text`` · no side effects. |
| func | `def scan_secrets(text)` | Return every SECRET-grade pattern hit · these are Block candidates. |
| func | `def scrub_pii(text)` | Replace PII matches with placeholders. Returns (rewritten, hits). |

### `soul.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def get_constitution_summary()` | Return the compact summary block · idempotent · safe to inject multiple times (no embedded placeholders). |

### `trust_signal.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def compute_guard_trust_score(digest, category, min_judged_for_signal)` | Compute trust score from a GuardTelemetry digest. |
| func | `def classify_trust_score(score)` | Bucket a numeric score into a coarse label for downstream use. |
| func | `def fetch_current_trust_score(category, min_judged_for_signal)` | Read the singleton GuardTelemetry sink and compute current trust. |
| func | `def render_trust_summary(digest, category)` | One-line summary for logs / dashboard / CLI. |


## Who imports this

**19** file(s) reference this package:

- **`runtime/adapters/`** · 1 file(s)
  - `runtime/adapters/channels/base.py`
- **`runtime/cli_serve.py/`** · 1 file(s)
  - `runtime/cli_serve.py`
- **`runtime/core/`** · 4 file(s)
  - `runtime/core/cerebrum/_react_execution_phase6d.py`
  - `runtime/core/cerebrum/_react_prompt_assembly_state.py`
  - `runtime/core/cerebrum/react_parallel_dispatch.py`
  - `runtime/core/cerebrum/react_resume.py`
- **`runtime/execution/`** · 7 file(s)
  - `runtime/execution/agents/loader.py`
  - `runtime/execution/codex_backend/dynamic_tools.py`
  - `runtime/execution/misc/parallel_runner.py`
  - `runtime/execution/parallel_agents/orchestrator.py`
  - `runtime/execution/subagents/bridge.py`
  - _… and 2 more_
- **`runtime/memory/`** · 1 file(s)
  - `runtime/memory/threads/llm_summariser.py`
- **`runtime/safety/`** · 4 file(s)
  - `runtime/safety/approval/approval_gate.py`
  - `runtime/safety/evolution/weekly_report.py`
  - `runtime/safety/experiments/prompt_evolver.py`
  - `runtime/safety/governance/execution_policy.py`
- **`runtime/sensing/`** · 1 file(s)
  - `runtime/sensing/gateway/_config_endpoints_security.py`

