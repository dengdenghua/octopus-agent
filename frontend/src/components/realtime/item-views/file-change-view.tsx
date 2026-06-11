import { useState } from "react";
import {
  ChevronDownIcon,
  ChevronRightIcon,
  FileIcon,
  FilePenIcon,
  FilePlus2Icon,
  FileXIcon,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { FileChange, FileChangeItem, FileHunk } from "@/core/realtime";
import { useI18n } from "@/core/i18n/hooks";

/**
 * Per-hunk decision callback. The page wires this up to the
 * `decideHunk` action on the realtime hook; we keep the signature
 * `(hunkId, path, decision, diff?) => void` so the caller can pass
 * `(hunkId, path, decision, diff) => onDecideHunk({ turnId, itemId, ... })`
 * as a thin closure.
 */
export type DecideHunkFn = (
  hunkId: string,
  path: string,
  decision: "accepted" | "rejected",
  diff?: string,
) => void;

export function FileChangeView({
  item,
  onDecide,
}: {
  item: FileChangeItem;
  onDecide: DecideHunkFn;
}) {
  const { t } = useI18n();
  return (
    <div
      className={cn(
        "rounded-md border border-border/50 bg-muted/20 p-3",
      )}
      data-status={item.status}
    >
      <div className="mb-2 flex items-center gap-1.5 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
        <FileIcon className="size-3" />
        {t.realtimeItems.fileChange.title(item.changes.length)}
      </div>
      <div className="flex flex-col gap-2">
        {item.changes.map((change, idx) => (
          <FileChangeGroup
            key={`${change.path}-${idx}`}
            change={change}
            onDecide={onDecide}
          />
        ))}
      </div>
    </div>
  );
}

function FileChangeGroup({
  change,
  onDecide,
}: {
  change: FileChange;
  onDecide: DecideHunkFn;
}) {
  const { t } = useI18n();
  const [open, setOpen] = useState(true);
  const hunks = change.hunks ?? [];
  const OpIcon =
    change.op === "create"
      ? FilePlus2Icon
      : change.op === "delete"
        ? FileXIcon
        : FilePenIcon;
  const opColor =
    change.op === "create"
      ? "text-emerald-600 dark:text-emerald-400"
      : change.op === "delete"
        ? "text-red-600 dark:text-red-400"
        : "text-amber-600 dark:text-amber-400";
  return (
    <div className="rounded border border-border/40 bg-background/60">
      <button
        type="button"
        onClick={() => setOpen(prev => !prev)}
        className="flex w-full items-center gap-2 px-2 py-1.5 text-left transition-colors hover:bg-muted/40"
        aria-expanded={open}
      >
        {open ? (
          <ChevronDownIcon className="size-3.5 shrink-0 text-muted-foreground" />
        ) : (
          <ChevronRightIcon className="size-3.5 shrink-0 text-muted-foreground" />
        )}
        <OpIcon className={cn("size-3.5 shrink-0", opColor)} />
        <span className={cn("text-[10px] font-semibold uppercase tracking-wider", opColor)}>
          {t.realtimeItems.fileChange.operations[change.op]}
        </span>
        <code className="min-w-0 flex-1 truncate font-mono text-xs text-foreground">
          {change.path}
        </code>
        {hunks.length > 0 && (
          <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
            {t.realtimeItems.fileChange.hunkCount(hunks.length)}
          </span>
        )}
      </button>
      {open && (
        <div className="border-t border-border/40 p-2">
          {hunks.length === 0 ? (
            change.diff ? (
              <DiffPre diff={change.diff} />
            ) : (
              <p className="px-1 py-0.5 text-xs text-muted-foreground italic">
                {t.realtimeItems.fileChange.noDiff}
              </p>
            )
          ) : (
            <div className="flex flex-col gap-2">
              {hunks.map(hunk => (
                <HunkView
                  key={hunk.id}
                  hunk={hunk}
                  path={change.path}
                  wholeFileDiff={change.diff ?? null}
                  onDecide={onDecide}
                />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function HunkView({
  hunk,
  path,
  wholeFileDiff,
  onDecide,
}: {
  hunk: FileHunk;
  path: string;
  wholeFileDiff: string | null;
  onDecide: DecideHunkFn;
}) {
  const { t } = useI18n();
  const diffForRevert = singleHunkDiff(path, hunk, wholeFileDiff);
  const header = `@@ -${hunk.oldStart},${hunk.oldLines} +${hunk.newStart},${hunk.newLines} @@`;
  const bodyLines = hunk.body.split(/\r?\n/);
  return (
    <div
      className="overflow-hidden rounded border border-border/40 bg-card/60 text-xs"
      data-hunk-decision={hunk.decision}
    >
      <div className="flex items-center justify-between gap-2 border-b border-border/40 bg-muted/30 px-2 py-1">
        <span className="font-mono text-[11px] text-muted-foreground">
          {header}
        </span>
        <div className="flex items-center gap-2">
          <DecisionBadge decision={hunk.decision} />
          {hunk.decision === "pending" && (
            <>
              <Button
                size="sm"
                variant="default"
                className="h-6 px-2 text-[11px]"
                onClick={() => onDecide(hunk.id, path, "accepted")}
              >
                {t.realtimeItems.fileChange.accept}
              </Button>
              <Button
                size="sm"
                variant="outline"
                className="h-6 px-2 text-[11px]"
                onClick={() => onDecide(hunk.id, path, "rejected", diffForRevert)}
              >
                {t.realtimeItems.fileChange.reject}
              </Button>
            </>
          )}
        </div>
      </div>
      <pre className="overflow-x-auto font-mono text-[11px] leading-snug">
        {bodyLines.map((line, idx) =>
          line ? (
            <div key={idx} className={cn("px-2", toneForLine(line))}>
              {line}
            </div>
          ) : null,
        )}
      </pre>
    </div>
  );
}

function DecisionBadge({
  decision,
}: {
  decision: FileHunk["decision"];
}) {
  const { t } = useI18n();
  const cls =
    decision === "accepted"
      ? "bg-emerald-500/15 text-emerald-700 dark:text-emerald-400"
      : decision === "rejected"
        ? "bg-red-500/15 text-red-700 dark:text-red-400"
        : "bg-muted text-muted-foreground";
  return (
    <span
      className={cn(
        "rounded px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide",
        cls,
      )}
    >
      {t.realtimeItems.fileChange.decisions[decision]}
    </span>
  );
}

function DiffPre({ diff }: { diff: string }) {
  const lines = diff.split(/\r?\n/);
  return (
    <pre className="overflow-x-auto font-mono text-[11px] leading-snug">
      {lines.map((line, idx) =>
        line ? (
          <div key={idx} className={cn("px-2", toneForLine(line))}>
            {line}
          </div>
        ) : null,
      )}
    </pre>
  );
}

function toneForLine(line: string): string {
  if (line.startsWith("+++") || line.startsWith("---") || line.startsWith("@@")) {
    return "text-muted-foreground";
  }
  if (line.startsWith("+")) return "bg-emerald-500/10 text-emerald-700 dark:text-emerald-400";
  if (line.startsWith("-")) return "bg-red-500/10 text-red-700 dark:text-red-400";
  return "text-foreground/80";
}

/**
 * Build a minimal unified-diff containing only the target hunk so the
 * server can reverse-apply just this one without touching its
 * siblings. We prefer the whole-file diff when supplied (server echoes
 * it alongside the hunks); otherwise synthesize one from the hunk body.
 *
 * Copied verbatim from the original page.tsx — keeping the same
 * shape so the round-trip semantics are identical.
 */
export function singleHunkDiff(
  path: string,
  hunk: FileHunk,
  _wholeFileDiff: string | null,
): string {
  const header = `@@ -${hunk.oldStart},${hunk.oldLines} +${hunk.newStart},${hunk.newLines} @@`;
  const body = hunk.body.endsWith("\n") ? hunk.body : hunk.body + "\n";
  return `--- a/${path}\n+++ b/${path}\n${header}\n${body}`;
}
