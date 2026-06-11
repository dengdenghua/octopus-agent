import { BrainCircuitIcon, CheckCircle2Icon, XCircleIcon } from "lucide-react";

import { cn } from "@/lib/utils";
import type { SubagentItem } from "@/core/realtime";

export function SubagentView({ item }: { item: SubagentItem }) {
  const failed = item.status === "failed" || !!item.error;
  const running = item.status === "inProgress";
  const label = item.codename || item.name || item.role || item.subagentId;
  return (
    <div
      className={cn(
        "rounded-md border p-3 text-xs",
        failed ? "border-red-500/40 bg-red-500/5" : "border-border/50 bg-muted/20",
      )}
      data-status={item.status}
    >
      <div className="flex items-center gap-2">
        <BrainCircuitIcon
          className={cn("size-4 shrink-0 text-sky-500", running && "animate-pulse")}
        />
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium">{label}</p>
          <p className="truncate text-[11px] text-muted-foreground">
            {item.role || "subagent"} · {item.status}
          </p>
        </div>
        {failed ? (
          <XCircleIcon className="size-4 shrink-0 text-red-500" />
        ) : !running ? (
          <CheckCircle2Icon className="size-4 shrink-0 text-emerald-500" />
        ) : null}
      </div>
      {item.summary && (
        <p className="mt-2 whitespace-pre-wrap text-sm text-foreground">{item.summary}</p>
      )}
      {item.error && (
        <p className="mt-2 rounded bg-red-500/10 px-2 py-1 font-mono text-[11px] text-red-700 dark:text-red-400">
          {item.error}
        </p>
      )}
      {item.filesTouched.length > 0 && (
        <p className="mt-2 truncate font-mono text-[11px] text-muted-foreground">
          {item.filesTouched.join(", ")}
        </p>
      )}
    </div>
  );
}
