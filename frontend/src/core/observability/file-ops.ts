/* Implementation note. */
import { useEffect, useState } from "react";

import {
  subscribeFileOps,
  subscribePreviewRefresh,
  type FileOpEvent,
  type PreviewRefreshEvent,
} from "./api";

export interface UseFileOpStreamOptions {
  /* Implementation note. */
  limit?: number;
  /* Implementation note. */
  enabled?: boolean;
}

export function useFileOpStream(
  opts: UseFileOpStreamOptions = {},
): FileOpEvent[] {
  const limit = opts.limit ?? 20;
  const enabled = opts.enabled ?? true;
  const [events, setEvents] = useState<FileOpEvent[]>([]);

  useEffect(() => {
    if (!enabled) return undefined;
    const unsub = subscribeFileOps((evt) => {
      setEvents((prev) => {
        const next = [...prev, evt];
        // Implementation note.
        return next.length > limit ? next.slice(next.length - limit) : next;
      });
    });
    return () => {
      unsub();
    };
  }, [limit, enabled]);

  return events;
}

export interface UsePreviewRefreshOptions {
  /* Implementation note. */
  enabled?: boolean;
  /* Implementation note. */
  onRefresh?: (e: PreviewRefreshEvent) => void;
}

/* Implementation note. */
export function usePreviewRefresh(
  opts: UsePreviewRefreshOptions = {},
): PreviewRefreshEvent | null {
  const enabled = opts.enabled ?? true;
  const { onRefresh } = opts;
  const [latest, setLatest] = useState<PreviewRefreshEvent | null>(null);

  useEffect(() => {
    if (!enabled) return undefined;
    const unsub = subscribePreviewRefresh((evt) => {
      setLatest(evt);
      onRefresh?.(evt);
    });
    return () => unsub();
  }, [enabled, onRefresh]);

  return latest;
}
