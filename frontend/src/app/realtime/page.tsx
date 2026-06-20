import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { swallow } from "@/core/utils/log";
import { getToken } from "@/core/auth/api";
import { getBackendBaseURL } from "@/core/config";
import { useI18n } from "@/core/i18n/hooks";
import {
  createDefaultClient,
  type RealtimeClient,
  type ThreadSummary,
} from "@/core/realtime";

// Landing page for the realtime UI.
//
//   * "New thread" button mints a fresh id and navigates.
//   * Resume box accepts an id and jumps directly.
//   * The recent-threads list is fetched once via a transient
//     WebSocket → ``thread/list`` round-trip and renders cards a
//     click can re-enter.
//
// One-shot socket: we open it just for the list call and immediately
// close. The thread page itself opens its own long-lived connection
// when navigated to. This avoids holding two sockets per user just
// to render a sidebar.

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

export default function RealtimeIndex() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const [joinId, setJoinId] = useState("");
  const [threads, setThreads] = useState<ThreadSummary[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    let client: RealtimeClient | null = null;
    const load = async () => {
      try {
        client = createDefaultClient({
          baseURL: getBackendBaseURL(),
          authToken: () => getToken(),
          // Index page never receives server-initiated requests, but
          // the contract requires *some* responder; reject with
          // method-not-found so a stray push doesn't deadlock the
          // server's pending future.
          onIncomingRequest: async () => {
            throw new Error("index page does not handle server requests");
          },
          onNotification: () => {
            // Notifications are also irrelevant here; ignored.
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

  const onNew = useCallback(() => {
    navigate(`/realtime/${randomThreadId()}`);
  }, [navigate]);

  const onJoin = useCallback(() => {
    const id = joinId.trim();
    if (!id) return;
    navigate(`/realtime/${encodeURIComponent(id)}`);
  }, [joinId, navigate]);

  return (
    <div className="mx-auto flex min-h-screen max-w-4xl flex-col gap-6 p-8">
      <header className="flex flex-col gap-2 border-b pb-6">
        <h1 className="text-2xl font-semibold">{t.realtime.title}</h1>
        <p className="text-sm text-muted-foreground">
          {t.realtime.subtitle}
        </p>
      </header>

      <section className="flex items-center gap-3">
        <Button onClick={onNew}>{t.realtime.newThread}</Button>
        <span className="text-muted-foreground">{t.realtime.orResume}</span>
        <div className="flex items-center gap-2">
          <Input
            placeholder={t.realtime.threadIdPlaceholder}
            value={joinId}
            onChange={(e) => setJoinId(e.target.value)}
            className="w-60"
          />
          <Button
            variant="secondary"
            onClick={onJoin}
            disabled={!joinId.trim()}
          >
            {t.realtime.open}
          </Button>
        </div>
      </section>

      <section className="flex flex-col gap-3">
        <h2 className="text-sm font-medium text-muted-foreground">
          {t.realtime.recent}
        </h2>
        <ThreadGrid
          threads={threads}
          loadError={loadError}
          onSelect={navigate}
        />
      </section>
    </div>
  );
}

function ThreadGrid(props: {
  threads: ThreadSummary[] | null;
  loadError: string | null;
  onSelect: (path: string) => void;
}) {
  const { t } = useI18n();
  const { threads, loadError, onSelect } = props;
  if (loadError) {
    return (
      <div className="rounded-md border border-dashed p-6 text-sm text-muted-foreground">
        {t.realtime.loadError(loadError)}
      </div>
    );
  }
  if (threads === null) {
    return (
      <div className="text-sm text-muted-foreground">
        {t.realtime.loading}
      </div>
    );
  }
  if (threads.length === 0) {
    return (
      <div className="rounded-md border border-dashed p-6 text-sm text-muted-foreground">
        {t.realtime.empty}
      </div>
    );
  }
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {threads.map((t) => (
        <ThreadCard key={t.threadId} thread={t} onSelect={onSelect} />
      ))}
    </div>
  );
}

function ThreadCard(props: {
  thread: ThreadSummary;
  onSelect: (path: string) => void;
}) {
  const { t } = useI18n();
  const { thread, onSelect } = props;
  const updated = new Date(thread.updatedAt);
  const updatedLabel = isNaN(updated.getTime())
    ? thread.updatedAt
    : updated.toLocaleString();
  return (
    <button
      type="button"
      onClick={() =>
        onSelect(`/realtime/${encodeURIComponent(thread.threadId)}`)
      }
      className="text-left"
    >
      <Card className="transition hover:border-primary/40 hover:bg-muted/40">
        <CardHeader>
          <CardTitle className="truncate font-mono text-xs">
            {thread.threadId}
          </CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-1 text-xs text-muted-foreground">
          <span>{t.realtime.turns(thread.turnCount)}</span>
          <span>{t.realtime.lastStatus(thread.lastTurnStatus ?? "—")}</span>
          <span>{t.realtime.updated(updatedLabel)}</span>
        </CardContent>
      </Card>
    </button>
  );
}
