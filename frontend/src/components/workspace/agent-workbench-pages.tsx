import {
  BotIcon,
  CheckIcon,
  ChevronDownIcon,
  ChevronRightIcon,
  CircleIcon,
  BrainCircuitIcon,
  FilePlus2Icon,
  FileTextIcon,
  GitBranchIcon,
  GlobeIcon,
  ListChecksIcon,
  Loader2Icon,
  MoreHorizontalIcon,
  UsersIcon,
  type LucideIcon,
} from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";

import { FileTree, type FileTreeEvent } from "@/components/workspace/file-tree";
import {
  phaseStatusText,
  type AgentPhase,
  type AgentPhaseStatus,
} from "./agent-phases";
import type { LiveToolEvent } from "./live-tool-timeline";
import { pickCurrentWorkBlock, type WorkBlock } from "./work-blocks";
import { cn } from "@/lib/utils";
import {
  type AgentTile,
  type DiffEntry,
  type AgentWorkbenchTabId,
  statusIcon,
  compactDetail,
  agentProgressPercent,
  durationLabel,
  timeLabel,
  agentEventGroupId,
  FILES_TAB_LABEL,
  SUBAGENTS_TAB_LABEL,
  DIFF_TAB_LABEL,
} from "./agent-workbench-utils";

// ── Shared UI primitives ──────────────────────────────────────────────

export function StatusGlyph({
  status,
  className,
}: {
  status: LiveToolEvent["status"] | AgentPhaseStatus;
  className?: string;
}) {
  const Icon = statusIcon(status);
  return (
    <Icon
      className={cn(
        "size-4 shrink-0",
        status === "running" && "animate-spin text-foreground",
        status === "done" && "text-emerald-500",
        status === "error" && "text-destructive",
        status === "pending" && "text-muted-foreground/45",
        status === "waiting_approval" && "text-amber-500",
        className,
      )}
    />
  );
}

export function WorkBlockDetailSection({
  content,
  empty,
  title,
}: {
  content: string;
  empty?: ReactNode;
  title: string;
}) {
  const isLong = content.length > 360 || content.split(/\r?\n/).length > 6;
  const [open, setOpen] = useState(!isLong);
  const preview = compactDetail(content, 240);

  return (
    <div>
      <div className="flex items-center gap-2 border-b border-border/45 px-3 py-1.5 text-[11px] font-medium text-muted-foreground">
        <span>{title}</span>
        {isLong && (
          <button
            type="button"
            onClick={() => setOpen((value) => !value)}
            className="ml-auto inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[10px] transition-colors hover:bg-muted hover:text-foreground"
            aria-expanded={open}
          >
            <ChevronDownIcon
              className={cn(
                "size-3 transition-transform",
                open && "rotate-180",
              )}
            />
            {open ? "收起" : "展开详情"}
          </button>
        )}
      </div>
      {content ? (
        open ? (
          <pre className="max-h-36 overflow-auto whitespace-pre-wrap break-words px-3 py-2.5 font-mono text-[11px] leading-5 text-foreground/80">
            {content}
          </pre>
        ) : (
          <div className="px-3 py-2.5 text-sm leading-6 text-foreground/75">
            {preview}
          </div>
        )
      ) : (
        empty
      )}
    </div>
  );
}

export function WorkbenchEmptyPage({
  description,
  title,
}: {
  description: string;
  title: string;
}) {
  return (
    <div className="flex min-h-0 flex-1 items-center justify-center bg-background/70 p-6 text-center">
      <div className="max-w-xs">
        <div className="text-sm font-medium text-foreground">{title}</div>
        <p className="mt-1 text-xs leading-5 text-muted-foreground">
          {description}
        </p>
      </div>
    </div>
  );
}

export function AgentMetric({
  label,
  value,
}: {
  label: string;
  value: ReactNode;
}) {
  return (
    <div className="rounded-md border border-border/45 bg-background/70 px-3 py-2">
      <div className="text-[11px] text-muted-foreground">{label}</div>
      <div className="mt-1 min-h-5 text-sm font-medium text-foreground">
        {value}
      </div>
    </div>
  );
}

function SummaryDiffEntryList({
  entries,
  kind,
  onOpenEntry,
}: {
  entries: DiffEntry[];
  kind: "artifact" | "change";
  onOpenEntry?: (entry: DiffEntry, kind: "artifact" | "change") => void;
}) {
  const Icon = kind === "artifact" ? FilePlus2Icon : FileTextIcon;
  return (
    <ul className="max-h-48 divide-y divide-border/20 overflow-y-auto">
      {entries.map((entry) => (
        <li key={entry.id}>
          <button
            type="button"
            onClick={() => onOpenEntry?.(entry, kind)}
            className="flex w-full items-center gap-2 px-3 py-2 text-left transition-colors hover:bg-muted/45 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            aria-label={`${kind === "artifact" ? "打开产物" : "查看 Diff"} ${entry.title}`}
            title={entry.path}
          >
            <Icon
              className={cn(
                "size-3.5 shrink-0",
                kind === "artifact" ? "text-emerald-500" : "text-blue-500",
              )}
            />
            <span className="min-w-0 flex-1 truncate text-[11px] text-foreground">
              {entry.title}
            </span>
            <ChevronRightIcon className="size-3.5 shrink-0 text-muted-foreground/55" />
          </button>
        </li>
      ))}
    </ul>
  );
}

type ObservedReferenceTabId = "files" | "plans" | "web" | "memory" | "other";

interface ObservedReferenceItem {
  id: string;
  title: string;
  subtitle?: string;
  tag?: string;
}

interface ObservedReferenceTab {
  id: ObservedReferenceTabId;
  label: string;
  items: ObservedReferenceItem[];
}

const OBSERVED_REFERENCE_TABS: Array<{
  id: ObservedReferenceTabId;
  label: string;
}> = [
  { id: "files", label: "文件" },
  { id: "plans", label: "待办 plan" },
  { id: "web", label: "搜索/网页" },
  { id: "memory", label: "记忆" },
  { id: "other", label: "其他" },
];

const OBSERVED_REFERENCE_META: Record<
  ObservedReferenceTabId,
  {
    Icon: LucideIcon;
    barClassName: string;
    dotClassName: string;
    iconClassName: string;
  }
> = {
  files: {
    Icon: FileTextIcon,
    barClassName: "bg-blue-400",
    dotClassName: "bg-blue-400",
    iconClassName: "text-blue-500",
  },
  plans: {
    Icon: ListChecksIcon,
    barClassName: "bg-violet-400",
    dotClassName: "bg-violet-400",
    iconClassName: "text-violet-500",
  },
  web: {
    Icon: GlobeIcon,
    barClassName: "bg-sky-400",
    dotClassName: "bg-sky-400",
    iconClassName: "text-sky-500",
  },
  memory: {
    Icon: BrainCircuitIcon,
    barClassName: "bg-amber-400",
    dotClassName: "bg-amber-400",
    iconClassName: "text-amber-500",
  },
  other: {
    Icon: MoreHorizontalIcon,
    barClassName: "bg-muted-foreground/50",
    dotClassName: "bg-muted-foreground/50",
    iconClassName: "text-muted-foreground",
  },
};

function buildObservedReferenceTabs(
  blocks: WorkBlock[],
): ObservedReferenceTab[] {
  const buckets: Record<ObservedReferenceTabId, ObservedReferenceItem[]> = {
    files: [],
    plans: [],
    web: [],
    memory: [],
    other: [],
  };

  for (const block of blocks) {
    if (isAgentLifecycleBlock(block)) continue;
    const tabId = referenceTabForBlock(block);
    buckets[tabId].push(...referenceItemsForBlock(block));
  }

  return OBSERVED_REFERENCE_TABS.map((tab) => ({
    ...tab,
    items: dedupeReferenceItems(buckets[tab.id]).slice(0, 50),
  })).filter((tab) => tab.items.length > 0);
}

function referenceTabForBlock(block: WorkBlock): ObservedReferenceTabId {
  const signature = [
    block.event.name,
    block.title,
    block.subtitle,
    block.event.agentName,
    block.event.subAgentRole,
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();

  if (
    /(^|[_\s-])(memory|remember|recall|profile_memory|user_preferences)([_\s-]|$)/i.test(
      signature,
    )
  ) {
    return "memory";
  }
  if (block.kind === "file" || block.kind === "read") return "files";
  if (block.kind === "todo") return "plans";
  if (block.kind === "search" || block.kind === "browser") return "web";
  return "other";
}

function referenceItemsForBlock(block: WorkBlock): ObservedReferenceItem[] {
  if (block.kind === "todo") return [];

  if (block.kind === "file" || block.kind === "read") {
    const fileItems = fileReferenceItems(block);
    if (fileItems.length > 0) return fileItems;
  }
  if (block.kind === "search" || block.kind === "browser") {
    const webItems = webReferenceItems(block);
    if (webItems.length > 0) return webItems;
  }

  const target = referenceTarget(block);
  const title = target || block.title || block.event.name;
  if (!title) return [];
  const detail =
    target && block.title && block.title !== target
      ? block.title
      : block.subtitle || compactReference(block.outputText, 96);
  return [
    {
      id: block.id,
      title: compactReference(title, 120),
      subtitle: detail ? compactReference(detail, 128) : undefined,
      tag: referenceStatusLabel(block.status),
    },
  ];
}

function fileReferenceItems(block: WorkBlock): ObservedReferenceItem[] {
  return uniqueStrings([
    ...changePaths(block.event.input),
    ...stringArrayFromInput(block.event.input, [
      "paths",
      "files",
      "file_paths",
    ]),
    ...stringValuesFromInput(block.event.input, [
      "path",
      "file_path",
      "filepath",
      "filename",
    ]),
    ...(block.event.filesTouched ?? []),
  ]).map((path, index) => {
    const name = basename(path);
    return {
      id: `${block.id}:file:${index}:${path}`,
      title: compactReference(name || path, 120),
      subtitle: path !== name ? compactReference(path, 140) : block.title,
      tag: fileKindLabel(path),
    };
  });
}

function webReferenceItems(block: WorkBlock): ObservedReferenceItem[] {
  const pages = dedupeWebPages([
    ...webPagesFromValue(block.event.output),
    ...webPagesFromValue(block.event.input?.output),
  ]);
  if (pages.length === 0) {
    const url = firstInputString(block.event.input, ["url"]);
    if (url) {
      return [
        {
          id: `${block.id}:url:${url}`,
          title: compactReference(pageTitleFromUrl(url), 120),
          subtitle: compactReference(url, 140),
          tag: hostLabel(url),
        },
      ];
    }
    return [];
  }

  return pages.slice(0, 8).map((page, index) => ({
    id: `${block.id}:web:${index}:${page.url || page.title}`,
    title: compactReference(page.title || pageTitleFromUrl(page.url), 120),
    subtitle: page.url
      ? compactReference(page.url, 140)
      : page.snippet
        ? compactReference(page.snippet, 140)
        : undefined,
    tag: page.url ? hostLabel(page.url) : undefined,
  }));
}

function webPagesFromValue(value: unknown): Array<{
  title: string;
  url: string;
  snippet?: string;
}> {
  if (typeof value === "string") {
    return dedupeWebPages([
      ...parsedJsonValuesFromText(value).flatMap(webPagesFromValue),
      ...webPagesFromText(value),
    ]);
  }

  const candidates = resultRecordsFromValue(value);
  return candidates.flatMap((record) => {
    const url = firstInputString(record, ["url", "link", "href"]);
    const title =
      firstInputString(record, ["title", "name", "text"]) ||
      pageTitleFromUrl(url);
    const snippet = firstInputString(record, [
      "snippet",
      "description",
      "summary",
      "content",
    ]);
    if (!url && !title) return [];
    return [
      {
        title: cleanWebText(title),
        url: cleanWebText(url),
        snippet: snippet ? cleanWebText(snippet) : undefined,
      },
    ];
  });
}

function resultRecordsFromValue(value: unknown): Record<string, unknown>[] {
  if (Array.isArray(value)) {
    return value.filter(isRecord);
  }
  if (!isRecord(value)) return [];
  for (const key of ["results", "items", "pages", "documents", "data"]) {
    const nested = value[key];
    if (Array.isArray(nested)) return nested.filter(isRecord);
  }
  return [value];
}

function parsedJsonValuesFromText(text: string): unknown[] {
  const trimmed = text.trim();
  const startIndexes = [trimmed.indexOf("{"), trimmed.indexOf("[")]
    .filter((index) => index >= 0)
    .sort((a, b) => a - b);

  const parsed: unknown[] = [];
  for (const start of startIndexes) {
    try {
      parsed.push(JSON.parse(trimmed.slice(start)));
      break;
    } catch {
      // Aggregated command output is sometimes truncated. Fall back to the
      // conservative title/url extractor below.
    }
  }
  return parsed;
}

function webPagesFromText(text: string): Array<{
  title: string;
  url: string;
  snippet?: string;
}> {
  const pages: Array<{ title: string; url: string; snippet?: string }> = [];
  const patterns = [
    /"title"\s*:\s*"([^"]+)"[\s\S]{0,800}?"url"\s*:\s*"([^"\r\n}]*)/g,
    /'title'\s*:\s*'([^']+)'[\s\S]{0,800}?'url'\s*:\s*'([^'\r\n}]*)/g,
  ];

  for (const pattern of patterns) {
    for (const match of text.matchAll(pattern)) {
      const title = cleanWebText(match[1] ?? "");
      const url = cleanWebText(match[2] ?? "");
      if (!title && !url) continue;
      pages.push({ title: title || pageTitleFromUrl(url), url });
    }
  }
  return pages;
}

function dedupeWebPages(
  pages: Array<{ title: string; url: string; snippet?: string }>,
): Array<{ title: string; url: string; snippet?: string }> {
  const seen = new Set<string>();
  const result: Array<{ title: string; url: string; snippet?: string }> = [];
  for (const page of pages) {
    const key = `${page.url || page.title}`.toLowerCase();
    if (!key || seen.has(key)) continue;
    seen.add(key);
    result.push(page);
  }
  return result;
}

function cleanWebText(text: string): string {
  return text
    .replace(/\\"/g, '"')
    .replace(/\\'/g, "'")
    .replace(/&quot;/g, '"')
    .replace(/&#x27;/g, "'")
    .replace(/&#39;/g, "'")
    .replace(/&amp;/g, "&")
    .trim();
}

function referenceTarget(block: WorkBlock): string {
  const input = block.event.input;
  return (
    changePaths(input)[0] ||
    firstInputString(input, ["path", "file_path", "filepath", "filename"]) ||
    firstInputString(input, ["url"]) ||
    firstInputString(input, ["query", "pattern"]) ||
    firstInputString(input, ["command", "cmd"]) ||
    firstInputString(input, ["key", "name", "title"])
  );
}

function stringValuesFromInput(
  input: Record<string, unknown> | undefined,
  keys: string[],
): string[] {
  if (!input) return [];
  return keys.flatMap((key) => {
    const value = input[key];
    if (typeof value === "string" && value.trim()) return [value.trim()];
    if (typeof value === "number") return [String(value)];
    return [];
  });
}

function stringArrayFromInput(
  input: Record<string, unknown> | undefined,
  keys: string[],
): string[] {
  if (!input) return [];
  return keys.flatMap((key) => {
    const value = input[key];
    if (!Array.isArray(value)) return [];
    return value.flatMap((item) => {
      if (typeof item === "string" && item.trim()) return [item.trim()];
      if (isRecord(item)) {
        return stringValuesFromInput(item, ["path", "file_path", "filepath"]);
      }
      return [];
    });
  });
}

function firstInputString(
  input: Record<string, unknown> | undefined,
  keys: string[],
): string {
  if (!input) return "";
  for (const key of keys) {
    const value = input[key];
    if (typeof value === "string" && value.trim()) return value.trim();
    if (typeof value === "number") return String(value);
  }
  return "";
}

function changePaths(input: Record<string, unknown> | undefined): string[] {
  const changes = input?.changes;
  if (!Array.isArray(changes)) return [];
  return changes.flatMap((change) => {
    if (!isRecord(change)) return [];
    const path = change.path;
    return typeof path === "string" && path.trim() ? [path.trim()] : [];
  });
}

function dedupeReferenceItems(
  items: ObservedReferenceItem[],
): ObservedReferenceItem[] {
  const seen = new Set<string>();
  const result: ObservedReferenceItem[] = [];
  for (const item of items) {
    const key = `${item.title}\u0000${item.subtitle ?? ""}`;
    if (seen.has(key)) continue;
    seen.add(key);
    result.push(item);
  }
  return result;
}

function referenceStatusLabel(status: WorkBlock["status"]): string {
  if (status === "running") return "进行中";
  if (status === "waiting_approval") return "待确认";
  if (status === "error") return "异常";
  return "已完成";
}

function fileKindLabel(path: string): string | undefined {
  const name = basename(path);
  const match = /\.([a-z0-9]+)$/i.exec(name);
  return match?.[1]?.toUpperCase();
}

function basename(path: string): string {
  return path.split(/[\\/]/).filter(Boolean).pop() ?? path;
}

function pageTitleFromUrl(url: string): string {
  if (!url) return "";
  try {
    const parsed = new URL(url);
    return parsed.hostname.replace(/^www\./, "") || url;
  } catch {
    return url;
  }
}

function hostLabel(url: string): string | undefined {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return undefined;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === "object" && !Array.isArray(value));
}

function uniqueStrings(values: string[]): string[] {
  const seen = new Set<string>();
  const result: string[] = [];
  for (const value of values) {
    const clean = value.trim();
    if (!clean || seen.has(clean)) continue;
    seen.add(clean);
    result.push(clean);
  }
  return result;
}

function compactReference(value: string, max: number): string {
  const clean = value.replace(/\s+/g, " ").trim();
  return clean.length <= max ? clean : `${clean.slice(0, max - 1)}…`;
}

// ============================================================================
// 看板概要页 (Agent Summary Dashboard)
// ============================================================================
export function AgentSummaryPage({
  phases,
  diffEntries,
  agentTiles,
  blocks,
  onSelectTab,
}: {
  phases: AgentPhase[];
  diffEntries: DiffEntry[];
  agentTiles: AgentTile[];
  blocks: WorkBlock[];
  onSelectTab?: (tabId: AgentWorkbenchTabId) => void;
}) {
  const [expandedSections, setExpandedSections] = useState<Set<string>>(
    new Set(["progress", "artifacts", "references", "operations", "subagents"]),
  );
  const [refTab, setRefTab] = useState<ObservedReferenceTabId>("files");
  const artifactDiffEntries = useMemo(
    () => diffEntries.filter((entry) => entry.created),
    [diffEntries],
  );
  const changedFileEntries = useMemo(
    () => diffEntries.filter((entry) => !entry.created),
    [diffEntries],
  );
  const openDiffEntry = (_entry: DiffEntry, kind: "artifact" | "change") => {
    onSelectTab?.(kind === "artifact" ? "files" : "diff");
  };

  const toggleSection = (section: string) => {
    setExpandedSections((prev) => {
      const next = new Set(prev);
      if (next.has(section)) next.delete(section);
      else next.add(section);
      return next;
    });
  };

  const observedReferenceTabs = useMemo(
    () => buildObservedReferenceTabs(blocks),
    [blocks],
  );
  const activeRefTab = observedReferenceTabs.some((tab) => tab.id === refTab)
    ? refTab
    : (observedReferenceTabs[0]?.id ?? "files");
  const activeRefItems =
    observedReferenceTabs.find((tab) => tab.id === activeRefTab)?.items ?? [];
  const activeRefMeta = OBSERVED_REFERENCE_META[activeRefTab];
  const ActiveRefIcon = activeRefMeta.Icon;
  const totalReferenceItems = observedReferenceTabs.reduce(
    (sum, tab) => sum + tab.items.length,
    0,
  );
  const agentHealth = useMemo(() => {
    const total = agentTiles.length;
    const done = agentTiles.filter((agent) => agent.status === "done").length;
    const running = agentTiles.filter(
      (agent) => agent.status === "running",
    ).length;
    const failed = agentTiles.filter(
      (agent) => agent.status === "error",
    ).length;
    const pending = agentTiles.filter(
      (agent) => agent.status === "pending",
    ).length;
    const failedLabels = agentTiles
      .filter((agent) => agent.status === "error")
      .map((agent) => agent.taskLabel ?? agent.name ?? agent.role ?? agent.id);
    return { done, failed, failedLabels, pending, running, total };
  }, [agentTiles]);

  // 上下文容量估算
  const contextStats = useMemo(() => {
    // 粗略估算：每4个字符约等于1个token
    const estimateTokens = (text: string) => Math.ceil(text.length / 4);
    let fileTokens = 0;
    let otherTokens = 0;
    const tokenByTab: Record<ObservedReferenceTabId, number> = {
      files: 0,
      plans: 0,
      web: 0,
      memory: 0,
      other: 0,
    };

    for (const block of blocks) {
      if (isAgentLifecycleBlock(block)) continue;
      const referenceItems = referenceItemsForBlock(block);
      if (referenceItems.length === 0) continue;

      const inputTokens = estimateTokens(block.inputText || "");
      const outputTokens = estimateTokens(block.outputText || "");
      const total = inputTokens + outputTokens;
      tokenByTab[referenceTabForBlock(block)] += total;

      if (block.kind === "file" || block.kind === "read") {
        fileTokens += total;
      } else {
        otherTokens += total;
      }
    }

    const totalTokens = fileTokens + otherTokens;
    const visualWindow = 128000;
    const percentage =
      totalTokens > 0
        ? Math.max(
            1,
            Math.min(Math.round((totalTokens / visualWindow) * 100), 100),
          )
        : 0;
    const filePercentage =
      totalTokens > 0 ? Math.round((fileTokens / totalTokens) * 100) : 0;
    const otherPercentage = totalTokens > 0 ? 100 - filePercentage : 0;
    const segments = OBSERVED_REFERENCE_TABS.map((tab) => ({
      id: tab.id,
      label: tab.label,
      percentage:
        totalTokens > 0
          ? Math.max(1, Math.round((tokenByTab[tab.id] / totalTokens) * 100))
          : 0,
      tokens: tokenByTab[tab.id],
    })).filter((segment) => segment.tokens > 0);

    return {
      totalTokens,
      percentage,
      filePercentage,
      otherPercentage,
      segments,
    };
  }, [blocks]);

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-y-auto bg-background/70">
      <div className="mx-auto w-full max-w-2xl divide-y divide-border/30">
        {/* 进展 */}
        {phases.length > 0 && (
          <section className="bg-background/85">
            <button
              type="button"
              onClick={() => toggleSection("progress")}
              className="flex w-full items-center gap-1.5 px-3 py-2 text-left transition-colors hover:bg-muted/30"
            >
              <h3 className="text-xs font-medium text-foreground">进展</h3>
              {expandedSections.has("progress") ? (
                <ChevronDownIcon className="ml-auto size-3.5 text-muted-foreground" />
              ) : (
                <ChevronRightIcon className="ml-auto size-3.5 text-muted-foreground" />
              )}
            </button>
            {expandedSections.has("progress") && (
              <ul className="max-h-48 divide-y divide-border/20 overflow-y-auto border-t border-border/30">
                {phases.map((phase) => (
                  <li
                    key={phase.id}
                    className="flex items-center gap-2 px-3 py-1.5"
                  >
                    {phase.status === "done" ? (
                      <span className="flex size-4 shrink-0 items-center justify-center rounded-full bg-muted">
                        <CheckIcon className="size-2.5 text-muted-foreground" />
                      </span>
                    ) : phase.status === "running" ? (
                      <Loader2Icon className="size-3.5 shrink-0 animate-spin text-primary" />
                    ) : (
                      <CircleIcon className="size-3.5 shrink-0 text-muted-foreground/40" />
                    )}
                    <span className="min-w-0 flex-1 truncate text-xs text-foreground">
                      {phase.title}
                    </span>
                    <span className="shrink-0 text-[11px] text-muted-foreground">
                      {phaseStatusText(phase.status)}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </section>
        )}

        {/* 产物 */}
        {diffEntries.length > 0 && (
          <section className="bg-background/85">
            <button
              type="button"
              onClick={() => toggleSection("artifacts")}
              className="flex w-full items-center gap-1.5 px-3 py-2 text-left transition-colors hover:bg-muted/30"
            >
              <h3 className="text-xs font-medium text-foreground">产物</h3>
              {expandedSections.has("artifacts") ? (
                <ChevronDownIcon className="ml-auto size-3.5 text-muted-foreground" />
              ) : (
                <ChevronRightIcon className="ml-auto size-3.5 text-muted-foreground" />
              )}
            </button>
            {expandedSections.has("artifacts") && (
              <div className="border-t border-border/30">
                {artifactDiffEntries.length > 0 && (
                  <>
                    <div className="flex items-center gap-1.5 border-b border-border/20 px-3 py-1.5">
                      <span className="text-[11px] font-medium text-foreground">
                        生成产物
                      </span>
                      <span className="text-[10px] text-muted-foreground">
                        {artifactDiffEntries.length}
                      </span>
                    </div>
                    <SummaryDiffEntryList
                      entries={artifactDiffEntries}
                      kind="artifact"
                      onOpenEntry={openDiffEntry}
                    />
                  </>
                )}
                {changedFileEntries.length > 0 && (
                  <>
                    <div
                      className={cn(
                        "flex items-center gap-1.5 border-b border-border/20 px-3 py-1.5",
                        artifactDiffEntries.length > 0 &&
                          "border-t border-border/20",
                      )}
                    >
                      <span className="text-[11px] font-medium text-foreground">
                        变更文件
                      </span>
                      <span className="text-[10px] text-muted-foreground">
                        {changedFileEntries.length}
                      </span>
                    </div>
                    <SummaryDiffEntryList
                      entries={changedFileEntries}
                      kind="change"
                      onOpenEntry={openDiffEntry}
                    />
                  </>
                )}
              </div>
            )}
          </section>
        )}

        {/* 子智能体 */}
        {agentTiles.length > 0 && (
          <section className="bg-background/85">
            <button
              type="button"
              onClick={() => toggleSection("subagents")}
              className="flex w-full items-center gap-1.5 px-3 py-2 text-left transition-colors hover:bg-muted/30"
            >
              <h3 className="text-xs font-medium text-foreground">子智能体</h3>
              {expandedSections.has("subagents") ? (
                <ChevronDownIcon className="ml-auto size-3.5 text-muted-foreground" />
              ) : (
                <ChevronRightIcon className="ml-auto size-3.5 text-muted-foreground" />
              )}
            </button>
            {expandedSections.has("subagents") && (
              <div className="border-t border-border/30">
                <div
                  className={cn(
                    "border-b border-border/20 px-3 py-2 text-[11px]",
                    agentHealth.failed > 0
                      ? "bg-destructive/5"
                      : "bg-emerald-500/5",
                  )}
                >
                  <div className="flex items-center gap-2">
                    <BrainCircuitIcon
                      className={cn(
                        "size-3.5 shrink-0",
                        agentHealth.failed > 0
                          ? "text-destructive"
                          : "text-emerald-600",
                      )}
                    />
                    <span className="font-medium text-foreground">
                      {agentHealth.done}/{agentHealth.total} 已完成
                    </span>
                    {agentHealth.failed > 0 && (
                      <span className="font-medium text-destructive">
                        {agentHealth.failed} 异常
                      </span>
                    )}
                    {agentHealth.running > 0 && (
                      <span className="text-muted-foreground">
                        {agentHealth.running} 运行中
                      </span>
                    )}
                    {agentHealth.pending > 0 && (
                      <span className="text-muted-foreground">
                        {agentHealth.pending} 等待中
                      </span>
                    )}
                  </div>
                  {agentHealth.failedLabels.length > 0 && (
                    <div className="mt-1 line-clamp-2 text-destructive/90">
                      失败 lane: {agentHealth.failedLabels.join(" / ")}
                    </div>
                  )}
                </div>
                <ul className="max-h-48 divide-y divide-border/20 overflow-y-auto">
                  {agentTiles.map((tile) => (
                    <li
                      key={tile.id}
                      className="flex items-start gap-2 px-3 py-2"
                    >
                      <span className="flex size-5 shrink-0 items-center justify-center rounded bg-amber-100 text-amber-700">
                        <BotIcon className="size-3" />
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="flex items-center gap-2">
                          <span className="min-w-0 flex-1 truncate text-xs font-medium text-foreground">
                            {tile.taskLabel ??
                              tile.codename ??
                              tile.name ??
                              tile.label}
                          </span>
                          <span
                            className={cn(
                              "size-1.5 shrink-0 rounded-full",
                              tile.status === "error"
                                ? "bg-destructive"
                                : tile.status === "running"
                                  ? "bg-emerald-500"
                                  : tile.status === "done"
                                    ? "bg-muted-foreground/45"
                                    : "bg-amber-400",
                            )}
                            aria-hidden="true"
                          />
                        </span>
                        {(tile.resultSummary ??
                          tile.error ??
                          tile.lastThought) && (
                          <span className="mt-0.5 block line-clamp-2 text-[11px] leading-4 text-muted-foreground">
                            {tile.error ??
                              tile.resultSummary ??
                              tile.lastThought}
                          </span>
                        )}
                      </span>
                      <ChevronRightIcon className="size-3.5 shrink-0 text-muted-foreground/50" />
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </section>
        )}

        {/* 上下文（只展示本轮事件流里可确认的内容） */}
        <section className="mt-2 border-t-4 border-muted/80 bg-background/90">
          <button
            type="button"
            onClick={() => toggleSection("references")}
            className="flex w-full items-start gap-2 px-3 py-3 text-left transition-colors hover:bg-muted/30"
          >
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <h3 className="text-sm font-semibold text-foreground">
                  上下文
                </h3>
                <span className="rounded-md border border-border/45 bg-muted/35 px-1.5 py-0.5 text-[10px] text-muted-foreground">
                  本轮可观测
                </span>
                <span className="text-[10px] text-muted-foreground">
                  来源 {totalReferenceItems} 条
                </span>
                <span className="text-[10px] text-muted-foreground">
                  估算 {contextStats.percentage}%
                </span>
              </div>
              <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px] text-muted-foreground">
                {observedReferenceTabs.length === 0 ? (
                  <span>暂无来源</span>
                ) : (
                  observedReferenceTabs.map((tab) => {
                    const meta = OBSERVED_REFERENCE_META[tab.id];
                    return (
                      <span key={tab.id} className="flex items-center gap-1">
                        <span
                          className={cn(
                            "inline-block size-2 rounded-sm",
                            meta.dotClassName,
                          )}
                        />
                        {tab.label} {tab.items.length}
                      </span>
                    );
                  })
                )}
                {contextStats.totalTokens > 0 && (
                  <span className="font-mono">
                    {contextStats.totalTokens.toLocaleString()} 估算 token
                  </span>
                )}
              </div>
            </div>
            {expandedSections.has("references") ? (
              <ChevronDownIcon className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" />
            ) : (
              <ChevronRightIcon className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" />
            )}
          </button>
          {expandedSections.has("references") && (
            <div className="border-t border-border/30">
              {/* 上下文来源进度条 */}
              <div className="px-3 py-2">
                <div className="h-1.5 overflow-hidden rounded-full bg-muted/50">
                  <div
                    className="flex h-full"
                    style={{ width: `${contextStats.percentage}%` }}
                  >
                    {contextStats.segments.length === 0 ? (
                      <div className="h-full w-full bg-muted-foreground/30" />
                    ) : (
                      contextStats.segments.map((segment) => (
                        <div
                          key={segment.id}
                          className={cn(
                            "h-full transition-all",
                            OBSERVED_REFERENCE_META[segment.id].barClassName,
                          )}
                          style={{ width: `${segment.percentage}%` }}
                          title={`${segment.label} ${segment.tokens.toLocaleString()} 估算 token`}
                        />
                      ))
                    )}
                  </div>
                </div>
              </div>
              {/* 标签页切换 */}
              {observedReferenceTabs.length > 0 && (
                <div className="flex gap-1.5 overflow-x-auto border-b border-border/20 px-3 pb-2">
                  {observedReferenceTabs.map((tab) => {
                    const meta = OBSERVED_REFERENCE_META[tab.id];
                    const TabIcon = meta.Icon;
                    return (
                      <button
                        key={tab.id}
                        type="button"
                        aria-label={`${tab.label} ${tab.items.length} 条来源`}
                        onClick={() => setRefTab(tab.id)}
                        className={cn(
                          "inline-flex shrink-0 items-center gap-1.5 rounded-md border px-2 py-1 text-[11px] font-medium transition-colors",
                          activeRefTab === tab.id
                            ? "border-primary/45 bg-primary/10 text-foreground"
                            : "border-border/45 bg-background text-muted-foreground hover:bg-muted/50 hover:text-foreground",
                        )}
                      >
                        <TabIcon
                          className={cn("size-3.5", meta.iconClassName)}
                        />
                        <span>{tab.label}</span>
                        <span className="rounded bg-muted px-1 font-mono text-[9px] text-muted-foreground">
                          {tab.items.length}
                        </span>
                      </button>
                    );
                  })}
                </div>
              )}
              {/* 上下文列表 */}
              <ul className="max-h-48 divide-y divide-border/20 overflow-y-auto">
                {observedReferenceTabs.length === 0 ? (
                  <li className="px-3 py-4 text-center text-[11px] text-muted-foreground">
                    本轮暂无可确认的上下文引用
                  </li>
                ) : (
                  activeRefItems.map((ref) => (
                    <li
                      key={ref.id}
                      className="flex items-center gap-2 px-3 py-2"
                    >
                      <span className="flex size-6 shrink-0 items-center justify-center rounded-md bg-muted/55">
                        <ActiveRefIcon
                          className={cn(
                            "size-3.5",
                            activeRefMeta.iconClassName,
                          )}
                        />
                      </span>
                      <div className="min-w-0 flex-1">
                        <span className="block truncate text-[11px] text-foreground">
                          {ref.title}
                        </span>
                        {ref.subtitle && (
                          <span className="block truncate text-[10px] text-muted-foreground">
                            {ref.subtitle}
                          </span>
                        )}
                      </div>
                      {ref.tag && (
                        <span className="shrink-0 rounded bg-muted px-1 py-0.5 text-[9px] text-muted-foreground">
                          {ref.tag}
                        </span>
                      )}
                    </li>
                  ))
                )}
              </ul>
            </div>
          )}
        </section>

        {/* 空状态 */}
        {phases.length === 0 &&
          diffEntries.length === 0 &&
          agentTiles.length === 0 && (
            <div className="flex flex-col items-center justify-center px-4 py-8 text-center">
              <BotIcon className="mb-2 size-8 text-muted-foreground/50" />
              <p className="text-xs font-medium text-foreground">看板概览</p>
              <p className="mt-1 max-w-[240px] text-[11px] text-muted-foreground">
                Agent 开始工作后，这里会显示进展、产物和本轮可确认上下文
              </p>
            </div>
          )}
      </div>
    </div>
  );
}

export function AgentSubagentsPage({
  agentStatusClass,
  agentStatusLabel,
  agents,
  onSelectAgent,
  selectedAgent,
}: {
  agentStatusClass: (status: AgentTile["status"]) => string;
  agentStatusLabel: (status: AgentTile["status"]) => string;
  agents: AgentTile[];
  onSelectAgent: (agentId: string) => void;
  selectedAgent?: AgentTile;
}) {
  if (agents.length === 0) {
    return (
      <WorkbenchEmptyPage
        title={SUBAGENTS_TAB_LABEL}
        description="暂未观测到子智能体。触发 call_agent_parallel 后，这里会按父任务聚合每个 subagent 的状态、工具、黑板写入和文件改动。"
      />
    );
  }

  const active = selectedAgent ?? agents[0];
  const running = agents.filter((agent) => agent.status === "running").length;
  const done = agents.filter((agent) => agent.status === "done").length;
  const errors = agents.filter((agent) => agent.status === "error").length;

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-y-auto bg-background/70 p-3">
      <div className="mx-auto flex w-full max-w-3xl flex-col gap-3">
        <section className="grid grid-cols-3 gap-2">
          <AgentMetric label="运行中" value={running} />
          <AgentMetric label="已完成" value={done} />
          <AgentMetric label="异常" value={errors} />
        </section>

        <section className="grid gap-2 md:grid-cols-2">
          {agents.map((agent) => {
            const selected = active?.id === agent.id;
            const percent = agentProgressPercent(agent.status);
            return (
              <button
                key={agent.id}
                type="button"
                onClick={() => onSelectAgent(agent.id)}
                className={cn(
                  "rounded-lg border bg-background/85 p-3 text-left shadow-sm transition-colors",
                  selected
                    ? "border-foreground/45 ring-1 ring-foreground/10"
                    : "border-border/55 hover:bg-muted/40",
                )}
              >
                <div className="flex items-start gap-2.5">
                  {agent.avatar ? (
                    <span
                      className="flex size-8 shrink-0 items-center justify-center rounded-md border border-border/45 bg-background text-base"
                      aria-hidden="true"
                    >
                      {agent.avatar}
                    </span>
                  ) : (
                    <BotIcon className="size-8 shrink-0 rounded-md border border-border/45 bg-background p-1.5 text-foreground" />
                  )}
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="truncate text-sm font-semibold text-foreground">
                        {agent.name}
                      </span>
                      <span className="shrink-0 rounded bg-muted px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">
                        {agent.label}
                      </span>
                    </div>
                    <div className="mt-0.5 truncate text-xs text-muted-foreground">
                      {agent.role ?? "subagent"}
                    </div>
                  </div>
                  <StatusGlyph status={agent.status} />
                </div>
                <div
                  className={cn(
                    "mt-2 text-xs font-medium",
                    agentStatusClass(agent.status),
                  )}
                >
                  {agentStatusLabel(agent.status)}
                </div>
                <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-muted">
                  <div
                    className={cn(
                      "h-full rounded-full transition-all",
                      agent.status === "error"
                        ? "bg-destructive"
                        : "bg-emerald-500",
                    )}
                    style={{ width: `${percent}%` }}
                  />
                </div>
                <div className="mt-2 line-clamp-2 text-xs leading-5 text-muted-foreground">
                  {agent.lastThought ?? agent.currentTool ?? "等待任务事件"}
                </div>
              </button>
            );
          })}
        </section>

        {active && (
          <details className="group rounded-lg border border-border/55 bg-background/90 shadow-sm">
            <summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-2">
              <UsersIcon className="size-4 text-muted-foreground" />
              <span className="min-w-0 flex-1 truncate text-sm font-semibold text-foreground">
                子智能体运行详情
              </span>
              <span
                className={cn(
                  "shrink-0 text-xs font-medium",
                  agentStatusClass(active.status),
                )}
              >
                {agentStatusLabel(active.status)}
              </span>
              <ChevronDownIcon className="size-4 shrink-0 text-muted-foreground transition-transform group-open:rotate-180" />
            </summary>
            <div className="border-t border-border/45 p-3">
              <div className="grid gap-2 md:grid-cols-2">
                <AgentMetric label="角色" value={active.role ?? "subagent"} />
                <AgentMetric
                  label="当前工具"
                  value={active.currentTool ?? "暂无"}
                />
                <AgentMetric
                  label="开始时间"
                  value={timeLabel(active.startedAt)}
                />
                <AgentMetric
                  label="耗时"
                  value={durationLabel(active.durationMs)}
                />
                <AgentMetric label="事件数" value={`${active.eventCount} 条`} />
                <AgentMetric
                  label="父任务"
                  value={active.parentToolUseId ?? "暂无"}
                />
              </div>

              <div className="mt-3 grid gap-2">
                <AgentMetric
                  label="最近思考"
                  value={active.lastThought ?? "暂无"}
                />
                <AgentMetric
                  label="结果摘要"
                  value={active.resultSummary ?? "暂无"}
                />
                <AgentMetric
                  label="黑板写入"
                  value={
                    active.blackboardWrites.length > 0
                      ? active.blackboardWrites.join(" / ")
                      : "暂无"
                  }
                />
                <AgentMetric
                  label="触碰文件"
                  value={
                    active.filesTouched.length > 0
                      ? active.filesTouched.join(" / ")
                      : "暂无"
                  }
                />
                {active.error && (
                  <AgentMetric
                    label="错误"
                    value={
                      <span className="text-destructive">{active.error}</span>
                    }
                  />
                )}
              </div>
            </div>
          </details>
        )}
      </div>
    </div>
  );
}

export function AgentCreationCard({
  agent,
  agentStatusClass,
  agentStatusLabel,
}: {
  agent: AgentTile;
  agentStatusClass: (status: AgentTile["status"]) => string;
  agentStatusLabel: (status: AgentTile["status"]) => string;
}) {
  const [showBrief, setShowBrief] = useState(false);
  const displayName = agent.codename ?? agent.name;
  const roleName = friendlyRoleName(agent.role ?? agent.name);
  const fullBrief = agent.prompt ?? agent.task ?? agent.lastThought ?? "";
  const motto =
    agent.lastThought ??
    agent.task ??
    agent.currentTool ??
    "我会负责这一路任务，并把进展同步回主控。";
  const active = agent.status === "running";

  return (
    <section className="overflow-hidden rounded-lg border border-border/55 bg-background shadow-sm">
      <div className="flex items-center justify-center border-b border-border/45 px-3 py-2 text-sm font-medium text-muted-foreground">
        Agent 集群 - 创建助手
      </div>
      <div className="flex justify-center bg-[color:color-mix(in_oklch,var(--muted)_38%,var(--background))] px-4 py-5">
        <div className="relative w-full max-w-sm">
          <div className="absolute left-1/2 -top-7 h-10 w-7 -translate-x-1/2 rounded-b border-x border-border bg-foreground/90" />
          <div className="absolute left-1/2 top-1 h-2 w-16 -translate-x-1/2 rounded-full bg-background shadow-sm" />
          <div className="min-h-[28rem] rounded-xl border border-border/70 bg-background px-5 py-5 shadow-lg">
            {showBrief ? (
              <div className="flex h-full min-h-[25rem] flex-col">
                <div className="flex items-center gap-3">
                  <button
                    type="button"
                    onClick={() => setShowBrief(false)}
                    className="flex size-8 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                    aria-label="返回角色卡"
                    title="返回角色卡"
                  >
                    <ChevronRightIcon className="size-4 rotate-180" />
                  </button>
                  <div className="min-w-0 flex-1 text-center text-xl font-semibold text-foreground">
                    角色说明
                  </div>
                  <span className="w-8" aria-hidden="true" />
                </div>
                <div className="mt-6 flex items-center gap-3 rounded-lg bg-muted/35 px-3 py-2">
                  <span className="flex size-10 shrink-0 items-center justify-center rounded-full bg-background text-xl">
                    {agent.avatar || (
                      <BotIcon className="size-5 text-muted-foreground" />
                    )}
                  </span>
                  <div className="min-w-0">
                    <div className="truncate text-sm font-semibold text-foreground">
                      {displayName}
                    </div>
                    <div className="truncate text-xs text-muted-foreground">
                      {roleName}
                    </div>
                  </div>
                  <span className="ml-auto font-mono text-sm text-foreground">
                    {agent.label}
                  </span>
                </div>
                <div className="mt-5 max-h-72 flex-1 overflow-y-auto whitespace-pre-wrap break-words text-base leading-7 text-foreground">
                  {fullBrief || "暂无完整角色说明。"}
                </div>
              </div>
            ) : (
              <>
                <div className="rounded-md bg-foreground px-3 py-2 text-base font-semibold text-background">
                  {displayName}
                </div>
                <div className="mt-12 flex size-28 items-center justify-center rounded-lg border border-border bg-muted/20">
                  {agent.avatar ? (
                    <span className="text-5xl" aria-hidden="true">
                      {agent.avatar}
                    </span>
                  ) : (
                    <BotIcon className="size-14 text-foreground" />
                  )}
                </div>
                <div className="mt-8 text-2xl font-semibold tracking-normal text-foreground">
                  {roleName}
                </div>
                <p className="mt-3 line-clamp-3 text-base leading-7 text-muted-foreground">
                  {motto}
                </p>
                <div className="my-5 border-t border-dashed border-border" />
                <div className="flex items-end gap-3">
                  <div className="text-3xl font-bold tracking-normal text-foreground">
                    OCTOPUS
                  </div>
                  <button
                    type="button"
                    onClick={() => setShowBrief(true)}
                    className="ml-auto rounded-md bg-foreground px-2.5 py-1.5 text-xs font-medium text-background transition-opacity hover:opacity-85"
                    title="查看角色说明"
                  >
                    角色说明
                  </button>
                </div>
                <div className="mt-3 flex items-center gap-2">
                  <span
                    className={cn(
                      "inline-flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs font-medium",
                      agentStatusClass(agent.status),
                      active ? "bg-emerald-500/10" : "bg-muted",
                    )}
                  >
                    {active && <Loader2Icon className="size-3 animate-spin" />}
                    {agentStatusLabel(agent.status)}
                  </span>
                  {agent.iterationCount !== undefined && (
                    <span className="text-xs text-muted-foreground">
                      {agent.iterationCount} 轮
                    </span>
                  )}
                </div>
              </>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}

export function isAgentCreationBlock(
  block: WorkBlock | null | undefined,
): boolean {
  const event = block?.event;
  return Boolean(
    event &&
    (event.lifecycle === "spawned" || /subagent_spawned/i.test(event.name)),
  );
}

export function isAgentLifecycleBlock(block: WorkBlock): boolean {
  return Boolean(
    block.event.lifecycle ||
    /subagent_(spawned|finished)/i.test(block.event.name),
  );
}

export function pickCurrentScreenFrame(blocks: WorkBlock[]): WorkBlock | null {
  const newestFirst = [...blocks].reverse();
  return (
    newestFirst.find(
      (block) =>
        !isAgentLifecycleBlock(block) &&
        (block.status === "running" || block.status === "waiting_approval"),
    ) ??
    newestFirst.find((block) => !isAgentLifecycleBlock(block)) ??
    pickCurrentWorkBlock(blocks) ??
    blocks[blocks.length - 1] ??
    null
  );
}

export function agentTileForBlock(
  block: WorkBlock | null | undefined,
  agents: AgentTile[],
): AgentTile | undefined {
  const event = block?.event;
  if (!event) return undefined;
  const id = agentEventGroupId(event);
  return agents.find(
    (agent) =>
      agent.id === id ||
      agent.id === event.agentId ||
      agent.codename === event.subagentCodename ||
      agent.name === event.agentName ||
      agent.role === event.subAgentRole,
  );
}

export function findAgentTileByFocusId(
  focusId: string,
  agents: AgentTile[],
): AgentTile | undefined {
  return agents.find((agent) =>
    [
      agent.id,
      agent.codename,
      agent.name,
      agent.role,
      agent.parentToolUseId,
      agent.label,
    ].some((value) => value === focusId),
  );
}

export function friendlyRoleName(role: string | undefined | null): string {
  const value = role?.trim();
  if (!value) return "Task Agent";
  const lower = value.toLowerCase();
  const map: Record<string, string> = {
    architect: "Architect",
    critic: "Reviewer",
    debugger: "Debugger",
    designer: "Designer",
    implementer: "Builder",
    planner: "Planner",
    researcher: "Researcher",
    reviewer: "Reviewer",
    security: "Security Reviewer",
    synthesizer: "Synthesizer",
    writer: "Writer",
  };
  return map[lower] ?? value.replace(/[_-]+/g, " ");
}

export function AgentFilesPage({
  recentFileEvents,
  threadId,
  workDir,
}: {
  recentFileEvents: FileTreeEvent[];
  threadId?: string | null;
  workDir?: string;
}) {
  if (!workDir) {
    return (
      <WorkbenchEmptyPage
        title={FILES_TAB_LABEL}
        description="还没有定位到工作目录。Agent 读取或写入文件后，这里会自动关联项目文件。"
      />
    );
  }
  return (
    <div className="flex min-h-0 flex-1 flex-col bg-background/70 p-2">
      <FileTree
        workDir={workDir}
        threadId={threadId}
        recentFileEvents={recentFileEvents}
        className="min-h-0 flex-1 overflow-auto rounded-md border border-border/55 bg-background/80"
      />
    </div>
  );
}

export function DiffText({ text }: { text: string }) {
  const lines = text.split(/\r?\n/);
  return (
    <pre className="max-h-[22rem] overflow-auto whitespace-pre-wrap break-words px-3 py-2.5 font-mono text-[11px] leading-5 text-foreground/80">
      {lines.map((line, index) => (
        <span
          key={`${index}-${line}`}
          className={cn(
            "block min-h-5",
            line.startsWith("+") &&
              !line.startsWith("+++") &&
              "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300",
            line.startsWith("-") &&
              !line.startsWith("---") &&
              "bg-destructive/10 text-destructive",
            (line.startsWith("@@") ||
              line.startsWith("diff --git") ||
              line.startsWith("+++") ||
              line.startsWith("---")) &&
              "text-muted-foreground",
          )}
        >
          {line || " "}
        </span>
      ))}
    </pre>
  );
}

export function AgentDiffPage({ entries }: { entries: DiffEntry[] }) {
  if (entries.length === 0) {
    return (
      <WorkbenchEmptyPage
        title={DIFF_TAB_LABEL}
        description="还没有捕获到可展示的 diff。文件编辑工具返回补丁后会显示在这里。"
      />
    );
  }
  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-y-auto bg-background/70 p-3">
      <div className="mx-auto w-full max-w-2xl space-y-3">
        {entries.map((entry) => (
          <section
            key={entry.id}
            className="overflow-hidden rounded-lg border border-border/55 bg-background/85 shadow-sm"
          >
            <div className="flex items-center gap-2 border-b border-border/45 px-3 py-2">
              <StatusGlyph status={entry.status} />
              <GitBranchIcon className="size-4 shrink-0 text-muted-foreground" />
              <span className="min-w-0 flex-1 truncate text-xs font-semibold text-foreground">
                {entry.title}
              </span>
            </div>
            <DiffText text={entry.text} />
          </section>
        ))}
      </div>
    </div>
  );
}
