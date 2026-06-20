import {
  ActivityIcon,
  CoinsIcon,
  CpuIcon,
  Loader2Icon,
  RefreshCwIcon,
  WrenchIcon,
  ZapIcon,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { swallow } from "@/core/utils/log";
import { authHeaders } from "@/core/auth/api";
import { getBackendBaseURL } from "@/core/config";
import { useI18n } from "@/core/i18n/hooks";
import type { Message } from "@/core/api/types";
import { accumulateUsage, formatTokenCount } from "@/core/messages/usage";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ToolEvent {
  name: string;
  success: boolean;
  durationMs: number;
  timestamp: number;
}

interface MonitorStats {
  sessionTokens: {
    input: number;
    output: number;
    cacheRead: number;
    total: number;
  };
  sessionCost: number;
  turnCount: number;
  toolCalls: ToolEvent[];
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatCost(usd: number): string {
  if (usd < 0.001) return "$0.00";
  if (usd < 0.01) return `$${usd.toFixed(4)}`;
  if (usd < 1) return `$${usd.toFixed(3)}`;
  return `$${usd.toFixed(2)}`;
}

function extractMonitorStats(messages: Message[]): MonitorStats {
  // Reuse the shared usage accumulator instead of re-implementing
  const usage = accumulateUsage(messages);
  const stats: MonitorStats = {
    sessionTokens: {
      input: usage?.inputTokens ?? 0,
      output: usage?.outputTokens ?? 0,
      cacheRead: 0,
      total: usage?.totalTokens ?? 0,
    },
    sessionCost: 0,
    turnCount: 0,
    toolCalls: [],
  };

  for (const msg of messages) {
    if (msg.type === "ai") {
      // Count turns
      const u = (msg as unknown as Record<string, unknown>).usage_metadata;
      if (u) stats.turnCount++;

      // Track tool calls
      const toolCalls = (msg as unknown as Record<string, unknown>)
        .tool_calls as Array<{ name?: string }> | undefined;
      if (toolCalls && Array.isArray(toolCalls)) {
        for (const tc of toolCalls) {
          stats.toolCalls.push({
            name: tc.name ?? "unknown",
            success: true,
            durationMs: 0,
            timestamp: Date.now(),
          });
        }
      }
    }
  }

  // Estimate cost (rough pricing)
  const inputCostPer1M = 3.0; // default sonnet-like pricing
  const outputCostPer1M = 15.0;
  stats.sessionCost =
    (stats.sessionTokens.input / 1_000_000) * inputCostPer1M +
    (stats.sessionTokens.output / 1_000_000) * outputCostPer1M;

  return stats;
}

// ---------------------------------------------------------------------------
// Components
// ---------------------------------------------------------------------------

function StatCard({
  icon: Icon,
  label,
  value,
  sub,
  color = "text-muted-foreground",
}: {
  icon: React.ElementType;
  label: string;
  value: string;
  sub?: string;
  color?: string;
}) {
  return (
    <div className="flex items-start gap-2.5 rounded-lg border border-border/60 bg-card p-2.5 transition-shadow hover:shadow-sm">
      <div
        className={cn(
          "mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-lg bg-muted/50",
          color,
        )}
      >
        <Icon className="size-3.5" />
      </div>
      <div className="min-w-0">
        <div className="text-muted-foreground text-[10px]">{label}</div>
        <div className="text-foreground text-sm font-semibold leading-tight">
          {value}
        </div>
        {sub && (
          <div className="text-muted-foreground/70 text-[10px]">{sub}</div>
        )}
      </div>
    </div>
  );
}

function ToolCallList({
  tools,
  noToolCallsLabel,
}: {
  tools: ToolEvent[];
  noToolCallsLabel: string;
}) {
  // Aggregate by tool name
  const aggregated = useMemo(() => {
    const map: Record<string, { count: number; name: string }> = {};
    for (const t of tools) {
      if (!map[t.name]) {
        map[t.name] = { count: 0, name: t.name };
      }
      map[t.name]!.count++;
    }
    return Object.values(map).sort((a, b) => b.count - a.count);
  }, [tools]);

  if (aggregated.length === 0) {
    return (
      <div className="text-muted-foreground/50 py-3 text-center text-[10px]">
        {noToolCallsLabel}
      </div>
    );
  }

  return (
    <div className="space-y-0.5">
      {aggregated.slice(0, 10).map((t) => (
        <div
          key={t.name}
          className="flex items-center justify-between px-1 py-0.5 text-[11px]"
        >
          <span className="text-foreground/80 truncate font-mono">
            {t.name}
          </span>
          <span className="text-muted-foreground ml-2 shrink-0 tabular-nums">
            {t.count}x
          </span>
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main Panel
// ---------------------------------------------------------------------------

export function MonitorPanel({
  messages,
  className,
}: {
  messages: Message[];
  className?: string;
}) {
  const { t } = useI18n();
  const [telemetryConfig, setTelemetryConfig] = useState<Record<
    string,
    unknown
  > | null>(null);
  const [loading, setLoading] = useState(false);

  const stats = useMemo(() => extractMonitorStats(messages), [messages]);

  const fetchTelemetryConfig = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(`${getBackendBaseURL()}/api/telemetry/stats`, {
        headers: authHeaders(),
      });
      if (res.ok) {
        setTelemetryConfig(await res.json());
      }
    } catch (e) {
      swallow(e);
      // Backend may not have telemetry endpoint yet
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchTelemetryConfig();
  }, [fetchTelemetryConfig]);

  return (
    <div className={cn("flex flex-col gap-3 p-3", className)}>
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5">
          <div className="flex size-6 items-center justify-center rounded-lg bg-primary/10">
            <ActivityIcon className="text-primary size-3.5" />
          </div>
          <span className="text-xs font-semibold">{t.monitor.title}</span>
        </div>
        <button
          onClick={() => void fetchTelemetryConfig()}
          className="text-muted-foreground hover:text-foreground p-1 rounded-lg hover:bg-muted/60 transition-colors"
          title="Refresh"
        >
          {loading ? (
            <Loader2Icon className="size-3 animate-spin" />
          ) : (
            <RefreshCwIcon className="size-3" />
          )}
        </button>
      </div>

      {/* Stats Grid */}
      <div className="grid grid-cols-2 gap-1.5">
        <StatCard
          icon={ZapIcon}
          label={t.monitor.tokens}
          value={formatTokenCount(stats.sessionTokens.total)}
          sub={`${formatTokenCount(stats.sessionTokens.input)} in / ${formatTokenCount(stats.sessionTokens.output)} out`}
          color="text-blue-500"
        />
        <StatCard
          icon={CoinsIcon}
          label={t.monitor.estCost}
          value={formatCost(stats.sessionCost)}
          sub={`${stats.turnCount} ${t.monitor.turns}`}
          color="text-amber-500"
        />
        <StatCard
          icon={WrenchIcon}
          label={t.monitor.toolCalls}
          value={String(stats.toolCalls.length)}
          sub={`${new Set(stats.toolCalls.map((tc) => tc.name)).size} ${t.monitor.unique}`}
          color="text-green-500"
        />
        <StatCard
          icon={CpuIcon}
          label={t.monitor.cacheReads}
          value={formatTokenCount(stats.sessionTokens.cacheRead)}
          sub={t.monitor.tokensCached}
          color="text-purple-500"
        />
      </div>

      {/* Tool Call Breakdown */}
      <div>
        <div className="text-muted-foreground mb-1 text-[10px] font-medium uppercase tracking-wider">
          {t.monitor.toolUsage}
        </div>
        <div className="rounded-lg border">
          <ToolCallList
            tools={stats.toolCalls}
            noToolCallsLabel={t.monitor.noToolCalls}
          />
        </div>
      </div>

      {/* Telemetry Status */}
      {telemetryConfig && (
        <div>
          <div className="text-muted-foreground mb-1 text-[10px] font-medium uppercase tracking-wider">
            {t.monitor.telemetry}
          </div>
          <div className="space-y-0.5 rounded-lg border p-2 text-[11px]">
            <div className="flex items-center gap-1.5">
              <div
                className={cn(
                  "size-1.5 rounded-lg",
                  telemetryConfig.enabled
                    ? "bg-green-500"
                    : "bg-muted-foreground/30",
                )}
              />
              <span className="text-muted-foreground">
                {telemetryConfig.enabled
                  ? t.monitor.otelEnabled
                  : t.monitor.otelDisabled}
              </span>
            </div>
            {!!telemetryConfig.enabled && (
              <>
                <div className="text-muted-foreground/70 pl-3">
                  {t.monitor.metrics}:{" "}
                  {String(telemetryConfig.metrics_exporter)}
                </div>
                <div className="text-muted-foreground/70 pl-3">
                  {t.monitor.privacy}:{" "}
                  {telemetryConfig.redact_prompts
                    ? t.monitor.promptsRedacted
                    : t.monitor.promptsLogged}
                </div>
              </>
            )}
          </div>
        </div>
      )}

      {/* Token Breakdown Bar */}
      {stats.sessionTokens.total > 0 && (
        <div>
          <div className="text-muted-foreground mb-1 text-[10px] font-medium uppercase tracking-wider">
            {t.monitor.tokenDistribution}
          </div>
          <div className="flex h-2 overflow-hidden rounded-lg">
            <div
              className="bg-blue-500"
              style={{
                width: `${(stats.sessionTokens.input / stats.sessionTokens.total) * 100}%`,
              }}
              title={`Input: ${formatTokenCount(stats.sessionTokens.input)}`}
            />
            <div
              className="bg-amber-500"
              style={{
                width: `${(stats.sessionTokens.output / stats.sessionTokens.total) * 100}%`,
              }}
              title={`Output: ${formatTokenCount(stats.sessionTokens.output)}`}
            />
            {stats.sessionTokens.cacheRead > 0 && (
              <div
                className="bg-purple-400"
                style={{
                  width: `${(stats.sessionTokens.cacheRead / stats.sessionTokens.total) * 100}%`,
                }}
                title={`Cache: ${formatTokenCount(stats.sessionTokens.cacheRead)}`}
              />
            )}
          </div>
          <div className="text-muted-foreground/60 mt-0.5 flex gap-3 text-[9px]">
            <span className="flex items-center gap-0.5">
              <span className="inline-block size-1.5 rounded-lg bg-blue-500" />{" "}
              {t.monitor.inputLabel}
            </span>
            <span className="flex items-center gap-0.5">
              <span className="inline-block size-1.5 rounded-lg bg-amber-500" />{" "}
              {t.monitor.outputLabel}
            </span>
            {stats.sessionTokens.cacheRead > 0 && (
              <span className="flex items-center gap-0.5">
                <span className="inline-block size-1.5 rounded-lg bg-purple-400" />{" "}
                {t.monitor.cacheLabel}
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
