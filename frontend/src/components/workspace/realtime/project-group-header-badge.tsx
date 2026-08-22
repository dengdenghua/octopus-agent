import { FolderKanbanIcon, UsersIcon } from "lucide-react";

import { cn } from "@/lib/utils";

const PROJECT_STATUS_LABELS: Record<string, string> = {
  planning: "筹备中",
  running: "进行中",
  blocked: "有风险",
  done: "已完成",
  failed: "异常",
};

const PROJECT_STATUS_DOT: Record<string, string> = {
  planning: "bg-amber-500",
  running: "bg-emerald-500",
  blocked: "bg-amber-500",
  done: "bg-sky-500",
  failed: "bg-destructive",
};

export function ProjectGroupHeaderBadge({
  name,
  status,
  memberCount,
}: {
  name: string;
  status: string;
  memberCount: number;
}) {
  const safeName = name.trim() || "项目群";
  const safeStatus = status.trim().toLowerCase();
  const statusLabel = PROJECT_STATUS_LABELS[safeStatus] || "项目群";
  const count = Math.max(1, Math.floor(memberCount));

  return (
    <div
      aria-label={`${safeName} · ${statusLabel} · ${count} 位成员`}
      className="flex min-w-0 max-w-[min(30rem,48vw)] shrink-0 items-center gap-2"
    >
      <span className="flex size-8 shrink-0 items-center justify-center rounded-xl border border-primary/15 bg-primary/10 text-primary shadow-[var(--shadow-xs)]">
        <FolderKanbanIcon className="size-4" aria-hidden="true" />
      </span>
      <span className="min-w-0 leading-none">
        <span className="block truncate text-sm font-semibold text-foreground">
          {safeName}
        </span>
        <span className="mt-1 flex items-center gap-1.5 text-[10px] leading-none text-muted-foreground">
          <span
            className={cn(
              "size-1.5 shrink-0 rounded-full",
              PROJECT_STATUS_DOT[safeStatus] || "bg-muted-foreground/55",
            )}
            aria-hidden="true"
          />
          <span>{statusLabel}</span>
          <span aria-hidden="true">·</span>
          <UsersIcon className="size-3" aria-hidden="true" />
          <span>{count} 位成员</span>
        </span>
      </span>
    </div>
  );
}
