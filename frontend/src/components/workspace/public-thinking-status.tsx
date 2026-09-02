"use client";

import { useEffect, useRef, useState } from "react";

import { useI18n } from "@/core/i18n/hooks";
import {
  FIRST_RESPONSE_DELAY_NOTICE_MS,
  formatStreamElapsed,
  type StreamVitals,
} from "@/core/realtime/stream-vitals";
import { cn } from "@/lib/utils";

import type { LiveToolEvent } from "./live-tool-timeline";

interface PublicThinkingStatusProps {
  isLoading: boolean;
  liveToolEvents: LiveToolEvent[];
  hasStreamingMessage?: boolean;
  vitals?: StreamVitals;
  className?: string;
  /** Render the screen-reader live region. MessageList owns one outside its log. */
  renderAnnouncement?: boolean;
  /** Render the visible activity line. */
  renderVisual?: boolean;
}

function compact(value: unknown, max = 80): string | undefined {
  if (value === undefined || value === null) return undefined;
  const text = typeof value === "string" ? value : JSON.stringify(value);
  const normalized = text.replace(/\s+/g, " ").trim();
  if (!normalized) return undefined;
  return normalized.length > max
    ? `${normalized.slice(0, max)}...`
    : normalized;
}

function basenamePath(value: string): string {
  const normalized = value.replace(/\\/g, "/").replace(/\/+$/, "");
  return normalized.split("/").filter(Boolean).at(-1) ?? normalized;
}

function compactUrl(value: string): string {
  try {
    const url = new URL(value);
    return url.hostname || value;
  } catch {
    return value;
  }
}

function eventTarget(event: LiveToolEvent): string | undefined {
  const input = event.input ?? {};
  const queryTarget = compact(input.query);
  if (queryTarget && !isSensitiveTarget(queryTarget)) return queryTarget;
  const urlTarget = compact(input.url);
  if (urlTarget && !isSensitiveTarget(urlTarget)) return compactUrl(urlTarget);
  const fileTarget = compact(input.path) ?? compact(input.file_path);
  if (fileTarget) return basenamePath(fileTarget);
  return undefined;
}

function isSensitiveTarget(value: string): boolean {
  return /(?:sk-[\w-]+|bearer\s+[a-z0-9._-]+|api[_-]?key|token|secret|credential|password|passwd)/i.test(
    value,
  );
}

function eventActionLabel(
  event: LiveToolEvent,
  t: ReturnType<typeof useI18n>["t"],
): string {
  const name = event.name.toLowerCase();
  if (
    name === "call_agent" ||
    name === "call_agent_parallel" ||
    name === "delegate_agent" ||
    name === "spawn_agent"
  ) {
    return t.messageGrouping.callTeammate;
  }
  if (name.includes("search") || name.includes("glob")) {
    return t.messageGrouping.searchSources;
  }
  if (
    name.includes("fetch") ||
    name.includes("browser") ||
    name.includes("web")
  ) {
    return t.messageGrouping.readWebpage;
  }
  if (name.includes("read") || name === "ls" || name === "list_cwd") {
    return t.messageGrouping.readFile;
  }
  if (
    name.includes("write") ||
    name.includes("edit") ||
    name.includes("replace") ||
    name.includes("patch")
  ) {
    return t.messageGrouping.updateFile;
  }
  return t.messageGrouping.runAction;
}

function eventSummary(
  event: LiveToolEvent | undefined,
  t: ReturnType<typeof useI18n>["t"],
): string | undefined {
  if (!event) return undefined;
  const label = eventActionLabel(event, t);
  const target = eventTarget(event);
  return target ? `${label}: ${target}` : label;
}

function latestRunningEvent(events: LiveToolEvent[]) {
  let latest: LiveToolEvent | undefined;
  let latestTimestamp = Number.NEGATIVE_INFINITY;
  for (const event of events) {
    if (event.status !== "running" && event.status !== "waiting_approval") {
      continue;
    }
    const timestamp = event.finishedAt ?? event.startedAt;
    // Preserve the stable-sort behaviour of the old implementation when two
    // events share a timestamp: the first event remains the selected one.
    if (!latest || timestamp > latestTimestamp) {
      latest = event;
      latestTimestamp = timestamp;
    }
  }
  return latest;
}

export function PublicThinkingStatus({
  isLoading,
  liveToolEvents,
  hasStreamingMessage,
  vitals,
  className,
  renderAnnouncement = true,
  renderVisual = true,
}: PublicThinkingStatusProps) {
  const { t } = useI18n();

  // An optimistic outbound message becomes visible before turn/started can
  // seed vitals. During that receipt gap ``isLoading`` is already true while
  // vitals are still idle; treat it as an honest first-response wait so the
  // assistant lane appears immediately after Send.
  const measuredPhase = vitals?.phase;
  const phase =
    measuredPhase && measuredPhase !== "idle"
      ? measuredPhase
      : hasStreamingMessage
        ? "streaming"
        : "waiting";
  const running = latestRunningEvent(liveToolEvents);
  const action = running ? eventSummary(running, t) : undefined;
  const firstResponseDelayed =
    phase === "waiting" &&
    (vitals?.elapsedMs ?? 0) >= FIRST_RESPONSE_DELAY_NOTICE_MS;
  // "思考中" (waitingForModel) is reserved for the genuinely pre-response
  // state of a fresh turn — nothing from the agent yet. Once the task is
  // underway the line must say what is happening (the running action, or a
  // neutral "processing" between rounds), not collapse every pause into
  // "thinking".
  const label =
    phase === "disconnected"
      ? t.publicThinkingStatus.reconnecting
      : phase === "slow"
        ? t.publicThinkingStatus.slowResponse
        : firstResponseDelayed
          ? t.publicThinkingStatus.firstResponseSlow
          : phase === "waiting"
            ? t.publicThinkingStatus.waitingForModel
            : (action ?? t.publicThinkingStatus.processing);
  // In the working phase the action already leads the line; only the
  // alert phases keep it as trailing context.
  const detail = phase === "working" ? undefined : action;
  const elapsed =
    !action && vitals && vitals.elapsedMs >= 3_000
      ? formatStreamElapsed(vitals.elapsedMs)
      : undefined;
  const activeAnnouncement =
    phase === "streaming"
      ? t.publicThinkingStatus.processing
      : detail
        ? `${label} · ${detail}`
        : label;
  const [announcement, setAnnouncement] = useState("");
  const previousIsLoadingRef = useRef(false);

  useEffect(() => {
    if (!renderAnnouncement) return;
    const wasLoading = previousIsLoadingRef.current;
    previousIsLoadingRef.current = isLoading;
    if (isLoading) {
      setAnnouncement(activeAnnouncement);
    } else if (wasLoading) {
      // `isLoading` also settles after a failure, cancellation or explicit
      // stop. Keep this announcement outcome-neutral; the adjacent receipt
      // carries the precise terminal status.
      setAnnouncement(t.publicThinkingStatus.runEnded);
    }
  }, [
    activeAnnouncement,
    isLoading,
    renderAnnouncement,
    t.publicThinkingStatus.runEnded,
  ]);

  return (
    <>
      {/* Keep exactly one stable live region for meaningful run-state changes.
          The visual timer below updates every second and is intentionally not
          part of this region, otherwise screen readers repeatedly announce it. */}
      {renderAnnouncement && (
        <span
          role="status"
          aria-live="polite"
          aria-atomic="true"
          className="sr-only"
          data-testid="conversation-activity-status"
        >
          {announcement}
        </span>
      )}
      {renderVisual && isLoading && phase !== "streaming" && (
        <span
          aria-hidden="true"
          data-phase={phase}
          data-first-response-delayed={firstResponseDelayed ? "true" : "false"}
          data-testid="conversation-activity-pulse"
          className={cn(
            "my-1.5 ml-11 flex min-w-0 items-center gap-1.5 text-xs leading-4 text-muted-foreground/55",
            className,
          )}
        >
          <span
            className={cn(
              "inline-block size-1 shrink-0 rounded-full animate-pulse",
              phase === "slow" || firstResponseDelayed
                ? "bg-warning/50"
                : phase === "disconnected"
                  ? "bg-destructive/50"
                  : "bg-muted-foreground/40",
            )}
          />
          <span className="shrink-0">{label}</span>
          {detail && (
            <span className="min-w-0 truncate text-muted-foreground/45">
              · {detail}
            </span>
          )}
          {elapsed && (
            <span
              className="shrink-0 tabular-nums text-muted-foreground/45"
              data-testid="conversation-activity-elapsed"
            >
              · {elapsed}
            </span>
          )}
        </span>
      )}
    </>
  );
}
