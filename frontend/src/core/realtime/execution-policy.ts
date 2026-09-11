import type { ExecutionSnapshot } from "./items";

export type ExecutionEngine = ExecutionSnapshot["engine"];
export type ExecutionEnginePreference = "auto" | ExecutionEngine;

export function executionEnginePreference(
  value: unknown,
): ExecutionEnginePreference {
  return value === "codex" || value === "octopus" || value === "opencode"
    ? value
    : "auto";
}

/** Preview of the server policy. The runtime validates again before effects. */
export function previewExecutionEngine({
  preference,
  roleBackend,
  orchestrated,
}: {
  preference: ExecutionEnginePreference;
  roleBackend?: unknown;
  codingTask: boolean;
  orchestrated: boolean;
  codexAvailable: boolean;
}): ExecutionEngine {
  if (preference !== "auto") return preference;
  if (orchestrated) return "opencode";
  if (roleBackend === "codex_app_server") return "codex";
  return "opencode";
}
