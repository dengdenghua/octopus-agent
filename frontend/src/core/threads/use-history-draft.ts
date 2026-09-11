import { useEffect } from "react";

/** Editing prepares a new message. It never rewrites history or rolls back files. */
export function useHistoryDraft(
  threadId: string,
  setDraft: (text: string) => void,
) {
  useEffect(() => {
    const edit = (event: Event) => {
      const detail = (event as CustomEvent<unknown>).detail;
      if (!detail || typeof detail !== "object") return;
      const request = detail as { threadId?: unknown; text?: unknown };
      if (request.threadId !== threadId || typeof request.text !== "string")
        return;
      setDraft(request.text);
    };
    window.addEventListener("octopus:edit-message", edit);
    return () => window.removeEventListener("octopus:edit-message", edit);
  }, [threadId, setDraft]);
}
