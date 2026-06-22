
# ruff: noqa: E402 — module-level imports below intentionally appear
# after the local logger is built so that runtime modules log through
# the configured handler from their first import-time side effects.
from __future__ import annotations

import json
import logging
import re
from typing import Any

_logger = logging.getLogger(__name__)

from runtime.adapters.instrumentation import trace_stage
from runtime.execution.suckers import SkillRegistry
from runtime.memory.hemolymph import ContextComposer
from runtime.memory.journal import Journal
from runtime.platform.models import (
    BudgetSpec,
    ParsedIntent,
    SkillId,
    TaskGraph,
    TaskNode,
    WorkflowEdge,
)
from runtime.platform.models.llm import (
    Message,
    ModelRequest,
    ModelRouter,
)
from runtime.platform.prompts import get_prompt

from .planner import PlannerError

_PLANNER_SYSTEM_PROMPT: str = ""


def _load_planner_prompt() -> str:
    global _PLANNER_SYSTEM_PROMPT
    _PLANNER_SYSTEM_PROMPT = get_prompt("planner_base")
    return _PLANNER_SYSTEM_PROMPT


_load_planner_prompt()


# Fenced ```json ... ``` code block · preferred form because it's
# unambiguous even when the LLM's prose contains other braces. The
# planner prompt itself asks for this form, so the happy path is
# fenced; non-fenced is the fallback.
_JSON_FENCED_RE = re.compile(
    r"```(?:json)?\s*\n(\{.*?\})\s*\n```",
    re.DOTALL | re.IGNORECASE,
)


# Template-reference scan pattern — match ``{nN}`` / ``{nN.field}`` /
# ``{nN.field.sub}`` embedded anywhere in a string. Used to infer
# data dependencies when the LLM didn't emit explicit ``depends_on``.
_TEMPLATE_REF_RE = re.compile(r"\{(n\d+)(?:\.[a-zA-Z0-9_.]+)?\}")

_NON_SKILL_ACTION_NAMES: frozenset[str] = frozenset({
    "call_agent",
})


def _render_team_roster_section(user_context: dict) -> str:
    roster = user_context.get("agent_roster") if isinstance(user_context, dict) else None
    if not isinstance(roster, list) or not roster:
        return ""
    team_mode = str(user_context.get("team_mode") or "chat").strip().lower()
    team_phase = str(user_context.get("team_phase") or "").strip().lower()

    # Find the active speaker · the per-turn user_context tags the
    # currently-running agent with ``is_self=True``. Without a
    # "YOU ARE" banner the LLM looks at the roster and cosplays the
    # first-listed teammate (previously this meant every agent, including
    # Coder, said "I'm Octopus"). We also render a per-entry ``(YOU)``
    # marker so the association survives any prompt reordering.
    self_entry: dict | None = None
    for entry in roster:
        if isinstance(entry, dict) and entry.get("is_self"):
            self_entry = entry
            break
    self_role = str((self_entry or {}).get("role") or "").strip().lower()

    lines: list[str] = []
    if self_entry is not None:
        self_id = str(self_entry.get("agent_id") or "").strip()
        self_name = str(self_entry.get("display_name") or self_id)
        lines.append("## YOUR IDENTITY")
        lines.append(
            f"You are **{self_name}** (agent id: `{self_id}`). When asked "
            f"who you are, say you are {self_name}. Do NOT impersonate "
            "teammates from the roster below · they are DIFFERENT agents "
            "sharing this thread with you."
        )
        # Persona vocabulary rule · the framework's organ-naming
        # convention ("19 organs", "tentacle", "siphon", "eyes", etc.)
        # is INTERNAL · the user sees a team of named characters /
        # their soul or training data and sound like organs instead
        # of teammates.
        lines.append(
            "Refer to yourself and your teammates as people / characters "
            "/ team members (人物 / 队友 / 成员) — NEVER as "
            "\"tentacles\" or \"触手\". The internal organ names are "
            "an implementation detail; the user-facing team is "
            "a cast of personas."
        )
        lines.append("")

    lines.append("## TEAM ROSTER")
    lines.append(
        "You are part of a multi-agent team in this thread. Your teammates:"
    )
    for entry in roster:
        if not isinstance(entry, dict):
            continue
        aid = str(entry.get("agent_id") or "").strip()
        if not aid:
            continue
        name = str(entry.get("display_name") or aid)
        role = str(entry.get("role") or "").strip()
        role_tag = " · **TL (team lead)**" if role == "tl" else ""
        self_tag = " · **(YOU)**" if entry.get("is_self") else ""
        lines.append(f"- `{aid}` — {name}{role_tag}{self_tag}")
    lines.append(
        "\nWhen the user asks who else is on the team, list these "
        "teammates by name. Do NOT claim to be alone · they are real "
        "agents."
    )
    if team_mode == "chat":
        lines.append(
            "\n### ROUTING PROTOCOL (chat mode · team lead only)\n"
            "You have TWO directive sentinels. Use at most ONE per turn, "
            "and only when the situation warrants it.\n\n"
            "**1 · Handoff** · route to a single specialist:\n\n"
            "    [ROUTE TO: <agent_id>]\n"
            "    <one-sentence handoff note>\n\n"
            "Use when one teammate is clearly the right fit. After the "
            "sentinel line STOP — do not attempt to answer yourself.\n\n"
            "**2 · Vote** · collect answers from the whole roster and "
            "arbitrate (MAJORITY / synthesis):\n\n"
            "    [VOTE: <question to put to the team>]\n\n"
            "Use when the question is CONTENTIOUS or BENEFITS from "
            "multiple perspectives (architecture choices, 'should we …', "
            "strategy decisions with tradeoffs). The dispatcher runs "
            "every teammate on the question in parallel, then an "
            "arbiter agent compares the candidate answers and writes a "
            "consolidated verdict. After the sentinel line STOP.\n\n"
            "Rules for BOTH:\n"
            "- Use SPARINGLY · default to answering yourself.\n"
            "- DO NOT self-route · never emit ``[ROUTE TO: <your_own_id>]``.\n"
            "- DO NOT route or vote for conversational exchanges ('你好', "
            "'谢谢', '介绍一下') · handle directly.\n"
            "- Voting is heavier than routing · prefer routing when one "
            "specialist suffices."
        )
    elif team_mode == "cowork":
        phase_label = team_phase or "work"
        lines.append(
            "\n### COWORK PROTOCOL\n"
            f"Current cowork phase: `{phase_label}`. Your roster role: "
            f"`{self_role or 'member'}`.\n\n"
            "Cowork mode is a coordinated team round: the TL plans, "
            "members contribute from their own expertise, then the TL "
            "synthesizes the final answer. Do NOT emit [ROUTE TO] or "
            "[VOTE] sentinels in cowork mode.\n\n"
            "Phase rules:\n"
            "- `plan` + TL: write a brief plan and assign what each "
            "member should inspect. Stop after the plan; do not present "
            "the final answer yet.\n"
            "- `work` + member: provide your focused contribution, "
            "evidence, risks, assumptions, and recommended next step. "
            "Do not impersonate the TL and do not claim final authority.\n"
            "- `synthesize` + TL: merge teammate messages into one final "
            "answer, name important disagreements or uncertainty, and "
            "give concrete next actions."
        )
    return "\n".join(lines)


def _render_conversation_history(
    intent: ParsedIntent,
    *,
    max_messages: int = 12,
    max_chars: int = 4_000,
) -> str:
    """Render OpenAI-compatible chat history carried by the gateway."""
    payload = intent.user_context.get("conversation_messages", [])
    if not isinstance(payload, list):
        return ""
    rendered: list[str] = []
    total = 0
    for item in payload[-max_messages:]:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = item.get("content")
        if role not in ("system", "user", "assistant"):
            continue
        if not isinstance(content, str) or not content.strip():
            continue
        line = f"[{role}] {content.replace(chr(10), ' ').strip()}"
        remaining = max_chars - total
        if remaining <= 0:
            break
        if len(line) > remaining:
            line = line[: max(0, remaining - 1)] + "…"
        rendered.append(line)
        total += len(line) + 1
    return "\n".join(rendered)


def _extract_edges(
    plan_nodes: list[dict], node_count: int,
) -> list[WorkflowEdge]:
    """Compute the TaskGraph edges for a plan.

    Three signals are tried, in priority order:

    1. **Explicit ``depends_on``** in the plan node. A list of node
       index integers (``0``, ``1``, ...) or node-id strings
       (``"n0"``, ``"n1"``, ...). Most expressive · the LLM says
       outright "n2 needs n0 and n1".
    2. **Template-reference inference.** Scan every arg string for
       ``{nX}`` / ``{nX.key}`` patterns. If n2's args reference n0,
       we add the edge n0→n2 even without ``depends_on``. This is
       the bridge for existing prompts that already use the
       template syntax (see planner_base doc) but haven't been
       updated to emit ``depends_on``.
    3. **Linear fallback.** If neither signal yields any edge for a
       given node, stitch it to the previous one — the pre-2026-04
       behavior. Preserves the "always produce a valid serial plan"
       property as a floor.

    Why three signals and not just one:
    * Removing the linear fallback would break every existing
      planner_base prompt in the wild, and the tests that assert
      "2 nodes → 1 edge" in downstream pipelines.
    * Requiring ``depends_on`` would require every deployment to
      update their prompt before the new code works.
    * Template inference alone can miss cases where the LLM
      passes intermediate values via metadata or closures (rare
      but not impossible).

    The merged edge set is deduplicated and sanity-checked for
    cycles — cyclic deps would cause topo sort to deadlock.
    """
    from runtime.platform.models import WorkflowEdge as _WE  # noqa: N814

    edges: set[tuple[str, str]] = set()

    # Nodes whose ``depends_on`` field is a deliberate signal · pass
    # 3's linear fallback must respect these and NOT add a spurious
    # edge from the previous node.
    #
    # A ``depends_on`` is "deliberate" iff:
    #   (a) it's an empty list → LLM explicitly said "no deps", or
    #   (b) at least one of its entries resolved to a valid node →
    #       the LLM gave a usable dependency; trust the rest of
    #       its intent too
    #
    # A list of all-invalid entries (``["n99", "typo"]``) is
    # treated as absence-of-signal and falls back to linear · that
    # matches the pre-fix "typos don't break plans" behavior so
    # an LLM that miscounts indices still produces a runnable plan.
    explicit_deps_nodes: set[str] = set()

    # ── Pass 1: explicit depends_on ─────────────────────────
    for i, nd in enumerate(plan_nodes):
        # ``nd.get("depends_on") or []`` would conflate ``None`` and
        # ``[]`` — tell them apart via ``"depends_on" in nd`` so
        # only an actually-present field can register as explicit.
        has_field = "depends_on" in nd
        raw_deps = nd.get("depends_on")
        if not isinstance(raw_deps, list):
            # Non-list (None / string / dict / ...) · no signal.
            continue
        if has_field and len(raw_deps) == 0:
            # depends_on=[] · explicit "no deps".
            explicit_deps_nodes.add(f"n{i}")
        accepted_any = False
        for dep in raw_deps:
            src = _normalize_node_ref(dep)
            if src is None:
                continue
            # Self-reference / out-of-range → drop silently so an
            # LLM typo doesn't sink the whole plan. Topological
            # validation catches any remaining issue later.
            if src == f"n{i}":
                continue
            idx = _node_index(src)
            if idx is None or idx >= node_count:
                continue
            edges.add((src, f"n{i}"))
            accepted_any = True
        if accepted_any:
            # At least one usable dep · we take that as the LLM
            # having successfully declared its parents · skip the
            # fallback here too.
            explicit_deps_nodes.add(f"n{i}")

    # ── Pass 2: template reference scan ─────────────────────
    for i, nd in enumerate(plan_nodes):
        args = nd.get("args") or {}
        if not isinstance(args, dict):
            continue
        target = f"n{i}"
        for value in args.values():
            if not isinstance(value, str):
                continue
            for m in _TEMPLATE_REF_RE.finditer(value):
                src = m.group(1)
                if src == target:
                    continue
                idx = _node_index(src)
                if idx is None or idx >= node_count:
                    continue
                edges.add((src, target))

    # ── Pass 3: linear fallback for orphans ─────────────────
    # A node is "orphan" iff:
    #   - it's not the first node, AND
    #   - it has no incoming edge from pass 1 or 2, AND
    #   - it did NOT explicitly declare depends_on (any form).
    # The third clause is what makes ``depends_on: []`` mean "no
    # dependencies, run in parallel with siblings" · without it
    # that explicit signal would get squashed back into a linear
    # chain here.
    in_degrees = {f"n{i}": 0 for i in range(node_count)}
    for _src, dst in edges:
        in_degrees[dst] = in_degrees.get(dst, 0) + 1
    for i in range(1, node_count):
        node_id = f"n{i}"
        if node_id in explicit_deps_nodes:
            # LLM spoke · trust it · no fallback.
            continue
        if in_degrees.get(node_id, 0) == 0:
            edges.add((f"n{i-1}", node_id))

    # ── Cycle check ─────────────────────────────────────────
    # If the LLM emitted contradictory depends_on (a cycle), we'd
    # rather raise here than have GraphRuntime deadlock on topo
    # sort later. Simple DFS white/gray/black.
    if _has_cycle(node_count, edges):
        raise PlannerError(
            f"LLM plan has cyclic dependencies: {sorted(edges)}"
        )

    # Stable order for deterministic tests · sort by (src index, dst index).
    ordered = sorted(
        edges,
        key=lambda e: (_node_index(e[0]) or 0, _node_index(e[1]) or 0),
    )
    return [_WE(from_node=s, to_node=d) for s, d in ordered]


def _normalize_node_ref(ref: Any) -> str | None:
    """Accept ``0`` / ``"0"`` / ``"n0"`` / ``"N0"`` — any form a
    reasonable LLM might emit · return the canonical ``"n0"`` form."""
    if isinstance(ref, int):
        return f"n{ref}" if ref >= 0 else None
    if isinstance(ref, str):
        r = ref.strip().lower()
        if r.startswith("n") and r[1:].isdigit():
            return r
        if r.isdigit():
            return f"n{r}"
    return None


def _node_index(node_id: str) -> int | None:
    if not node_id.startswith("n"):
        return None
    try:
        return int(node_id[1:])
    except ValueError:
        return None


def _has_cycle(node_count: int, edges: set[tuple[str, str]]) -> bool:
    """DFS cycle detection on the directed edge set. O(V + E)."""
    adj: dict[str, list[str]] = {f"n{i}": [] for i in range(node_count)}
    for src, dst in edges:
        adj.setdefault(src, []).append(dst)
    WHITE, GRAY, BLACK = 0, 1, 2  # noqa: N806
    color = {n: WHITE for n in adj}

    def visit(n: str) -> bool:
        color[n] = GRAY
        for nxt in adj.get(n, []):
            c = color.get(nxt, WHITE)
            if c == GRAY:
                return True
            if c == WHITE and visit(nxt):
                return True
        color[n] = BLACK
        return False

    return any(visit(n) for n in adj if color[n] == WHITE)


def _scan_balanced_object(text: str, start: int) -> str | None:
    """Walk forward from ``start`` (must point at a ``{``) and return
    the slice ending at the matching close brace, or ``None`` if no
    balanced close exists.

    String-aware: any ``{``/``}`` inside a double-quoted string — even
    an escaped ``\"`` — does not affect the nesting counter. This is
    what makes this function robust to LLM output like::

        Here is your plan: {
          "reasoning": "the path is {foo}/bar.txt",
          "nodes": [...]
        }
        (hope that helps!)

    The naive ``r"\\{.*\\}"`` regex would grab from the first ``{``
    through the ``}`` inside the string literal — or through any later
    brace in the free-form tail — and produce unparseable junk.
    """
    if start >= len(text) or text[start] != "{":
        return None
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if escape:
            escape = False
            continue
        if in_string:
            if ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


class LLMPlanner:
    """LLM-driven task planner: takes a parsed intent, emits a TaskGraph.

    ╔════════════════════════════════════════════════════════════════════╗
    ║ llm_planner.py · navigation map (1037 lines).                      ║
    ║                                                                    ║
    ║   §1 prompt loading + team roster rendering       ~L38             ║
    ║   §2 conversation history rendering               ~L183            ║
    ║   §3 edge extraction + cycle detection            ~L215            ║
    ║   §4 LLMPlanner class (the bulk, ~580 lines)      ~L450            ║
    ║       §4.1 __init__ + learning hooks              ~L452-580        ║
    ║       §4.2 KG attachment + recipe assessment      ~L555-614        ║
    ║       §4.3 plan() — main entrypoint               ~L615            ║
    ║       §4.4 recipe ID + hash                       ~L815            ║
    ║       §4.5 _extract_json + _validate_nodes        ~L857            ║
    ║       §4.6 autosave (rules + memories)            ~L989            ║
    ║   §5 _derive_task_type (free helper)              ~L1029           ║
    ╚════════════════════════════════════════════════════════════════════╝
    """

    def __init__(
        self,
        router: ModelRouter,
        registry: SkillRegistry,
        composer: ContextComposer,
        planner_model: str = "mock/planner",
        default_budget: BudgetSpec | None = None,
        max_nodes: int = 10,
        learned_rules_section: str = "",
        learned_memories_section: str = "",
        *,
        auto_persist_rules_path: Any = None,       # str | Path | None
        auto_persist_memories_path: Any = None,    # str | Path | None
    ) -> None:
        self.router = router
        self.registry = registry
        self.composer = composer
        self.planner_model = planner_model
        self.default_budget = default_budget or BudgetSpec(tokens=50_000, usd=0.50)
        self.max_nodes = max_nodes
        self.auto_persist_rules_path = auto_persist_rules_path
        self.auto_persist_memories_path = auto_persist_memories_path

        if auto_persist_rules_path is not None:
            from .prompt_persistence import load_section

            loaded = load_section(auto_persist_rules_path)
            if loaded:
                learned_rules_section = loaded
        if auto_persist_memories_path is not None:
            from .prompt_persistence import load_section

            loaded = load_section(auto_persist_memories_path)
            if loaded:
                learned_memories_section = loaded

        self.learned_rules_section = learned_rules_section
        self.learned_memories_section = learned_memories_section
        self.kg: Any = None
        self.kg_max_triples: int = 15
        # When True, ``learn_kg_from_journal`` accumulates into the attached
        # durable KG instead of rebuilding a throwaway in-memory graph — so
        # learned facts survive restarts (see ``enable_persistent_kg``).
        self._kg_persistent: bool = False
        self.current_recipe_verdict: Any = None  # RecipeScore | None
        self._rules_updated_count = 0  # Implementation note.
        self._memories_updated_count = 0
        self._kg_attached_count = 0
        self._recipe_assessed_count = 0


    def update_learned_rules(self, rules: list, *, max_total_chars: int = 2000) -> None:
        from runtime.safety.recovery import format_rules_for_prompt

        self.learned_rules_section = format_rules_for_prompt(
            rules, max_total_chars=max_total_chars
        )
        self._rules_updated_count += 1
        with trace_stage("cerebrum.rules_updated") as span:
            span.set_attribute("octopus.rules.count", len(rules))
            span.set_attribute(
                "octopus.rules.prompt_section_chars",
                len(self.learned_rules_section),
            )
        self._autosave_rules()

    def learn_from_journal(
        self,
        journal: Journal,
        *,
        min_hits: int = 3,
        max_rules: int = 30,
    ) -> int:
        from runtime.safety.recovery import ExtractorConfig, RuleExtractor

        extractor = RuleExtractor(
            journal=journal,
            config=ExtractorConfig(min_hits=min_hits, max_rules_per_run=max_rules),
        )
        report = extractor.extract()
        self.update_learned_rules(report.rules_produced)
        return len(report.rules_produced)

    def update_learned_memories(
        self, memories: list, *, max_total_chars: int = 2000
    ) -> None:
        from runtime.safety.recovery import format_memories_for_prompt

        self.learned_memories_section = format_memories_for_prompt(
            memories, max_total_chars=max_total_chars
        )
        self._memories_updated_count += 1
        with trace_stage("cerebrum.memories_updated") as span:
            span.set_attribute("octopus.memories.count", len(memories))
            span.set_attribute(
                "octopus.memories.prompt_section_chars",
                len(self.learned_memories_section),
            )
        self._autosave_memories()

    def learn_memories_from_journal(self, journal: Journal) -> int:
        from runtime.safety.recovery import MemoryConsolidator

        report = MemoryConsolidator(journal).consolidate()
        self.update_learned_memories(report.memories_produced)
        return len(report.memories_produced)

    def attach_kg(self, kg: Any, *, max_triples: int = 15) -> None:
        self.kg = kg
        self.kg_max_triples = max_triples
        self._kg_attached_count += 1
        with trace_stage("cerebrum.kg_attached") as span:
            size = kg.count() if hasattr(kg, "count") else 0
            span.set_attribute("octopus.kg.triples", size)
            span.set_attribute("octopus.kg.max_triples", max_triples)

    def enable_persistent_kg(
        self, db_path: Any, *, max_triples: int | None = None
    ) -> int:
        """Back the planner's KG with a durable on-disk store.

        Once enabled, :meth:`learn_kg_from_journal` ACCUMULATES distilled
        triples into this store instead of rebuilding a throwaway in-memory
        graph each call, so knowledge survives process restarts and compounds
        across sessions — the durable half of the self-evolution loop. Triples
        already on disk are loaded immediately, so recall sees them on the very
        first turn. Returns the triple count loaded from disk.
        """
        from runtime.memory.knowledge_graph.sqlite_kg import SqliteKnowledgeGraph

        kg = SqliteKnowledgeGraph(db_path)
        self.attach_kg(
            kg,
            max_triples=max_triples if max_triples is not None else self.kg_max_triples,
        )
        self._kg_persistent = True
        return kg.count()

    def learn_kg_from_journal(
        self, journal: Journal, *, max_triples: int | None = None
    ) -> int:
        from runtime.safety.recovery import KGUpdater

        if max_triples is not None:
            self.kg_max_triples = max_triples

        # Durable path: accumulate into the attached persistent store (de-duped
        # + persisted) rather than discarding a fresh graph each call. This is
        # not a re-attach, so ``_kg_attached_count`` is left untouched.
        if self._kg_persistent and self.kg is not None:
            KGUpdater(journal, self.kg).update()
            return self.kg.count()

        # Legacy ephemeral path (unchanged): rebuild an in-memory graph.
        from runtime.memory.knowledge_graph import KnowledgeGraph

        kg = KnowledgeGraph()
        KGUpdater(journal, kg).update()
        self.attach_kg(kg, max_triples=self.kg_max_triples)
        return kg.count()

    def _render_kg_section(self) -> str:
        if self.kg is None:
            return ""
        from runtime.memory.knowledge_graph import format_triples_for_prompt

        triples = self.kg.query()  # Implementation note.
        return format_triples_for_prompt(triples, max_triples=self.kg_max_triples)

    def _render_codebase_section(self, intent: Any) -> str:
        """Auto-retrieve codebase grounding the context composer never provides
        (wiki pages + source chunks for the goal). Shared with the react chat
        loop via ``render_codebase_context``. Disable with
        OCTOPUS_CODEBASE_CONTEXT=0."""
        from runtime.memory.hemolymph.repo_context import render_codebase_context

        try:
            return render_codebase_context(
                str(getattr(intent, "normalized_goal", "") or ""),
            )
        except Exception:  # noqa: BLE001 — grounding must never break planning
            return ""

    def assess_recipe_from_journal(self, journal: Journal) -> Any:
        from runtime.safety.recovery import RecipeEvaluator

        report = RecipeEvaluator(journal).evaluate()
        my_hash = self.recipe_hash()
        match = next((s for s in report.scores if s.recipe_id == my_hash), None)
        self.current_recipe_verdict = match
        self._recipe_assessed_count += 1
        with trace_stage("cerebrum.recipe_assessed") as span:
            span.set_attribute("octopus.recipe.id", my_hash)
            span.set_attribute(
                "octopus.recipe.verdict",
                match.verdict if match else "not_found",
            )
            if match is not None:
                span.set_attribute("octopus.recipe.score", match.score)
        return match

    def _render_recipe_self_assessment(self) -> str:
        v = self.current_recipe_verdict
        if v is None or v.verdict != "losing":
            return ""
        return (
            "RECIPE SELF-ASSESSMENT (warning):\n"
            f"  Your current prompt recipe ({v.recipe_id}) has been scored "
            f"as LOSING from {v.uses} past runs (success rate "
            f"{v.success_rate * 100:.0f}%, avg ${v.avg_cost_usd:.4f}).\n"
            "  Consider being more conservative: prefer fewer, safer steps; "
            "avoid repeating patterns that previously failed."
        )


    def plan(
        self,
        intent: ParsedIntent,
        *,
        allowed_skills: list[str] | None = None,
        soul: str | None = None,
        model: str | None = None,
    ) -> TaskGraph:
        base_prompt = _PLANNER_SYSTEM_PROMPT
        from datetime import datetime as _dt
        base_prompt += (
            f"\n\n当前日期: {_dt.now().strftime('%Y-%m-%d %A')}。"
            " 搜索时请注意信息时效性,优先引用最新来源。"
        )
        if soul:
            base_prompt = f"# Agent Soul\n\n{soul}\n\n---\n\n" + base_prompt
        # Team-mode awareness · when the turn runs inside a group-chat
        # thread, tell the LLM which teammates exist so it stops
        # Source · intent.user_context["agent_roster"] · populated by the
        # turn-builder (``build_turn_session`` / realtime gateway) when
        # the thread values / metadata supply a roster. Absent roster
        # → no section, prompt length unchanged for solo turns.
        team_section = _render_team_roster_section(intent.user_context)
        if team_section:
            base_prompt = base_prompt + "\n\n" + team_section
        if self.learned_rules_section:
            base_prompt = base_prompt + "\n\n" + self.learned_rules_section
        if self.learned_memories_section:
            base_prompt = base_prompt + "\n\n" + self.learned_memories_section
        # GEPA-optimized addendum · written by
        # ``/api/evolution/gepa/apply``. Re-read on every plan() call
        # so a hot apply is picked up without restarting the planner
        # instance · cheap since the file is small + OS-cached.
        #
        # Two sources, concatenated in this order so per-recipe
        # instructions take precedence by recency:
        #
        #   1. Legacy global ``data/gepa_planner_addendum.md`` ·
        #      affects all turns regardless of recipe. Kept for
        #      backward compat with first-cut deployments.
        #   2. Per-recipe ``data/gepa_addendums/<base_recipe_id>.md``
        #      · only fires when this planner's BASE recipe_hash
        #      matches. Computed BEFORE the addendum gets folded in
        #      (recipe_hash() doesn't include the addendum), so
        #      there's no chicken-and-egg cycle.
        try:
            from runtime.safety.recovery.gepa_addendum_store import (
                load_for_recipe,
                load_global,
            )
            _global_section = load_global()
            if _global_section:
                base_prompt = base_prompt + "\n\n" + _global_section
            # Per-recipe lookup · key on BASE recipe (no addendum).
            _base_recipe_id = self.recipe_hash()
            # Multi-variant lookup FIRST · when a manifest exists for
            # this recipe, we A/B-split traffic across variants by
            # ``hash(conversation_id) % total_weight``. Sticky per
            # conversation so a thread's prompt doesn't flip
            # mid-turn. When no manifest exists, fall back to the
            # single-file per-recipe addendum (legacy behaviour).
            try:
                from runtime.safety.recovery.gepa_variants import (
                    select_variant,
                )
                _conv_id = (
                    intent.user_context.get("conversation_id")
                    if isinstance(intent.user_context, dict) else None
                )
                _variant_id, _variant_content = select_variant(
                    _base_recipe_id, _conv_id,
                )
            except (OSError, ImportError, ValueError):
                _variant_id, _variant_content = None, ""
            if _variant_id is not None:
                # Multi-variant mode is active for this recipe.
                # Empty content == we picked the control-group
                # ("no addendum") branch · don't append anything.
                if _variant_content:
                    base_prompt = base_prompt + "\n\n" + _variant_content
                # Stash the chosen variant on the planner instance
                # so downstream consumers (trajectory recorder /
                # synthesize_reply) can attribute outcomes to the
                # variant. None vs ""  vs "<vid>" distinguishes:
                #   None → no manifest, single-file path
                #   ""   → manifest present, control branch picked
                #   "vA" → variant vA picked
                self._last_chosen_variant = _variant_id  # type: ignore[attr-defined]
            else:
                # No manifest · fall back to single-file addendum.
                _recipe_section = load_for_recipe(_base_recipe_id)
                if _recipe_section:
                    base_prompt = base_prompt + "\n\n" + _recipe_section
                self._last_chosen_variant = None  # type: ignore[attr-defined]
        except (OSError, ImportError, ValueError) as exc:
            _logger.debug("recipe/variant load skipped: %s", exc)
        kg_section = self._render_kg_section()
        if kg_section:
            base_prompt = base_prompt + "\n\n" + kg_section
        codebase_section = self._render_codebase_section(intent)
        if codebase_section:
            base_prompt = base_prompt + "\n\n" + codebase_section
        recipe_warning = self._render_recipe_self_assessment()
        if recipe_warning:
            base_prompt = base_prompt + "\n\n" + recipe_warning

        packet = self.composer.compose(
            task_info=intent,
            system_prompt=base_prompt,
            budget_tokens=8_000,  # Implementation note.
            relevant_skills=allowed_skills,
        )

        system_parts = [s.content for s in packet.segments if s.bucket == "system"]
        sucker_parts = [s.content for s in packet.segments if s.bucket == "suckers"]
        user_parts = [f"USER GOAL: {intent.normalized_goal}"]
        from runtime.memory.users.profile import render_profile_memories

        profile_section = render_profile_memories(
            intent.user_context.get("profile_memories", []),
        )
        if profile_section:
            user_parts.insert(0, profile_section)
        conversation_history = _render_conversation_history(intent)
        if conversation_history:
            user_parts.insert(
                0,
                "CONVERSATION HISTORY (oldest to newest):\n"
                f"{conversation_history}",
            )

        messages = [
            Message(role="system", content="\n\n".join(system_parts)),
            Message(role="user", content="\n\n".join(sucker_parts + user_parts)),
        ]

        prefer = "default"
        if (
            self.current_recipe_verdict is not None
            and getattr(self.current_recipe_verdict, "verdict", None) == "losing"
        ):
            prefer = "strong"
        response = self.router.call(
            ModelRequest(
                model=model or self.planner_model,
                messages=messages,
                max_tokens=1024,
                temperature=0.0,
                system_provider="anthropic",
                prefer_strength=prefer,  # type: ignore[arg-type]
            )
        )

        # Stash the last plan's LLM usage on the planner instance so
        # the realtime gateway / OpenAI-compat handler can reconcile
        # it into ``additional_kwargs.octopus`` after the graph runs.
        # Without this, plan-path turns show Budget.tokens_spent (which
        # only counts executor-level commits — excludes the planner's
        # own LLM call) and under-report input/output tokens.
        #
        # Thread-safety: planner is shared across requests, so this
        # attribute races if two turns execute concurrently. For
        # accurate per-turn accounting the caller should read it
        # BEFORE yielding control. Best-effort · never raises.
        self.last_plan_usage = {
            "input_tokens": int(getattr(response, "input_tokens", 0) or 0),
            "output_tokens": int(getattr(response, "output_tokens", 0) or 0),
        }

        plan_dict = self._extract_json(response.text)
        nodes = self._validate_nodes(plan_dict.get("nodes", []))

        # (explicit depends_on > template refs > linear fallback).
        # Pre-2026-04 edges were unconditionally linear, which made
        # swarm split_strategy="topo_layers" degenerate to "single" —
        # killing all parallelism the LLM could have expressed.
        edges = _extract_edges(nodes, len(nodes))
        return TaskGraph(
            nodes=[
                TaskNode(
                    node_id=f"n{i}",
                    skill_ref=SkillId(nd["skill"]),
                    kind="sucker",
                    args_template=nd.get("args") or {},
                )
                for i, nd in enumerate(nodes)
            ],
            edges=edges,
            budget=self.default_budget,
            strategy="llm_planner",
            task_type=_derive_task_type(intent),
            # When a GEPA variant was picked for this turn, stamp it
            # onto the recipe_hash so RecipeEvaluator naturally groups
            # success/failure by (recipe + variant). Format:
            #   ``llm@bad42``        · base recipe, no variant
            #   ``llm@bad42#vA``     · variant vA picked
            #   ``llm@bad42#__default__`` · control branch (no addendum)
            # The base hash is unchanged; the suffix is purely for
            # downstream attribution. ``_last_chosen_variant`` is set
            # in the variant-selection block above.
            recipe_hash=self._compose_trajectory_recipe_id(),
        )

    def _compose_trajectory_recipe_id(self) -> str:
        """Build the recipe_id stamped on this turn's TaskGraph ·
        base ``recipe_hash()`` plus the GEPA-variant suffix when a
        variant was picked. Set on the planner instance by the
        variant-selection block in plan().

        Suffix conventions:
          * ``""`` (empty)       → control branch picked (no addendum
                                   content was injected). We stamp
                                   the suffix anyway so the evaluator
                                   can group "no-addendum baseline"
                                   separately from "no-manifest base".
          * ``"vA"`` etc          → that named variant was picked
          * ``None``              → no manifest at all (legacy single
                                   file or no addendum) · no suffix
        """
        base = self.recipe_hash()
        v = getattr(self, "_last_chosen_variant", None)
        if v is None:
            return base
        if v == "":
            return f"{base}#__default__"
        return f"{base}#{v}"


    def recipe_hash(self) -> str:
        import hashlib

        kg_fingerprint = ""
        if self.kg is not None and hasattr(self.kg, "count"):
            kg_fingerprint = f"kg@{self.kg.count()}@{self.kg_max_triples}"
        payload = "|".join([
            self.planner_model,
            _PLANNER_SYSTEM_PROMPT,
            self.learned_rules_section,
            self.learned_memories_section,
            kg_fingerprint,
        ])
        h = hashlib.blake2b(payload.encode("utf-8"), digest_size=4).hexdigest()
        return f"llm@{h}"


    def _extract_json(self, text: str) -> dict:
        """Extract the LLM's JSON plan from free-form text.

        Strategy (tries in order, returns the first that parses):

        1. **Fenced block** — ``` ```json\\n{...}\\n``` ``` — matches
           the planner prompt's stated output format exactly. This is
           the fast path for well-behaved models.
        2. **Balanced-brace scan** — walk from each ``{`` looking for
           the matching close, string-aware. Tolerates the LLM
           putting prose before/after or mixing in example JSON the
           way some models do.

        History: the previous implementation was a single greedy
        ``r"\\{.*\\}"`` regex. When the LLM's response contained any
        extra ``{`` (example args, emoji, a braces-in-string literal)
        it would grab from the *first* ``{`` through the *last* ``}``
        across the whole document, producing an unparseable mega-blob.
        The failure mode was intermittent parse errors with no hint
        that the extractor itself was to blame.
        """
        # Path 1 · fenced block
        fenced = _JSON_FENCED_RE.search(text)
        if fenced:
            candidate = fenced.group(1)
            try:
                parsed = json.loads(candidate)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:  # noqa: BLE001 — fenced block wasn't valid JSON; fall through to balanced-scan
                pass

        # Path 2 · balanced-brace scan from each ``{`` in text order.
        # We can't short-circuit on the first ``{`` because the
        # model might write ``"{example}"`` or ``{foo}`` in prose
        # before the real plan object. Try each position and use the
        # first one that parses as a dict.
        i = 0
        last_parse_error: Exception | None = None
        while True:
            idx = text.find("{", i)
            if idx < 0:
                break
            slice_ = _scan_balanced_object(text, idx)
            # If this ``{`` has no matching ``}`` (unbalanced remainder),
            # skip past it and try the next ``{`` rather than giving up —
            # a malformed opener earlier in the text shouldn't prevent
            # finding a well-formed object later.
            if slice_ is None:
                i = idx + 1
                continue
            try:
                parsed = json.loads(slice_)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError as e:
                last_parse_error = e
            i = idx + 1  # try next ``{``

        # Exhausted — raise with both error kinds distinguished so
        # the caller's log tells "no JSON found" apart from "JSON
        # present but all candidates malformed".
        if last_parse_error is not None:
            raise PlannerError(
                f"LLM JSON parse failed (no balanced candidate parsed): "
                f"{last_parse_error}"
            ) from last_parse_error
        raise PlannerError(f"LLM response lacks JSON: {text[:200]!r}")

    def _validate_nodes(
        self,
        nodes: list,
    ) -> list[dict]:
        if not isinstance(nodes, list) or not nodes:
            raise PlannerError("LLM plan has no nodes")
        if len(nodes) > self.max_nodes:
            raise PlannerError(f"LLM plan too long: {len(nodes)} > {self.max_nodes}")

        validated: list[dict] = []
        for i, nd in enumerate(nodes):
            if not isinstance(nd, dict):
                raise PlannerError(f"node {i} is not a dict")
            skill = nd.get("skill")
            if not isinstance(skill, str) or not skill:
                raise PlannerError(f"node {i} missing skill name")
            if skill in _NON_SKILL_ACTION_NAMES:
                raise PlannerError(
                    f"node {i}: {skill!r} is a subagent action, not a skill; "
                    "use the team routing/subagent dispatch channel instead"
                )
            if not self.registry.has(skill):
                raise PlannerError(
                    f"node {i}: unknown skill {skill!r} "
                    f"(available: {', '.join(self.registry.all_names()[:10])}...)"
                )
            args = nd.get("args", {})
            if not isinstance(args, dict):
                raise PlannerError(f"node {i}: args must be dict, got {type(args).__name__}")
            out: dict[str, Any] = {"skill": skill, "args": args}
            # Preserve explicit ``depends_on`` so ``_extract_edges``
            # can honor it. Pre-2026-04 this field got stripped here
            # before ``plan()`` built edges · meaning the LLM's
            # parallel-DAG signal was silently dropped and swarm
            # split_strategy="topo_layers" always degenerated.
            # Validation keeps the "explicit vs absent" distinction
            # the extractor relies on: the KEY must survive when the
            # LLM provided one (even if the list is empty · "[]" is
            # the explicit "no deps" signal).
            if "depends_on" in nd:
                raw = nd.get("depends_on")
                if raw is None:
                    # None is ambiguous · treat like absent to avoid
                    # conflating "field present set to null" with
                    # "explicit empty list". Drop the key.
                    pass
                elif isinstance(raw, list):
                    cleaned: list[Any] = []
                    for entry in raw:
                        # Accept ints (node index), "nX" ids, bare
                        # ``n`` numerics. Anything else is silently
                        # dropped · no crash on slightly-off LLM output.
                        if isinstance(entry, int) or isinstance(entry, str) and entry:
                            cleaned.append(entry)
                    out["depends_on"] = cleaned
                else:
                    # Not a list · ignore · extractor interprets as
                    # "no explicit signal".
                    pass
            validated.append(out)
        return validated


    def _autosave_rules(self) -> None:
        if self.auto_persist_rules_path is None:
            return
        try:
            from .prompt_persistence import dump_section

            dump_section(
                self.auto_persist_rules_path,
                self.learned_rules_section,
                label="learned_rules",
            )
        except OSError as e:
            # Disk full / permission denied / path invalid. Don't
            # fail the turn · the rules live in memory and can re-
            # persist next turn. Logger rather than silent drop so
            # operators see recurring write failures.
            _logger.warning(
                "learned_rules autosave failed (%s): %s", type(e).__name__, e,
            )

    def _autosave_memories(self) -> None:
        if self.auto_persist_memories_path is None:
            return
        try:
            from .prompt_persistence import dump_section

            dump_section(
                self.auto_persist_memories_path,
                self.learned_memories_section,
                label="learned_memories",
            )
        except OSError as e:
            _logger.warning(
                "learned_memories autosave failed (%s): %s",
                type(e).__name__, e,
            )




def _derive_task_type(intent: ParsedIntent) -> str:
    mapping = {
        "debug": "code_fix",
        "refactor": "code_design",
        "plan": "multi_step_reasoning",
        "query": "quick_lookup",
        "chitchat": "chitchat",
    }
    return mapping.get(intent.intent_type, "general")
