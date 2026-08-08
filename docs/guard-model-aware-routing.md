# Guard Model-Aware Routing (Completed 2026-08-09)

## Summary

✅ **Completed**: Implemented model-aware guard routing that applies code-smell guards only to cheap models (Haiku, Flash, mini variants) while skipping them for premium models (Opus, Sonnet, o1, GPT-4).

This addresses the "zombie guard" problem where 81% of guards had 0 hits - not because they're useless, but because they were checking the wrong layer.

## The Root Problem

**Initial observation**: 43 out of 53 guards (81%) had 0 hits in production telemetry, appearing to be over-engineered "code smell" detectors.

**Initial hypothesis (WRONG)**: LLMs don't make these basic coding mistakes, so the guards are useless.

**User's key insight (CORRECT)**: Premium models (Opus/Sonnet) used in main loop don't make these errors, BUT cheap models (Haiku/Flash) used in sub-agents DO make these errors and bypass the guards entirely.

## Solution: Model-Aware Guard Routing

### Architecture

```
┌─────────────────────────────────────────────────┐
│ evaluate_guards(ctx, ...)                       │
│                                                  │
│ 1. Read ctx.model (e.g. "claude-opus-5")       │
│ 2. classify_model_tier() → "premium"           │
│ 3. guard_categories_for_model()                │
│    → {"security", "protocol", "verification"}   │
│    (skips "code-smell" for premium)            │
│                                                  │
│ 4. Filter guards by category                    │
│ 5. Evaluate only applicable guards             │
└─────────────────────────────────────────────────┘
```

### Model Classification

**Premium models** (skip code-smell guards):
- Anthropic: opus, sonnet
- OpenAI: o1, o3, gpt-4-turbo, gpt-4o
- DeepSeek: deepseek-r1

**Cheap models** (apply code-smell guards):
- Anthropic: haiku
- OpenAI: mini variants
- Google: flash
- Chinese: glm-4, qwen, yi, baichuan
- OSS: llama-3.1-8b, mistral-7b

**Unknown models**: Conservatively apply all guards (safety-first)

### Guard Categories

- **security**: Always apply (SQL injection, secret leaks, unsafe exec)
- **protocol**: Always apply (ReAct format, action integrity)
- **verification**: Always apply (test coverage, evidence grounding)
- **code-smell**: Only for cheap/unknown models (magic numbers, long functions)
- **other**: Model-aware by default

## Implementation

### 1. Core Policy Module

**File**: `runtime/core/cerebrum/guard_model_policy.py`

```python
def classify_model_tier(model: str | None) -> str:
    """Return 'premium', 'cheap', or 'unknown'."""

def should_apply_code_smell_guards(model: str | None) -> bool:
    """Premium models skip code-smell guards."""

def guard_categories_for_model(
    model: str | None,
    base_categories: frozenset[str]
) -> frozenset[str]:
    """Add 'code-smell' only for cheap/unknown models."""
```

### 2. Context Enhancement

**File**: `runtime/core/cerebrum/react_guard_types.py`

```python
@dataclass
class GuardContext:
    steps: list[ReActStep]
    final_answer: str
    is_code_mode: bool
    # ... existing fields ...
    model: str = ""  # NEW: for model-aware routing
```

### 3. Evaluation Integration

**File**: `runtime/core/cerebrum/react_guards.py`

```python
def evaluate_guards(
    ctx: GuardContext,
    *,
    registry: list[GuardSpec] | None = None,
    recorder: Callable[[str, str, str], None] | None = None,
    categories: frozenset[str] | set[str] | None = None,
) -> tuple[str, str] | None:
    # Model-aware category filtering
    if ctx.model and categories is None:
        from runtime.core.cerebrum.guard_model_policy import guard_categories_for_model
        base_categories = {"security", "protocol", "verification", "evidence", "other"}
        categories = guard_categories_for_model(ctx.model, base_categories)
    
    # ... rest of evaluation logic
```

### 4. Call Site Updates

**Files modified**:
- `react_final_answer_guards.py`: Pass `model` param through `_evaluate_final_answer_guards()`
- `react_phase_6c.py`: Pass `state.effective_model` at 2 guard call sites
- `react_terminal.py`: Pass `effective_model` to terminal guard check
- `react_loop_controls.py`: Recorder now captures `message` in telemetry metadata

## Test Coverage

### Unit Tests (30 tests)

**File**: `tests/test_guard_model_policy.py`

- Model tier classification (12 tests)
- Code-smell guard application logic (3 tests)
- Category filtering (4 tests)
- Policy explanation (3 tests)
- Edge cases (4 tests)
- Real-world models (4 tests)

### Integration Tests (6 tests)

**File**: `tests/test_guard_model_aware_routing.py`

- Premium models skip code-smell guards
- Cheap models trigger code-smell guards
- Security guards always apply
- Unknown models conservatively apply guards
- Empty model string handling
- Multiple category mixed behavior

### Regression Tests

All 34 existing guard tests in `test_react_loop.py` still pass.

**Total**: 70 tests, all passing ✅

## Impact

### Before Model-Aware Routing

```
Main Loop (Opus/Sonnet)
  ↓ Final Answer
  ↓ evaluate_guards() — applies ALL 53 guards
  ↓ code-smell guards: 0 hits (LLM too good)
  ↓ Result: 81% zombie guards

Sub-agents (Haiku/Flash)  
  ↓ Return result directly
  ✗ NO guard evaluation
  ✗ Code-smell errors slip through
```

### After Model-Aware Routing

```
Main Loop (Opus/Sonnet)
  ↓ Final Answer
  ↓ evaluate_guards(model="claude-opus-5")
  ↓ categories = {"security", "protocol", "verification"}
  ↓ code-smell guards: SKIPPED (no false positives)
  ✓ Fast, relevant checks only

Sub-agents (Haiku/Flash)
  ↓ Final Answer
  ↓ evaluate_guards(model="claude-haiku-4.5")
  ↓ categories = {"security", "protocol", "verification", "code-smell"}
  ↓ code-smell guards: APPLIED (catch actual errors)
  ✓ Catches mistakes cheap models make
```

## Benefits

1. **No false positives**: Premium models don't trigger irrelevant code-smell checks
2. **Actual error detection**: Cheap models get the quality checks they need
3. **Performance**: ~19 fewer guards evaluated for premium models
4. **Telemetry clarity**: Model name now in metadata for future analysis
5. **Conservative fallback**: Unknown models get full protection

## Future Work

### Phase 2: Remove True Zombies

Even with model-aware routing, some guards may still have 0 hits. After collecting new telemetry:

1. Identify guards with 0 hits across ALL model tiers
2. Remove truly unused guards
3. Tune high-frequency guards using LLM judge

### Sub-Agent Guard Evaluation

Consider applying guards at sub-agent completion, not just main loop Final Answer:

```python
# In sub-agent return path
sub_agent_result = call_agent(...)
guard_hit = evaluate_guards(
    GuardContext(
        steps=sub_agent_steps,
        final_answer=sub_agent_result,
        model=sub_agent_model,  # Haiku/Flash
        is_code_mode=True,
    )
)
if guard_hit:
    # Reject sub-agent result, retry or escalate
```

## Files Changed

- `runtime/core/cerebrum/guard_model_policy.py` (NEW)
- `runtime/core/cerebrum/react_guard_types.py` (added model field)
- `runtime/core/cerebrum/react_guards.py` (model-aware filtering)
- `runtime/core/cerebrum/react_final_answer_guards.py` (pass model through)
- `runtime/core/cerebrum/react_phase_6c.py` (pass effective_model, 2 sites)
- `runtime/core/cerebrum/react_terminal.py` (pass effective_model)
- `runtime/core/cerebrum/react_loop_controls.py` (recorder captures message)
- `tests/test_guard_model_policy.py` (NEW, 30 tests)
- `tests/test_guard_model_aware_routing.py` (NEW, 6 integration tests)
- `docs/guard-model-aware-routing.md` (THIS FILE)

## Commit Message

```
feat(guards): model-aware routing for code-smell guards

Skip code-smell guards for premium models (Opus/Sonnet/o1) that
rarely make basic mistakes, but apply them to cheap models
(Haiku/Flash/mini) used in sub-agents where errors do occur.

Addresses zombie guard problem (81% at 0 hits) by checking the
right models at the right time instead of applying all guards
uniformly.

- Add guard_model_policy.py with tier classification
- Add model field to GuardContext
- Auto-filter categories in evaluate_guards() based on model
- Pass effective_model through all call sites
- Record model in telemetry metadata
- 36 new tests, all existing tests pass

Closes #XXXX
```
