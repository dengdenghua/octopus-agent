"""
Pydantic response models for the config router.

Split out of config_router.py (pure structural refactor — no logic
changes). Imported back by config_router.py.

These give openapi.json real shape info for the config surface
(CustomModel / IdentityLock / Provider / Constitution endpoints).
"""

from __future__ import annotations

try:
    from pydantic import BaseModel, Field

    FASTAPI_AVAILABLE = True
except ImportError:  # pragma: no cover
    FASTAPI_AVAILABLE = False
    BaseModel = object  # type: ignore[assignment, misc]
    Field = None  # type: ignore[assignment, misc]

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
        context_window: int | None = None
        enable_1m_context: bool = False
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
        # Vision auto-detection · ``True`` when the image canary was
        # accepted, ``False`` when the model rejected image input, and
        # ``None`` when the probe was inconclusive (no info). The UI
        # uses ``False`` to lock the vision toggle off.
        supports_vision: bool | None = None

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


__all__ = [
    "ConstitutionProfilePutBody",
    "ConstitutionProfileResponse",
    "CustomModelDeleteResponse",
    "CustomModelEntry",
    "CustomModelsList",
    "CustomModelTestResponse",
    "CustomModelUpsertResponse",
    "CustomModelUpsertStatus",
    "FASTAPI_AVAILABLE",
    "IdentityLockPutBody",
    "IdentityLockResponse",
    "ProviderCapabilitiesWire",
    "ProvidersResponse",
]
