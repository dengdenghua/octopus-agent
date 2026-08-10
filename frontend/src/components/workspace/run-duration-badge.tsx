import { useI18n } from "@/core/i18n/hooks";
import type { StreamVitals } from "@/core/realtime";
import { cn } from "@/lib/utils";

export function RunDurationBadge({
  isLoading,
  vitals,
  className,
}: {
  isLoading: boolean;
  vitals?: StreamVitals;
  className?: string;
}) {
  const { t } = useI18n();

  if (!isLoading) return null;

  const phase = vitals?.phase;
  const statusLabel =
    phase === "disconnected"
      ? t.publicThinkingStatus.reconnecting
      : phase === "slow"
        ? t.publicThinkingStatus.slowResponse
        : phase === "waiting"
          ? t.publicThinkingStatus.waitingForModel
          : t.publicThinkingStatus.processing;
  const elapsedSeconds = Math.floor((vitals?.elapsedMs ?? 0) / 1000);
  // Time-to-first-token: rendered once the first token has arrived, so the
  // user sees the model's response latency for this turn at a glance.
  const ttftSeconds =
    vitals?.ttftMs != null && vitals.ttftMs >= 0
      ? vitals.ttftMs / 1000
      : null;

  // Tone follows the run state machine (red = disconnected, yellow = slow,
  // green = working/waiting) instead of a fixed accent colour.
  const tone =
    phase === "disconnected"
      ? "text-destructive"
      : phase === "slow"
        ? "text-warning"
        : "text-success";
  const dot =
    phase === "disconnected"
      ? "bg-destructive"
      : phase === "slow"
        ? "bg-warning"
        : "bg-success";

  return (
    <div
      aria-live="polite"
      aria-label={`${statusLabel} ${elapsedSeconds}s`}
      className={cn(
        "inline-flex shrink-0 items-center gap-1.5 text-xs",
        tone,
        className,
      )}
      data-testid="run-duration-badge"
      role="status"
    >
      <span aria-hidden="true" className={cn("size-1.5 rounded-full", dot)} />
      <span className="max-w-24 truncate">{statusLabel}</span>
      <span className="tabular-nums opacity-70">{elapsedSeconds}s</span>
      {ttftSeconds != null && (
        <span
          className="tabular-nums opacity-70"
          title={t.publicThinkingStatus.ttftHint}
          data-testid="ttft-badge"
        >
          {t.publicThinkingStatus.ttftLabel} {ttftSeconds.toFixed(1)}s
        </span>
      )}
    </div>
  );
}
