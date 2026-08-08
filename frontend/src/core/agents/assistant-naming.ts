/**
 * Custom display name for the Octopus assistant (the global fixed role).
 *
 * The assistant's default name comes from the backend agent profile
 * (`agents/octopus/profile.jsonc` → "章鱼助手"). Users may override it to
 * a personal nickname; the override lives in localStorage so it applies
 * instantly across every UI surface (welcome, header badge, sidebar entry)
 * without a backend restart.
 */
import { swallow } from "@/core/utils/log";

export const ASSISTANT_NAME_KEY = "octopus.assistant-name";

/** Default assistant name — mirrors `agents/octopus/profile.jsonc`. */
export const DEFAULT_ASSISTANT_NAME = "章鱼助手";

export function getAssistantDisplayName(): string {
  try {
    const raw = window.localStorage.getItem(ASSISTANT_NAME_KEY)?.trim();
    if (raw) return raw;
  } catch (e) {
    swallow(e, "storage");
  }
  return DEFAULT_ASSISTANT_NAME;
}

export function setAssistantDisplayName(name: string): void {
  const trimmed = name.trim();
  try {
    if (trimmed) {
      window.localStorage.setItem(ASSISTANT_NAME_KEY, trimmed);
    } else {
      window.localStorage.removeItem(ASSISTANT_NAME_KEY);
    }
  } catch (e) {
    swallow(e, "storage");
  }
}