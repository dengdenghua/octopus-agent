import { AlertCircleIcon } from "lucide-react";

import { cn } from "@/lib/utils";
import type { ErrorItem } from "@/core/realtime";
import { useI18n } from "@/core/i18n/hooks";

/**
 * Red-bordered error card.
 *
 * The `willRetry` flag tells the user whether the agent will keep
 * trying on its own or whether they need to intervene; we surface it
 * as a small footer hint so the message itself stays the headline.
 */
export function ErrorView({ item }: { item: ErrorItem }) {
  const { t } = useI18n();
  return (
    <div
      className={cn(
        "rounded-md border border-red-500/50 bg-red-500/5 p-3 text-sm",
      )}
      data-status={item.status}
    >
      <div className="flex items-start gap-2">
        <AlertCircleIcon className="mt-0.5 size-4 shrink-0 text-red-600 dark:text-red-400" />
        <div className="min-w-0 flex-1">
          <p className="text-[10px] font-semibold uppercase tracking-wider text-red-700 dark:text-red-400">
            {t.realtimeItems.error.label}
          </p>
          <p className="mt-0.5 whitespace-pre-wrap break-words text-sm text-foreground">
            {item.message}
          </p>
          <p className="mt-2 text-[11px] text-muted-foreground">
            {t.realtimeItems.error.willRetry}:{" "}
            {item.willRetry
              ? t.realtimeItems.error.yes
              : t.realtimeItems.error.no}
          </p>
        </div>
      </div>
    </div>
  );
}
