/**
 * Which modules the user keeps in their sidebar.
 *
 * Storage is behind a tiny provider seam (`ModuleStateProvider`) so a backend
 * per-user preference endpoint can replace localStorage without touching any
 * caller. There is no such endpoint today — `IdentityStore` is read-only
 * (loaded from YAML, no write path), so cross-device sync is a follow-up.
 *
 * Persisted shape is a *disabled* list, not an enabled one: that way modules
 * added to the catalog in a later release default to visible instead of
 * silently staying hidden for existing users.
 */
import { useSyncExternalStore } from "react";

import { defaultEnabledModuleIds, moduleById, pinnedModuleIds } from "./catalog";

export interface ModuleStateProvider {
  readDisabled(): string[];
  writeDisabled(ids: string[]): void;
}

const STORAGE_KEY = "octopus.modules.disabled";

const localStorageProvider: ModuleStateProvider = {
  readDisabled() {
    try {
      const raw = window.localStorage.getItem(STORAGE_KEY);
      if (!raw) return [];
      const parsed = JSON.parse(raw);
      return Array.isArray(parsed)
        ? parsed.filter((id): id is string => typeof id === "string")
        : [];
    } catch {
      return [];
    }
  },
  writeDisabled(ids) {
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(ids));
    } catch {
      /* private mode / quota — this session only */
    }
  },
};

let provider: ModuleStateProvider = localStorageProvider;

/** Swap the persistence backend (tests, or a future server-backed provider). */
export function setModuleStateProvider(next: ModuleStateProvider): void {
  provider = next;
  cache = null;
  notify();
}

let cache: Set<string> | null = null;
/**
 * Runtime availability is deliberately separate from the user's sidebar
 * preference. A false value means the backend reports the module unavailable.
 */
let availabilityCache: ReadonlyMap<string, boolean> | null = null;
const listeners = new Set<() => void>();

function notify(): void {
  for (const listener of listeners) listener();
}

/** Pinned modules can never be disabled, whatever storage claims. */
function readDisabledSet(): Set<string> {
  const pinned = new Set(pinnedModuleIds());
  const stored = provider
    .readDisabled()
    // Drop ids that no longer exist so a removed module can't haunt storage.
    .filter((id) => moduleById(id) !== undefined && !pinned.has(id));
  return new Set(stored);
}

function getDisabledSet(): Set<string> {
  if (cache) return cache;
  cache = readDisabledSet();
  return cache;
}

export function isModuleEnabled(id: string): boolean {
  return !getDisabledSet().has(id);
}

export function enabledModuleIds(): string[] {
  const disabled = getDisabledSet();
  return defaultEnabledModuleIds().filter(
    (id) => !disabled.has(id) && availabilityCache?.get(id) !== false,
  );
}

/** Replace the server-backed availability snapshot for installable modules. */
export function setModuleAvailabilitySnapshot(
  availability: Readonly<Record<string, boolean>> | null,
): void {
  availabilityCache = availability
    ? new Map(
        Object.entries(availability).filter(
          ([id]) => moduleById(id) !== undefined,
        ),
      )
    : null;
  snapshotKey = "";
  snapshot = [];
  notify();
}

/** Update one module after an install/enable/disable/uninstall mutation. */
export function setModuleAvailable(id: string, available: boolean): void {
  if (!moduleById(id)) return;
  const next = new Map(availabilityCache ?? []);
  next.set(id, available);
  availabilityCache = next;
  snapshotKey = "";
  snapshot = [];
  notify();
}

/** Enable/disable one module. Pinned modules are silently ignored. */
export function setModuleEnabled(id: string, enabled: boolean): void {
  const descriptor = moduleById(id);
  if (!descriptor || !descriptor.removable) return;

  const next = new Set(getDisabledSet());
  if (enabled) next.delete(id);
  else next.add(id);

  cache = next;
  provider.writeDisabled([...next]);
  notify();
}

function handleStorage(event: StorageEvent): void {
  if (event.key === STORAGE_KEY) {
    cache = null; // force re-read so other tabs stay consistent
    notify();
  }
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  window.addEventListener("storage", handleStorage);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", handleStorage);
  };
}

// Snapshot must be referentially stable — useSyncExternalStore re-renders on
// every changed reference, and a fresh array each call would loop forever.
let snapshot: string[] = [];
let snapshotKey = "";

function getSnapshot(): string[] {
  const ids = enabledModuleIds();
  const key = ids.join("|");
  if (key !== snapshotKey) {
    snapshotKey = key;
    snapshot = ids;
  }
  return snapshot;
}

const SERVER_SNAPSHOT: string[] = defaultEnabledModuleIds();

/** Subscribe to the enabled-module id list. */
export function useEnabledModuleIds(): string[] {
  return useSyncExternalStore(subscribe, getSnapshot, () => SERVER_SNAPSHOT);
}

/** Test seam: drop the memoized state. */
export function resetModuleStateCache(): void {
  cache = null;
  availabilityCache = null;
  snapshotKey = "";
  snapshot = [];
  notify();
}
