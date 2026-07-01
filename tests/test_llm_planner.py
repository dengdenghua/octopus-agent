"""Implementation note."""

from __future__ import annotations

import json
import threading

import pytest

from runtime.core.cerebrum import LLMPlanner, PlannerError
from runtime.execution.suckers import SkillRegistry
from runtime.execution.suckers.builtins import register_builtins
from runtime.memory.hemolymph import ContextComposer
from runtime.memory.journal import InMemoryJournal
from runtime.platform.models import BudgetSpec, ParsedIntent
from runtime.sensing.model_router import MockModelRouter, ModelResponse


@pytest.fixture
def registry() -> SkillRegistry:
    r = SkillRegistry()
    register_builtins(r)
    return r


@pytest.fixture
def composer(registry) -> ContextComposer:
    return ContextComposer(registry=registry, journal=InMemoryJournal())


@pytest.fixture
def intent() -> ParsedIntent:
    return ParsedIntent(raw="x", intent_type="task", normalized_goal="list files")


def _make_plan_json(nodes: list[dict]) -> str:
    return json.dumps({"reasoning": "test", "nodes": nodes})


class _ConcurrentUsageRouter:
    def __init__(self, response: str) -> None:
        self.response = response
        self.both_started = threading.Barrier(2)
        self.allow_beta_response = threading.Event()

    def call(self, request) -> ModelResponse:
        content = str(request.messages[-1].content)
        is_beta = "goal-beta" in content
        self.both_started.wait(timeout=5)
        if is_beta:
            assert self.allow_beta_response.wait(timeout=5)
            return ModelResponse(text=self.response, input_tokens=31, output_tokens=7)
        return ModelResponse(text=self.response, input_tokens=17, output_tokens=5)


# ═══════════════════════════════════════════════════════════
# Happy Path
# ═══════════════════════════════════════════════════════════


class TestHappyPath:
    def test_valid_plan_produces_graph(self, registry, composer, intent):
        response = _make_plan_json(
            [
                {"skill": "list_cwd", "args": {"path": "."}},
                {"skill": "count_words", "args": {"text": "{n0.path}"}},
            ]
        )
        router = MockModelRouter(response=response)
        planner = LLMPlanner(router=router, registry=registry, composer=composer)

        graph = planner.plan(intent)
        assert graph.strategy == "llm_planner"
        assert len(graph.nodes) == 2
        assert graph.nodes[0].skill_ref == "list_cwd"
        assert graph.nodes[1].skill_ref == "count_words"
        assert graph.nodes[1].args_template == {"text": "{n0.path}"}

    def test_planner_usage_is_attached_to_each_graph(self, registry, composer, intent):
        response = _make_plan_json([{"skill": "list_cwd", "args": {}}])
        planner = LLMPlanner(
            router=MockModelRouter(response=response, default_input_tokens=17),
            registry=registry,
            composer=composer,
        )

        first = planner.plan(intent)
        planner.router._default_in = 31  # type: ignore[attr-defined]
        second = planner.plan(intent)

        assert first.planner_usage["input_tokens"] == 17
        assert second.planner_usage["input_tokens"] == 31
        assert planner.last_plan_usage["input_tokens"] == 31

    def test_last_plan_usage_is_thread_local(self, registry, composer):
        response = _make_plan_json([{"skill": "list_cwd", "args": {}}])
        router = _ConcurrentUsageRouter(response)
        planner = LLMPlanner(router=router, registry=registry, composer=composer)
        beta_done = threading.Event()
        results: dict[str, dict[str, int]] = {}
        errors: list[BaseException] = []

        def _alpha() -> None:
            try:
                graph = planner.plan(ParsedIntent(
                    raw="goal-alpha",
                    intent_type="task",
                    normalized_goal="goal-alpha",
                ))
                results["alpha_graph"] = graph.planner_usage
                router.allow_beta_response.set()
                assert beta_done.wait(timeout=5)
                results["alpha_last"] = planner.last_plan_usage
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        def _beta() -> None:
            try:
                graph = planner.plan(ParsedIntent(
                    raw="goal-beta",
                    intent_type="task",
                    normalized_goal="goal-beta",
                ))
                results["beta_graph"] = graph.planner_usage
                results["beta_last"] = planner.last_plan_usage
                beta_done.set()
            except BaseException as exc:  # noqa: BLE001
                router.allow_beta_response.set()
                beta_done.set()
                errors.append(exc)

        threads = [threading.Thread(target=_alpha), threading.Thread(target=_beta)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        assert not errors
        assert all(not thread.is_alive() for thread in threads)
        assert results["alpha_graph"]["input_tokens"] == 17
        assert results["beta_graph"]["input_tokens"] == 31
        assert results["alpha_last"]["input_tokens"] == 17
        assert results["beta_last"]["input_tokens"] == 31

    def test_edges_linear(self, registry, composer, intent):
        response = _make_plan_json(
            [
                {"skill": "list_cwd", "args": {}},
                {"skill": "count_words", "args": {}},
                {"skill": "hash_text", "args": {}},
            ]
        )
        router = MockModelRouter(response=response)
        graph = LLMPlanner(router=router, registry=registry, composer=composer).plan(intent)
        assert len(graph.edges) == 2
        assert [e.from_node for e in graph.edges] == ["n0", "n1"]
        assert [e.to_node for e in graph.edges] == ["n1", "n2"]

    def test_plan_preserves_depends_on_for_parallel_edges(self, registry, composer, intent):
        response = _make_plan_json(
            [
                {"skill": "list_cwd", "args": {}},
                {"skill": "count_words", "args": {}, "depends_on": [0]},
                {"skill": "hash_text", "args": {}, "depends_on": [0]},
            ]
        )
        router = MockModelRouter(response=response)
        graph = LLMPlanner(router=router, registry=registry, composer=composer).plan(intent)
        pairs = {(e.from_node, e.to_node) for e in graph.edges}
        assert ("n0", "n1") in pairs
        assert ("n0", "n2") in pairs
        assert ("n1", "n2") not in pairs

    def test_task_type_derived(self, registry, composer):
        debug_intent = ParsedIntent(raw="x", intent_type="debug", normalized_goal="fix bug")
        router = MockModelRouter(response=_make_plan_json([{"skill": "list_cwd", "args": {}}]))
        graph = LLMPlanner(router=router, registry=registry, composer=composer).plan(debug_intent)
        assert graph.task_type == "code_fix"

    def test_markdown_fence_tolerated(self, registry, composer, intent):
        wrapped = (
            "Here is my plan:\n```json\n"
            + _make_plan_json([{"skill": "list_cwd", "args": {}}])
            + "\n```\n"
        )
        router = MockModelRouter(response=wrapped)
        graph = LLMPlanner(router=router, registry=registry, composer=composer).plan(intent)
        assert len(graph.nodes) == 1


# ═══════════════════════════════════════════════════════════
# Implementation note.
# ═══════════════════════════════════════════════════════════


class TestErrorPaths:
    def test_non_json_response_raises(self, registry, composer, intent):
        router = MockModelRouter(response="plain text no json here")
        with pytest.raises(PlannerError, match="lacks JSON"):
            LLMPlanner(router=router, registry=registry, composer=composer).plan(intent)

    def test_malformed_json_raises(self, registry, composer, intent):
        router = MockModelRouter(response="{nodes: [this is broken json}")
        with pytest.raises(PlannerError, match="parse failed"):
            LLMPlanner(router=router, registry=registry, composer=composer).plan(intent)

    def test_empty_nodes_raises(self, registry, composer, intent):
        router = MockModelRouter(response=_make_plan_json([]))
        with pytest.raises(PlannerError, match="no nodes"):
            LLMPlanner(router=router, registry=registry, composer=composer).plan(intent)

    def test_unknown_skill_raises(self, registry, composer, intent):
        router = MockModelRouter(
            response=_make_plan_json([{"skill": "totally_fake_skill", "args": {}}])
        )
        with pytest.raises(PlannerError, match="unknown skill"):
            LLMPlanner(router=router, registry=registry, composer=composer).plan(intent)

    def test_call_agent_requires_explicit_allow(self, intent):
        from runtime.execution.suckers.sub_agent import register_sub_agent_skill

        registry = SkillRegistry()
        register_builtins(registry)
        register_sub_agent_skill(registry)
        composer = ContextComposer(registry=registry, journal=InMemoryJournal())
        router = MockModelRouter(
            response=_make_plan_json(
                [
                    {
                        "skill": "call_agent",
                        "args": {"agent_id": "coder", "prompt": "handle this"},
                    }
                ]
            )
        )
        planner = LLMPlanner(router=router, registry=registry, composer=composer)

        with pytest.raises(PlannerError, match="subagent action"):
            planner.plan(intent)

    def test_args_not_dict_raises(self, registry, composer, intent):
        router = MockModelRouter(
            response=_make_plan_json([{"skill": "list_cwd", "args": "not-a-dict"}])
        )
        with pytest.raises(PlannerError, match="args must be dict"):
            LLMPlanner(router=router, registry=registry, composer=composer).plan(intent)

    def test_too_many_nodes_raises(self, registry, composer, intent):
        too_many = [{"skill": "list_cwd", "args": {}}] * 20
        router = MockModelRouter(response=_make_plan_json(too_many))
        planner = LLMPlanner(router=router, registry=registry, composer=composer, max_nodes=5)
        with pytest.raises(PlannerError, match="too long"):
            planner.plan(intent)


# ═══════════════════════════════════════════════════════════
# Implementation note.
# ═══════════════════════════════════════════════════════════


class TestInterfaceCompat:
    def test_signature_matches_staticplanner(self, registry, composer, intent):
        """Implementation note."""
        router = MockModelRouter(response=_make_plan_json([{"skill": "list_cwd", "args": {}}]))
        llm = LLMPlanner(router=router, registry=registry, composer=composer)
        from runtime.core.cerebrum import StaticPlanner

        static = StaticPlanner(rules=[], default_budget=BudgetSpec(tokens=100, usd=0.01))

        # Implementation note.
        assert callable(llm.plan)
        assert callable(static.plan)


class TestRouterReceivesContext:
    def test_call_log_shows_system_and_user(self, registry, composer, intent):
        router = MockModelRouter(response=_make_plan_json([{"skill": "list_cwd", "args": {}}]))
        LLMPlanner(router=router, registry=registry, composer=composer).plan(intent)

        assert len(router.call_log) == 1
        msgs = router.call_log[0].messages
        roles = [m.role for m in msgs]
        assert "system" in roles
        assert "user" in roles
        # Implementation note.
        user_text = next(m.content for m in msgs if m.role == "user")
        assert "list files" in user_text
