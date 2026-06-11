/* Implementation note. */
import { RefreshCcwIcon } from "lucide-react";
import { useEffect, useState } from "react";

import { usePreviewRefresh } from "@/core/observability/file-ops";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

interface Props {
  className?: string;
}

export function PreviewRefreshIndicator({ className }: Props) {
  const { t } = useI18n();
  const latest = usePreviewRefresh();
  const [flashKey, setFlashKey] = useState<number | null>(null);
  const [count, setCount] = useState(0);

  useEffect(() => {
    if (!latest) return;
    setFlashKey(Date.now());
    setCount((c) => c + 1);
  }, [latest]);

  if (!latest) return null;

  return (
    <button
      type="button"
      className={cn(
        "flex items-center gap-1 rounded-md px-2 py-1 text-[11px]",
        "text-muted-foreground hover:bg-muted/60 hover:text-foreground",
        "transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-ring/40",
        className,
      )}
      title={
        latest.reason
          ? t.activityIndicators.previewLastRefresh(latest.reason)
          : t.activityIndicators.previewWaitingForRefresh
      }
      data-testid="preview-refresh-indicator"
    >
      <RefreshCcwIcon
        key={flashKey ?? "idle"}
        className={cn(
          "size-3.5",
          flashKey !== null &&
            "animate-learn-pulse text-[color:var(--primary)]",
        )}
        onAnimationEnd={() => setFlashKey(null)}
      />
      <span>{t.activityIndicators.previewPrefix(count)}</span>
    </button>
  );
}
