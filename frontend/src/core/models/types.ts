export interface Model {
  id: string;
  name: string;
  model: string;
  display_name: string;
  description?: string | null;
  supports_thinking?: boolean;
  supports_vision?: boolean;
  supports_reasoning_effort?: boolean;
  context_window?: number | null;
  // Provider identification · used to look up ProviderCapabilities for
  // UI gating (e.g. grey out "upload image" for vision-less providers,
  // show a cache-hit badge for cache-supported ones).
  provider?: string;
  [key: string]: unknown;
}

/**
 * Provider capabilities · mirrors backend
 * `runtime/sensing/eyes/provider.py::ProviderCapabilities`. Fetched
 * from `GET /api/providers` and cached via `useProviders()`.
 *
 * The type is re-exported from the auto-generated OpenAPI bundle
 * (see docs/adr/004-openapi-ts-codegen.md). Pre-codegen this was a
 * hand-written interface that had ``default_model: string`` /
 * ``pricing_hint: string`` · both are actually ``string | null``
 * on the backend (FastAPI serializes ``None`` → ``null``). Using the
 * generated type closes that drift; any caller that assumed
 * non-null now gets a TS error where it matters.
 */
import type { components } from "@/core/api/openapi-types";

export type ProviderCapabilities =
  components["schemas"]["ProviderCapabilitiesWire"];
