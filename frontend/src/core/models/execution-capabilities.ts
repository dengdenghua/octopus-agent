import type { ReasoningEffort } from "@/core/threads";

/** Unknown capabilities are unavailable until the model catalog confirms them. */
export function supportedReasoningEfforts(
  model?: {
    reasoning_efforts?: readonly string[] | null;
    supports_reasoning_effort?: boolean;
  } | null,
): ReasoningEffort[] {
  if (model?.supports_reasoning_effort === false) return [];
  const known = new Set([
    "off",
    "minimal",
    "low",
    "medium",
    "high",
    "xhigh",
    "max",
  ]);
  return [...new Set(model?.reasoning_efforts ?? [])].filter(
    (effort): effort is ReasoningEffort => known.has(effort),
  );
}
