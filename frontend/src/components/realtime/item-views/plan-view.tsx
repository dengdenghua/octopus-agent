import { ListChecksIcon } from "lucide-react";

import { MessageResponse } from "@/components/ai-elements/message";
import { cn } from "@/lib/utils";
import type { PlanItem } from "@/core/realtime";
import { useI18n } from "@/core/i18n/hooks";

/**
 * Free-form plan / strategy block.
 *
 * The agent occasionally emits a high-level plan that's distinct from
 * the structured `todo-list` (which is checkbox state). We render it
 * as markdown — the agent often uses headings and bullets — with a
 * small chip in the corner to label it as a plan so it doesn't get
 * confused with regular agent messages.
 */
export function PlanView({ item }: { item: PlanItem }) {
  const { t } = useI18n();
  return (
    <div
      className={cn(
        "relative rounded-md border border-border/40 bg-muted/20 p-3 pt-8 text-sm",
      )}
      data-status={item.status}
    >
      <span
        className={cn(
          "absolute left-3 top-2 inline-flex items-center gap-1 rounded-full",
          "bg-primary/10 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider text-primary",
        )}
      >
        <ListChecksIcon className="size-3" />
        {t.realtimeItems.plan.label}
      </span>
      <div
        className={cn(
          "prose prose-sm max-w-none",
          "[&>*:first-child]:mt-0 [&>*:last-child]:mb-0",
        )}
      >
        <MessageResponse className="prose-sm">{item.text}</MessageResponse>
      </div>
    </div>
  );
}
