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

  return (
    <div
      aria-live="polite"
      aria-label={`${statusLabel} ${elapsedSeconds}s`}
      className={cn(
        "inline-flex h-7 shrink-0 items-center gap-1.5 rounded-full border border-primary/20 bg-primary/5 px-2.5 text-xs text-primary/85",
        className,
      )}
      data-testid="run-duration-badge"
      role="status"
    >
      <span
        aria-hidden="true"
        className={cn(
          "size-1.5 rounded-full",
          phase === "slow"
            ? "bg-warning"
            : phase === "disconnected"
              ? "bg-destructive"
              : "animate-pulse bg-primary",
        )}
      />
      <span className="max-w-24 truncate">{statusLabel}</span>
      <span className="tabular-nums text-primary/65">{elapsedSeconds}s</span>
    </div>
  );
}
