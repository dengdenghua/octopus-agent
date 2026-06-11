import { Loader2Icon, TerminalIcon } from "lucide-react";

import { cn } from "@/lib/utils";
import type { CommandExecutionItem } from "@/core/realtime";
import { useI18n } from "@/core/i18n/hooks";

/**
 * Terminal-style card for shell command execution.
 *
 * Header: monospace prompt with the command, plus an exit-code badge
 *   - green for 0
 *   - red for non-zero
 *   - amber with spinner while running (exitCode null + status inProgress)
 *
 * Body: `aggregatedOutput` in a bounded, scroll-y pre so a 10k-line
 * log doesn't blow out the page layout. While still running we show
 * a small Loader2 spinner next to the command as a second in-progress
 * signal next to the amber badge.
 */
export function CommandExecutionView({ item }: { item: CommandExecutionItem }) {
  const { t } = useI18n();
  const running = item.status === "inProgress" && item.exitCode == null;
  return (
    <div
      className={cn(
        "overflow-hidden rounded-md border border-border/50 bg-zinc-950 text-xs text-zinc-100",
      )}
      data-status={item.status}
    >
      <div className="flex items-center justify-between gap-2 border-b border-zinc-800 px-3 py-1.5">
        <div className="flex min-w-0 items-center gap-2">
          <TerminalIcon className="size-3.5 shrink-0 text-zinc-400" />
          <code className="min-w-0 truncate font-mono text-zinc-200">
            {item.command}
          </code>
          {running && (
            <Loader2Icon className="size-3.5 shrink-0 animate-spin text-amber-400" />
          )}
        </div>
        <ExitBadge exitCode={item.exitCode} running={running} />
      </div>
      {item.cwd && (
        <div className="border-b border-zinc-800/60 bg-zinc-900/40 px-3 py-1 font-mono text-[10px] text-zinc-500">
          {t.realtimeItems.command.cwd}: {item.cwd}
        </div>
      )}
      {item.aggregatedOutput ? (
        <pre
          className={cn(
            "max-h-96 overflow-auto whitespace-pre-wrap break-words",
            "px-3 py-2 font-mono text-[11px] leading-snug text-zinc-200",
          )}
        >
          {item.aggregatedOutput}
        </pre>
      ) : running ? (
        <div className="px-3 py-2 font-mono text-[11px] italic text-zinc-500">
          {t.realtimeItems.command.waitingOutput}
        </div>
      ) : null}
    </div>
  );
}

function ExitBadge({
  exitCode,
  running,
}: {
  exitCode: number | null;
  running: boolean;
}) {
  const { t } = useI18n();
  if (running) {
    return (
      <span className="rounded bg-amber-500/20 px-1.5 py-0.5 font-mono text-[10px] font-medium text-amber-300">
        {t.realtimeItems.command.running}
      </span>
    );
  }
  if (exitCode == null) {
    return (
      <span className="rounded bg-zinc-800 px-1.5 py-0.5 font-mono text-[10px] font-medium text-zinc-400">
        —
      </span>
    );
  }
  const ok = exitCode === 0;
  return (
    <span
      className={cn(
        "rounded px-1.5 py-0.5 font-mono text-[10px] font-medium",
        ok
          ? "bg-emerald-500/20 text-emerald-300"
          : "bg-red-500/20 text-red-300",
      )}
    >
      {t.realtimeItems.command.exitCode(exitCode)}
    </span>
  );
}
