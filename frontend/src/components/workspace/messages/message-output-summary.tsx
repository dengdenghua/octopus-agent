import type { AIMessage, Message, ToolCall } from "@/core/api/types";
import type { FileHunk } from "@/core/realtime";
import { singleHunkDiff } from "@/components/realtime/item-views/file-change-view";
import { artifactDisplayPath } from "@/core/artifacts/utils";
import { getBackendBaseURL } from "@/core/config";
import { useI18n } from "@/core/i18n/hooks";
import { swallow } from "@/core/utils/log";
import {
  getFileExtensionDisplayName,
  getFileIcon,
  getFileName,
} from "@/core/utils/files";
import { cn } from "@/lib/utils";
import {
  CheckCircle2Icon,
  ChevronDownIcon,
  DownloadIcon,
  ExternalLinkIcon,
  FileCheck2Icon,
  FilePlus2Icon,
  Loader2Icon,
  RotateCcwIcon,
  UserCheckIcon,
} from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";

import { useArtifacts } from "../artifacts";

type OutputArtifact = {
  path: string;
  title?: string | null;
  kind?: string | null;
};

type OutputChange = {
  created: boolean;
  diff?: string;
  diffTruncated: boolean;
  path: string;
  op?: string | null;
  added: number;
  removed: number;
  hunks: FileHunk[];
};

type OutputSummary = {
  artifacts: OutputArtifact[];
  changes: OutputChange[];
};

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object"
    ? (value as Record<string, unknown>)
    : null;
}

function diffCounts(diff: unknown): { added: number; removed: number } {
  if (typeof diff !== "string" || diff.length === 0) {
    return { added: 0, removed: 0 };
  }
  let added = 0;
  let removed = 0;
  for (const line of diff.split(/\r?\n/)) {
    if (line.startsWith("+++") || line.startsWith("---")) continue;
    if (line.startsWith("+")) added += 1;
    else if (line.startsWith("-")) removed += 1;
  }
  return { added, removed };
}

function isCreatedFileChange(
  op: string | null,
  diff: unknown,
  counts: { added: number; removed: number },
) {
  const normalizedOp = op?.toLowerCase() ?? null;
  if (
    normalizedOp &&
    [
      "add",
      "added",
      "create",
      "created",
      "generate",
      "generated",
      "new",
    ].includes(normalizedOp)
  ) {
    return true;
  }
  if (typeof diff === "string") {
    return (
      /^---\s+\/dev\/null/m.test(diff) ||
      /^new file mode\b/m.test(diff) ||
      /^@@\s+-0,0\s+\+\d+(?:,\d+)?\s+@@/m.test(diff)
    );
  }
  return !normalizedOp && counts.added > 0 && counts.removed === 0;
}

function artifactFromToolCall(toolCall: ToolCall): OutputArtifact | null {
  if (toolCall.name !== "artifact") return null;
  const path = toolCall.args.path;
  if (typeof path !== "string" || !path.trim()) return null;
  return {
    path,
    title: typeof toolCall.args.title === "string" ? toolCall.args.title : null,
    kind: typeof toolCall.args.kind === "string" ? toolCall.args.kind : null,
  };
}

function hunksFromChange(change: Record<string, unknown>): FileHunk[] {
  if (!Array.isArray(change.hunks)) return [];
  const out: FileHunk[] = [];
  for (const raw of change.hunks) {
    const hunk = asRecord(raw);
    if (!hunk) continue;
    if (typeof hunk.id !== "string" || typeof hunk.body !== "string") continue;
    out.push({
      id: hunk.id,
      oldStart: typeof hunk.oldStart === "number" ? hunk.oldStart : 0,
      oldLines: typeof hunk.oldLines === "number" ? hunk.oldLines : 0,
      newStart: typeof hunk.newStart === "number" ? hunk.newStart : 0,
      newLines: typeof hunk.newLines === "number" ? hunk.newLines : 0,
      body: hunk.body,
      decision:
        hunk.decision === "accepted" || hunk.decision === "rejected"
          ? hunk.decision
          : "pending",
    });
  }
  return out;
}

function changesFromToolCall(toolCall: ToolCall): OutputChange[] {
  if (
    toolCall.name !== "file_change" ||
    !Array.isArray(toolCall.args.changes)
  ) {
    return [];
  }
  const out: OutputChange[] = [];
  for (const raw of toolCall.args.changes) {
    const change = asRecord(raw);
    if (!change) continue;
    const path = change?.path;
    if (typeof path !== "string" || !path.trim()) continue;
    const op = typeof change.op === "string" ? change.op : null;
    const counts = diffCounts(change.diff);
    out.push({
      created: isCreatedFileChange(op, change.diff, counts),
      diff: typeof change.diff === "string" ? change.diff : undefined,
      diffTruncated: change.diffTruncated === true,
      path,
      op,
      added: counts.added,
      removed: counts.removed,
      hunks: hunksFromChange(change),
    });
  }
  return out;
}

function summarizeOutputs(messages: Message[]): OutputSummary {
  const artifacts = new Map<string, OutputArtifact>();
  const changes = new Map<string, OutputChange>();

  for (const message of messages) {
    if (message.type !== "ai") continue;
    for (const toolCall of (message as AIMessage).tool_calls ?? []) {
      const artifact = artifactFromToolCall(toolCall);
      if (artifact) {
        artifacts.set(artifact.path, artifact);
      }
      for (const change of changesFromToolCall(toolCall)) {
        const existing = changes.get(change.path);
        const seen = new Set(change.hunks.map((h) => h.id));
        const carried = (existing?.hunks ?? []).filter((h) => !seen.has(h.id));
        changes.set(change.path, {
          ...change,
          added: (existing?.added ?? 0) + change.added,
          created: Boolean(existing?.created || change.created),
          removed: (existing?.removed ?? 0) + change.removed,
          diffTruncated: Boolean(
            existing?.diffTruncated || change.diffTruncated,
          ),
          hunks: [...carried, ...change.hunks],
        });
      }
    }
  }

  return {
    artifacts: [...artifacts.values()],
    changes: [...changes.values()],
  };
}

export function hasMessageOutputSummary(messages: Message[]): boolean {
  const summary = summarizeOutputs(messages);
  return summary.artifacts.length > 0 || summary.changes.length > 0;
}

export function MessageOutputSummary({
  auditNotice,
  messages,
  threadId,
  className,
}: {
  auditNotice?: string | null;
  messages: Message[];
  threadId?: string;
  className?: string;
}) {
  const { t } = useI18n();
  const { select, setOpen } = useArtifacts();
  const summary = useMemo(() => summarizeOutputs(messages), [messages]);
  const [changesOpen, setChangesOpen] = useState(summary.changes.length <= 3);
  const reviewAssignees = useMemo(
    () => [
      { value: "self", label: t.message.reviewSelf },
      { value: "team", label: t.message.reviewTeam },
      { value: "security", label: t.message.reviewSecurity },
    ],
    [t.message],
  );
  const [reviewAssignee, setReviewAssignee] = useState(
    reviewAssignees[0]!.value,
  );
  const [reverting, setReverting] = useState(false);

  if (summary.artifacts.length === 0 && summary.changes.length === 0) {
    return null;
  }

  const openArtifact = (path: string) => {
    select(path);
    setOpen(true);
  };

  const totalAdded = summary.changes.reduce((sum, item) => sum + item.added, 0);
  const totalRemoved = summary.changes.reduce(
    (sum, item) => sum + item.removed,
    0,
  );
  const createdChanges = summary.changes.filter((change) => change.created);
  const editedChanges = summary.changes.filter((change) => !change.created);
  const hasOnlyCreatedChanges =
    createdChanges.length > 0 && editedChanges.length === 0;
  const changeSummaryLabel = hasOnlyCreatedChanges
    ? t.message.artifactsCreated(createdChanges.length)
    : createdChanges.length > 0
      ? t.message.artifactsCreatedAndFilesEdited(
          createdChanges.length,
          editedChanges.length,
        )
      : t.message.filesEdited(editedChanges.length);
  const ChangeSummaryIcon = hasOnlyCreatedChanges
    ? FilePlus2Icon
    : FileCheck2Icon;
  const visibleChanges = changesOpen
    ? summary.changes
    : summary.changes.slice(0, 3);
  // A truncated diff may end mid-hunk; reverse-applying it would
  // conflict or corrupt the file, so it never enters the revert batch.
  const revertableChanges = summary.changes.filter(
    (change) => change.diff?.trim() && !change.diffTruncated,
  );
  const showAuditActions = Boolean(auditNotice);

  const handleRevertAll = async () => {
    if (revertableChanges.length === 0 || reverting) return;
    setReverting(true);
    try {
      const base = getBackendBaseURL();
      for (const change of revertableChanges) {
        const response = await fetch(`${base}/api/fs/revert-diff`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            path: change.path,
            diff: change.diff,
            thread_id: threadId,
            delete_empty: change.created,
          }),
        });
        if (!response.ok) {
          throw new Error(await responseErrorMessage(response));
        }
      }
      notifyWorkspaceChanged();
      toast.success(t.message.revertSuccess(revertableChanges.length));
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : t.message.revertFailed,
      );
    } finally {
      setReverting(false);
    }
  };

  const handleReviewAssigneeChange = (value: string) => {
    setReviewAssignee(value);
    const label =
      reviewAssignees.find((item) => item.value === value)?.label ?? value;
    toast.info(t.message.reviewAssigned(label));
  };

  return (
    <div className={cn("mt-4 flex w-full flex-col gap-2", className)}>
      <div className="flex flex-wrap items-center gap-2 rounded-xl border border-emerald-500/20 bg-emerald-500/[0.055] px-3 py-2 text-xs">
        <CheckCircle2Icon className="size-4 shrink-0 text-emerald-600 dark:text-emerald-400" />
        <div className="min-w-0 flex-1">
          <div className="font-semibold text-foreground">
            {t.message.taskOutputs}
          </div>
          <div className="truncate text-[11px] text-muted-foreground">
            {t.message.taskCompleted}
            {summary.changes.length > 0 ? ` · ${changeSummaryLabel}` : ""}
            {summary.artifacts.length > 0
              ? ` · ${t.message.artifactsCreated(summary.artifacts.length)}`
              : ""}
          </div>
        </div>
        {summary.changes.length > 0 && (
          <div className="shrink-0 rounded-full bg-background/75 px-2 py-1 font-mono text-[11px] shadow-sm">
            <span className="text-emerald-600 dark:text-emerald-400">
              +{totalAdded}
            </span>
            <span className="mx-1 text-muted-foreground"> </span>
            <span className="text-red-600 dark:text-red-400">
              -{totalRemoved}
            </span>
          </div>
        )}
      </div>
      {summary.artifacts.length > 0 && (
        <section aria-label={t.message.artifactsSummary} className="space-y-2">
          <div className="text-sm font-semibold text-foreground">
            {t.message.artifactsSummary}
          </div>
          <div className="flex flex-col gap-2">
            {summary.artifacts.map((artifact) => (
              <button
                key={artifact.path}
                type="button"
                onClick={() => openArtifact(artifact.path)}
                className={cn(
                  "group flex w-full items-center gap-3 rounded-lg border border-border/70 bg-muted/25 px-3 py-2.5 text-left",
                  "transition-colors hover:border-border hover:bg-muted/45",
                )}
              >
                <span className="shrink-0">
                  {getFileIcon(artifactDisplayPath(artifact.path), "size-7")}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-semibold text-foreground">
                    {artifact.title ||
                      getFileName(artifactDisplayPath(artifact.path))}
                  </span>
                  <span className="block truncate text-xs text-muted-foreground">
                    {artifact.kind ||
                      getFileExtensionDisplayName(
                        artifactDisplayPath(artifact.path),
                      )}
                  </span>
                </span>
                <ExternalLinkIcon className="size-4 shrink-0 text-muted-foreground opacity-70 transition-opacity group-hover:opacity-100" />
              </button>
            ))}
          </div>
        </section>
      )}

      {summary.changes.length > 0 && (
        <Collapsible open={changesOpen} onOpenChange={setChangesOpen}>
          <section
            aria-label={t.message.changesSummary}
            className="overflow-hidden rounded-lg border border-border/70 bg-muted/25"
          >
            <div className="flex flex-wrap items-start gap-2 px-3 py-2.5 sm:flex-nowrap sm:items-center">
              <ChangeSummaryIcon className="mt-0.5 size-4 shrink-0 text-muted-foreground/45" />
              <CollapsibleTrigger className="flex min-w-0 flex-1 items-center gap-2 text-left outline-none">
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-semibold text-foreground">
                    {changeSummaryLabel}
                  </span>
                  <span className="mt-0.5 block font-mono text-[10px] leading-none">
                    <span className="text-emerald-600 dark:text-emerald-400">
                      +{totalAdded}
                    </span>
                    <span className="mx-1 text-muted-foreground"> </span>
                    <span className="text-red-600 dark:text-red-400">
                      -{totalRemoved}
                    </span>
                  </span>
                </span>
                <ChevronDownIcon
                  className={cn(
                    "size-4 shrink-0 text-muted-foreground/60 transition-transform",
                    !changesOpen && "-rotate-90",
                  )}
                />
              </CollapsibleTrigger>
              {showAuditActions && (
                <div
                  aria-label={t.message.auditActions}
                  className="ml-auto flex shrink-0 items-center gap-1.5"
                >
                  <button
                    type="button"
                    onClick={() => void handleRevertAll()}
                    disabled={reverting || revertableChanges.length === 0}
                    className={cn(
                      "inline-flex h-7 shrink-0 items-center gap-1 rounded-md border border-border/70 bg-transparent px-2 text-[11px] font-medium text-foreground/80 transition-colors",
                      "hover:bg-muted/60 disabled:cursor-not-allowed disabled:opacity-55",
                    )}
                  >
                    {reverting ? (
                      <Loader2Icon className="size-3 animate-spin text-muted-foreground/70" />
                    ) : (
                      <RotateCcwIcon className="size-3 text-muted-foreground/70" />
                    )}
                    {t.common.revert}
                  </button>
                  <label className="relative inline-flex h-7 shrink-0 cursor-pointer items-center gap-1 overflow-hidden rounded-md border border-border/70 bg-transparent px-2 text-[11px] font-medium text-foreground/80 transition-colors hover:bg-muted/60">
                    <UserCheckIcon className="size-3 text-muted-foreground/70" />
                    {t.common.review}
                    <ChevronDownIcon className="size-3 text-muted-foreground/55" />
                    <select
                      aria-label={t.message.assignReviewTo}
                      value={reviewAssignee}
                      onChange={(event) =>
                        handleReviewAssigneeChange(event.target.value)
                      }
                      className="absolute inset-0 h-full w-full cursor-pointer opacity-0"
                    >
                      {reviewAssignees.map((item) => (
                        <option key={item.value} value={item.value}>
                          {item.label}
                        </option>
                      ))}
                    </select>
                  </label>
                </div>
              )}
            </div>
            <CollapsibleContent>
              <ul className="divide-y divide-border/50 border-t border-border/60">
                {visibleChanges.map((change) => (
                  <ChangeRow
                    key={change.path}
                    change={change}
                    threadId={threadId}
                  />
                ))}
                {!changesOpen && summary.changes.length > 3 && (
                  <li className="px-3 py-2 text-xs text-muted-foreground">
                    {t.message.moreFiles(summary.changes.length - 3)}
                  </li>
                )}
              </ul>
            </CollapsibleContent>
            {summary.artifacts.length > 0 && (
              <div className="border-t border-border/50 px-3 py-2 text-xs text-muted-foreground">
                <DownloadIcon className="mr-1 inline size-3.5 align-[-2px]" />
                {t.message.downloadStillInArtifactsPanel}
              </div>
            )}
          </section>
        </Collapsible>
      )}
    </div>
  );
}

/**
 * One file row in the changes summary. When the server streamed
 * per-hunk metadata (FileChangeItem.changes[].hunks) the row becomes
 * expandable and each hunk can be accepted or rejected individually.
 * Reject reverse-applies just that hunk through the same
 * ``/api/fs/revert-diff`` endpoint the "撤销" (revert-all) button uses;
 * accept is informational — the file already contains the change.
 */
function ChangeRow({
  change,
  threadId,
}: {
  change: OutputChange;
  threadId?: string;
}) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const [decisions, setDecisions] = useState<
    Record<string, "accepted" | "rejected">
  >({});
  const [rejecting, setRejecting] = useState<string | null>(null);
  const hasHunks = change.hunks.length > 0;

  const rejectHunk = async (hunk: FileHunk) => {
    if (rejecting) return;
    setRejecting(hunk.id);
    try {
      const base = getBackendBaseURL();
      const response = await fetch(`${base}/api/fs/revert-diff`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          path: change.path,
          diff: singleHunkDiff(change.path, hunk, change.diff ?? null),
          thread_id: threadId,
          delete_empty: false,
        }),
      });
      if (!response.ok) {
        throw new Error(await responseErrorMessage(response));
      }
      setDecisions((prev) => ({ ...prev, [hunk.id]: "rejected" }));
      notifyWorkspaceChanged();
      toast.success(t.message.hunkReverted);
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : t.message.hunkRevertFailed,
      );
    } finally {
      setRejecting(null);
    }
  };

  return (
    <li className="text-sm">
      <div
        className={cn(
          "flex items-center gap-3 px-3 py-2",
          hasHunks && "cursor-pointer hover:bg-muted/30",
        )}
        onClick={hasHunks ? () => setOpen((prev) => !prev) : undefined}
      >
        {hasHunks && (
          <ChevronDownIcon
            className={cn(
              "size-3.5 shrink-0 text-muted-foreground/60 transition-transform",
              !open && "-rotate-90",
            )}
          />
        )}
        <span
          className={cn(
            "shrink-0 rounded px-1.5 py-0.5 text-[10px]",
            change.created
              ? "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
              : "bg-muted text-muted-foreground",
          )}
        >
          {change.created ? t.message.fileCreated : t.message.fileEdited}
        </span>
        <span className="min-w-0 flex-1 truncate font-mono text-muted-foreground">
          {change.path}
        </span>
        {change.diffTruncated && (
          <span
            title={t.message.diffTruncatedTooltip}
            className="shrink-0 rounded bg-amber-500/15 px-1.5 py-0.5 text-[10px] text-amber-700 dark:text-amber-400"
          >
            {t.message.diffTruncated}
          </span>
        )}
        <span className="shrink-0 font-mono text-xs">
          <span className="text-emerald-600 dark:text-emerald-400">
            +{change.added}
          </span>
          <span className="mx-1 text-muted-foreground"> </span>
          <span className="text-red-600 dark:text-red-400">
            -{change.removed}
          </span>
        </span>
      </div>
      {hasHunks && open && (
        <div className="flex flex-col gap-1.5 px-3 pb-2 pl-9">
          {change.hunks.map((hunk) => (
            <HunkDecisionRow
              key={hunk.id}
              hunk={hunk}
              decision={decisions[hunk.id] ?? hunk.decision}
              rejecting={rejecting === hunk.id}
              onAccept={() =>
                setDecisions((prev) => ({ ...prev, [hunk.id]: "accepted" }))
              }
              onReject={() => void rejectHunk(hunk)}
            />
          ))}
        </div>
      )}
    </li>
  );
}

function HunkDecisionRow({
  hunk,
  decision,
  rejecting,
  onAccept,
  onReject,
}: {
  hunk: FileHunk;
  decision: "pending" | "accepted" | "rejected";
  rejecting: boolean;
  onAccept: () => void;
  onReject: () => void;
}) {
  const { t } = useI18n();
  const header = `@@ -${hunk.oldStart},${hunk.oldLines} +${hunk.newStart},${hunk.newLines} @@`;
  return (
    <div
      className="overflow-hidden rounded border border-border/40 bg-card/60 text-xs"
      data-hunk-decision={decision}
    >
      <div className="flex items-center justify-between gap-2 border-b border-border/40 bg-muted/30 px-2 py-1">
        <span className="font-mono text-[11px] text-muted-foreground">
          {header}
        </span>
        <div className="flex items-center gap-1.5">
          {decision === "pending" ? (
            <>
              <button
                type="button"
                onClick={onAccept}
                className="inline-flex h-6 items-center rounded-md border border-border/70 px-2 text-[11px] font-medium text-emerald-700 transition-colors hover:bg-emerald-500/10 dark:text-emerald-400"
              >
                {t.message.accept}
              </button>
              <button
                type="button"
                onClick={onReject}
                disabled={rejecting}
                className="inline-flex h-6 items-center gap-1 rounded-md border border-border/70 px-2 text-[11px] font-medium text-red-700 transition-colors hover:bg-red-500/10 disabled:cursor-not-allowed disabled:opacity-55 dark:text-red-400"
              >
                {rejecting && (
                  <Loader2Icon className="size-3 animate-spin text-muted-foreground/70" />
                )}
                {t.message.reject}
              </button>
            </>
          ) : (
            <span
              className={cn(
                "rounded px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide",
                decision === "accepted"
                  ? "bg-emerald-500/15 text-emerald-700 dark:text-emerald-400"
                  : "bg-red-500/15 text-red-700 dark:text-red-400",
              )}
            >
              {decision === "accepted"
                ? t.message.accepted
                : t.message.rejected}
            </span>
          )}
        </div>
      </div>
      <pre className="max-h-48 overflow-auto font-mono text-[11px] leading-snug">
        {hunk.body.split(/\r?\n/).map((line, idx) =>
          line ? (
            <div key={idx} className={cn("px-2", hunkLineTone(line))}>
              {line}
            </div>
          ) : null,
        )}
      </pre>
    </div>
  );
}

function hunkLineTone(line: string): string {
  if (line.startsWith("@@")) return "text-muted-foreground";
  if (line.startsWith("+"))
    return "bg-emerald-500/10 text-emerald-700 dark:text-emerald-400";
  if (line.startsWith("-"))
    return "bg-red-500/10 text-red-700 dark:text-red-400";
  return "text-foreground/80";
}

function notifyWorkspaceChanged() {
  window.dispatchEvent(new CustomEvent("octopus:workspace-changed"));
}

async function responseErrorMessage(response: Response): Promise<string> {
  try {
    const payload = await response.json();
    if (typeof payload?.detail === "string") return payload.detail;
    if (payload?.detail?.error) return String(payload.detail.error);
  } catch (e) {
    swallow(e);
  }
  return response.statusText || `Request failed (${response.status})`;
}
