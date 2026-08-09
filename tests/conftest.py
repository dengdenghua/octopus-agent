"""Implementation note."""

from __future__ import annotations

import functools
from uuid import uuid4

import pytest

from runtime.platform.models import (
    Budget,
    BudgetLimits,
    BudgetSpec,
    CostEntry,
    ExecutionResult,
    ParsedIntent,
    Step,
    TaskGraph,
    TaskId,
    TaskNode,
    ToolCall,
    Trajectory,
    TrajectoryOutcome,
)


@pytest.fixture(autouse=True)
def _reset_module_state():
    """Reset process-wide mutable state between tests.

    Prevents cross-test leakage through module-level knobs. As more
    such knobs land (prompt cache toggle, rate limiter, etc.), add
    them here so every test starts from a clean slate.

    Currently resets:
      - ``runtime.platform.runtime_policy.identity_filter._RUNTIME_OVERRIDE`` — set by
        ``PUT /api/config/identity-lock``; if a test flips it to False
        and forgets to clean up, later "lock is on by default" tests
        would spuriously see it off.
      - All eight singletons (EventBus, StateStore, PluginLoader,
        UsagePricing, EvolutionAutoTrigger, AmbientScheduler,
        CamouflageScheduler, RegenerationScheduler). Without this,
        tests that triggered a scheduler thread or populated the
        eventbus could leak state into the next test — e.g. the
        invariants_router cache picking up stale third-party module
        state, or anthropic SDK lazy-imports surviving across tests.
    """
    from runtime.platform import identity_filter as _idf

    _idf.set_runtime_lock(None)
    _reset_injection_taint()
    _reset_delegation_budget()
    _reset_subagent_runners()
    yield
    _idf.set_runtime_lock(None)
    _reset_injection_taint()
    _reset_delegation_budget()
    _reset_subagent_runners()
    _reset_singletons()


def _reset_subagent_runners() -> None:
    """Clear the process-wide subagent dispatch globals.

    App wiring (serve startup, or any test that builds the FastAPI app)
    installs the persistent and ephemeral runners via
    ``set_sub_agent_runner`` / ``set_ephemeral_role_runner``. Without a
    reset they leak into later tests — cowork's runner-availability
    probe then reports "runner configured" and
    ``test_runtime_does_not_enable_runner_without_subagent_executor``
    only failed when the full suite ran in one process.
    """
    from runtime.execution.subagents import set_sub_agent_runner
    from runtime.execution.suckers.ephemeral_agents import set_ephemeral_role_runner

    set_sub_agent_runner(None)
    set_ephemeral_role_runner(None)


@pytest.fixture(autouse=True)
def _isolate_gene_locks(tmp_path, monkeypatch):
    """Give every test a private gene-locks store.

    The store path resolves under the app data dir, so the suite would
    otherwise read — and on first boot even WRITE — the live
    ``data/gene_locks.json`` of this checkout. Whatever mode/maturity a
    serve run last persisted there then decides whether planner-rewrite
    and promotion tests pass (production+low level → "gene_locks
    blocked"), which is exactly the flappy cluster we kept chasing.
    Fresh per-test state = dev mode, no cooldowns, deterministic.
    """
    from runtime.safety.gene_locks import simple_gate as _sg

    monkeypatch.setattr(_sg, "_store_path", lambda: tmp_path / "gene_locks.json")
    monkeypatch.setattr(_sg, "_CACHED", None)
    monkeypatch.setattr(_sg, "_INTEGRITY_FAILED", None)
    monkeypatch.delenv("OCTOPUS_GENE_LOCKS_MODE", raising=False)
    yield
    # Drop state minted against the tmp path so the next test (whose
    # fixture re-nulls anyway) can never see a Path that no longer exists.
    _sg._CACHED = None
    _sg._INTEGRITY_FAILED = None


@pytest.fixture(autouse=True)
def _disable_os_keychain(monkeypatch):
    """Keep the suite away from the developer's real OS keychain.

    At-rest encryption keys resolve through
    ``runtime.platform.credentials.secret_store``, which mints and stores a
    key in the platform keychain when none is configured. Left enabled, a
    test run would prompt for keychain access, write entries into the
    developer's login keyring, and — worse — make outcomes depend on
    whether a key happened to exist, so the same test would encrypt on a
    laptop and stay plaintext in CI. ``OCTOPUS_KEYCHAIN=off`` pins every
    test to the no-keychain path; tests that want a key set the explicit
    env var instead.

    The resolved-key cache is process-wide, so it is cleared on both sides
    of the test: a key cached under one test's env would otherwise leak
    into the next one and silently decide whether it encrypts.
    """
    from runtime.platform.credentials import secret_store as _ss

    monkeypatch.setenv("OCTOPUS_KEYCHAIN", "off")
    _ss.reset_key_cache_for_tests()
    yield
    _ss.reset_key_cache_for_tests()


@pytest.fixture(autouse=True)
def _protect_live_custom_models():
    """Restore ``data/custom_models.json`` if a test writes the live copy.

    This file is the operator's real model catalog: base URLs, API keys, and
    the rows the in-app ModelPicker renders. It is gitignored, so a stray
    write leaves no diff to notice and no history to bisect — the checkout
    this guard was added from had accumulated eight entries pointing at
    ``x.test`` / ``mirror.example.com`` / ``example.test``, which are RFC
    reserved names that can never resolve. They still rendered as selectable
    models, so the picker offered mostly dead options.

    Most suites redirect correctly (``monkeypatch.chdir(tmp_path)`` is enough,
    because ``app_paths()`` walks up for a project sentinel and a tmp dir has
    none). But the config router resolves its path ONCE at construction, so
    any test that builds the app before redirecting cwd — directly or through
    a fixture ordering change — silently writes the real file. Rather than
    chase each route, snapshot and put it back.

    Deliberately restore-only, not a hard failure: a test that legitimately
    exercises persistence against the default path should still pass, it just
    must not leave the operator's catalog mutated.
    """
    from runtime.platform.process.paths import app_paths

    try:
        path = app_paths().custom_models_path
        before = path.read_bytes() if path.exists() else None
    except OSError:  # unreadable / no data dir → nothing to protect
        yield
        return
    yield
    try:
        if before is None:
            if path.exists():
                path.unlink()
        elif path.read_bytes() != before:
            path.write_bytes(before)
    except OSError:  # noqa: S110 — cleanup must never fail a test
        pass


def _reset_injection_taint() -> None:
    """Clear the per-thread prompt-injection taint + gate-handled contextvars.

    These are set during a turn (untrusted tool output) and the react loop
    only resets them at its OWN start — so executor-level tests that call
    ``execute_step`` directly, or any test that runs after a taint-marking
    one, would otherwise inherit a stale taint and spuriously block/allow
    tools. Reset every test for isolation."""
    try:
        from runtime.safety.validation import prompt_injection as _pi

        _pi.reset_injection_taint()
        _pi.set_injection_gate_handled(False)
    except Exception:  # noqa: BLE001 — never let cleanup break a test
        pass


def _reset_delegation_budget() -> None:
    """Clear per-turn delegation ledgers between tests.

    Delegation budget keeps process-wide OrderedDicts keyed by turn_id. Tests
    that leak an active session can otherwise make a later session-less
    delegation test inherit an exhausted budget and flake.
    """
    try:
        from runtime.execution.suckers import delegation_budget as _db

        _db._TURN_DELEGATIONS.clear()
        _db._TURN_FAILED_FINGERPRINTS.clear()
    except Exception:  # noqa: BLE001 — never let cleanup break a test
        pass


def _reset_singletons() -> None:
    """Drop every process-wide singleton between tests.

    Each ``reset()`` is wrapped in a try/except: a singleton that
    can't be reset (because its module failed to import on this
    platform) shouldn't take down the rest of the suite. The reset
    methods themselves are documented as test-only.
    """
    import logging

    _log = logging.getLogger(__name__)

    # (module_path, attr) tuples — imported lazily so a missing
    # optional dep on the import chain doesn't break the fixture.
    _SINGLETONS = (  # noqa: N806
        ("runtime.platform.process.eventbus", "EventBus"),
        ("runtime.platform.process.state", "StateStore"),
        ("runtime.platform.plugins.plugin_loader", "PluginLoader"),
        ("runtime.platform.budget.usage_pricing", "UsagePricing"),
        ("runtime.safety.evolution.auto_trigger", "EvolutionAutoTrigger"),
        ("runtime.memory.skills_lib.ambient_suggestions_scheduler", "AmbientScheduler"),
        ("runtime.safety.experiments.scheduler", "CamouflageScheduler"),
        ("runtime.safety.recovery.scheduler", "RegenerationScheduler"),
    )
    for mod_path, cls_name in _SINGLETONS:
        try:
            import importlib

            mod = importlib.import_module(mod_path)
            cls = getattr(mod, cls_name, None)
            if cls is None:
                continue
            reset = getattr(cls, "reset", None)
            if reset is not None:
                reset()
        except Exception as exc:  # noqa: BLE001 — singleton reset must not fail tests
            _log.debug("singleton reset skipped for %s.%s: %s", mod_path, cls_name, exc)

    # ServiceProvider stitches eventbus/statestore/plugin_loader together
    # at first ``get_provider()`` call. If we've blanked those out, the
    # provider is also stale.
    try:
        from runtime.platform import service_provider as _sp

        _sp._PROVIDER = None  # noqa: SLF001 — test reset only
    except Exception as exc:  # noqa: BLE001
        _log.debug("service_provider reset skipped: %s", exc)


@pytest.fixture
def small_limits() -> BudgetLimits:
    return BudgetLimits(tokens=1_000, usd=0.10)


@pytest.fixture
def small_budget(small_limits: BudgetLimits) -> Budget:
    return Budget(task_id=TaskId(uuid4()), limits=small_limits)


@pytest.fixture
def sample_cost() -> CostEntry:
    return CostEntry(tokens_in=100, tokens_out=50, usd=0.001, latency_ms=200.0)


@pytest.fixture
def sample_intent() -> ParsedIntent:
    return ParsedIntent(
        raw="test intent",
        intent_type="task",
        normalized_goal="run a unit test",
    )


@pytest.fixture
def sample_graph() -> TaskGraph:
    return TaskGraph(
        nodes=[
            TaskNode(node_id="n1", skill_ref="read_file"),
            TaskNode(node_id="n2", skill_ref="run_test"),
        ],
        budget=BudgetSpec(tokens=10_000, usd=0.10),
        task_type="code_fix",
    )


@pytest.fixture
def sample_step(sample_cost: CostEntry) -> Step:
    call = ToolCall(
        caller="arm:code_arm",
        sucker_id="read_file",
        args={"path": "a.py"},
    )
    result = ExecutionResult(
        call_id=call.call_id,
        status="success",
        output="ok",
        cost=sample_cost,
    )
    return Step(step_id=0, node_id="n1", action=call, result=result)


@pytest.fixture
def sample_trajectory(sample_step: Step, sample_graph: TaskGraph) -> Trajectory:
    return Trajectory(
        task_id=sample_graph.task_id,
        arm_id="code_arm",
        steps=[sample_step],
        outcome=TrajectoryOutcome(success=True),
    )


# ═══════════════════════════════════════════════════════════
# Browser availability
# ═══════════════════════════════════════════════════════════


@functools.lru_cache(maxsize=1)
def _chromium_unavailable_reason() -> str | None:
    """Why a real-browser test cannot run here, or None when it can.

    ``pytest.importorskip("playwright")`` only proves the PACKAGE is present.
    The browser binary is downloaded separately and is versioned against the
    package, so "installed package, missing or stale binary" is a real state —
    and in it those tests failed instead of skipping, which reads as a product
    regression rather than an unprovisioned machine.

    Playwright's default headless launch wants the separate
    ``chromium_headless_shell`` build, so a machine that has the full chromium
    but not the shell would skip everything for no good reason. Falling back to
    ``channel="chromium"`` runs the tests for real instead.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return "playwright is not installed"
    last: str | None = None
    for channel in (None, "chromium"):
        kwargs = {"headless": True}
        if channel:
            kwargs["channel"] = channel
        try:
            with sync_playwright() as playwright:
                playwright.chromium.launch(**kwargs).close()
            _LAUNCH_KWARGS.clear()
            _LAUNCH_KWARGS.update(kwargs)
            return None
        except Exception as exc:  # noqa: BLE001 — any launch failure means unusable
            last = str(exc).splitlines()[0][:160]
    return f"chromium cannot launch: {last}"


# Populated by the probe above with the kwargs that actually worked, so tests
# launching their own browser can match it instead of rediscovering the shell
# fallback themselves.
_LAUNCH_KWARGS: dict[str, object] = {}


def chromium_launch_kwargs() -> dict[str, object]:
    """Launch kwargs known to work here. Call ``requires_chromium()`` first."""
    return dict(_LAUNCH_KWARGS) or {"headless": True}


def requires_chromium() -> None:
    """Skip the calling test unless a launchable chromium is present.

    Install with: uv pip install playwright && python -m playwright install chromium
    """
    reason = _chromium_unavailable_reason()
    if reason is not None:
        pytest.skip(reason)
