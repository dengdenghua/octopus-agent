"""Custom-model lifecycle endpoints for the config router.

Pure structural split of ``_config_endpoints.py`` — no logic changes.
``_register_custom_models`` attaches the upsert / delete / test endpoints
for user-added models to the injected router, reading shared state through
the injected ``_ConfigCtx``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import HTTPException

from runtime.sensing.gateway._config_helpers import (
    _custom_model_wire_entry,
    _entry_1m_enabled,
    _entry_context_window,
)
from runtime.sensing.gateway._config_models import (
    CustomModelDeleteResponse,
    CustomModelTestResponse,
)

if TYPE_CHECKING:
    from ._config_endpoints import _ConfigCtx


def _register_custom_models(router: Any, ctx: _ConfigCtx) -> None:
    custom_models_state = ctx.custom_models
    save = ctx.save
    register = ctx.register
    unregister_entry = ctx.unregister_entry

    @router.put("/api/config/custom-models/{model_id}")
    def api_upsert_custom_model(
        model_id: str,
        body: dict[str, Any],
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
        raw_context_window = (
            body.get("context_window") if "context_window" in body else prev.get("context_window")
        )
        try:
            context_window = int(raw_context_window) if raw_context_window is not None else 0
        except (TypeError, ValueError):
            context_window = 0
        if not 8_192 <= context_window <= 2_000_000:
            context_window = _entry_context_window({}, models)
        enable_1m_context = (
            bool(body["enable_1m_context"])
            if "enable_1m_context" in body
            else _entry_1m_enabled(prev, models)
        )
        entry = {
            "id": model_id,
            "name": body.get("name") or model_id,
            "provider": body.get("provider") or prev.get("provider") or "openai",
            "base_url": body.get("base_url") or prev.get("base_url") or "",
            "api_key": body.get("api_key") or prev.get("api_key") or "",
            "models": models,
            "context_window": context_window,
            "enable_1m_context": enable_1m_context,
            "display_name": (body.get("display_name") or body.get("name") or model_id),
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
                body["compat_profile"] if "compat_profile" in body else prev.get("compat_profile")
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
            unregister_entry(prev, fallback_id=model_id)
        custom_models_state[model_id] = entry
        save(model_id)
        status = register(entry)
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
        save(model_id)
        removed = unregister_entry(prev, fallback_id=model_id)
        return {"ok": True, "removed": removed}

    @router.post(
        "/api/config/custom-models/test",
        response_model=CustomModelTestResponse,
    )
    def api_test_custom_model(body: dict[str, Any]) -> dict[str, Any]:
        """Run a tiny real chat completion against a custom model."""
        import time

        model_id = body.get("id")
        prev = (custom_models_state.get(model_id) if isinstance(model_id, str) else {}) or {}
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

                router_for_test: Any = AnthropicModelRouter(
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
                    base_url=(base_url or "https://generativelanguage.googleapis.com/v1beta"),
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
            resp = router_for_test.call(
                ModelRequest(
                    model=upstream_model,
                    messages=[Message(role="user", content="ping")],
                    max_tokens=8,
                    temperature=0,
                )
            )
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
