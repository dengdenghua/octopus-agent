export type CodexComposerMode = "plan" | "spec" | "goal";

const CODEX_MODE_RE = /^\/codex\s+(plan|spec|goal)(?:\s+|$)/i;

export interface CodexComposerModeParseResult {
  text: string;
  mode?: CodexComposerMode;
}

export function codexComposerModeMarker(mode: CodexComposerMode): string {
  return `/codex ${mode}`;
}

export function parseCodexComposerModeMarker(
  rawText: string,
): CodexComposerModeParseResult {
  const source = rawText.trim();
  const match = CODEX_MODE_RE.exec(source);
  if (!match) return { text: source };
  const mode = match[1]?.toLowerCase() as CodexComposerMode;
  const text = source.slice(match[0].length).trimStart();
  return { text, mode };
}

export function applyCodexComposerModeContext(
  context: Record<string, unknown>,
  mode: CodexComposerMode | undefined,
): Record<string, unknown> {
  if (!mode) return context;
  return {
    ...context,
    codex_mode: mode,
    completion_policy: mode,
    ...(mode === "goal" ? { goal_mode: true } : {}),
    mode_preset: `codex.${mode}`,
    workflow_preset: `codex.${mode}`,
  };
}
