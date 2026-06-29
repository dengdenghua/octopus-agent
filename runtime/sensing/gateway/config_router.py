"""
Config router · identity-lock + providers + custom-models.

Carved out of the monolithic ``runtime/platform/ui/app.py`` (which
owned 48 endpoints in a single 2324-line factory). This router owns
the "configuration surface" that the frontend Settings / ModelPicker
panels speak to:

    GET    /api/config/identity-lock       · privacy-filter state
    PUT    /api/config/identity-lock       · admin toggle
    GET    /api/providers                  · LLM provider capability list
    GET    /api/config/custom-models       · list user-added models
    PUT    /api/config/custom-models/{id}  · upsert + persist + register
    DELETE /api/config/custom-models/{id}  · remove + persist + unregister

Public API is a single factory ``create_config_router(...)``. It
returns a ``ConfigRouter`` thin wrapper that exposes:

    .router           — FastAPI APIRouter to include on the main app
    .custom_models    — live dict, shared with app.py's /api/llm-models
                        merge endpoint so the existing merge logic
                        doesn't need duplicating here

Design notes
------------

* **State ownership moves with the routes.** The ``custom_models``
  dict used to be a local in ``create_app``; now it's owned by the
  router. app.py reads it through the returned wrapper to merge with
  molili's built-in preset list (that merge stays in app.py for now
  — it also pulls from the molili gateway which is wired there).
* **Disk format unchanged.** Path and JSON shape stay the same so an
  in-place deploy doesn't lose user config. Integration tests in
  ``tests/test_app_config_endpoints.py`` pin this contract.
* **Dispatcher is optional.** Without a ``stack.planner.router``,
  register/unregister degrade to no-ops with a reason field —
  matches the pre-split behavior. Tests rely on this to exercise
  persistence without needing a full execution stack.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from runtime.platform.process.paths import app_paths

try:
    from fastapi import APIRouter, Depends, HTTPException, Request
    from pydantic import BaseModel, Field

    FASTAPI_AVAILABLE = True
except ImportError:  # pragma: no cover
    FASTAPI_AVAILABLE = False
    APIRouter = None  # type: ignore[assignment, misc]
    Depends = None  # type: ignore[assignment, misc]
    HTTPException = None  # type: ignore[assignment, misc]
    Request = None  # type: ignore[assignment, misc]
    BaseModel = object  # type: ignore[assignment, misc]
    Field = None  # type: ignore[assignment, misc]


# ═══════════════════════════════════════════════════════════
# Response models · shape contracts for the frontend
# ═══════════════════════════════════════════════════════════
#
# Why these exist: FastAPI generates OpenAPI schema from the return
# type annotation. ``-> dict[str, Any]`` produces a meaningless
# ``{additionalProperties: true}`` blob — any frontend tooling
# generating types from the schema gets no constraints. Explicit
# pydantic models here give openapi.json real shape info, which the
# snapshot test catches on drift and any future TS codegen can use.


if FASTAPI_AVAILABLE:
    class CustomModelEntry(BaseModel):
        """One custom-model row as shown to the UI. ``api_key`` is
        intentionally absent · ``has_api_key`` reports presence
        without exposing the secret.

        ``models`` is the open-ended list of upstream model IDs that
        this entry can dispatch to. The first item is the picker
        default; the last item is what Auto mode uses for
        performance-tier turns (long / multi-step / code / research).
        Operators can have any number of items · the smart router
        cycles through them in order when a tier escalates, so 1
        item, 2 items, or N items all work the same way. See
        ``turn_complexity._resolve_tier_value`` for the index
        selection rules."""

        # ``model`` and ``model_performance`` both start with the
        # ``model_`` pydantic-protected namespace, hence the opt-out
        # below. The fields themselves are intentional — the protected
        # namespace is meant to stop *us* from shadowing pydantic
        # internals like ``model_dump()``, and these are LLM model
        # names, not pydantic machinery.
        model_config = {"protected_namespaces": ()}

        id: str
        name: str
        provider: str
        base_url: str
        # Open-ended list of model IDs this entry can route to. Order
        # matters · index 0 is the picker default, index -1 is the
        # strongest tier for Auto mode's performance verdict.
        models: list[str] = Field(default_factory=list)
        display_name: str
        has_api_key: bool
        max_tokens: int | None = None
        supports_thinking: bool | None = None
        supports_vision: bool | None = None
        supports_tool_use: bool | None = None
        omit_sampling_parameters: bool | None = None
        compat_profile: str | None = None
        thinking_request_style: str | None = None
        drop_tool_choice: bool | None = None
        strict_tool_schema: bool | None = None
        max_temperature: float | None = None
        unsupported_request_fields: list[str] | None = None
        default_header_names: list[str] = Field(default_factory=list)
        has_default_headers: bool = False

    class CustomModelsList(BaseModel):
        models: list[CustomModelEntry]

    class CustomModelUpsertStatus(BaseModel):
        model_config = {"protected_namespaces": ()}

        ok: bool
        model_id: str | None = None
        error: str | None = None

    class CustomModelUpsertResponse(BaseModel):
        # ``model`` conflicts with pydantic's ``model_`` namespace and
        # the nested ``_status`` key needs an alias · but mixing both
        # with populate_by_name tripped PydanticUserError. Dropped
        # this model · the upsert endpoint stays un-annotated for now
        # (returns ``dict[str, Any]``) so the OpenAPI row is generic.
        # Proper typing for it is follow-up work.
        pass

    class CustomModelDeleteResponse(BaseModel):
        ok: bool
        removed: bool

    class CustomModelTestResponse(BaseModel):
        ok: bool
        provider: str
        model: str
        latency_ms: int | None = None
        message: str | None = None
        error: str | None = None

    class IdentityLockResponse(BaseModel):
        locked: bool
        source: str  # "runtime" | "env" | "default"
        unlock_paths: list[str]

    class IdentityLockPutBody(BaseModel):
        locked: bool | None

    class ProviderCapabilitiesWire(BaseModel):
        name: str
        supports_vision: bool
        supports_tool_use: bool
        supports_streaming: bool
        supports_prompt_cache: bool
        supports_structured_output: bool
        default_model: str | None = None
        pricing_hint: str | None = None

    class ProvidersResponse(BaseModel):
        providers: list[ProviderCapabilitiesWire]

    class ConstitutionProfileResponse(BaseModel):
        profile: str  # "strict" | "normal" | "lax"
        available: list[str]

    class ConstitutionProfilePutBody(BaseModel):
        profile: str


# ═══════════════════════════════════════════════════════════
# Wrapper · holds router + shared mutable state
# ═══════════════════════════════════════════════════════════


@dataclass
class ConfigRouter:
    """Bundle returned by ``create_config_router``.

    ╔════════════════════════════════════════════════════════════════════╗
    ║ config_router.py · navigation map (1265 lines).                    ║
    ║                                                                    ║
    ║   §1 ConfigRouter dataclass                       ~L180            ║
    ║   §2 create_config_router (factory)               ~L198            ║
    ║       §2.1 /api/config (root + put)               ~L426            ║
    ║       §2.2 /api/providers                         ~L489            ║
    ║       §2.3 /api/config/custom-models (CRUD)       ~L528            ║
    ║       §2.4 /api/config/local-models/scan|import   ~L650            ║
    ║       §2.5 /api/llm-models (merged catalog)       ~L996            ║
    ║       §2.6 /api/feature-flags                     ~L1112           ║
    ║       §2.7 /api/smart-routing                     ~L1140           ║
    ║       §2.8 /api/ai-mode                           ~L1178           ║
    ║       §2.9 /api/path-denylist                     ~L1230           ║
    ╚════════════════════════════════════════════════════════════════════╝

    ``custom_models`` is the canonical in-memory view of the
    persisted ``custom_models.json`` — callers outside this module
    (app.py's /api/llm-models merge) read it directly. Mutations
    happen only through the PUT/DELETE handlers so the on-disk file
    stays authoritative.
    """
    router: Any
    custom_models: dict[str, dict[str, Any]]


# ═══════════════════════════════════════════════════════════
# Factory
# ═══════════════════════════════════════════════════════════


def create_config_router(
    *,
    stack: Any = None,
    custom_models_path: Path | str | None = None,
    identity_store: Any = None,
    require_auth: bool = False,
    jwt_secret: str | None = None,
    jwt_issuer: str | None = None,
    jwt_audience: str | None = None,
) -> ConfigRouter:
    """Build the FastAPI router + state bundle.

    Parameters
    ----------
    stack :
        Execution stack exposing ``.planner.router`` (a
        ``ModelDispatchRouter``). When absent, custom-model
        register/unregister become no-ops (still persisted to disk
        so a later start can register them once the stack is live).
    custom_models_path :
        Where to persist user-added models. Default preserves the
        pre-split location. Tests override with a tmp_path.
    """
    if not FASTAPI_AVAILABLE:
        raise RuntimeError("fastapi not installed")

    def _auth_dep(request: Request) -> None:
        # Router-level gate keeps the whole config surface aligned with
        # the rest of the auth-aware control plane. require_auth=False
        # stays a no-op for single-user dev; auth-on deployments get a
        # consistent 401 before any config state is exposed or mutated.
        from runtime.adapters.web_auth import _resolve_actor

        _resolve_actor(
            request,
            identity_store,
            require_auth,
            jwt_secret=jwt_secret,
            jwt_issuer=jwt_issuer,
            jwt_audience=jwt_audience,
        )

    def _resolve_identity(request: Request) -> Any:
        """Resolve the full Identity (with roles) for admin checks. ``None``
        when auth is disabled or no valid bearer is present."""
        if not require_auth or identity_store is None:
            return None
        auth = request.headers.get("Authorization") or ""
        if not auth.lower().startswith("bearer "):
            return None
        token = auth[7:].strip()
        if jwt_secret and token.count(".") == 2:
            try:
                identity = identity_store.verify_jwt(
                    token,
                    secret=jwt_secret,
                    required_issuer=jwt_issuer,
                    required_audience=jwt_audience,
                )
                if identity is not None:
                    return identity
            except Exception:  # noqa: BLE001 — fall through to api-key check
                pass
        try:
            return identity_store.verify_api_key(token)
        except Exception:  # noqa: BLE001 — unresolved identity → no roles
            return None

    def _require_admin(request: Request) -> None:
        """Mutating config endpoints that are themselves security controls (the
        path-denylist is one) need the ``admin`` role when auth is on. The
        router-level ``_auth_dep`` already enforced authentication; this adds
        the role gate on top. Dev mode (require_auth=False) stays a no-op for
        single-user local use."""
        if not require_auth:
            return
        identity = _resolve_identity(request)
        roles = getattr(identity, "roles", ()) or ()
        if "admin" not in {str(r).lower() for r in roles}:
            raise HTTPException(403, "admin role required")

    router = APIRouter(tags=["config"], dependencies=[Depends(_auth_dep)])
    path = Path(custom_models_path) if custom_models_path is not None else app_paths().custom_models_path
    custom_models_state: dict[str, dict[str, Any]] = {}

    # ─── Persistence helpers ────────────────────────────────
    # These used to be nested inside create_app; moving them here
    # keeps the "own your state" principle — same file, one level of
    # scoping instead of two.

    def _save() -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(custom_models_state, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:  # noqa: BLE001 — disk full / permission denied; in-memory PUT already succeeded
            # Disk full / permission denied / etc. — surfacing this as
            # a 5xx would mask the PUT that actually worked in-memory;
            # the next save attempt retries.
            pass

    def _load() -> None:
        try:
            raw = path.read_text(encoding="utf-8")
            data = json.loads(raw)
            if isinstance(data, dict):
                for entry in data.values():
                    if isinstance(entry, dict):
                        entry.pop("max_tokens", None)
                custom_models_state.update(
                    {k: v for k, v in data.items() if isinstance(v, dict)}
                )
                _save()
        except (OSError, json.JSONDecodeError):  # noqa: BLE001 — fresh install or corrupt file; start empty rather than crash boot
            # Fresh install (no file) or corrupted file — start empty
            # rather than crashing app boot. Corrupt files should be
            # inspected by ops, not auto-wiped.
            pass

    # ─── Dispatcher registration · sub-router builder ─────────
    # Given a user-supplied provider config, construct the right
    # ``ModelRouter`` subclass and register it under the user's
    # chosen model_id on the live dispatcher. Wrapped so the request
    # carrying our dispatch alias ("claude-mirror") gets the
    # upstream real model name ("claude-sonnet-4-6") substituted
    # before the sub-router sees it — without that wrap mirrors
    # reject the alias as an unknown model.

    def _dispatcher() -> Any:
        return getattr(
            getattr(stack, "planner", None) if stack else None, "router", None,
        )

    def _entry_model_id(entry: dict[str, Any]) -> str:
        raw = entry.get("id") or entry.get("name")
        return raw if isinstance(raw, str) else ""

    def _entry_upstreams(entry: dict[str, Any], model_id: str) -> list[str]:
        # Read the open-ended ``models`` list. Falls back to legacy
        # ``model`` + optional ``model_performance`` for entries
        # persisted before the list refactor, so an in-place deploy
        # doesn't lose user config.
        raw_models = entry.get("models")
        if isinstance(raw_models, list) and raw_models:
            upstreams: list[str] = [
                str(m).strip() for m in raw_models if str(m or "").strip()
            ]
        else:
            legacy: list[str] = []
            primary = entry.get("model")
            if isinstance(primary, str) and primary.strip():
                legacy.append(primary.strip())
            perf = entry.get("model_performance")
            if (
                isinstance(perf, str)
                and perf.strip()
                and perf.strip() != primary
            ):
                legacy.append(perf.strip())
            upstreams = legacy or [model_id]
        return upstreams

    def _entry_route_ids(entry: dict[str, Any], fallback_id: str = "") -> list[str]:
        model_id = _entry_model_id(entry) or fallback_id
        route_ids: list[str] = []
        for raw in [model_id, *_entry_upstreams(entry, model_id)]:
            route_id = str(raw or "").strip()
            if route_id and route_id not in route_ids:
                route_ids.append(route_id)
        return route_ids

    def _unregister_entry(
        entry: dict[str, Any] | None,
        *,
        fallback_id: str = "",
    ) -> bool:
        dispatcher = _dispatcher()
        if dispatcher is None or not hasattr(dispatcher, "unregister"):
            return False
        route_ids = (
            _entry_route_ids(entry, fallback_id)
            if isinstance(entry, dict)
            else ([fallback_id] if fallback_id else [])
        )
        removed = False
        for route_id in route_ids:
            removed = bool(dispatcher.unregister(route_id)) or removed
        return removed

    def _register(entry: dict[str, Any]) -> dict[str, Any]:
        dispatcher = _dispatcher()
        if dispatcher is None or not hasattr(dispatcher, "register"):
            return {"ok": False, "error": "planner has no ModelDispatchRouter"}
        model_id = _entry_model_id(entry)
        if not model_id:
            return {"ok": False, "error": "id required"}
        provider = (entry.get("provider") or "openai").lower()
        base_url = entry.get("base_url") or ""
        api_key = entry.get("api_key") or ""
        upstreams = _entry_upstreams(entry, model_id)
        if not upstreams:
            return {"ok": False, "error": "models list is empty"}
        primary_model = upstreams[0]
        default_headers = entry.get("default_headers") or {}
        if not isinstance(default_headers, dict):
            default_headers = {}
        try:
            if provider in ("anthropic", "claude"):
                from runtime.sensing.model_router.anthropic_router import (
                    AnthropicModelRouter,
                )
                sub_router = AnthropicModelRouter(
                    api_key=api_key,
                    default_model=primary_model,
                    base_url=(base_url or None),
                )
            elif provider in ("gemini", "google"):
                from runtime.sensing.model_router.gemini_router import (
                    GeminiModelRouter,
                )
                sub_router = GeminiModelRouter(
                    api_key=api_key,
                    default_model=primary_model,
                    base_url=(base_url or "https://generativelanguage.googleapis.com/v1beta"),
                    extra_headers=default_headers,
                )
            else:
                from runtime.sensing.model_router.openai_router import (
                    OpenAIModelRouter,
                )
                if not base_url:
                    return {
                        "ok": False,
                        "error": "base_url required for openai-compat",
                    }
                sub_router = OpenAIModelRouter(
                    base_url=base_url,
                    api_key=api_key or "dummy",
                    default_model=primary_model,
                    extra_headers=default_headers,
                )
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": f"router init failed: {e}"}

        from runtime.sensing.model_router.models import (
            ModelRequest as _MR,  # noqa: N814
        )
        from runtime.sensing.model_router.models import (
            ModelRouter as _MRR,  # noqa: N814
        )

        class _UpstreamModelRewrite(_MRR):
            """Dispatch wrapper that maps a request to one of the
            entry's ``upstreams`` slots, then delegates to the inner
            provider-specific router.

            Behavior:
              * If ``request.model`` is one of the entry's
                ``upstreams``, use it as the real upstream id. This
                is the path Auto mode takes after
                ``turn_complexity`` picks ``entry.models[0]`` (cheap
                tier) or ``entry.models[-1]`` (performance tier) and
                rewrites ``request.model`` to that concrete value.
              * Otherwise fall back to ``upstreams[0]``. This covers
                the user-pinned path in ModelPicker — when the user
                picks the entry id (e.g. ``openai-prod``) rather than
                a specific model name, we still want the cheap slot
                by default and let the user re-pick via Auto mode for
                a stronger tier.
            """

            def __init__(self, inner: _MRR, upstreams: list[str]) -> None:
                self._inner = inner
                self._upstreams = list(upstreams)
                self._default = self._upstreams[0] if self._upstreams else ""

            def _resolve(self, request: _MR) -> str:
                if request.model in self._upstreams:
                    return request.model
                return self._default

            def call(self, request: _MR):
                rewritten = request.model_copy(
                    update={"model": self._resolve(request)},
                )
                return self._inner.call(rewritten)

            def call_stream(self, request: _MR):
                # Mirror ``call`` · route to the right upstream slot,
                # then delegate to the inner router's streaming path.
                # Required for multi-model entries (e.g. ``openai-prod``
                # with ``[gpt-4o-mini, gpt-4o]``) to emit real deltas
                # from the chosen slot instead of always-defaulting
                # to the cheap one.
                rewritten = request.model_copy(
                    update={"model": self._resolve(request)},
                )
                yield from self._inner.call_stream(rewritten)

            @property
            def default_model(self) -> str:
                return self._default

        wrapper = _UpstreamModelRewrite(sub_router, upstreams)
        for route_id in _entry_route_ids(entry, model_id):
            dispatcher.register(route_id, wrapper)
        return {"ok": True, "model_id": model_id}

    def _unregister(model_id: str) -> bool:
        return _unregister_entry(
            custom_models_state.get(model_id),
            fallback_id=model_id,
        )

    def _compat_diagnostic_for_entry(entry: dict[str, Any]) -> dict[str, Any]:
        provider = str(entry.get("provider") or "openai").lower()
        model_id = _entry_model_id(entry)
        base_url = str(entry.get("base_url") or "")
        upstreams = _entry_upstreams(entry, model_id)
        header_names = sorted(
            str(name)
            for name in (entry.get("default_headers") or {})
            if str(name).strip()
        )
        if provider not in {"openai", "openai-compatible", "openai_compat", "custom"}:
            return {
                "id": model_id,
                "provider": provider,
                "applicable": False,
                "reason": "provider is not OpenAI-compatible",
                "upstreams": upstreams,
                "default_header_names": header_names,
            }

        from runtime.sensing.model_router.openai_compat_providers import (
            apply_custom_openai_compat_profile,
            describe_openai_compat_profile,
            normalize_openai_compat_payload,
            plan_openai_compat_retries,
            resolve_openai_compat_profile,
        )

        rows: list[dict[str, Any]] = []
        for upstream in upstreams:
            base_profile = resolve_openai_compat_profile(base_url, upstream)
            profile = apply_custom_openai_compat_profile(
                entry,
                base_profile=base_profile,
            )
            profile_summary = describe_openai_compat_profile(profile)
            original = _sample_openai_compat_payload(upstream)
            normalized = normalize_openai_compat_payload(
                original,
                profile=profile,
            )
            removed, added, changed = _field_delta(original, normalized)
            retry_plan = plan_openai_compat_retries(
                normalized,
                status_code=400,
                body=(
                    "unsupported reasoning_effort thinking tool_choice "
                    "temperature top_p max_completion_tokens stream_options "
                    "response_format "
                    "additionalProperties extra inputs are not permitted "
                    "unsupported parameter"
                ),
                profile=profile,
            )
            diagnostic_summary = _compat_diagnostic_summary(
                normalized=normalized,
                removed_fields=removed,
                changed_fields=changed,
                retry_plan=retry_plan,
                compat_score=profile_summary["compat_score"],
            )
            rows.append({
                "model": upstream,
                "profile": profile.id,
                "profile_display_name": profile.display_name,
                "profile_summary": profile_summary,
                "compat_score": profile_summary["compat_score"],
                "normalization_hints": profile_summary["normalization_hints"],
                "compatibility_notes": profile_summary["notes"],
                "thinking_request_style": profile.thinking_request_style,
                "omit_sampling_parameters": profile.omit_sampling_parameters,
                "drop_tool_choice": profile.drop_tool_choice,
                "strict_tool_schema": profile.strict_tool_schema,
                "max_temperature": profile.max_temperature,
                "unsupported_request_fields": list(
                    profile.unsupported_request_fields,
                ),
                "dry_run": True,
                "risk_level": diagnostic_summary["risk_level"],
                "risk_reasons": diagnostic_summary["risk_reasons"],
                "capability_matrix": diagnostic_summary["capability_matrix"],
                "normalization": {
                    "removed_fields": removed,
                    "added_fields": added,
                    "changed_fields": changed,
                    "normalized_fields": sorted(normalized),
                    "payload": normalized,
                },
                "fallback_retries": [
                    {
                        "reason": item.reason,
                        "removed_fields": list(item.removed_fields),
                        "added_fields": list(item.added_fields),
                        "changed_fields": list(item.changed_fields),
                        "payload_fields": sorted(item.payload),
                    }
                    for item in retry_plan
                ],
            })
        return {
            "id": model_id,
            "provider": provider,
            "base_url": base_url,
            "applicable": True,
            "has_api_key": bool(entry.get("api_key")),
            "default_header_names": header_names,
            "upstreams": rows,
        }

    def _default_header_names(entry: dict[str, Any]) -> list[str]:
        headers = entry.get("default_headers") or {}
        if not isinstance(headers, dict):
            return []
        return sorted(str(name) for name in headers if str(name).strip())

    def _custom_model_wire_entry(entry: dict[str, Any]) -> dict[str, Any]:
        """Return a custom-model row safe for browser/API responses.

        ``api_key`` and ``default_headers`` both contain secrets. The
        browser only needs presence + header names so users can see what is
        configured without receiving bearer tokens or route keys back over the
        wire.
        """
        header_names = _default_header_names(entry)
        safe = {
            k: v
            for k, v in entry.items()
            if k not in {"api_key", "default_headers"}
        }
        safe["has_api_key"] = bool(entry.get("api_key"))
        safe["default_header_names"] = header_names
        safe["has_default_headers"] = bool(header_names)
        return safe

    def _sample_openai_compat_payload(model: str) -> dict[str, Any]:
        return {
            "model": model,
            "messages": [{"role": "user", "content": "ping"}],
            "temperature": 0.7,
            "top_p": 0.9,
            "presence_penalty": 0.0,
            "frequency_penalty": 0.0,
            "max_tokens": 8,
            "stream": True,
            "stream_options": {"include_usage": True},
            "response_format": {"type": "json_object"},
            "reasoning_effort": "high",
            "thinking": {"type": "enabled"},
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "diagnostic_ping",
                        "description": "No-op compatibility probe.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "path": {"type": "string"},
                            },
                            "additionalProperties": True,
                        },
                    },
                },
            ],
            "tool_choice": "auto",
            "parallel_tool_calls": True,
        }

    def _builtin_openai_compat_catalog() -> list[dict[str, Any]]:
        from runtime.sensing.model_router.openai_compat_providers import (
            known_openai_compat_profiles,
        )

        catalog: list[dict[str, Any]] = []
        for profile in known_openai_compat_profiles():
            model = _sample_model_for_profile(profile)
            base_url = _sample_base_url_for_profile(profile)
            diagnostic = _compat_diagnostic_for_entry({
                "id": profile.id,
                "name": profile.display_name,
                "provider": "openai",
                "base_url": base_url,
                "models": [model],
                "compat_profile": profile.id,
            })
            diagnostic["built_in"] = True
            diagnostic["sample_base_url"] = base_url
            catalog.append(diagnostic)
        return catalog

    def _sample_model_for_profile(profile: Any) -> str:
        if profile.id == "kimi_coding":
            return "kimi-k2.7-code"
        if profile.id == "kimi":
            return "kimi-k2-0711-preview"
        if profile.id == "deepseek":
            return "deepseek-chat"
        if profile.id == "qwen":
            return "qwen-plus"
        if profile.id == "glm":
            return "glm-4-flash"
        if profile.id == "doubao":
            return "doubao-pro-32k"
        if profile.id == "minimax":
            return "MiniMax-M2"
        if profile.id == "hunyuan":
            return "hunyuan-large"
        if profile.id == "baichuan":
            return "Baichuan4"
        if profile.id == "yi":
            return "yi-lightning"
        if profile.id == "stepfun":
            return "step-2-mini"
        if profile.id == "siliconflow":
            return "deepseek-ai/DeepSeek-V3"
        if profile.id == "qianfan":
            return "ernie-4.5-turbo-128k"
        markers = tuple(getattr(profile, "model_markers", ()) or ())
        marker = str(markers[0] if markers else profile.id).rstrip("-_/ ")
        return marker or profile.id

    def _sample_base_url_for_profile(profile: Any) -> str:
        markers = tuple(getattr(profile, "base_url_markers", ()) or ())
        marker = str(markers[0] if markers else "example.com/v1")
        if marker.startswith("http://") or marker.startswith("https://"):
            return marker.rstrip("/")
        if marker.startswith("/"):
            return f"https://api.example.com{marker}".rstrip("/")
        return f"https://{marker.rstrip('/')}"

    def _field_delta(
        original: dict[str, Any],
        normalized: dict[str, Any],
    ) -> tuple[list[str], list[str], list[str]]:
        original_keys = set(original)
        normalized_keys = set(normalized)
        return (
            sorted(original_keys - normalized_keys),
            sorted(normalized_keys - original_keys),
            sorted(
                key
                for key in original_keys & normalized_keys
                if original.get(key) != normalized.get(key)
            ),
        )

    def _compat_diagnostic_summary(
        *,
        normalized: dict[str, Any],
        removed_fields: list[str],
        changed_fields: list[str],
        retry_plan: list[Any],
        compat_score: int,
    ) -> dict[str, Any]:
        retry_removed: set[str] = set()
        retry_changed: set[str] = set()
        retry_reasons: list[str] = []
        for retry in retry_plan:
            retry_reasons.append(str(getattr(retry, "reason", "") or ""))
            retry_removed.update(str(v) for v in getattr(retry, "removed_fields", ()) or ())
            retry_changed.update(str(v) for v in getattr(retry, "changed_fields", ()) or ())

        removed = set(removed_fields)
        changed = set(changed_fields)
        matrix = [
            _compat_capability_row(
                "chat_completion",
                "pass" if {"model", "messages"}.issubset(normalized) else "warn",
                [
                    "model preserved" if "model" in normalized else "model missing",
                    "messages preserved" if "messages" in normalized else "messages missing",
                ],
                ["dry_run_request_shape_only"],
            ),
            _compat_capability_row(
                "streaming",
                "warn" if "stream_options" in retry_removed else "unverified",
                [
                    "stream flag preserved" if normalized.get("stream") is True else "stream flag not preserved",
                    (
                        "stream_options preserved"
                        if "stream_options" in normalized
                        else "stream_options absent"
                    ),
                ],
                [
                    "dry_run_does_not_open_stream",
                    *(
                        ["strict fallback may drop stream_options"]
                        if "stream_options" in retry_removed
                        else []
                    ),
                ],
            ),
            _compat_capability_row(
                "tool_calling",
                "warn" if {"tools", "tool_choice"} & (removed | retry_removed) else "pass",
                [
                    "tools preserved" if "tools" in normalized else "tools removed",
                    (
                        "tool_choice preserved"
                        if "tool_choice" in normalized
                        else "tool_choice absent"
                    ),
                ],
                [
                    *(
                        ["parallel_tool_calls removed"]
                        if "parallel_tool_calls" in removed
                        else []
                    ),
                    *(["tool schema normalized"] if "tools" in changed else []),
                    *(
                        ["fallback may drop tool_choice"]
                        if "tool_choice" in retry_removed
                        else []
                    ),
                    *(
                        ["fallback may drop tools"]
                        if "tools" in retry_removed
                        else []
                    ),
                ],
            ),
            _compat_capability_row(
                "structured_output",
                "warn" if "response_format" in retry_removed else "unverified",
                [
                    (
                        "response_format preserved"
                        if "response_format" in normalized
                        else "response_format absent"
                    ),
                ],
                [
                    "dry_run_does_not_validate_response_schema",
                    *(
                        ["strict fallback may drop response_format"]
                        if "response_format" in retry_removed
                        else []
                    ),
                ],
            ),
            _compat_capability_row(
                "reasoning_request",
                "warn"
                if {"reasoning_effort", "thinking"} & (removed | changed | retry_removed | retry_changed)
                else "pass",
                [
                    (
                        "reasoning_effort preserved"
                        if "reasoning_effort" in normalized
                        else "reasoning_effort absent"
                    ),
                    "thinking preserved" if "thinking" in normalized else "thinking absent",
                ],
                [
                    *(
                        ["reasoning request normalized"]
                        if {"reasoning_effort", "thinking"} & (removed | changed)
                        else []
                    ),
                    *(
                        ["fallback may drop reasoning fields"]
                        if {"reasoning_effort", "thinking"} & retry_removed
                        else []
                    ),
                ],
            ),
            _compat_capability_row(
                "usage_accounting",
                "warn" if "stream_options" in retry_removed else "unverified",
                [
                    (
                        "stream usage requested"
                        if normalized.get("stream_options", {}).get("include_usage") is True
                        else "stream usage not requested"
                    ),
                ],
                [
                    "response_usage_shape_not_called_in_dry_run",
                    *(
                        ["strict fallback may drop stream usage"]
                        if "stream_options" in retry_removed
                        else []
                    ),
                ],
            ),
            _compat_capability_row(
                "fallback_retries",
                "pass" if retry_plan else "unverified",
                [
                    f"{len(retry_plan)} retry variants planned",
                    *retry_reasons[:4],
                ],
                ["dry_run_representative_400"],
            ),
        ]

        risk_reasons: list[str] = []
        risk_points = 0

        def add_risk(reason: str, points: int = 1) -> None:
            nonlocal risk_points
            if reason not in risk_reasons:
                risk_reasons.append(reason)
            risk_points += points

        if compat_score < 80:
            add_risk(f"compat_score:{compat_score}", 2 if compat_score < 70 else 1)
        if {"reasoning_effort", "thinking"} & (removed | changed):
            add_risk("reasoning_request_normalized", 1)
        if {"temperature", "top_p", "presence_penalty", "frequency_penalty"} & removed:
            add_risk("sampling_parameters_removed", 1)
        if "parallel_tool_calls" in removed:
            add_risk("parallel_tool_calls_removed", 1)
        if "tool_choice" in removed:
            add_risk("tool_calling_control_removed", 2)
        if "tools" in changed:
            add_risk("tool_schema_normalized", 1)
        if {"tool_choice", "tools"} & retry_removed:
            add_risk("tool_calling_fallback_degrades_control", 1)
        if {"response_format", "stream_options"} & retry_removed:
            add_risk("strict_provider_may_drop_optional_features", 0)
        if {"model", "messages"} & removed:
            add_risk("core_request_field_removed", 3)
        if "tools" in removed:
            add_risk("tool_calling_removed", 2)

        if risk_points >= 5:
            risk_level = "high"
        elif risk_points >= 2:
            risk_level = "medium"
        else:
            risk_level = "low"

        return {
            "risk_level": risk_level,
            "risk_reasons": risk_reasons,
            "capability_matrix": matrix,
        }

    def _compat_capability_row(
        capability: str,
        status: str,
        evidence: list[str],
        notes: list[str],
    ) -> dict[str, Any]:
        return {
            "capability": capability,
            "status": status,
            "evidence": [item for item in evidence if item],
            "notes": [item for item in notes if item],
        }

    # Hydrate from disk + re-register each entry so the dispatcher
    # sees them on the first request.
    _load()
    for _entry in custom_models_state.values():
        _register(_entry)

    # ═══ Endpoints ═══════════════════════════════════════════

    @router.get(
        "/api/config/identity-lock", response_model=IdentityLockResponse,
    )
    def api_identity_lock_get() -> dict[str, Any]:
        """Report current identity-lock state.

        Fields
        ------
        locked : bool
            True if vendor/model names are being scrubbed from LLM
            replies in the current process.
        source : str
            ``"runtime"`` (admin toggled via PUT), ``"env"``
            (``OCTOPUS_IDENTITY_LOCK`` set), or ``"default"``.
        unlock_paths : list[str]
            Ways the filter can be bypassed even when locked.
        """
        from runtime.platform import identity_filter as _idf

        rt = _idf.get_runtime_lock()
        if rt is not None:
            source = "runtime"
            locked = rt
        elif os.environ.get("OCTOPUS_IDENTITY_LOCK"):
            source = "env"
            locked = _idf._env_lock_enabled()
        else:
            source = "default"
            locked = True
        return {
            "locked": locked,
            "source": source,
            "unlock_paths": [
                "env OCTOPUS_IDENTITY_LOCK=0",
                "user prompt starts with /raw",
                "body.context.raw_identity=true on thread run",
                "PUT /api/config/identity-lock { locked: false }",
            ],
        }

    @router.put(
        "/api/config/identity-lock", response_model=IdentityLockResponse,
    )
    def api_identity_lock_put(body: dict[str, Any]) -> dict[str, Any]:
        """Admin · toggle identity lock at runtime.

        ``null`` clears the runtime override and defers to the env var /
        default. Authentication, when enabled, is enforced once at the
        router level so every config endpoint stays aligned.
        """
        from runtime.platform import identity_filter as _idf

        raw = body.get("locked") if isinstance(body, dict) else None
        if raw is None:
            _idf.set_runtime_lock(None)
        elif isinstance(raw, bool):
            _idf.set_runtime_lock(raw)
        else:
            raise HTTPException(
                400, "body.locked must be true / false / null",
            )
        return api_identity_lock_get()

    @router.get("/api/providers", response_model=ProvidersResponse)
    def api_list_providers() -> dict[str, Any]:
        """List available LLM providers with their declared capabilities.

        Pulled from the ``Provider`` mixin on each router subclass.
        Used by the frontend ModelPicker to badge models with capability
        hints and to gate UI features (hide "upload image" for
        vision-less models).
        """
        providers: list[dict[str, Any]] = []
        _specs: list[tuple[str, str, str]] = [
            ("anthropic", "runtime.sensing.model_router.anthropic_router", "AnthropicModelRouter"),
            ("openai",    "runtime.sensing.model_router.openai_router",    "OpenAIModelRouter"),
            ("gemini",    "runtime.sensing.model_router.gemini_router",    "GeminiModelRouter"),
            ("molili",    "runtime.sensing.model_router.molili_router",    "MoliliModelRouter"),
        ]
        for name, modpath, classname in _specs:
            try:
                mod = __import__(modpath, fromlist=[classname])
                cls = getattr(mod, classname, None)
                if cls is None:
                    continue
                caps = getattr(cls, "capabilities", None)
                if caps is None:
                    continue
                providers.append({
                    "name": getattr(cls, "provider_name", name),
                    "supports_vision": caps.supports_vision,
                    "supports_tool_use": caps.supports_tool_use,
                    "supports_streaming": caps.supports_streaming,
                    "supports_prompt_cache": caps.supports_prompt_cache,
                    "supports_structured_output": caps.supports_structured_output,
                    "default_model": caps.default_model,
                    "pricing_hint": caps.pricing_hint,
                })
            except (OSError, ValueError, AttributeError):  # noqa: BLE001
                continue
        return {"providers": providers}

    @router.get(
        "/api/config/custom-models", response_model=CustomModelsList,
    )
    def api_list_custom_models() -> dict[str, Any]:
        """List user-added models. ``api_key`` is NEVER echoed back —
        presence reported as ``has_api_key`` boolean only."""
        return {
            "models": [
                _custom_model_wire_entry(entry)
                for entry in custom_models_state.values()
            ],
        }

    @router.get("/api/config/custom-models/compat-diagnostics")
    def api_custom_model_compat_diagnostics(
        model_id: str | None = None,
    ) -> dict[str, Any]:
        """Dry-run OpenAI-compatible request shaping for custom models.

        This endpoint does **not** call an upstream model and never
        returns API keys. It shows the operator which compat profile
        each custom model resolves to, which request fields are
        removed/changed before dispatch, and which fallback retries
        would be attempted for a representative strict-provider 400.
        """
        entries = [
            entry
            for entry in custom_models_state.values()
            if model_id is None or _entry_model_id(entry) == model_id
        ]
        return {
            "schema": "octopus.openai_compat_diagnostics.v1",
            "total": len(entries),
            "diagnostics": [
                _compat_diagnostic_for_entry(entry) for entry in entries
            ],
        }

    @router.get("/api/config/openai-compat-profiles")
    def api_openai_compat_profiles() -> dict[str, Any]:
        """List built-in OpenAI-compatible provider profiles.

        This is a dry run over representative provider/model pairs: no
        upstream request is made and no API key is required. It gives
        operators a stable compatibility matrix before any custom model
        is configured.
        """
        diagnostics = _builtin_openai_compat_catalog()
        return {
            "schema": "octopus.openai_compat_profile_catalog.v1",
            "total": len(diagnostics),
            "diagnostics": diagnostics,
        }

    @router.put("/api/config/custom-models/{model_id}")
    def api_upsert_custom_model(
        model_id: str, body: dict[str, Any],
    ) -> dict[str, Any]:
        """Upsert a custom model. Missing fields in ``body`` are
        preserved from the prior entry (so a PUT without api_key keeps
        the existing secret instead of wiping it).

        ``body.models`` is the open-ended list of upstream model ids
        (index 0 = picker default, index -1 = performance slot for
        Auto mode). When the request omits ``models`` but includes
        the legacy ``model`` + optional ``model_performance`` fields,
        they're folded into a list in the same value→performance
        order so older clients keep working."""
        prev = custom_models_state.get(model_id, {})
        default_headers = body.get("default_headers")
        if default_headers is None:
            default_headers = prev.get("default_headers") or {}
        if not isinstance(default_headers, dict):
            default_headers = {}
        # Normalize ``models`` — explicit list wins, else fold the
        # legacy ``model`` + ``model_performance`` pair, else inherit
        # the prior list, else fall back to [model_id] so we never
        # persist an empty upstreams list (which would break the
        # dispatcher).
        raw_models = body.get("models")
        models: list[str]
        if isinstance(raw_models, list):
            models = [str(m).strip() for m in raw_models if str(m or "").strip()]
        else:
            models = []
            if "model" in body and isinstance(body["model"], str) and body["model"].strip():
                models.append(body["model"].strip())
            if (
                "model_performance" in body
                and isinstance(body["model_performance"], str)
                and body["model_performance"].strip()
                and body["model_performance"].strip() not in models
            ):
                models.append(body["model_performance"].strip())
        if not models and isinstance(prev.get("models"), list) and prev["models"]:
            models = [str(m).strip() for m in prev["models"] if str(m or "").strip()]
        if not models:
            legacy_primary = prev.get("model")
            if isinstance(legacy_primary, str) and legacy_primary.strip():
                models.append(legacy_primary.strip())
        if not models:
            models = [model_id]
        entry = {
            "id": model_id,
            "name": body.get("name") or model_id,
            "provider": body.get("provider") or prev.get("provider") or "openai",
            "base_url": body.get("base_url") or prev.get("base_url") or "",
            "api_key": body.get("api_key") or prev.get("api_key") or "",
            "models": models,
            "display_name": (
                body.get("display_name") or body.get("name") or model_id
            ),
            "supports_thinking": (
                body["supports_thinking"]
                if "supports_thinking" in body
                else prev.get("supports_thinking", False)
            ),
            "supports_vision": (
                body["supports_vision"]
                if "supports_vision" in body
                else prev.get("supports_vision", False)
            ),
            "supports_tool_use": (
                body["supports_tool_use"]
                if "supports_tool_use" in body
                else prev.get("supports_tool_use", True)
            ),
            "omit_sampling_parameters": (
                body["omit_sampling_parameters"]
                if "omit_sampling_parameters" in body
                else prev.get("omit_sampling_parameters")
            ),
            "compat_profile": (
                body["compat_profile"]
                if "compat_profile" in body
                else prev.get("compat_profile")
            ),
            "thinking_request_style": (
                body["thinking_request_style"]
                if "thinking_request_style" in body
                else prev.get("thinking_request_style")
            ),
            "drop_tool_choice": (
                body["drop_tool_choice"]
                if "drop_tool_choice" in body
                else prev.get("drop_tool_choice")
            ),
            "strict_tool_schema": (
                body["strict_tool_schema"]
                if "strict_tool_schema" in body
                else prev.get("strict_tool_schema")
            ),
            "max_temperature": (
                body["max_temperature"]
                if "max_temperature" in body
                else prev.get("max_temperature")
            ),
            "unsupported_request_fields": (
                body["unsupported_request_fields"]
                if "unsupported_request_fields" in body
                else prev.get("unsupported_request_fields")
            ),
            "default_headers": default_headers,
        }
        if prev:
            _unregister_entry(prev, fallback_id=model_id)
        custom_models_state[model_id] = entry
        _save()
        status = _register(entry)
        return {"model": _custom_model_wire_entry(entry), "_status": status}

    @router.delete(
        "/api/config/custom-models/{model_id}",
        response_model=CustomModelDeleteResponse,
    )
    def api_delete_custom_model(model_id: str) -> dict[str, Any]:
        """Remove a custom model. Idempotent — deleting a missing id
        returns ok:true with removed:false rather than 404, matching
        the UI's double-click race semantics."""
        prev = custom_models_state.pop(model_id, None)
        _save()
        removed = _unregister_entry(prev, fallback_id=model_id)
        return {"ok": True, "removed": removed}

    # ─── Local-model discovery + one-click import ────────────
    # These two endpoints back the "本地模型" collapsible in the
    # settings page · operators with Ollama / LM Studio / vLLM /
    # llama.cpp already running shouldn't have to hand-fill the
    # base_url for each. ``scan`` probes a small set of well-known
    # ports in parallel and reports what's reachable; ``import``
    # then takes one of those entries and writes it into
    # ``custom_models_state`` via the same code path that
    # ``api_upsert_custom_model`` uses, so the dispatcher and
    # smart-routing tier resolution pick it up immediately.
    #
    # We deliberately *do not* auto-import — operators should see
    # what's on their box first (avoids leaking dev-only services
    # into the production dispatch table), but the import itself
    # is one click and pre-fills models/base_url.

    @router.get("/api/config/local-models/scan")
    def api_scan_local_models(targets: str | None = None) -> dict[str, Any]:
        """Probe common local LLM server ports in parallel. Each
        probe tries the OpenAI-compat ``/v1/models`` endpoint; for
        Ollama we also try ``/api/tags`` as a fallback because
        Ollama only serves the OpenAI-compat surface when its
        ``OLLAMA_ORIGINS`` setting is permissive.

        ``targets`` is an optional comma-separated list of base
        URLs to probe instead of the production defaults. Tests
        use it to point the scanner at a temporary ``http.server``
        without monkeypatching private state; operators can use
        it to probe a remote dev box (e.g.
        ``?targets=http://10.0.0.5:11434,http://10.0.0.5:1234``).

        Returned shape:
          ``{"services": [ { provider, base_url, models, status,
          error? }, ... ]}``

        ``status`` is one of:
          * ``"ok"`` — service responded with at least one model id
          * ``"empty"`` — service responded, no models listed (yet)
          * ``"error"`` — service responded but with an unexpected
            shape, or the connection failed (see ``error``)

        Services that didn't respond at all are simply omitted from
        the list — no need to surface a "port 8001 is dead" row
        for every silent port on the box.
        """
        import concurrent.futures
        import urllib.error
        import urllib.request

        # Each candidate is (provider_hint, base_url, model_path).
        # ``provider_hint`` is what we'd tell the dispatcher if the
        # user imports this row — Ollama is OpenAI-compat at ``/v1``
        # when that surface is enabled, otherwise it still serves
        # the native ``/api/tags`` schema which our probe path
        # handles separately. Other rows are stock OpenAI-compat.
        if targets:
            override: list[tuple[str, str, str]] = []
            for raw in targets.split(","):
                base = raw.strip().rstrip("/")
                if not base:
                    continue
                override.append(("openai", base, "/v1/models"))
            candidates = override
        else:
            candidates = [
                ("openai", "http://127.0.0.1:11434", "/v1/models"),
                ("openai", "http://127.0.0.1:1234", "/v1/models"),
                ("openai", "http://127.0.0.1:8000", "/v1/models"),
                ("openai", "http://127.0.0.1:8001", "/v1/models"),
                ("openai", "http://127.0.0.1:8080", "/v1/models"),
            ]
        # Ollama native probe — separate candidate so the error
        # path is "Ollama isn't running" rather than "the v1 surface
        # isn't enabled". Only meaningful for the 11434 row.
        ollama_native = ("openai", "http://127.0.0.1:11434", "/api/tags")

        def _probe(
            base: str, path: str, timeout: float = 0.6,
        ) -> tuple[list[str], str | None]:
            url = base.rstrip("/") + path
            try:
                req = urllib.request.Request(url, headers={"Accept": "application/json"})
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    if not (200 <= resp.status < 300):
                        return [], f"http {resp.status}"
                    payload = resp.read().decode("utf-8", errors="replace")
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                return [], f"connection: {type(e).__name__}"
            try:
                data = json.loads(payload)
            except json.JSONDecodeError:
                return [], "invalid json"
            # OpenAI-compat shape · ``data[].id``
            if isinstance(data, dict) and isinstance(data.get("data"), list):
                ids = [
                    m.get("id")
                    for m in data["data"]
                    if isinstance(m, dict) and isinstance(m.get("id"), str)
                ]
                return ids, None
            # Ollama native shape · ``models[].name``
            if isinstance(data, dict) and isinstance(data.get("models"), list):
                names = [
                    m.get("name")
                    for m in data["models"]
                    if isinstance(m, dict) and isinstance(m.get("name"), str)
                ]
                return names, None
            return [], "unexpected schema"

        # Run all probes concurrently so a full scan completes in
        # ~one timeout window even when several ports are dead.
        results: list[dict[str, Any]] = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
            futures = {
                ex.submit(_probe, base, path): (base, path)
                for (provider, base, path) in candidates
            }
            for fut in concurrent.futures.as_completed(futures):
                base, path = futures[fut]
                ids, err = fut.result()
                if err is not None and "connection" in err:
                    # Silent port — drop it, the UI doesn't need
                    # to see every dead localhost listener.
                    continue
                # Decide provider hint from the probed base. The
                # base URL is what the UI will pre-fill; we don't
                # need to distinguish "ollama native" vs "ollama
                # v1" because both end up routed through the
                # OpenAI-compat adapter with the same base_url.
                provider_hint = "openai"
                base_url = base.rstrip("/") + "/v1"  # normalize
                results.append(
                    {
                        "provider": provider_hint,
                        "base_url": base_url,
                        "probe_path": path,
                        "models": ids,
                        "status": "ok" if ids else "empty",
                        **({"error": err} if err else {}),
                    }
                )
        # Ollama native fallback — only when nothing on 11434's
        # v1 surface came back. Avoids double-reporting.
        if not any(
            r["base_url"].startswith("http://127.0.0.1:11434") for r in results
        ):
            # Tuple is (provider_hint, base_url, probe_path); we
            # want the base_url and probe_path here.
            _, ollama_base, ollama_path = ollama_native
            ids, err = _probe(ollama_base, ollama_path)
            if err is None:
                results.append(
                    {
                        "provider": "openai",
                        "base_url": "http://127.0.0.1:11434/v1",
                        "probe_path": ollama_path,
                        "models": ids,
                        "status": "ok" if ids else "empty",
                    }
                )
        return {"services": results}

    @router.post("/api/config/local-models/import")
    def api_import_local_model(body: dict[str, Any]) -> dict[str, Any]:
        """Take one row from ``/scan`` and write it into
        ``custom_models_state``. Mirrors what
        ``api_upsert_custom_model`` does for the public PUT path
        but skips the HTTP round-trip — local imports are trusted.

        Body shape:
          ``{ base_url, models, display_name?, id? }``

        ``id`` defaults to the first non-empty model id (the
        picker default) so the dispatcher's lookup key matches
        the user's mental model. ``api_key`` is left empty —
        local services don't need one, and the OpenAI-compat
        router ships a dummy key for unauthenticated calls.
        """
        base_url = str(body.get("base_url") or "").rstrip("/")
        if not base_url:
            return {"ok": False, "error": "base_url required"}
        raw_models = body.get("models")
        if not isinstance(raw_models, list):
            return {"ok": False, "error": "models list required"}
        models = [str(m).strip() for m in raw_models if str(m or "").strip()]
        if not models:
            return {"ok": False, "error": "at least one model id required"}
        display_name = str(body.get("display_name") or models[0])
        # Stable id derived from the base URL host:port (so two
        # imports of the same service overwrite each other instead
        # of stacking duplicate rows). The user can still rename
        # in the edit form afterwards.
        from urllib.parse import urlparse
        parsed = urlparse(base_url)
        host = parsed.hostname or "localhost"
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        # sanitize for filesystem/id safety
        id_seed = f"local-{host}-{port}".replace(".", "-")
        provided_id = body.get("id")
        if isinstance(provided_id, str) and provided_id.strip():
            id_seed = provided_id.strip()
        model_id = id_seed
        # Avoid clobbering an unrelated entry whose id collides —
        # append a numeric suffix until we hit a free slot, but
        # never overwrite an existing import of the same id (the
        # caller can re-run scan to refresh its models list and
        # we'll just update in place).
        suffix = 1
        while model_id in custom_models_state and custom_models_state[model_id].get(
            "base_url",
        ) != base_url:
            suffix += 1
            model_id = f"{id_seed}-{suffix}"
        entry = {
            "id": model_id,
            "name": model_id,
            "provider": "openai",
            "base_url": base_url,
            "api_key": "",
            "models": models,
            "display_name": display_name,
            "supports_thinking": False,
            "supports_vision": False,
            "supports_tool_use": True,
            "omit_sampling_parameters": None,
            "compat_profile": None,
            "thinking_request_style": None,
            "drop_tool_choice": None,
            "strict_tool_schema": None,
            "max_temperature": None,
            "unsupported_request_fields": None,
            "default_headers": {},
        }
        custom_models_state[model_id] = entry
        _save()
        status = _register(entry)
        return {
            "ok": True,
            "model_id": model_id,
            "entry": _custom_model_wire_entry(entry),
            "_status": status,
        }

    # ─── Merged listing · molili presets + custom models ─────
    # Frontend ModelPicker consumes this · it's declared on the
    # config router so it runs BEFORE the openai_gateway's own
    # /api/llm-models (FastAPI picks first-match). Living here
    # keeps the merge logic close to the ``custom_models_state``
    # dict it reads from.

    @router.post(
        "/api/config/custom-models/test",
        response_model=CustomModelTestResponse,
    )
    def api_test_custom_model(body: dict[str, Any]) -> dict[str, Any]:
        """Run a tiny real chat completion against a custom model."""
        import time

        model_id = body.get("id")
        prev = (
            custom_models_state.get(model_id)
            if isinstance(model_id, str)
            else {}
        ) or {}
        provider = str(
            body.get("provider") or prev.get("provider") or "openai",
        ).lower()
        base_url = str(body.get("base_url") or prev.get("base_url") or "")
        api_key = str(body.get("api_key") or prev.get("api_key") or "")
        # Resolve the test target model — explicit ``model`` wins for
        # backwards compat, else first item of the new ``models`` list,
        # else first item of the persisted list, else the id. Always
        # test the cheap slot (index 0) so the test is fast and cheap.
        upstream_model = ""
        if isinstance(body.get("model"), str) and body["model"].strip():
            upstream_model = body["model"].strip()
        if not upstream_model:
            raw = body.get("models")
            if isinstance(raw, list):
                for m in raw:
                    if isinstance(m, str) and m.strip():
                        upstream_model = m.strip()
                        break
        if not upstream_model and isinstance(prev.get("models"), list):
            for m in prev["models"]:
                if isinstance(m, str) and m.strip():
                    upstream_model = m.strip()
                    break
        if not upstream_model and isinstance(prev.get("model"), str) and prev["model"].strip():
            upstream_model = prev["model"].strip()
        if not upstream_model:
            upstream_model = model_id or ""
        default_headers = body.get("default_headers")
        if default_headers is None:
            default_headers = prev.get("default_headers") or {}
        if not isinstance(default_headers, dict):
            default_headers = {}

        if not upstream_model:
            raise HTTPException(400, "model is required")
        if not api_key:
            raise HTTPException(400, "api_key is required")
        if provider not in ("anthropic", "claude") and not base_url:
            raise HTTPException(400, "base_url is required")

        try:
            from runtime.sensing.model_router.models import Message, ModelRequest

            if provider in ("anthropic", "claude"):
                from runtime.sensing.model_router.anthropic_router import (
                    AnthropicModelRouter,
                )
                router_for_test = AnthropicModelRouter(
                    api_key=api_key,
                    default_model=upstream_model,
                    base_url=(base_url or None),
                )
                provider_name = "anthropic"
            elif provider in ("gemini", "google"):
                from runtime.sensing.model_router.gemini_router import (
                    GeminiModelRouter,
                )
                router_for_test = GeminiModelRouter(
                    api_key=api_key,
                    default_model=upstream_model,
                    base_url=(
                        base_url
                        or "https://generativelanguage.googleapis.com/v1beta"
                    ),
                    extra_headers=default_headers,
                )
                provider_name = "gemini"
            else:
                from runtime.sensing.model_router.openai_router import (
                    OpenAIModelRouter,
                )
                router_for_test = OpenAIModelRouter(
                    base_url=base_url,
                    api_key=api_key,
                    default_model=upstream_model,
                    extra_headers=default_headers,
                    timeout_seconds=15.0,
                )
                provider_name = "openai"

            started = time.perf_counter()
            resp = router_for_test.call(ModelRequest(
                model=upstream_model,
                messages=[Message(role="user", content="ping")],
                max_tokens=8,
                temperature=0,
            ))
            latency_ms = int((time.perf_counter() - started) * 1000)
            return {
                "ok": True,
                "provider": provider_name,
                "model": upstream_model,
                "latency_ms": latency_ms,
                "message": (resp.text or "").strip()[:120] or "ok",
            }
        except Exception as e:  # noqa: BLE001
            return {
                "ok": False,
                "provider": provider,
                "model": upstream_model,
                "latency_ms": None,
                "error": f"{type(e).__name__}: {e}",
            }

    @router.get("/api/llm-models")
    def api_llm_models() -> dict[str, Any]:
        molili_presets = [
            {
                "id": "minimax-m2.5", "name": "minimax-m2.5",
                "display_name": "MiniMax M2.5", "provider": "molili",
            },
            {
                "id": "glm-4.7", "name": "glm-4.7",
                "display_name": "GLM-4.7", "provider": "molili",
            },
            {
                "id": "kimi-k2.5", "name": "kimi-k2.5",
                "display_name": "Kimi K2.5", "provider": "molili",
            },
            {
                "id": "deepseek-v3.2", "name": "deepseek-v3.2",
                "display_name": "DeepSeek-V3.2", "provider": "molili",
            },
            {
                "id": "qwen3-max", "name": "qwen3-max",
                "display_name": "Qwen3-Max", "provider": "molili",
            },
        ]
        custom: list[dict[str, Any]] = []
        for e in custom_models_state.values():
            entry_id = e["id"]
            entry_label = e.get("display_name") or e.get("name") or entry_id
            provider = e.get("provider") or "openai"
            supports_thinking = bool(e.get("supports_thinking"))
            supports_vision = bool(e.get("supports_vision"))
            supports_tool_use = bool(e.get("supports_tool_use", True))
            omit_sampling_parameters = e.get("omit_sampling_parameters")

            # Expand the entry's ``models`` list into one picker row per
            # variant so the UI can show concrete model ids
            # (e.g. ``mimo-v2.5-pro``, ``mimo-v2.5-flash``) instead of
            # the entry alias ``mimo2.5``. Falls back to legacy single-
            # ``model`` field, then to the entry id itself when neither
            # is present.
            raw_models = e.get("models")
            variants: list[str] = []
            if isinstance(raw_models, list):
                variants = [str(m).strip() for m in raw_models if str(m or "").strip()]
            if not variants:
                legacy = e.get("model")
                if isinstance(legacy, str) and legacy.strip():
                    variants = [legacy.strip()]
            if not variants:
                # Worst case: surface the entry id itself so the row
                # at least appears (the user can edit the entry to
                # add a real model id).
                variants = [entry_id]

            for variant in variants:
                # Show the concrete variant name only — no entry-id
                # prefix, since the variant id is already unique. The
                # entry id is still surfaced via ``entry_id`` for
                # downstream callers that need to know which custom-
                # model entry the variant came from (e.g. credentials
                # / base_url lookup).
                display = entry_label if len(variants) == 1 else (variant or entry_label)
                custom.append({
                    "id": variant,
                    "name": variant,
                    "display_name": display,
                    "provider": provider,
                    "supports_thinking": supports_thinking,
                    "supports_vision": supports_vision,
                    "supports_tool_use": supports_tool_use,
                    "omit_sampling_parameters": (
                        bool(omit_sampling_parameters)
                        if omit_sampling_parameters is not None
                        else None
                    ),
                    "compat_profile": e.get("compat_profile"),
                    "thinking_request_style": e.get("thinking_request_style"),
                    "drop_tool_choice": e.get("drop_tool_choice"),
                    "strict_tool_schema": e.get("strict_tool_schema"),
                    "max_temperature": e.get("max_temperature"),
                    "custom": True,
                    "entry_id": entry_id,
                })
        # Octopus Mix — built-in mixture-of-agents virtual model. Selecting
        # it routes /v1/chat/completions through proposers + aggregator
        # (see openai_gateway/mix.py). Listed first as the octopus-native
        # flagship; degrades to a single model if no proposer pool is set.
        from runtime.sensing.gateway.openai_gateway.mix import MIX_MODEL_ID
        mix_presets = [
            {
                "id": MIX_MODEL_ID, "name": MIX_MODEL_ID,
                "display_name": "Octopus Mix · 多模型协同",
                "provider": "octopus",
                "supports_thinking": True,
                "supports_vision": False,
                "supports_tool_use": True,
            },
        ]
        return {"models": mix_presets + molili_presets + custom}

    # ─── Constitution profile ────────────────────────────────
    #
    # Process-wide enforcement profile · strict / normal / lax.
    # Spec in docs/constitution.md §8 · ADR-008 explains the
    # downgrade rules. UI lives at the Privacy settings page.

    @router.get(
        "/api/safety/constitution-profile",
        response_model=ConstitutionProfileResponse,
    )
    def api_constitution_profile_get() -> dict[str, Any]:
        try:
            from runtime.safety.validation import get_profile
        except ImportError:
            return {"profile": "strict", "available": ["strict", "normal", "lax"]}
        return {
            "profile": get_profile(),
            "available": ["strict", "normal", "lax"],
        }

    @router.put(
        "/api/safety/constitution-profile",
        response_model=ConstitutionProfileResponse,
    )
    def api_constitution_profile_put(body: dict[str, Any]) -> dict[str, Any]:
        from runtime.safety.validation import get_profile, set_profile
        raw = body.get("profile") if isinstance(body, dict) else None
        if not isinstance(raw, str):
            raise HTTPException(400, "body.profile must be a string")
        try:
            set_profile(raw)  # type: ignore[arg-type]
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        return {
            "profile": get_profile(),
            "available": ["strict", "normal", "lax"],
        }

    # ─── LLM semantic-safety judge · runtime toggle ──────────
    #
    # The constitution's judge tier (gate Pass 3) — per-message semantic
    # review (PRIV/LAWF/DGNT). Off by default (one model call per unique
    # outbound message). ``safety.enable_llm_judge`` wires it at boot;
    # this lets the Privacy settings page flip it at RUNTIME via set_judge
    # (no restart). The profile (above) still decides whether a block
    # verdict hard-enforces (strict) or is audit-only (normal/lax).
    # ``available`` is false when there's no model router (static planner).

    def _judge_router() -> Any:
        return getattr(getattr(stack, "planner", None), "router", None)

    def _judge_state() -> dict[str, Any]:
        from runtime.safety.validation.judge import get_judge, null_judge

        return {
            "enabled": get_judge() is not null_judge,
            "available": _judge_router() is not None,
        }

    @router.get("/api/safety/llm-judge")
    def api_llm_judge_get() -> dict[str, Any]:
        return _judge_state()

    @router.put("/api/safety/llm-judge")
    def api_llm_judge_put(body: dict[str, Any]) -> dict[str, Any]:
        from runtime.safety.validation.judge import set_judge

        want = bool(body.get("enabled")) if isinstance(body, dict) else False
        if want:
            router_obj = _judge_router()
            if router_obj is None:
                raise HTTPException(
                    400,
                    "no model router available (static planner?) — cannot enable judge",
                )
            from runtime.safety.validation.llm_judge import build_judge_from_router

            set_judge(build_judge_from_router(router_obj))
        else:
            set_judge(None)  # back to null_judge (allow-all)
        return _judge_state()

    # ─── Feature flags ─────────────────────────────────────
    #
    # Returns the live catalog so the frontend can gate
    # experimental panels (ambient suggestions, team cowork,
    # etc.) without each component reading env directly.

    @router.get("/api/feature-flags")
    def api_feature_flags_list() -> dict[str, Any]:
        """List every registered feature flag with its resolved value.

        Read-only; mutations happen via env vars or
        ``data/feature_flags.json``. Frontend should treat this as
        a one-shot fetch on app load (re-fetch on settings change).

        Response
        --------
        ``{ "flags": [ { name, value, source, default,
        description, experimental, primary_env, legacy_env }, ... ] }``
        """
        from runtime.platform import feature_flags as _ff
        return {"flags": _ff.describe()}

    @router.post("/api/feature-flags/reload")
    def api_feature_flags_reload() -> dict[str, Any]:
        """Force a re-resolve from env + override file.

        Useful after editing ``data/feature_flags.json`` while the
        server is running. Returns the same shape as the list
        endpoint.
        """
        from runtime.platform import feature_flags as _ff
        _ff.reload()
        return {"flags": _ff.describe()}

    @router.get("/api/smart-routing")
    def api_smart_routing_get() -> dict[str, Any]:
        """Inspect the three-tier smart routing config.

        Returns:
            {
              "enabled": bool,
              "tiers": {
                "local":       <model name | null>,
                "value":       <model name | null>,
                "performance": <model name | null>,
              },
              "env_keys": {
                "local":       "OCTOPUS_MODEL_LOCAL",
                "value":       "OCTOPUS_MODEL_VALUE",
                "performance": "OCTOPUS_MODEL_PERFORMANCE",
              },
              "kill_switch_env": "OCTOPUS_SMART_ROUTING",
            }

        The frontend Settings panel reads this to render the three
        tier slots so users can pick a model per tier.
        """
        from runtime.core.cerebrum.turn_complexity import (
            get_tier_config,
            is_smart_routing_enabled,
        )
        return {
            "enabled": is_smart_routing_enabled(),
            "tiers": get_tier_config(),
            "env_keys": {
                "local": "OCTOPUS_MODEL_LOCAL",
                "value": "OCTOPUS_MODEL_VALUE",
                "performance": "OCTOPUS_MODEL_PERFORMANCE",
            },
            "kill_switch_env": "OCTOPUS_SMART_ROUTING",
        }

    @router.get("/api/ai-mode")
    def api_ai_mode_get() -> dict[str, Any]:
        """Inspect AI mode (Marvis-style efficiency / privacy).

        Returns the current mode + a one-shot device-capability
        recommendation the UI can show as "推荐使用：效率模式".
        Detection is bounded (≤ a few seconds) so the call is safe
        from the settings panel.
        """
        from runtime.core.cerebrum.ai_mode import (
            current_ai_mode,
            detect_device_summary,
            recommend_mode,
        )
        summary = detect_device_summary()
        return {
            "mode": current_ai_mode(),
            "recommended": recommend_mode(summary),
            "device": summary.to_dict(),
            "modes": [
                {
                    "id": "efficiency",
                    "label": "效率模式",
                    "description": (
                        "融合端侧的极致响应与云端的强大算力，"
                        "效果更好，速度更快，绝大多数用户的首选"
                    ),
                    "recommended_default": True,
                },
                {
                    "id": "privacy",
                    "label": "隐私模式",
                    "description": (
                        "专为保密场景设计，使用本地模型，"
                        "全部文件均在本地处理和分析"
                    ),
                    "recommended_default": False,
                },
            ],
        }

    @router.post("/api/ai-mode")
    def api_ai_mode_set(payload: dict[str, Any]) -> dict[str, Any]:
        """Persist the user's AI mode choice."""
        from runtime.core.cerebrum.ai_mode import set_ai_mode
        try:
            canonical = set_ai_mode(payload.get("mode", ""))
        except ValueError as exc:
            from fastapi import HTTPException
            raise HTTPException(400, str(exc)) from exc
        return {"mode": canonical, "ok": True}

    @router.get("/api/path-denylist")
    def api_path_denylist_get() -> dict[str, Any]:
        """List user-defined denied paths (privacy & security panel).

        Defaults shipped with the product (``.vscode``, ``AppData``,
        ``.cache``, etc.) are NOT returned — they're built-in policy.
        Only the user-managed list is surfaced; UI shows them with a
        "新增 / 删除" affordance.
        """
        from runtime.safety.auth.path_denylist import get_user_denylist
        return {"paths": get_user_denylist()}

    @router.post("/api/path-denylist", dependencies=[Depends(_require_admin)])
    def api_path_denylist_add(payload: dict[str, Any]) -> dict[str, Any]:
        """Append a path to the user denylist."""
        from runtime.safety.auth.path_denylist import add_user_denylist_entry
        path = payload.get("path", "")
        if not isinstance(path, str) or not path.strip():
            from fastapi import HTTPException
            raise HTTPException(400, "path must be a non-empty string")
        return {"paths": add_user_denylist_entry(path), "ok": True}

    @router.delete("/api/path-denylist", dependencies=[Depends(_require_admin)])
    def api_path_denylist_remove(payload: dict[str, Any]) -> dict[str, Any]:
        """Remove a path from the user denylist."""
        from runtime.safety.auth.path_denylist import remove_user_denylist_entry
        path = payload.get("path", "")
        if not isinstance(path, str) or not path.strip():
            from fastapi import HTTPException
            raise HTTPException(400, "path must be a non-empty string")
        return {"paths": remove_user_denylist_entry(path), "ok": True}

    return ConfigRouter(router=router, custom_models=custom_models_state)


__all__ = ["ConfigRouter", "create_config_router"]
