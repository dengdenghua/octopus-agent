"""Local user memory store used by chat and the settings UI.

The store is deliberately simple: a single JSON file under ``data/`` with
manual facts and lightweight text search. It only persists memories that are
explicitly provided by the user or by an API caller.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from runtime.platform.io import atomic_write_json
from runtime.platform.process.paths import app_paths

DEFAULT_MAX_FACTS = 500
HARD_MAX_FACTS = 2_000
DEFAULT_DEBOUNCE_SECONDS = 5
MAX_DEBOUNCE_SECONDS = 3_600
DEFAULT_MAX_INJECTION_TOKENS = 2_000
HARD_MAX_INJECTION_TOKENS = 32_000
MAX_FACT_CONTENT_CHARS = 500
MAX_SECTION_SUMMARY_CHARS = 4_000
MAX_LABEL_CHARS = 80
MAX_SCOPE_VALUE_CHARS = 120


def _memory_path() -> Path:
    return app_paths().user_memory_path


def _config_path() -> Path:
    return app_paths().user_memory_config_path


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def empty_memory() -> dict[str, Any]:
    now = now_iso()
    return {
        "version": "1",
        "lastUpdated": now,
        "user": {
            "workContext": {"summary": "", "updatedAt": ""},
            "personalContext": {"summary": "", "updatedAt": ""},
            "topOfMind": {"summary": "", "updatedAt": ""},
        },
        "history": {
            "recentMonths": {"summary": "", "updatedAt": ""},
            "earlierContext": {"summary": "", "updatedAt": ""},
            "longTermBackground": {"summary": "", "updatedAt": ""},
        },
        "facts": [],
    }


def read_memory() -> dict[str, Any]:
    path = _memory_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return empty_memory()
    except (TypeError, ValueError):
        return empty_memory()
    return normalize_memory(raw)


def write_memory(memory: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_memory(memory)
    normalized["lastUpdated"] = now_iso()
    path = _memory_path()
    atomic_write_json(path, normalized)
    return normalized


def add_fact(
    content: str,
    *,
    category: str = "profile",
    confidence: float = 0.85,
    source: str = "chat",
    scope: str = "global",
    agent_id: str | None = None,
    project: str | None = None,
) -> dict[str, Any] | None:
    if not read_config().get("enabled", True):
        return None
    content = _clean_text(content)
    if not content:
        return None
    memory = read_memory()
    facts = list(memory.get("facts") or [])
    max_facts = int(read_config().get("max_facts") or DEFAULT_MAX_FACTS)
    scope = _normalize_scope(scope, agent_id=agent_id, project=project)
    clean_agent = _clean_scope_value(agent_id)
    clean_project = _clean_scope_value(project)
    key = content.casefold()
    for fact in facts:
        if (
            str(fact.get("content") or "").strip().casefold() == key
            and str(fact.get("scope") or "global") == scope
            and str(fact.get("agent_id") or "") == clean_agent
            and str(fact.get("project") or "") == clean_project
        ):
            return fact
    fact = {
        "id": uuid4().hex,
        "content": content,
        "category": _clean_label(category or "profile", fallback="profile"),
        "confidence": max(0.0, min(1.0, _coerce_float(confidence, 0.85))),
        "createdAt": now_iso(),
        "source": _clean_label(source or "chat", fallback="chat"),
        "scope": scope,
        "agent_id": clean_agent,
        "project": clean_project,
    }
    memory["facts"] = [*facts, fact][-max_facts:]
    write_memory(memory)
    return fact


def _tokenize(text: str) -> list[str]:
    """中文按字符，英文按空格，统一小写。"""
    text = text.lower()
    tokens: list[str] = []
    for ch in text:
        if "\u4e00" <= ch <= "\u9fff" or ch.isalnum():
            tokens.append(ch)
        else:
            tokens.append(" ")
    return [t for t in "".join(tokens).split() if t]


def _cosine_similarity(q: list[str], d: list[str]) -> float:
    """词频向量余弦相似度。"""
    from collections import Counter

    if not q or not d:
        return 0.0
    cq = Counter(q)
    cd = Counter(d)
    vocab = set(cq.keys()) | set(cd.keys())
    dot = sum(cq.get(t, 0) * cd.get(t, 0) for t in vocab)
    norm_q = sum(v * v for v in cq.values()) ** 0.5
    norm_d = sum(v * v for v in cd.values()) ** 0.5
    if norm_q == 0 or norm_d == 0:
        return 0.0
    return dot / (norm_q * norm_d)


def search_facts(
    query: str,
    *,
    limit: int = 20,
    agent_id: str | None = None,
    project: str | None = None,
    include_global: bool = True,
    semantic: bool = False,
) -> list[dict[str, Any]]:
    query = _clean_text(query).casefold()
    if not query:
        return []
    terms = [term for term in query.split() if term]
    scored: list[tuple[float, dict[str, Any]]] = []
    query_tokens = _tokenize(query) if semantic else []
    for fact in read_memory().get("facts", []):
        if not isinstance(fact, dict):
            continue
        if not _fact_in_scope(
            fact,
            agent_id=agent_id,
            project=project,
            include_global=include_global,
        ):
            continue
        content = str(fact.get("content") or "")
        category = str(fact.get("category") or "")
        haystack = f"{content} {category}".casefold()
        if query in haystack:
            score = 1.0
        elif semantic and query_tokens:
            doc_tokens = _tokenize(haystack)
            score = _cosine_similarity(query_tokens, doc_tokens)
            if score <= 0:
                continue
        else:
            hits = sum(1 for term in terms if term in haystack)
            if hits <= 0:
                continue
            score = hits / max(1, len(terms))
        scored.append((score, fact))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [fact for _, fact in scored[:limit]]


def relevant_memory_texts(
    query: str,
    *,
    limit: int = 8,
    agent_id: str | None = None,
    project: str | None = None,
) -> list[str]:
    settings = read_config()
    if not settings.get("enabled", True) or not settings.get("injection_enabled", True):
        return []
    return [
        str(fact.get("content") or "").strip()
        for fact in search_facts(query, limit=limit, agent_id=agent_id, project=project)
        if str(fact.get("content") or "").strip()
    ]


def default_config() -> dict[str, Any]:
    return {
        "enabled": True,
        "storage_path": str(_memory_path()),
        "auto_capture_enabled": True,
        "debounce_seconds": DEFAULT_DEBOUNCE_SECONDS,
        "max_facts": DEFAULT_MAX_FACTS,
        "fact_confidence_threshold": 0.5,
        "injection_enabled": True,
        "max_injection_tokens": DEFAULT_MAX_INJECTION_TOKENS,
    }


def read_config() -> dict[str, Any]:
    path = _config_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default_config()
    except (TypeError, ValueError):
        return default_config()
    if not isinstance(raw, dict):
        return default_config()
    config = default_config()
    config.update({
        "enabled": bool(raw.get("enabled", config["enabled"])),
        "storage_path": str(_memory_path()),
        "auto_capture_enabled": bool(
            raw.get("auto_capture_enabled", config["auto_capture_enabled"])
        ),
        "debounce_seconds": _coerce_int(
            raw.get("debounce_seconds"),
            int(config["debounce_seconds"]),
        ),
        "max_facts": _coerce_int(raw.get("max_facts"), int(config["max_facts"])),
        "fact_confidence_threshold": _coerce_float(
            raw.get("fact_confidence_threshold"),
            float(config["fact_confidence_threshold"]),
        ),
        "injection_enabled": bool(raw.get("injection_enabled", config["injection_enabled"])),
        "max_injection_tokens": _coerce_int(
            raw.get("max_injection_tokens"),
            int(config["max_injection_tokens"]),
        ),
    })
    return read_config_from_raw(config)


def write_config(patch: dict[str, Any]) -> dict[str, Any]:
    config = read_config()
    for key in (
        "enabled",
        "auto_capture_enabled",
        "injection_enabled",
        "debounce_seconds",
        "max_facts",
        "fact_confidence_threshold",
        "max_injection_tokens",
    ):
        if key in patch:
            config[key] = patch[key]
    normalized = read_config_from_raw(config)
    path = _config_path()
    atomic_write_json(path, normalized)
    return normalized


def read_config_from_raw(raw: dict[str, Any]) -> dict[str, Any]:
    config = default_config()
    config.update(raw)
    config["enabled"] = bool(config.get("enabled", True))
    config["auto_capture_enabled"] = bool(config.get("auto_capture_enabled", True))
    config["injection_enabled"] = bool(config.get("injection_enabled", True))
    config["storage_path"] = str(_memory_path())
    config["debounce_seconds"] = max(
        0,
        min(
            MAX_DEBOUNCE_SECONDS,
            _coerce_int(config.get("debounce_seconds"), DEFAULT_DEBOUNCE_SECONDS),
        ),
    )
    config["max_facts"] = max(
        1,
        min(HARD_MAX_FACTS, _coerce_int(config.get("max_facts"), DEFAULT_MAX_FACTS)),
    )
    config["fact_confidence_threshold"] = max(
        0.0,
        min(
            1.0,
            _coerce_float(config.get("fact_confidence_threshold"), 0.5),
        ),
    )
    config["max_injection_tokens"] = max(
        0,
        min(
            HARD_MAX_INJECTION_TOKENS,
            _coerce_int(
                config.get("max_injection_tokens"),
                DEFAULT_MAX_INJECTION_TOKENS,
            ),
        ),
    )
    return config


def normalize_memory(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raw = {}
    base = empty_memory()
    last_updated = str(raw.get("lastUpdated") or base["lastUpdated"])
    user = raw.get("user") if isinstance(raw.get("user"), dict) else {}
    history = raw.get("history") if isinstance(raw.get("history"), dict) else {}
    facts: list[dict[str, Any]] = []
    for item in raw.get("facts") or []:
        if not isinstance(item, dict):
            continue
        content = _clean_text(item.get("content") or "")
        if not content:
            continue
        try:
            confidence = float(item.get("confidence", 0.8))
        except (TypeError, ValueError):
            confidence = 0.8
        facts.append({
            "id": str(item.get("id") or uuid4().hex),
            "content": content,
            "category": _clean_label(item.get("category") or "context", fallback="context"),
            "confidence": max(0.0, min(1.0, confidence)),
            "createdAt": str(item.get("createdAt") or last_updated),
            "source": _clean_label(item.get("source") or "manual", fallback="manual"),
            "scope": _normalize_scope(
                item.get("scope") or "global",
                agent_id=item.get("agent_id"),
                project=item.get("project"),
            ),
            "agent_id": _clean_scope_value(item.get("agent_id")),
            "project": _clean_scope_value(item.get("project")),
        })
    base.update({
        "version": str(raw.get("version") or "1"),
        "lastUpdated": last_updated,
        "user": {
            "workContext": _section(user.get("workContext"), last_updated),
            "personalContext": _section(user.get("personalContext"), last_updated),
            "topOfMind": _section(user.get("topOfMind"), last_updated),
        },
        "history": {
            "recentMonths": _section(history.get("recentMonths"), last_updated),
            "earlierContext": _section(history.get("earlierContext"), last_updated),
            "longTermBackground": _section(history.get("longTermBackground"), last_updated),
        },
        "facts": facts[-_configured_max_facts():],
    })
    return base


def _section(value: Any, fallback_updated_at: str) -> dict[str, str]:
    if isinstance(value, dict):
        return {
            "summary": _clean_section_summary(value.get("summary") or ""),
            "updatedAt": str(value.get("updatedAt") or fallback_updated_at or ""),
        }
    if isinstance(value, str):
        return {
            "summary": _clean_section_summary(value),
            "updatedAt": fallback_updated_at or "",
        }
    return {"summary": "", "updatedAt": fallback_updated_at or ""}


def _clean_text(value: Any) -> str:
    text = " ".join(str(value).split()).strip(" .。")
    return text[:MAX_FACT_CONTENT_CHARS].rstrip()


def _clean_scope_value(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()[:MAX_SCOPE_VALUE_CHARS]


def _clean_section_summary(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()[:MAX_SECTION_SUMMARY_CHARS].rstrip()


def _clean_label(value: Any, *, fallback: str) -> str:
    text = " ".join(str(value or "").split()).strip()
    return (text[:MAX_LABEL_CHARS].rstrip() or fallback)


def _coerce_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _coerce_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _configured_max_facts() -> int:
    try:
        return int(read_config().get("max_facts") or DEFAULT_MAX_FACTS)
    except (TypeError, ValueError):
        return DEFAULT_MAX_FACTS


def _normalize_scope(
    value: Any,
    *,
    agent_id: Any = None,
    project: Any = None,
) -> str:
    raw = str(value or "global").strip().lower()
    if raw not in {"global", "agent", "project"}:
        raw = "global"
    if raw == "project" and not _clean_scope_value(project):
        raw = "agent" if _clean_scope_value(agent_id) else "global"
    if raw == "agent" and not _clean_scope_value(agent_id):
        raw = "global"
    return raw


def _fact_in_scope(
    fact: dict[str, Any],
    *,
    agent_id: str | None,
    project: str | None,
    include_global: bool,
) -> bool:
    scope = str(fact.get("scope") or "global")
    if scope == "global":
        return include_global
    clean_agent = _clean_scope_value(agent_id)
    clean_project = _clean_scope_value(project)
    if scope == "agent":
        return bool(clean_agent) and str(fact.get("agent_id") or "") == clean_agent
    if scope == "project":
        return bool(clean_project) and str(fact.get("project") or "") == clean_project
    return include_global
