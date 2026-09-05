const BUILTIN_PERSONA_NAMES: Readonly<Record<string, string>> = {
  general: "Eve",
  coder: "Kane",
  desktop_operator: "Raven",
  aoi: "Zero",
  vibe_selling: "Luna",
};

/** Resolve stable builtin runtime ids to their user-facing persona names. */
export function builtinPersonaDisplayName(
  value: string | undefined | null,
): string | undefined {
  const normalized = value?.trim().toLowerCase();
  return normalized ? BUILTIN_PERSONA_NAMES[normalized] : undefined;
}
