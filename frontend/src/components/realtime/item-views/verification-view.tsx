import {
  CheckCircle2Icon,
  FileCode2Icon,
  FlaskConicalIcon,
  GitCompareIcon,
  XCircleIcon,
} from "lucide-react";

import { cn } from "@/lib/utils";
import type { VerificationItem } from "@/core/realtime";
import { useI18n } from "@/core/i18n/hooks";

export function VerificationView({ item }: { item: VerificationItem }) {
  const { t } = useI18n();
  const failed = item.status === "failed" || (item.exitCode ?? 0) !== 0;
  const running = item.status === "inProgress";
  const stateLabel = running
    ? t.realtimeItems.verification.running
    : failed
      ? t.realtimeItems.verification.failed
      : t.realtimeItems.verification.passed;
  const stateClass = failed
    ? "border-red-500/30 bg-red-500/10 text-red-700 dark:text-red-300"
    : running
      ? "border-violet-500/30 bg-violet-500/10 text-violet-700 dark:text-violet-300"
      : "border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300";
  return (
    <div
      className={cn(
        "rounded-md border p-3 text-xs",
        failed ? "border-red-500/40 bg-red-500/5" : "border-border/50 bg-muted/20",
      )}
      data-status={item.status}
    >
      <div className="flex items-center gap-2">
        <FlaskConicalIcon
          className={cn("size-4 shrink-0 text-violet-500", running && "animate-pulse")}
        />
        <span className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
          {t.realtimeItems.verification.title}
        </span>
        <code className="min-w-0 flex-1 truncate font-mono text-[11px]">
          {item.command}
        </code>
        <span
          className={cn(
            "inline-flex h-5 shrink-0 items-center rounded border px-1.5 text-[10px] font-medium uppercase tracking-wide",
            stateClass,
          )}
        >
          {stateLabel}
        </span>
        {failed ? (
          <XCircleIcon className="size-4 shrink-0 text-red-500" />
        ) : !running ? (
          <CheckCircle2Icon className="size-4 shrink-0 text-emerald-500" />
        ) : null}
      </div>
      <p className="mt-1 flex flex-wrap items-center gap-1.5 text-[11px] text-muted-foreground">
        {item.kind}
        {item.exitCode !== null ? (
          <span>{t.realtimeItems.verification.exitCode(item.exitCode)}</span>
        ) : null}
      </p>
      {(item.relatedFiles.length > 0 || item.relatedChangeItemIds.length > 0) && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {item.relatedFiles.length > 0 && (
            <span className="inline-flex max-w-full items-center gap-1 rounded border border-border/50 bg-background/70 px-1.5 py-0.5 text-[10px] text-muted-foreground">
              <FileCode2Icon className="size-3 shrink-0" />
              <span>{t.realtimeItems.verification.relatedFiles(item.relatedFiles.length)}</span>
            </span>
          )}
          {item.relatedChangeItemIds.length > 0 && (
            <span className="inline-flex max-w-full items-center gap-1 rounded border border-border/50 bg-background/70 px-1.5 py-0.5 text-[10px] text-muted-foreground">
              <GitCompareIcon className="size-3 shrink-0" />
              <span>{t.realtimeItems.verification.relatedChanges(item.relatedChangeItemIds.length)}</span>
            </span>
          )}
        </div>
      )}
      {item.relatedFiles.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1">
          {item.relatedFiles.slice(0, 8).map(file => (
            <code
              key={file}
              className="max-w-full truncate rounded bg-background/70 px-1.5 py-0.5 font-mono text-[10px] text-foreground/80"
              title={file}
            >
              {file}
            </code>
          ))}
        </div>
      )}
      {item.summary && (
        <p className="mt-2 whitespace-pre-wrap text-sm text-foreground">{item.summary}</p>
      )}
      {(item.stdoutTail || item.stderrTail) && (
        <pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap rounded bg-background/60 p-2 font-mono text-[10px] leading-snug">
          {[item.stdoutTail, item.stderrTail].filter(Boolean).join("\n")}
        </pre>
      )}
    </div>
  );
}
