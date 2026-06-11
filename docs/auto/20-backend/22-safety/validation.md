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
| `events.py` | Journal event types for constitution violations. |
| `gate.py` | The constitution gate · the single entry point channel adapters and outbound-path code call before sending anything externally. |
| `judge.py` | LLM-judge layer · semantic gate for cases regex can't catch. |
| `llm_judge.py` | Production LLM judge wiring · bridges ``constitution.judge`` to the runtime's ``ModelRouter`` abstraction. |
| `profiles.py` | Constitution profiles · strict / normal / lax. |
| `rules.py` | Rule-layer checks · regex-based PII + keyword-based hazard detection. |
| `soul.py` | Constitution internalization · compress the policy into a compact prompt section for injection into agent system prompts. |
| `trust_signal.py` | Trust signal — bridges P1 guard telemetry into P0 constitution decisions. |

## Who imports this

**6** file(s) reference this package:

- **`runtime/adapters/`** · 1 file(s)
  - `runtime/adapters/channels/base.py`
- **`runtime/core/`** · 1 file(s)
  - `runtime/core/cerebrum/react_loop.py`
- **`runtime/execution/`** · 1 file(s)
  - `runtime/execution/agents/loader.py`
- **`runtime/safety/`** · 2 file(s)
  - `runtime/safety/evolution/weekly_report.py`
  - `runtime/safety/experiments/prompt_evolver.py`
- **`runtime/sensing/`** · 1 file(s)
  - `runtime/sensing/gateway/config_router.py`

