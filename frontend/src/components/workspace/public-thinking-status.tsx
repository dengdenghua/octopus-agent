"use client";

import { useI18n } from "@/core/i18n/hooks";
import type { StreamVitals } from "@/core/realtime/stream-vitals";
import { cn } from "@/lib/utils";

import type { LiveToolEvent } from "./live-tool-timeline";

interface PublicThinkingStatusProps {
  isLoading: boolean;
  liveToolEvents: LiveToolEvent[];
  hasStreamingMessage?: boolean;
  vitals?: StreamVitals;
  className?: string;
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

function latestRunningEvent(events: LiveToolEvent[]) {
  return [...events]
    .filter(
      (event) =>
        event.status === "running" || event.status === "waiting_approval",
    )
    .sort(
      (a, b) => (b.finishedAt ?? b.startedAt) - (a.finishedAt ?? a.startedAt),
    )[0];
}

export function PublicThinkingStatus({
  isLoading,
  liveToolEvents,
  hasStreamingMessage,
  vitals,
  className,
}: PublicThinkingStatusProps) {
  const { t } = useI18n();

  if (!isLoading) return null;

  const phase =
    vitals?.phase ?? (hasStreamingMessage ? "streaming" : "working");
  if (phase === "idle" || phase === "streaming") return null;

  const running = latestRunningEvent(liveToolEvents);
  const label =
    phase === "disconnected"
      ? t.publicThinkingStatus.reconnecting
      : phase === "slow"
        ? t.publicThinkingStatus.slowResponse
        : phase === "waiting"
          ? t.publicThinkingStatus.waitingForModel
          : t.publicThinkingStatus.modelWorking;
  const elapsedSeconds = Math.floor((vitals?.elapsedMs ?? 0) / 1000);
  const detail = running ? eventSummary(running) : undefined;

  return (
    <div
      role="status"
      aria-live="polite"
      aria-atomic="false"
      data-phase={phase}
      data-testid="conversation-activity-pulse"
      className={cn(
        "my-1.5 ml-11 flex min-w-0 items-center gap-1.5 text-xs leading-4 text-muted-foreground/55",
        className,
      )}
    >
      <span className="relative flex size-1.5 shrink-0 items-center justify-center">
        {phase !== "slow" && phase !== "disconnected" && (
          <span className="absolute inline-flex size-1.5 animate-pulse rounded-full bg-primary/20 motion-reduce:animate-none" />
        )}
        <span
          className={cn(
            "relative inline-flex size-1 rounded-full",
            phase === "slow"
              ? "bg-amber-500/55"
              : phase === "disconnected"
                ? "bg-destructive/55"
                : "bg-primary/55",
          )}
        />
      </span>
      <span className="shrink-0">{label}</span>
      {elapsedSeconds > 0 && (
        <span className="tabular-nums text-muted-foreground/40">
          {elapsedSeconds}s
        </span>
      )}
      {detail && (
        <span className="min-w-0 truncate text-muted-foreground/45">
          · {detail}
        </span>
      )}
    </div>
  );
}
