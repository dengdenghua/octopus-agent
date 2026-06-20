import { MessageSquareIcon, PlusIcon, SearchIcon } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import { swallow } from "@/core/utils/log";
import { getToken } from "@/core/auth/api";
import { getBackendBaseURL } from "@/core/config";
import { useI18n } from "@/core/i18n/hooks";
import {
  createDefaultClient,
  type RealtimeClient,
  type ThreadSummary,
} from "@/core/realtime";
import { formatRelativeTimestamp } from "@/core/utils/datetime";
import { cn } from "@/lib/utils";

interface ThreadsSidebarProps {
  /** Currently active thread id; matched row gets the active highlight. */
  currentThreadId: string;
  className?: string;
}

// Mint a new thread id with the same shape as ``app/realtime/page.tsx``
// (``thr_`` + 12 hex chars). Kept inline so the sidebar doesn't need the
// page module as a dependency.
function randomThreadId(): string {
  const bytes = new Uint8Array(6);
  if (typeof crypto !== "undefined" && "getRandomValues" in crypto) {
    crypto.getRandomValues(bytes);
  } else {
    for (let i = 0; i < bytes.length; i++)
      bytes[i] = Math.floor(Math.random() * 256);
  }
  return `thr_${Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("")}`;
}

// Best-effort title for a thread row. The list payload is metadata-only
// (no message snippets), so we fall back to a short id form like
// ``thr_a1b2c3``. The page-level resume call has the message body.
function threadTitle(thread: ThreadSummary): string {
  const id = thread.threadId;
  if (id.length <= 12) return id;
  return id.slice(0, 10) + "…";
}

/**
 * Compact threads list for the realtime UI sidebar. Lists recent
 * conversations, supports client-side filtering, and navigates without
 * a page reload via ``useNavigate``.
 *
 * The data path mirrors the landing page (``app/realtime/page.tsx``):
 * open a transient WebSocket, issue ``thread/list``, close. We don't
 * hold a long-lived sidebar socket — the active thread page already
 * keeps one open and a second connection per user is wasteful.
 */
export function ThreadsSidebar({
  currentThreadId,
  className,
}: ThreadsSidebarProps) {
  const { t } = useI18n();
  const navigate = useNavigate();
  const [threads, setThreads] = useState<ThreadSummary[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [query, setQuery] = useState("");

  useEffect(() => {
    let cancelled = false;
    let client: RealtimeClient | null = null;
    const load = async () => {
      try {
        client = createDefaultClient({
          baseURL: getBackendBaseURL(),
          authToken: () => getToken(),
          // Sidebar never receives server-initiated requests, but the
          // client contract requires a responder; reject so a stray push
          // doesn't deadlock the server's pending future.
          onIncomingRequest: async () => {
            throw new Error("threads sidebar does not handle server requests");
          },
          onNotification: () => {
            // Notifications are irrelevant for the listing call.
          },
        });
        client.connect();
        const result = await client.request<{ threads: ThreadSummary[] }>(
          "thread/list",
          {},
        );
        if (!cancelled) setThreads(result.threads);
      } catch (err) {
        swallow(err);
        if (!cancelled) {
          setLoadError(err instanceof Error ? err.message : String(err));
          setThreads([]);
        }
      } finally {
        client?.close();
      }
    };
    void load();
    return () => {
      cancelled = true;
      client?.close();
    };
  }, []);

  const visibleThreads = useMemo(() => {
    if (!threads) return null;
    const q = query.trim().toLowerCase();
    if (!q) return threads;
    return threads.filter((thread) =>
      thread.threadId.toLowerCase().includes(q),
    );
  }, [threads, query]);

  const handleNew = () => {
    navigate(`/realtime/${randomThreadId()}`);
  };

  const handleSelect = (id: string) => {
    navigate(`/realtime/${encodeURIComponent(id)}`);
  };

  return (
    <div
      className={cn(
        "flex w-full flex-col gap-2 bg-background/50 p-2 text-[12px]",
        className,
      )}
    >
      {/* Header: title + new-thread button */}
      <div className="flex items-center justify-between gap-2 px-1">
        <span className="text-[11px] font-medium text-muted-foreground">
          {t.codeMode.threadsHistory}
        </span>
        <button
          type="button"
          onClick={handleNew}
          title={t.codeMode.newThread}
          className={cn(
            "inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px]",
            "text-muted-foreground transition-colors hover:bg-muted/40 hover:text-foreground",
          )}
        >
          <PlusIcon className="size-3" />
          <span>{t.codeMode.newThread}</span>
        </button>
      </div>

      {/* Search input */}
      <div className="relative px-1">
        <SearchIcon className="pointer-events-none absolute left-2.5 top-1/2 size-3 -translate-y-1/2 text-muted-foreground/60" />
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={t.codeMode.searchThreads}
          className={cn(
            "h-7 w-full rounded-md border border-border/40 bg-background/50 pl-7 pr-2 text-[11px]",
            "placeholder:text-muted-foreground/50 outline-none transition-colors",
            "hover:border-border/70 focus:border-border focus:bg-background",
          )}
        />
      </div>

      {/* Scrollable thread list */}
      <div className="flex-1 min-h-0 overflow-y-auto">
        {visibleThreads === null && !loadError ? (
          <div className="px-2 py-3 text-center text-[11px] text-muted-foreground">
            …
          </div>
        ) : loadError && (!threads || threads.length === 0) ? (
          <div
            className="px-2 py-3 text-center text-[11px] text-muted-foreground/80"
            title={loadError}
          >
            {t.codeMode.noThreadsYet}
          </div>
        ) : visibleThreads && visibleThreads.length === 0 ? (
          <div className="px-2 py-3 text-center text-[11px] text-muted-foreground">
            {t.codeMode.noThreadsYet}
          </div>
        ) : (
          <div className="space-y-0.5">
            {visibleThreads?.map((thread) => {
              const active = thread.threadId === currentThreadId;
              return (
                <button
                  key={thread.threadId}
                  type="button"
                  onClick={() => handleSelect(thread.threadId)}
                  title={thread.threadId}
                  className={cn(
                    "flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left transition-colors",
                    active ? "bg-muted/60" : "hover:bg-muted/40",
                  )}
                >
                  <MessageSquareIcon
                    className={cn(
                      "size-3 shrink-0",
                      active ? "text-foreground" : "text-muted-foreground/70",
                    )}
                  />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate font-mono text-[12px] text-foreground">
                      {threadTitle(thread)}
                    </span>
                    <span className="block truncate text-[10px] text-muted-foreground/80">
                      {formatRelativeTimestamp(thread.updatedAt)}
                    </span>
                  </span>
                </button>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
