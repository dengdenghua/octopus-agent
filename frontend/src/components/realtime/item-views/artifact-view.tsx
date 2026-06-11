import { FileIcon } from "lucide-react";

import { cn } from "@/lib/utils";
import type { ArtifactItem } from "@/core/realtime";

export function ArtifactView({ item }: { item: ArtifactItem }) {
  const failed = item.renderStatus === "failed" || item.validationStatus === "failed";
  return (
    <div
      className={cn(
        "rounded-md border p-3 text-xs",
        failed ? "border-red-500/40 bg-red-500/5" : "border-border/50 bg-muted/20",
      )}
      data-status={item.status}
    >
      <div className="flex items-center gap-2">
        <FileIcon className="size-4 shrink-0 text-cyan-500" />
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium">{item.title || item.path}</p>
          <p className="truncate font-mono text-[11px] text-muted-foreground">
            {item.kind} / {item.renderStatus} / {item.validationStatus}
          </p>
        </div>
      </div>
      <code className="mt-2 block truncate font-mono text-[11px] text-muted-foreground">
        {item.path}
      </code>
    </div>
  );
}
