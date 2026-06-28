"""Octopus Mix — a mixture-of-agents virtual model for the OpenAI gateway.

Exposes ``octopus-mix`` as a selectable model on ``/v1/chat/completions``.
When chosen, the request is answered by a *mixture of agents* instead of a
single model — the pattern popularized by Together AI, Nous Hermes' presets,
and Sakana Fugu:

  1. **Proposers** — N reference models each draft an answer to the user's
     message INDEPENDENTLY and IN PARALLEL. Proposers run as pure LLM calls
     with **no tool access** (``_direct_llm_fallback`` never touches the
     planner/tools), so they can't act — they only advise. Diversity comes
     from (a) different models when a pool is configured and (b) a distinct
     reasoning *lens* injected per proposer (so even a single-model
     deployment gets an ensemble).
  2. **Aggregator** — one model sees the conversation PLUS the proposers'
     drafts (injected as a trailing system message) and synthesizes the
     final answer. The aggregator runs a NORMAL turn (``_run_chat``), so it
     keeps **full tool access** — it can verify/extend the drafts, not just
     blend them.

Config (all optional, env-driven so it works on any deployment):
  - ``OCTOPUS_MIX_PROPOSERS``  comma-separated model ids for the proposer
    pool (e.g. ``"gpt-5.5,claude-opus-4-8,gemini-3.1-pro"``). Unset → run
    ``OCTOPUS_MIX_N`` proposers on the planner-default model, diversified by
    lens.
  - ``OCTOPUS_MIX_AGGREGATOR``  model id for the aggregator. Unset → planner
    default.
  - ``OCTOPUS_MIX_N``  proposer count when no explicit pool (default 3).

Degrades safely: if every proposer fails (or no router is configured), it
falls back to a single normal turn — never errors out.
"""

from __future__ import annotations

import contextvars
import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from uuid import uuid4

from runtime.platform.models import ParsedIntent

from .context_manager import _conversation_messages_payload
from .stream_handler import _direct_llm_fallback_with_usage

_log = logging.getLogger(__name__)

# The selectable virtual-model id. ``octopus-mix:<preset>`` is also accepted.
MIX_MODEL_ID = "octopus-mix"

# Per-proposer reasoning lenses — give an ensemble built from ONE model
# genuine diversity (different angle of attack per draft). Cycled across
# proposers; harmless when a multi-model pool already supplies diversity.
_LENSES: tuple[str, ...] = (
    "Answer directly and precisely; prioritize correctness above all.",
    "Reason step by step and surface edge cases or failure modes others miss.",
    "Take a creative, alternative angle; question the obvious assumptions.",
    "Be rigorous and skeptical; double-check every claim before stating it.",
    "Be concise and practical; focus on what actually matters to the user.",
)

_DEFAULT_N = 3
_MAX_PROPOSERS = 6


def is_mix_model(model: Any) -> bool:
    """True if ``model`` selects the Mix virtual model."""
    if not isinstance(model, str):
        return False
    name = model.strip().lower()
    return name == MIX_MODEL_ID or name.startswith(MIX_MODEL_ID + ":")


def mix_model_ids() -> list[str]:
    """Virtual-model ids to advertise on /v1/models."""
    return [MIX_MODEL_ID]


def _config_path() -> Path:
    return Path(os.path.expanduser("~/.octopus/mix_config.json"))


def load_mix_config() -> dict[str, Any]:
    """User-configured Mix preset (proposer pool / aggregator / count).

    Persisted by the UI via PUT /api/mix-config. Best-effort: a missing or
    malformed file yields {} so env / defaults take over. Resolution order is
    UI config → env → built-in default.
    """
    try:
        data = json.loads(_config_path().read_text("utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_mix_config(cfg: dict[str, Any]) -> dict[str, Any]:
    """Validate + persist the Mix preset; returns the cleaned config."""
    proposers = [
        str(m).strip()
        for m in (cfg.get("proposers") or [])
        if str(m or "").strip()
    ][:_MAX_PROPOSERS]
    try:
        n = int(cfg.get("n") or _DEFAULT_N)
    except (TypeError, ValueError):
        n = _DEFAULT_N
    clean = {
        "proposers": proposers,
        "aggregator": str(cfg.get("aggregator") or "").strip(),
        "n": max(1, min(_MAX_PROPOSERS, n)),
    }
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(clean, indent=2), encoding="utf-8")
    return clean


def _proposer_count() -> int:
    cfg_n = load_mix_config().get("n")
    if isinstance(cfg_n, int) and cfg_n > 0:
        return max(1, min(_MAX_PROPOSERS, cfg_n))
    raw = (os.environ.get("OCTOPUS_MIX_N") or "").strip()
    if raw.isdigit():
        return max(1, min(_MAX_PROPOSERS, int(raw)))
    return _DEFAULT_N


def _proposer_pool() -> list[str]:
    cfg_pool = load_mix_config().get("proposers")
    if isinstance(cfg_pool, list) and cfg_pool:
        return [str(m).strip() for m in cfg_pool if str(m or "").strip()][:_MAX_PROPOSERS]
    raw = (os.environ.get("OCTOPUS_MIX_PROPOSERS") or "").strip()
    if raw:
        models = [m.strip() for m in raw.split(",") if m.strip()]
        return models[:_MAX_PROPOSERS]
    return []


def _aggregator_model() -> str:
    cfg_agg = load_mix_config().get("aggregator")
    if isinstance(cfg_agg, str) and cfg_agg.strip():
        return cfg_agg.strip()
    return (os.environ.get("OCTOPUS_MIX_AGGREGATOR") or "").strip()


def _proposer_specs(requested_model: str) -> list[tuple[str, str]]:
    """Resolve ``(model, lens)`` pairs for the proposers.

    ``model == ""`` means "use the planner default model" (single-model
    deployments still get an ensemble via distinct lenses).
    """
    models = _proposer_pool() or [""] * _proposer_count()
    return [(m, _LENSES[i % len(_LENSES)]) for i, m in enumerate(models)]


def _proposer_intent(intent: ParsedIntent, lens: str) -> ParsedIntent:
    """Derive a proposer intent that prepends a reasoning ``lens``."""
    convo = [{"role": "system", "content": lens}, *_conversation_messages_payload(intent)]
    return intent.model_copy(
        update={
            "user_context": {
                **(intent.user_context or {}),
                "conversation_messages": convo,
            }
        }
    )


def _aggregator_intent(intent: ParsedIntent, drafts: list[str]) -> ParsedIntent:
    """Derive the aggregator intent with proposer drafts injected."""
    convo = list(_conversation_messages_payload(intent))
    convo.append({"role": "system", "content": _format_proposals(drafts)})
    return intent.model_copy(
        update={
            "user_context": {
                **(intent.user_context or {}),
                "conversation_messages": convo,
                "mix_proposals": list(drafts),
            }
        }
    )


def _format_proposals(drafts: list[str]) -> str:
    lines = [
        "You are the AGGREGATOR in a mixture-of-agents system. Several "
        "reference models independently drafted answers to the user's latest "
        "message (below). Treat them as ADVICE, not ground truth: synthesize "
        "ONE final answer that is more correct, complete, and useful than any "
        "single draft. Resolve disagreements by reasoning, and use tools to "
        "verify when it matters. Never mention the drafts, the references, or "
        "this process — just give the user the best answer.",
        "",
    ]
    for i, draft in enumerate(drafts, 1):
        text = (draft or "").strip()
        if text:
            lines.append(f"--- Draft {i} ---")
            lines.append(text)
            lines.append("")
    return "\n".join(lines).strip()


def run_mix_chat(
    stack: Any,
    intent: ParsedIntent,
    requested_model: str,
    default_arm: str,
    *,
    actor: str | None,
    agent: Any,
    run_chat: Any,
    optimizer: Any = None,
) -> dict[str, Any]:
    """Answer ``intent`` via mixture-of-agents and return a chat.completion.

    ``run_chat`` is injected (the gateway's ``_run_chat``) to avoid a circular
    import; it runs the aggregator as a normal, fully tool-enabled turn.
    """
    specs = _proposer_specs(requested_model)

    # ── Stage 1: proposers — parallel, NO tools ──────────────
    def _one(spec: tuple[str, str]) -> str | None:
        model, lens = spec
        try:
            reply, _usage = _direct_llm_fallback_with_usage(
                stack, _proposer_intent(intent, lens), agent, model=(model or None),
            )
            return reply
        except Exception as exc:  # noqa: BLE001 — one proposer failing must not sink the turn
            _log.warning("mix proposer (model=%r) failed: %s", model, exc)
            return None

    drafts: list[str] = []
    workers = max(1, min(len(specs), _MAX_PROPOSERS))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        # copy_context() per task so ContextVars (actor, session) propagate
        # into the worker threads — one fresh copy each (a context can be
        # entered only once).
        futures = [pool.submit(contextvars.copy_context().run, _one, spec) for spec in specs]
        for fut in futures:
            try:
                reply = fut.result()
            except Exception:  # noqa: BLE001 — defensive; _one already guards
                reply = None
            if reply and reply.strip():
                drafts.append(reply.strip())

    aggregator_model = _aggregator_model()

    # ── Stage 2: aggregator — full turn, WITH tools ──────────
    if not drafts:
        # Nothing usable to synthesize → just run one normal turn.
        result = run_chat(
            stack, intent, aggregator_model, default_arm,
            optimizer=optimizer, actor=actor, agent=agent,
        )
        if isinstance(result, dict):
            result.setdefault("octopus", {})["mix"] = {
                "proposers": len(specs),
                "drafts_used": 0,
                "degraded": True,
            }
            result["model"] = requested_model
        return result

    result = run_chat(
        stack, _aggregator_intent(intent, drafts), aggregator_model, default_arm,
        optimizer=optimizer, actor=actor, agent=agent,
    )
    if isinstance(result, dict):
        result.setdefault("octopus", {})["mix"] = {
            "proposers": len(specs),
            "drafts_used": len(drafts),
            "aggregator_model": aggregator_model or "default",
            "proposer_models": [m or "default" for m, _ in specs],
            "degraded": False,
        }
        result["model"] = requested_model
    return result


def mix_sse_frames(result: dict[str, Any], model: str):
    """Wrap a finished Mix completion as OpenAI-standard streaming SSE.

    Mix is computed non-streamed (proposers must finish before the aggregator
    starts); for ``stream=true`` clients we still emit a valid chunk sequence.
    """
    try:
        content = result["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        content = ""
    cid = result.get("id") or f"chatcmpl-{uuid4().hex[:16]}"
    created = result.get("created") or int(time.time())
    base = {"id": cid, "object": "chat.completion.chunk", "created": created, "model": model}

    def _frame(delta: dict[str, Any], finish: str | None) -> str:
        payload = {**base, "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    yield _frame({"role": "assistant"}, None)
    if content:
        yield _frame({"content": content}, None)
    yield _frame({}, "stop")
    yield "data: [DONE]\n\n"
