/**
 * Live up/down light for the local database (octopus-storage / File Agent).
 *
 * Reads the agent's heartbeat-backed `/api/storage/status`. Self-contained copy
 * (not the shared i18n bundle) to stay decoupled from concurrently-edited locale
 * files; falls back to English outside zh.
 */
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

import { useStorageStatus } from "@/core/storage/use-storage-status";

const LABELS = {
  zh: { up: "本地数据库已连接", down: "本地数据库未连接", checking: "检测本地数据库…" },
  en: { up: "Local database connected", down: "Local database offline", checking: "Checking local database…" },
};

export function StorageStatusDot({ className }: { className?: string }) {
  const { locale } = useI18n();
  const { status, isLoading } = useStorageStatus();
  const t = (locale || "en").slice(0, 2).toLowerCase() === "zh" ? LABELS.zh : LABELS.en;

  const state = isLoading && !status ? "checking" : status?.up ? "up" : "down";
  const label = t[state];
  const tone =
    state === "up"
      ? "bg-emerald-500"
      : state === "down"
        ? "bg-red-500"
        : "bg-muted-foreground/50 animate-pulse";

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 text-[11px] text-muted-foreground",
        className,
      )}
      title={label}
    >
      <span className={cn("size-2 shrink-0 rounded-full", tone)} aria-hidden="true" />
      <span className="truncate">{label}</span>
    </span>
  );
}
