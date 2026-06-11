import { ShieldCheckIcon } from "lucide-react";

import { cn } from "@/lib/utils";
import type { ApprovalItem } from "@/core/realtime";

export function ApprovalView({ item }: { item: ApprovalItem }) {
  return (
    <div
      className={cn(
        "rounded-md border border-amber-500/40 bg-amber-500/5 p-3 text-xs",
      )}
      data-status={item.status}
      data-decision={item.decision}
    >
      <div className="flex items-center gap-2">
        <ShieldCheckIcon className="size-4 shrink-0 text-amber-500" />
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium">{item.method}</p>
          <p className="text-[11px] text-muted-foreground">
            approval {item.decision}
          </p>
        </div>
      </div>
      {Object.keys(item.params).length > 0 && (
        <pre className="mt-2 max-h-40 overflow-auto whitespace-pre-wrap rounded bg-background/60 p-2 font-mono text-[10px] leading-snug">
          {JSON.stringify(item.params, null, 2)}
        </pre>
      )}
    </div>
  );
}
