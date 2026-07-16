"use client";

import {
  BrainCircuitIcon,
  ClockIcon,
  MessageSquareTextIcon,
  WrenchIcon,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

import type { LiveToolEvent } from "./live-tool-timeline";

interface PublicThinkingStatusProps {
  isLoading: boolean;
  liveToolEvents: LiveToolEvent[];
  hasStreamingMessage?: boolean;
  threadId?: string | null;
  className?: string;
}

interface StatusLine {
  label: string;
  detail?: string;
  tone?: "active" | "done";
  icon?: "brain" | "tool" | "message" | "clock";
}

interface ThinkingSignal {
  iteration?: number | null;
  type?: string | null;
}

function compact(value: unknown, max = 120): string | undefined {
  if (value === undefined || value === null) return undefined;
  const text = typeof value === "string" ? value : JSON.stringify(value);
  const normalized = text.replace(/\s+/g, " ").trim();
  if (!normalized) return undefined;
  return normalized.length > max
    ? `${normalized.slice(0, max)}...`
    : normalized;
}

function eventSummary(event: LiveToolEvent | undefined): string | undefined {
  if (!event) return undefined;
  const input = event.input ?? {};
  const main =
    compact(input.query) ??
    compact(input.command) ??
    compact(input.path) ??
    compact(input.file_path) ??
    compact(input.url);
  const name = event.name.replace(/_/g, " ");
  return main ? `${name}: ${main}` : name;
}

function latestEvent(
  events: LiveToolEvent[],
  predicate?: (event: LiveToolEvent) => boolean,
) {
  const filtered = predicate ? events.filter(predicate) : events;
  return [...filtered].sort(
    (a, b) => (b.finishedAt ?? b.startedAt) - (a.finishedAt ?? a.startedAt),
  )[0];
}

function statusLines({
  elapsedMs,
  liveToolEvents,
  hasStreamingMessage,
  thinkingSignal,
  t,
}: {
  elapsedMs: number;
  liveToolEvents: LiveToolEvent[];
  hasStreamingMessage?: boolean;
  thinkingSignal?: ThinkingSignal | null;
  t: {
    publicThinkingStatus: {
      organizingReply: string;
      executingTool: string;
      gotResults: string;
      analyzing: string;
      understandingTask: string;
      planningFirstStep: string;
      waitingForModel: string;
      stillWaiting: string;
    };
  };
}): StatusLine[] {
  const running = latestEvent(
    liveToolEvents,
    (event) =>
      event.status === "running" || event.status === "waiting_approval",
  );
  const finished = liveToolEvents.filter(
    (event) =>
      event.status !== "running" && event.status !== "waiting_approval",
  );
  const latestFinished = latestEvent(finished);
  const recentFinished = [...finished]
    .sort(
      (a, b) => (a.finishedAt ?? a.startedAt) - (b.finishedAt ?? b.startedAt),
    )
    .slice(-2)
    .map((event) => ({
      label: t.publicThinkingStatus.gotResults,
      detail: eventSummary(event),
      tone: "done" as const,
      icon: "tool" as const,
    }));

  if (hasStreamingMessage) {
    return [
      ...recentFinished.slice(-1),
      {
        label: t.publicThinkingStatus.organizingReply,
        tone: "active",
        icon: "message",
      },
    ];
  }

  if (running) {
    return [
      ...recentFinished.slice(-1),
      {
        label: t.publicThinkingStatus.executingTool,
        detail: eventSummary(running),
        tone: "active",
        icon: "tool",
      },
    ];
  }

  if (finished.length > 0) {
    return [
      ...(recentFinished.length > 0
        ? recentFinished
        : [
            {
              label: t.publicThinkingStatus.gotResults,
              detail: eventSummary(latestFinished),
              tone: "done" as const,
              icon: "tool" as const,
            },
          ]),
      {
        label: t.publicThinkingStatus.analyzing,
        tone: "active",
        icon: "brain",
      },
    ];
  }

  if (thinkingSignal) {
    return [
      {
        label:
          thinkingSignal.type === "text_delta"
            ? t.publicThinkingStatus.organizingReply
            : t.publicThinkingStatus.analyzing,
        detail: thinkingSignal.iteration
          ? `第 ${thinkingSignal.iteration} 轮`
          : undefined,
        tone: "active",
        icon: "brain",
      },
    ];
  }

  if (elapsedMs < 4000) {
    return [
      {
        label: t.publicThinkingStatus.understandingTask,
        tone: "active",
        icon: "brain",
      },
    ];
  }

  if (elapsedMs < 12000) {
    return [
      {
        label: t.publicThinkingStatus.planningFirstStep,
        tone: "active",
        icon: "brain",
      },
    ];
  }

  if (elapsedMs < 25000) {
    return [
      {
        label: t.publicThinkingStatus.waitingForModel,
        tone: "active",
        icon: "clock",
      },
    ];
  }

  return [
    {
      label: t.publicThinkingStatus.stillWaiting,
      tone: "active",
      icon: "clock",
    },
  ];
}

function StatusIcon({ line }: { line: StatusLine }) {
  const className = cn(
    "size-3.5 shrink-0",
    line.tone === "done" ? "text-emerald-500" : "text-primary",
  );
  if (line.icon === "tool") return <WrenchIcon className={className} />;
  if (line.icon === "message")
    return <MessageSquareTextIcon className={className} />;
  if (line.icon === "clock") return <ClockIcon className={className} />;
  return <BrainCircuitIcon className={className} />;
}

export function PublicThinkingStatus({
  isLoading,
  liveToolEvents,
  hasStreamingMessage,
  threadId,
  className,
}: PublicThinkingStatusProps) {
  const { t } = useI18n();
  const [elapsedMs, setElapsedMs] = useState(0);
  const [thinkingSignal, setThinkingSignal] = useState<ThinkingSignal | null>(
    null,
  );

  useEffect(() => {
    if (!isLoading) return;
    setElapsedMs(0);
    setThinkingSignal(null);
    const timers = [4_000, 12_000, 25_000].map((delay) =>
      window.setTimeout(() => setElapsedMs(delay), delay),
    );
    return () => timers.forEach((timer) => window.clearTimeout(timer));
  }, [isLoading]);

  useEffect(() => {
    if (!isLoading) {
      setThinkingSignal(null);
      return;
    }
    const handler = (event: Event) => {
      const detail = (
        event as CustomEvent<{
          threadId?: string | null;
          type?: string | null;
          iteration?: number | null;
        }>
      ).detail;
      if (!detail) return;
      if (threadId && detail.threadId && detail.threadId !== threadId) return;
      setThinkingSignal({
        iteration: detail.iteration ?? null,
        type: detail.type ?? null,
      });
    };
    window.addEventListener("octopus:thinking_signal", handler);
    return () => window.removeEventListener("octopus:thinking_signal", handler);
  }, [isLoading, threadId]);

  const lines = useMemo(
    () =>
      statusLines({
        elapsedMs,
        liveToolEvents,
        hasStreamingMessage,
        thinkingSignal,
        t,
      }),
    [elapsedMs, hasStreamingMessage, liveToolEvents, thinkingSignal, t],
  );

  if (!isLoading) return null;

  return (
    <div
      role="status"
      aria-live="polite"
      aria-atomic="false"
      data-testid="conversation-activity-pulse"
      className={cn("my-2 ml-11 w-auto text-xs", className)}
    >
      <div className="flex min-w-0 items-start gap-2.5 rounded-lg border-l-2 border-primary/20 bg-muted/15 px-3 py-2">
        <span className="relative mt-1.5 flex size-2.5 shrink-0 items-center justify-center">
          <span className="absolute inline-flex size-2.5 animate-ping rounded-full bg-primary/20 motion-reduce:animate-none" />
          <span className="relative inline-flex size-1.5 rounded-full bg-primary/70" />
        </span>
        <div className="min-w-0 flex-1 space-y-1">
          {lines.map((line, index) => (
            <div
              key={`${line.label}:${line.detail ?? ""}:${index}`}
              className="animate-in fade-in slide-in-from-bottom-1 flex min-w-0 gap-2 duration-200 motion-reduce:animate-none"
            >
              <div className="mt-0.5 shrink-0">
                <StatusIcon line={line} />
              </div>
              <div className="min-w-0">
                <div
                  className={cn(
                    "leading-5",
                    line.tone === "done"
                      ? "text-emerald-700 dark:text-emerald-300"
                      : "font-medium text-foreground",
                  )}
                >
                  {line.label}
                </div>
                {line.detail && (
                  <div className="mt-0.5 truncate text-[11px] leading-4 text-muted-foreground/80">
                    {line.detail}
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
