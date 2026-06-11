"use client";

import {
  BrainCircuitIcon,
  ClockIcon,
  Loader2Icon,
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

function elapsedLabel(ms: number) {
  const seconds = Math.max(0, Math.floor(ms / 1000));
  if (seconds < 60) return `${seconds}s`;
  return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
}

function compact(value: unknown, max = 120): string | undefined {
  if (value === undefined || value === null) return undefined;
  const text = typeof value === "string" ? value : JSON.stringify(value);
  const normalized = text.replace(/\s+/g, " ").trim();
  if (!normalized) return undefined;
  return normalized.length > max ? `${normalized.slice(0, max)}...` : normalized;
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

function latestEvent(events: LiveToolEvent[], predicate?: (event: LiveToolEvent) => boolean) {
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
  t: { publicThinkingStatus: { organizingReply: string; executingTool: string; gotResults: string; analyzing: string; understandingTask: string; planningFirstStep: string; waitingForModel: string; stillWaiting: string } };
}): StatusLine[] {
  const running = latestEvent(
    liveToolEvents,
    (event) => event.status === "running" || event.status === "waiting_approval",
  );
  const finished = liveToolEvents.filter(
    (event) => event.status !== "running" && event.status !== "waiting_approval",
  );
  const latestFinished = latestEvent(finished);

  if (hasStreamingMessage) {
    return [{ label: t.publicThinkingStatus.organizingReply, tone: "active", icon: "message" }];
  }

  if (running) {
    return [
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
      {
        label: t.publicThinkingStatus.gotResults,
        detail: eventSummary(latestFinished),
        tone: "done",
        icon: "tool",
      },
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
        detail: thinkingSignal.iteration ? `第 ${thinkingSignal.iteration} 轮` : undefined,
        tone: "active",
        icon: "brain",
      },
    ];
  }

  if (elapsedMs < 4000) {
    return [{ label: t.publicThinkingStatus.understandingTask, tone: "active", icon: "brain" }];
  }

  if (elapsedMs < 12000) {
    return [{ label: t.publicThinkingStatus.planningFirstStep, tone: "active", icon: "brain" }];
  }

  if (elapsedMs < 25000) {
    return [{ label: t.publicThinkingStatus.waitingForModel, tone: "active", icon: "clock" }];
  }

  return [{ label: t.publicThinkingStatus.stillWaiting, tone: "active", icon: "clock" }];
}

function StatusIcon({ line }: { line: StatusLine }) {
  const className = cn(
    "size-3.5 shrink-0",
    line.tone === "done" ? "text-emerald-500" : "text-primary",
  );
  if (line.icon === "tool") return <WrenchIcon className={className} />;
  if (line.icon === "message") return <MessageSquareTextIcon className={className} />;
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
  const [startedAt, setStartedAt] = useState(() => Date.now());
  const [now, setNow] = useState(() => Date.now());
  const [thinkingSignal, setThinkingSignal] = useState<ThinkingSignal | null>(null);

  useEffect(() => {
    if (!isLoading) return;
    const start = Date.now();
    setStartedAt(start);
    setNow(start);
    setThinkingSignal(null);
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [isLoading]);

  useEffect(() => {
    if (!isLoading) {
      setThinkingSignal(null);
      return;
    }
    const handler = (event: Event) => {
      const detail = (event as CustomEvent<{
        threadId?: string | null;
        type?: string | null;
        iteration?: number | null;
      }>).detail;
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

  const elapsedMs = Math.max(0, now - startedAt);
  const lines = useMemo(
    () => statusLines({ elapsedMs, liveToolEvents, hasStreamingMessage, thinkingSignal, t }),
    [elapsedMs, hasStreamingMessage, liveToolEvents, thinkingSignal, t],
  );

  if (!isLoading) return null;

  return (
    <div
      className={cn(
        "workspace-panel-subtle my-2 w-full rounded-lg border border-border/60 p-3 text-xs",
        className,
      )}
    >
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <span className="inline-flex items-center gap-1.5 font-semibold text-foreground">
          <Loader2Icon className="size-3.5 animate-spin text-primary" />
          {t.publicThinkingStatus.title}
        </span>
        <span className="text-[11px] tabular-nums text-muted-foreground">
          {elapsedLabel(elapsedMs)}
        </span>
      </div>
      <div className="space-y-1.5">
        {lines.map((line) => (
          <div key={`${line.label}:${line.detail ?? ""}`} className="flex gap-2">
            <div className="mt-0.5">
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
                <div className="mt-0.5 break-words text-[11px] leading-4 text-muted-foreground/85">
                  {line.detail}
                </div>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
