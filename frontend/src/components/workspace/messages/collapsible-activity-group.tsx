import {
  BrainIcon,
  CheckCircle2Icon,
  ChevronDownIcon,
  ClipboardListIcon,
  Loader2Icon,
  PencilLineIcon,
  WrenchIcon,
  XCircleIcon,
  type LucideIcon,
} from "lucide-react";
import { useMemo, useState } from "react";

import { cn } from "@/lib/utils";

export type ActivityKind = "think" | "plan" | "file_ops" | "tool_calls";

export interface ActivityItem {
  id: string;
  label: string;
  detail?: string;
  status?: "done" | "running" | "error";
  meta?: Record<string, unknown>;
}

interface Props {
  kind: ActivityKind;
  items: ActivityItem[];
  isRunning?: boolean;
  defaultOpen?: boolean;
  className?: string;
}

// -------------------------------------------------------------------------
// Meta helpers
// -------------------------------------------------------------------------

const KIND_ICON: Record<ActivityKind, LucideIcon> = {
  think: BrainIcon,
  plan: ClipboardListIcon,
  file_ops: PencilLineIcon,
  tool_calls: WrenchIcon,
};

function readNumberMeta(
  meta: Record<string, unknown> | undefined,
  key: string,
): number {
  if (!meta) return 0;
  const value = meta[key];
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string") {
    const parsed = Number.parseInt(value, 10);
    if (Number.isFinite(parsed)) return parsed;
  }
  return 0;
}

function sumMeta(items: ActivityItem[], key: string): number {
  let total = 0;
  for (const item of items) {
    total += readNumberMeta(item.meta, key);
  }
  return total;
}

/**
 * Build the folded-header summary text for this activity kind.
 * Returns null when the group should not be rendered at all (e.g. empty think).
 */
export function buildHeaderSummary(
  kind: ActivityKind,
  items: ActivityItem[],
): string | null {
  if (kind === "think") {
    if (items.length === 0) return null;
    const totalSeconds = Math.max(
      1,
      Math.round(sumMeta(items, "duration_seconds")),
    );
    return `🧠 思考 ${totalSeconds} 秒`;
  }
  if (kind === "plan") {
    return `📋 规划 ${items.length} 步`;
  }
  if (kind === "file_ops") {
    const added = sumMeta(items, "lines_added");
    const removed = sumMeta(items, "lines_removed");
    if (added === 0 && removed === 0) {
      return `✏️ 操作文件 ${items.length} 次`;
    }
    return `✏️ 操作文件 ${items.length} 次 (+${added} / -${removed})`;
  }
  // tool_calls
  return `🔧 工具调用 ${items.length} 次`;
}

// -------------------------------------------------------------------------
// Component
// -------------------------------------------------------------------------

function StatusIcon({ status }: { status?: ActivityItem["status"] }) {
  if (status === "running")
    return (
      <Loader2Icon className="size-3.5 animate-spin text-muted-foreground" />
    );
  if (status === "error")
    return <XCircleIcon className="size-3.5 text-red-500" />;
  if (status === "done")
    return (
      <CheckCircle2Icon className="size-3.5 text-green-500 dark:text-green-400" />
    );
  return <span className="size-3.5" />;
}

export function CollapsibleActivityGroup({
  kind,
  items,
  isRunning = false,
  defaultOpen = false,
  className,
}: Props) {
  const [open, setOpen] = useState(defaultOpen);

  const header = useMemo(() => buildHeaderSummary(kind, items), [kind, items]);
  const KindIcon = KIND_ICON[kind];
  const latest = items[items.length - 1];

  if (header === null) {
    return null;
  }

  return (
    <div
      className={cn(
        "w-full rounded-lg border border-border bg-muted/30",
        className,
      )}
    >
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={cn(
          "flex w-full items-center gap-2 px-3 py-2 text-left text-sm",
          "hover:bg-muted/50 transition-colors rounded-lg",
          "cursor-pointer",
        )}
        aria-expanded={open}
      >
        {isRunning ? (
          <Loader2Icon className="size-4 shrink-0 animate-spin text-muted-foreground" />
        ) : (
          <KindIcon className="size-4 shrink-0 text-muted-foreground" />
        )}
        <span className="font-medium text-foreground">{header}</span>
        {isRunning && latest && (
          <span className="ml-auto max-w-[360px] truncate text-xs text-muted-foreground">
            {latest.label}
          </span>
        )}
        <ChevronDownIcon
          className={cn(
            "ml-auto size-4 shrink-0 text-muted-foreground transition-transform",
            open ? "rotate-180" : "",
            isRunning && latest ? "ml-2" : "",
          )}
        />
      </button>
      {open && (
        <ul className="flex flex-col gap-1 border-t border-border px-3 py-2">
          {items.map((item) => (
            <li
              key={item.id}
              className="flex items-start gap-2 rounded py-1 text-sm"
            >
              <span className="mt-0.5 shrink-0">
                {item.status === "running" ? (
                  <Loader2Icon className="size-3.5 animate-spin text-muted-foreground" />
                ) : (
                  <StatusIcon status={item.status} />
                )}
              </span>
              <div className="flex min-w-0 flex-1 flex-col">
                <span
                  className={cn(
                    "truncate",
                    item.status === "error"
                      ? "text-red-500"
                      : "text-foreground",
                  )}
                >
                  {item.label}
                </span>
                {item.detail && (
                  <span className="mt-0.5 truncate text-xs text-muted-foreground">
                    {item.detail}
                  </span>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
