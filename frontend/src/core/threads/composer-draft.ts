/**
 * Per-thread composer draft persistence.
 *
 * The composer keeps its draft in component state, which meant switching
 * threads or reloading the page silently discarded half-typed messages.
 * Drafts are mirrored to localStorage keyed by thread id (a dedicated key
 * for the not-yet-created "new thread" composer). Writes are debounced by
 * the caller; storage failures (quota, private mode) are swallowed — a
 * lost draft is annoying, a thrown exception mid-typing is worse.
 */

const DRAFT_KEY_PREFIX = "octopus:composer-draft:";
export const NEW_THREAD_DRAFT_KEY = "__new__";

function storageKey(threadId: string | undefined | null): string {
  return DRAFT_KEY_PREFIX + (threadId?.trim() ? threadId : NEW_THREAD_DRAFT_KEY);
}

export function loadComposerDraft(
  threadId: string | undefined | null,
): string | null {
  try {
    const value = window.localStorage.getItem(storageKey(threadId));
    return value && value.length > 0 ? value : null;
  } catch {
    return null;
  }
}

export function saveComposerDraft(
  threadId: string | undefined | null,
  draft: string,
): void {
  try {
    if (draft) {
      window.localStorage.setItem(storageKey(threadId), draft);
    } else {
      window.localStorage.removeItem(storageKey(threadId));
    }
  } catch {
    // Storage unavailable (private mode / quota): drafts stay in-memory.
  }
}
