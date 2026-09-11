import { getBackendBaseURL } from "../config";
import { authHeaders } from "@/core/auth/api";

import type { Model } from "./types";

export async function loadModels(): Promise<Model[]> {
  // Use the LLM catalog endpoint, not /api/models — the latter aliases
  // the OpenAI-compat gateway which exposes *skills* (e.g.
  // "octopus-agent/list_cwd") as "models" for external clients that
  // want to call a skill via model= routing. For the in-app
  // ModelPicker we want real LLM options (Octopus Mix + configured custom models).
  const res = await fetch(`${getBackendBaseURL()}/api/llm-models`, {
    headers: authHeaders(),
  });
  if (!res.ok)
    throw new Error(`Failed to load models: ${res.status} ${res.statusText}`);
  const { models } = (await res.json()) as { models: Model[] };
  const officialResponse = await fetch(
    `${getBackendBaseURL()}/api/oct/openai/v1/models`,
    { headers: authHeaders() },
  ).catch(() => null);
  const official = officialResponse?.ok ? await officialResponse.json() : null;
  const officialRows: Model[] = Array.isArray(official?.data)
    ? official.data
        .filter(
          (row: { id: string }) => row.id && row.id.toLowerCase() !== "auto",
        )
        .map(
          (row: {
            id: string;
            display_name?: string;
            multiplier?: string;
            recommended?: boolean;
          }) => ({
            id: `official/${row.id}`,
            name: `official/${row.id}`,
            model: `official/${row.id}`,
            selection_id: `official/${row.id}`,
            entry_id: "official",
            provider: "oct",
            display_name: row.display_name || row.id,
            source_display_name: "官方模型",
            official: true,
            multiplier: row.multiplier,
            recommended: row.recommended,
          }),
        )
    : [];
  return [...(models ?? []), ...officialRows];
}
