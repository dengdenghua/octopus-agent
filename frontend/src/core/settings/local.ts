import type { AgentThreadContext, ReasoningEffort } from "../threads";
import { emitSettingsChanged, eventBus } from "../events";

export const DEFAULT_LOCAL_SETTINGS: LocalSettings = {
  notification: {
    enabled: true,
  },
  context: {
    model_name: "claude-opus",
    mode: "react",
    permission_mode: "default",
    execution_environment: "sandbox",
    reasoning_effort: undefined,
  },
  layout: {
    sidebar_collapsed: false,
  },
  browser_panel: {
    open: false,
    url: "",
    mode: "mobile",
  },
  display: {
    // Chat message font size. ``medium`` matches the historical default so
    // existing users see no visual change until they opt in.
    chat_font_size: "medium",
  },
  session: {
    auto_new_session_hours: 0,
  },
};

const LOCAL_SETTINGS_KEY = "octopus.local-settings";
const THREAD_MODEL_KEY_PREFIX = "octopus.thread-model.";

function isBrowser(): boolean {
  return typeof window !== "undefined";
}

export interface LocalSettings {
  notification: {
    enabled: boolean;
  };
  context: Omit<
    AgentThreadContext,
    | "thread_id"
    | "is_plan_mode"
    | "thinking_enabled"
    | "subagent_enabled"
    | "model_name"
    | "reasoning_effort"
  > & {
    model_name?: string | undefined;
    mode: "chat" | "code" | "react" | "deep" | "flash" | "thinking" | undefined;
    reasoning_effort?: ReasoningEffort;
  };
  layout: {
    sidebar_collapsed: boolean;
  };
  browser_panel: {
    open: boolean;
    url: string;
    mode: "mobile" | "desktop";
  };
  display: {
    chat_font_size: "small" | "medium" | "large";
  };
  session: {
    /** Hours of inactivity before a *new* chat session is auto-started when
     * the user sends the next message. `0` disables the behavior. */
    auto_new_session_hours: number;
  };
}

function mergeLocalSettings(settings?: Partial<LocalSettings>): LocalSettings {
  const context = {
    ...DEFAULT_LOCAL_SETTINGS.context,
    ...settings?.context,
  };
  const persistedMode = (context as { mode?: unknown }).mode;
  if (persistedMode === "chat" || persistedMode === "swarm") {
    context.mode = "react";
  }
  return {
    ...DEFAULT_LOCAL_SETTINGS,
    context,
    layout: {
      ...DEFAULT_LOCAL_SETTINGS.layout,
      ...settings?.layout,
    },
    notification: {
      ...DEFAULT_LOCAL_SETTINGS.notification,
      ...settings?.notification,
    },
    browser_panel: {
      ...DEFAULT_LOCAL_SETTINGS.browser_panel,
      ...settings?.browser_panel,
    },
    display: {
      ...DEFAULT_LOCAL_SETTINGS.display,
      ...settings?.display,
    },
    session: {
      ...DEFAULT_LOCAL_SETTINGS.session,
      ...settings?.session,
    },
  };
}

function getThreadModelStorageKey(threadId: string): string {
  return `${THREAD_MODEL_KEY_PREFIX}${threadId}`;
}

export function getThreadModelName(threadId: string): string | undefined {
  if (!isBrowser()) {
    return undefined;
  }
  return localStorage.getItem(getThreadModelStorageKey(threadId)) ?? undefined;
}

export function saveThreadModelName(
  threadId: string,
  modelName: string | undefined,
) {
  if (!isBrowser()) {
    return;
  }
  const key = getThreadModelStorageKey(threadId);
  if (!modelName) {
    localStorage.removeItem(key);
    return;
  }
  localStorage.setItem(key, modelName);
}

/**
 * Remove per-thread selections that point at a model which no longer exists.
 *
 * Custom models can be deleted from Settings while older threads still carry
 * a model override. Leaving those keys behind makes the picker appear to
 * select a deleted model when the thread is opened again.
 */
export function clearThreadModelReferences(modelName: string): number {
  if (!isBrowser() || !modelName) {
    return 0;
  }

  const keysToRemove: string[] = [];
  for (let index = 0; index < localStorage.length; index += 1) {
    const key = localStorage.key(index);
    if (
      key?.startsWith(THREAD_MODEL_KEY_PREFIX) &&
      localStorage.getItem(key) === modelName
    ) {
      keysToRemove.push(key);
    }
  }
  for (const key of keysToRemove) {
    localStorage.removeItem(key);
  }
  return keysToRemove.length;
}

function applyThreadModelOverride(
  settings: LocalSettings,
  threadId?: string,
): LocalSettings {
  const threadModelName = threadId ? getThreadModelName(threadId) : undefined;
  if (!threadModelName) {
    return settings;
  }
  return {
    ...settings,
    context: {
      ...settings.context,
      model_name: threadModelName,
    },
  };
}

export function getLocalSettings(): LocalSettings {
  if (!isBrowser()) {
    return DEFAULT_LOCAL_SETTINGS;
  }
  const json = localStorage.getItem(LOCAL_SETTINGS_KEY);
  try {
    if (json) {
      const settings = JSON.parse(json) as Partial<LocalSettings>;
      return mergeLocalSettings(settings);
    }
  } catch (e) {
    console.warn(
      "[LocalSettings] Failed to parse stored settings, using defaults.",
      e,
    );
  }
  return DEFAULT_LOCAL_SETTINGS;
}

export function getThreadLocalSettings(threadId: string): LocalSettings {
  return applyThreadModelOverride(getLocalSettings(), threadId);
}

/**
 * Settings change subscription using EventBus.
 * Same-tab useState subscribers rely on this to re-read: the native
 * ``storage`` event only fires on *other* tabs, so without a same-tab
 * broadcast, a settings change made in one component (say the Appearance
 * page) stays invisible to another component already mounted elsewhere
 * (say MarkdownContent), until the page is reloaded.
 */
export function saveLocalSettings(settings: LocalSettings) {
  if (!isBrowser()) {
    return;
  }
  localStorage.setItem(LOCAL_SETTINGS_KEY, JSON.stringify(settings));
  emitSettingsChanged();
}

export function subscribeLocalSettings(handler: () => void): () => void {
  if (!isBrowser()) return () => undefined;
  // Both signals: same-tab event bus + cross-tab storage event.
  const unsubscribe = eventBus.on("settings:changed", handler);
  const storageHandler = (e: StorageEvent) => {
    if (e.key === LOCAL_SETTINGS_KEY) handler();
  };
  window.addEventListener("storage", storageHandler);
  return () => {
    unsubscribe();
    window.removeEventListener("storage", storageHandler);
  };
}

export function saveThreadLocalSettings(
  threadId: string,
  settings: LocalSettings,
) {
  saveLocalSettings(settings);
  saveThreadModelName(threadId, settings.context.model_name);
}
