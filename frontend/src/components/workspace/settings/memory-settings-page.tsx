import {
  AlertTriangleIcon,
  DownloadIcon,
  Loader2Icon,
  PenLineIcon,
  PlusIcon,
  RefreshCwIcon,
  SearchIcon,
  Trash2Icon,
  UploadIcon,
} from "lucide-react";
import { Link } from "react-router-dom";
import {
  Suspense,
  lazy,
  useDeferredValue,
  useEffect,
  useId,
  useRef,
  useState,
} from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { useI18n } from "@/core/i18n/hooks";
import { exportMemory, searchMemory } from "@/core/memory/api";
import {
  useClearMemory,
  useCreateMemoryFact,
  useDeleteMemoryFact,
  useImportMemory,
  useMemory,
  useMemoryConfig,
  useUpdateMemoryConfig,
  useUpdateMemoryFact,
} from "@/core/memory/hooks";
import type {
  MemoryFactInput,
  MemoryFactPatchInput,
  MemoryConfigPatch,
  MemorySearchResult,
  UserMemory,
} from "@/core/memory/types";
import { useStreamdownPlugins } from "@/core/streamdown";
import { pathOfThread } from "@/core/threads/utils";
import { formatTimeAgo } from "@/core/utils/datetime";
import { cn } from "@/lib/utils";

import { SettingsSection } from "./settings-section";
import { getMemoryLoadErrorCopy } from "./settings-resilience";

const LazyStreamdown = lazy(
  () => import("@/components/ai-elements/streamdown-host"),
);

type MemoryViewFilter = "all" | "facts" | "summaries";
type MemoryFact = UserMemory["facts"][number];

type MemorySection = {
  title: string;
  summary: string;
  updatedAt?: string;
};

type MemorySectionGroup = {
  title: string;
  sections: MemorySection[];
};

type PendingImport = {
  fileName: string;
  memory: UserMemory;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isMemorySection(value: unknown): value is {
  summary: string;
  updatedAt: string;
} {
  return (
    isRecord(value) &&
    typeof value.summary === "string" &&
    typeof value.updatedAt === "string"
  );
}

function isMemoryFact(value: unknown): value is UserMemory["facts"][number] {
  return (
    isRecord(value) &&
    typeof value.id === "string" &&
    typeof value.content === "string" &&
    typeof value.category === "string" &&
    typeof value.confidence === "number" &&
    Number.isFinite(value.confidence) &&
    typeof value.createdAt === "string" &&
    typeof value.source === "string"
  );
}

function isImportedMemory(value: unknown): value is UserMemory {
  if (!isRecord(value)) {
    return false;
  }

  if (
    typeof value.version !== "string" ||
    typeof value.lastUpdated !== "string" ||
    !isRecord(value.user) ||
    !isRecord(value.history) ||
    !Array.isArray(value.facts)
  ) {
    return false;
  }

  return (
    isMemorySection(value.user.workContext) &&
    isMemorySection(value.user.personalContext) &&
    isMemorySection(value.user.topOfMind) &&
    isMemorySection(value.history.recentMonths) &&
    isMemorySection(value.history.earlierContext) &&
    isMemorySection(value.history.longTermBackground) &&
    value.facts.every(isMemoryFact)
  );
}

type FactFormState = {
  content: string;
  category: string;
  confidence: string;
};

const DEFAULT_FACT_FORM_STATE: FactFormState = {
  content: "",
  category: "context",
  confidence: "0.8",
};

function confidenceToLevelKey(confidence: unknown): {
  key: "veryHigh" | "high" | "normal" | "unknown";
  value?: number;
} {
  if (typeof confidence !== "number" || !Number.isFinite(confidence)) {
    return { key: "unknown" };
  }

  const value = Math.min(1, Math.max(0, confidence));
  if (value >= 0.85) return { key: "veryHigh", value };
  if (value >= 0.65) return { key: "high", value };
  return { key: "normal", value };
}

function formatMemorySection(
  section: MemorySection,
  t: ReturnType<typeof useI18n>["t"],
): string {
  const content =
    safeSummary(section) ||
    `<span class="text-muted-foreground">${t.settings.memory.markdown.empty}</span>`;
  return [
    `### ${section.title}`,
    content,
    "",
    section.updatedAt &&
      `> ${t.settings.memory.markdown.updatedAt}: \`${formatTimeAgo(section.updatedAt)}\``,
  ]
    .filter(Boolean)
    .join("\n");
}

function buildMemorySectionGroups(
  memory: UserMemory,
  t: ReturnType<typeof useI18n>["t"],
): MemorySectionGroup[] {
  // Implementation note.
  // Implementation note.
  const user = memory.user ?? ({} as UserMemory["user"]);
  const history = memory.history ?? ({} as UserMemory["history"]);
  const read = (
    s: { summary?: string; updatedAt?: string } | undefined | null,
  ): { summary: string; updatedAt: string } => ({
    summary: s?.summary ?? "",
    updatedAt: s?.updatedAt ?? "",
  });
  return [
    {
      title: t.settings.memory.markdown.userContext,
      sections: [
        {
          title: t.settings.memory.markdown.work,
          ...read(user.workContext),
        },
        {
          title: t.settings.memory.markdown.personal,
          ...read(user.personalContext),
        },
        {
          title: t.settings.memory.markdown.topOfMind,
          ...read(user.topOfMind),
        },
      ],
    },
    {
      title: t.settings.memory.markdown.historyBackground,
      sections: [
        {
          title: t.settings.memory.markdown.recentMonths,
          ...read(history.recentMonths),
        },
        {
          title: t.settings.memory.markdown.earlierContext,
          ...read(history.earlierContext),
        },
        {
          title: t.settings.memory.markdown.longTermBackground,
          ...read(history.longTermBackground),
        },
      ],
    },
  ];
}

function summariesToMarkdown(
  memory: UserMemory,
  sectionGroups: MemorySectionGroup[],
  t: ReturnType<typeof useI18n>["t"],
) {
  const parts: string[] = [];

  parts.push(`## ${t.settings.memory.markdown.overview}`);
  parts.push(
    `- **${t.common.lastUpdated}**: \`${formatTimeAgo(memory.lastUpdated)}\``,
  );

  for (const group of sectionGroups) {
    parts.push(`\n## ${group.title}`);
    for (const section of group.sections) {
      parts.push(formatMemorySection(section, t));
    }
  }

  const markdown = parts.join("\n\n");
  const lines = markdown.split("\n");
  const out: string[] = [];
  let i = 0;
  for (const line of lines) {
    i++;
    if (i !== 1 && line.startsWith("## ")) {
      if (out.length === 0 || out[out.length - 1] !== "---") {
        out.push("---");
      }
    }
    out.push(line);
  }

  return out.join("\n");
}

// Implementation note.
// Implementation note.
// Implementation note.
// Implementation note.
function safeSummary(section: { summary?: string } | undefined | null): string {
  return (section?.summary ?? "").trim();
}

function isMemorySummaryEmpty(memory: UserMemory) {
  const user = memory.user ?? ({} as UserMemory["user"]);
  const history = memory.history ?? ({} as UserMemory["history"]);
  return (
    safeSummary(user.workContext) === "" &&
    safeSummary(user.personalContext) === "" &&
    safeSummary(user.topOfMind) === "" &&
    safeSummary(history.recentMonths) === "" &&
    safeSummary(history.earlierContext) === "" &&
    safeSummary(history.longTermBackground) === ""
  );
}

function truncateFactPreview(content: string, maxLength = 140) {
  const normalized = content.replace(/\s+/g, " ").trim();
  if (normalized.length <= maxLength) {
    return normalized;
  }
  const ellipsis = "...";
  if (maxLength <= ellipsis.length) {
    return normalized.slice(0, maxLength);
  }
  return `${normalized.slice(0, maxLength - ellipsis.length)}${ellipsis}`;
}

function upperFirst(str: string) {
  return str.charAt(0).toUpperCase() + str.slice(1);
}

function factScopeLabel(
  fact: MemoryFact,
  t: {
    settings: {
      memory: { projectScope: string; agentScope: string; globalScope: string };
    };
  },
) {
  if (fact.scope === "project" && fact.project)
    return `${t.settings.memory.projectScope}${fact.project}`;
  if (fact.scope === "agent" && fact.agent_id)
    return `${t.settings.memory.agentScope}${fact.agent_id}`;
  return t.settings.memory.globalScope;
}

function isThreadSource(source: string) {
  return source !== "manual" && !source.includes(":") && source.length > 8;
}

export default function MemorySettingsPage() {
  const { t, locale } = useI18n();
  const streamdownPlugins = useStreamdownPlugins();
  const { memory, isLoading, error, refetch, isRefreshing } = useMemory();
  const { config: memoryConfig } = useMemoryConfig();
  const updateMemoryConfig = useUpdateMemoryConfig();
  const clearMemory = useClearMemory();
  const createMemoryFact = useCreateMemoryFact();
  const deleteMemoryFact = useDeleteMemoryFact();
  const importMemoryMutation = useImportMemory();
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const updateMemoryFact = useUpdateMemoryFact();
  const [clearDialogOpen, setClearDialogOpen] = useState(false);
  const [factToDelete, setFactToDelete] = useState<MemoryFact | null>(null);
  const [factToEdit, setFactToEdit] = useState<MemoryFact | null>(null);
  const [factEditorOpen, setFactEditorOpen] = useState(false);
  const [factForm, setFactForm] = useState<FactFormState>(
    DEFAULT_FACT_FORM_STATE,
  );
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<MemoryViewFilter>("all");
  const [pendingImport, setPendingImport] = useState<PendingImport | null>(
    null,
  );
  const [isExporting, setIsExporting] = useState(false);
  const deferredQuery = useDeferredValue(query);
  const normalizedQuery = deferredQuery.trim().toLowerCase();
  const [backendSearchResults, setBackendSearchResults] = useState<
    MemorySearchResult[] | null
  >(null);
  const [isSearching, setIsSearching] = useState(false);
  const searchAbortRef = useRef<AbortController | null>(null);

  // Debounced backend FTS5 search
  useEffect(() => {
    if (!normalizedQuery) {
      setBackendSearchResults(null);
      setIsSearching(false);
      return;
    }

    setIsSearching(true);
    const timer = window.setTimeout(() => {
      searchAbortRef.current?.abort();
      const controller = new AbortController();
      searchAbortRef.current = controller;

      searchMemory(deferredQuery.trim(), 100)
        .then((results) => {
          if (!controller.signal.aborted) {
            setBackendSearchResults(results);
            setIsSearching(false);
          }
        })
        .catch(() => {
          if (!controller.signal.aborted) {
            // Fallback: clear backend results so client-side filter is used
            setBackendSearchResults(null);
            setIsSearching(false);
          }
        });
    }, 300);

    return () => {
      window.clearTimeout(timer);
    };
  }, [normalizedQuery, deferredQuery]);

  const factContentInputId = useId();
  const factCategoryInputId = useId();
  const factConfidenceInputId = useId();
  const factConfidenceHintId = useId();

  const clearAllLabel = t.settings.memory.clearAll ?? "Clear all memory";
  const clearAllConfirmTitle =
    t.settings.memory.clearAllConfirmTitle ?? "Clear all memory?";
  const clearAllConfirmDescription =
    t.settings.memory.clearAllConfirmDescription ??
    "This will remove all saved summaries and facts. This action cannot be undone.";
  const clearAllSuccess =
    t.settings.memory.clearAllSuccess ?? "All memory cleared";
  const factDeleteConfirmTitle =
    t.settings.memory.factDeleteConfirmTitle ?? "Delete this fact?";
  const factDeleteConfirmDescription =
    t.settings.memory.factDeleteConfirmDescription ??
    "This fact will be removed from memory immediately. This action cannot be undone.";
  const factDeleteSuccess =
    t.settings.memory.factDeleteSuccess ?? "Fact deleted";
  const addFactLabel = t.settings.memory.addFact;
  const addFactTitle = t.settings.memory.addFactTitle;
  const editFactTitle = t.settings.memory.editFactTitle;
  const addFactSuccess = t.settings.memory.addFactSuccess;
  const editFactSuccess = t.settings.memory.editFactSuccess;
  const factContentLabel = t.settings.memory.factContentLabel;
  const factCategoryLabel = t.settings.memory.factCategoryLabel;
  const factConfidenceLabel = t.settings.memory.factConfidenceLabel;
  const factContentPlaceholder = t.settings.memory.factContentPlaceholder;
  const factCategoryPlaceholder = t.settings.memory.factCategoryPlaceholder;
  const factConfidenceHint = t.settings.memory.factConfidenceHint;
  const factSave = t.settings.memory.factSave;
  const factValidationContent = t.settings.memory.factValidationContent;
  const factValidationConfidence = t.settings.memory.factValidationConfidence;
  const noFacts = t.settings.memory.noFacts ?? "No saved facts yet.";
  const summaryReadOnly = t.settings.memory.summaryReadOnly;
  const memoryFullyEmpty =
    t.settings.memory.memoryFullyEmpty ?? "No memory saved yet.";
  const factPreviewLabel =
    t.settings.memory.factPreviewLabel ?? "Fact to delete";
  const searchPlaceholder =
    t.settings.memory.searchPlaceholder ?? "Search memory";
  const filterAll = t.settings.memory.filterAll ?? "All";
  const filterFacts = t.settings.memory.filterFacts ?? "Facts";
  const filterSummaries = t.settings.memory.filterSummaries ?? "Summaries";
  const noMatches = t.settings.memory.noMatches ?? "No matching memory found";
  const exportButton = t.settings.memory.exportButton ?? t.common.export;
  const exportSuccess =
    t.settings.memory.exportSuccess ?? t.common.exportSuccess;
  const importButton = t.settings.memory.importButton ?? t.common.import;
  const importSuccess = t.settings.memory.importSuccess ?? "Memory imported";
  const memoryConfigEnabled = memoryConfig?.enabled ?? true;
  const autoCaptureEnabled = memoryConfig?.auto_capture_enabled ?? true;
  const injectionEnabled = memoryConfig?.injection_enabled ?? true;

  async function handleMemoryConfigChange(patch: MemoryConfigPatch) {
    try {
      await updateMemoryConfig.mutateAsync(patch);
      toast.success(t.settings.memory.saved);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    }
  }

  const sectionGroups = memory ? buildMemorySectionGroups(memory, t) : [];
  const filteredSectionGroups = sectionGroups
    .map((group) => ({
      ...group,
      sections: group.sections.filter((section) =>
        normalizedQuery
          ? `${section.title} ${section.summary}`
              .toLowerCase()
              .includes(normalizedQuery)
          : true,
      ),
    }))
    .filter((group) => group.sections.length > 0);

  // Use backend FTS5 results when available; fall back to client-side filter
  const filteredFacts = (() => {
    if (!memory) return [];
    if (!normalizedQuery) return memory.facts;
    if (backendSearchResults !== null) {
      // Map backend results back to local facts for consistent rendering,
      // preserving relevance ordering from the backend.
      const factMap = new Map(memory.facts.map((f) => [f.id, f]));
      const matched: MemoryFact[] = [];
      for (const sr of backendSearchResults) {
        const local = factMap.get(sr.id);
        if (local) matched.push(local);
      }
      return matched;
    }
    // Client-side fallback (e.g. backend unreachable)
    return memory.facts.filter((fact) =>
      `${fact.content} ${fact.category}`
        .toLowerCase()
        .includes(normalizedQuery),
    );
  })();

  const showSummaries = filter !== "facts";
  const showFacts = filter !== "summaries";
  const shouldRenderSummariesBlock =
    showSummaries && (filteredSectionGroups.length > 0 || !normalizedQuery);
  const shouldRenderFactsBlock =
    showFacts &&
    (filteredFacts.length > 0 || !normalizedQuery || filter === "facts");
  const hasMatchingVisibleContent =
    !memory ||
    (showSummaries && filteredSectionGroups.length > 0) ||
    (showFacts && filteredFacts.length > 0);

  async function handleExportMemory() {
    try {
      setIsExporting(true);
      const exportedMemory = await exportMemory();
      const fileName = `octopus-memory-${(exportedMemory.lastUpdated || new Date().toISOString()).replace(/[:.]/g, "-")}.json`;
      const blob = new Blob([JSON.stringify(exportedMemory, null, 2)], {
        type: "application/json",
      });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = fileName;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
      toast.success(exportSuccess);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    } finally {
      setIsExporting(false);
    }
  }

  async function handleImportFileSelection(event: {
    target: HTMLInputElement;
  }) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) {
      return;
    }

    try {
      const parsed: unknown = JSON.parse(await file.text());
      if (!isImportedMemory(parsed)) {
        toast.error(t.settings.memory.importInvalidFile);
        return;
      }
      setPendingImport({
        fileName: file.name,
        memory: parsed,
      });
    } catch {
      toast.error(t.settings.memory.importInvalidFile);
    }
  }

  async function handleConfirmImport() {
    if (!pendingImport) {
      return;
    }

    try {
      await importMemoryMutation.mutateAsync(pendingImport.memory);
      toast.success(importSuccess);
      setPendingImport(null);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    }
  }

  async function handleClearMemory() {
    try {
      await clearMemory.mutateAsync();
      toast.success(clearAllSuccess);
      setClearDialogOpen(false);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    }
  }

  async function handleDeleteFact() {
    if (!factToDelete) return;

    try {
      await deleteMemoryFact.mutateAsync(factToDelete.id);
      toast.success(factDeleteSuccess);
      setFactToDelete(null);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    }
  }

  function openCreateFactDialog() {
    setFactToEdit(null);
    setFactForm(DEFAULT_FACT_FORM_STATE);
    setFactEditorOpen(true);
  }

  function openEditFactDialog(fact: MemoryFact) {
    setFactToEdit(fact);
    setFactForm({
      content: fact.content,
      category: fact.category,
      confidence: String(fact.confidence),
    });
    setFactEditorOpen(true);
  }

  async function handleSaveFact() {
    const trimmedContent = factForm.content.trim();
    if (!trimmedContent) {
      toast.error(factValidationContent);
      return;
    }

    const confidence = Number(factForm.confidence);
    if (!Number.isFinite(confidence) || confidence < 0 || confidence > 1) {
      toast.error(factValidationConfidence);
      return;
    }

    const input: MemoryFactInput = {
      content: trimmedContent,
      category: factForm.category.trim() || "context",
      confidence,
    };

    try {
      if (factToEdit) {
        const patchInput: MemoryFactPatchInput = {
          content: input.content,
          category: input.category,
          confidence: input.confidence,
        };
        await updateMemoryFact.mutateAsync({
          factId: factToEdit.id,
          input: patchInput,
        });
        toast.success(editFactSuccess);
      } else {
        await createMemoryFact.mutateAsync(input);
        toast.success(addFactSuccess);
      }
      setFactEditorOpen(false);
      setFactToEdit(null);
      setFactForm(DEFAULT_FACT_FORM_STATE);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    }
  }

  const isFactFormPending =
    createMemoryFact.isPending || updateMemoryFact.isPending;

  return (
    <>
      <SettingsSection
        title={t.settings.memory.title}
        description={t.settings.memory.description}
      >
        {isLoading ? (
          <div className="text-muted-foreground text-sm">
            {t.common.loading}
          </div>
        ) : error ? (
          <div
            role="alert"
            className="flex flex-col items-start justify-between gap-3 rounded-lg border border-destructive/20 bg-destructive/[0.04] px-4 py-3 sm:flex-row sm:items-center"
          >
            <div className="flex min-w-0 items-start gap-2 text-sm text-destructive">
              <AlertTriangleIcon className="mt-0.5 size-4 shrink-0" />
              <span>{getMemoryLoadErrorCopy(locale)}</span>
            </div>
            <Button
              type="button"
              size="sm"
              variant="outline"
              className="w-full shrink-0 sm:w-auto"
              disabled={isRefreshing}
              onClick={() => void refetch()}
            >
              <RefreshCwIcon
                className={cn(
                  "mr-1.5 size-3.5",
                  isRefreshing && "animate-spin",
                )}
              />
              {t.errorBoundary.retry}
            </Button>
          </div>
        ) : !memory ? (
          <div className="text-muted-foreground text-sm">
            {t.settings.memory.empty}
          </div>
        ) : (
          <div className="space-y-4">
            <div className="rounded-lg border p-4">
              <div className="grid gap-3 md:grid-cols-3">
                <div className="flex items-start justify-between gap-3 rounded-md border bg-muted/30 p-3">
                  <div className="min-w-0">
                    <div className="text-sm font-medium">
                      {t.settings.memory.enableMemory}
                    </div>
                    <div className="text-muted-foreground mt-1 text-xs">
                      {t.settings.memory.enableMemoryDesc}
                    </div>
                  </div>
                  <Switch
                    checked={memoryConfigEnabled}
                    disabled={updateMemoryConfig.isPending}
                    onCheckedChange={(enabled) =>
                      void handleMemoryConfigChange({ enabled })
                    }
                  />
                </div>

                <div className="flex items-start justify-between gap-3 rounded-md border bg-muted/30 p-3">
                  <div className="min-w-0">
                    <div className="text-sm font-medium">
                      {t.settings.memory.autoCapture}
                    </div>
                    <div className="text-muted-foreground mt-1 text-xs">
                      {t.settings.memory.autoCaptureDesc}
                    </div>
                  </div>
                  <Switch
                    checked={memoryConfigEnabled && autoCaptureEnabled}
                    disabled={
                      !memoryConfigEnabled || updateMemoryConfig.isPending
                    }
                    onCheckedChange={(auto_capture_enabled) =>
                      void handleMemoryConfigChange({ auto_capture_enabled })
                    }
                  />
                </div>

                <div className="flex items-start justify-between gap-3 rounded-md border bg-muted/30 p-3">
                  <div className="min-w-0">
                    <div className="text-sm font-medium">
                      {t.settings.memory.injectOnReply}
                    </div>
                    <div className="text-muted-foreground mt-1 text-xs">
                      {t.settings.memory.injectOnReplyDesc}
                    </div>
                  </div>
                  <Switch
                    checked={memoryConfigEnabled && injectionEnabled}
                    disabled={
                      !memoryConfigEnabled || updateMemoryConfig.isPending
                    }
                    onCheckedChange={(injection_enabled) =>
                      void handleMemoryConfigChange({ injection_enabled })
                    }
                  />
                </div>
              </div>
            </div>

            {isMemorySummaryEmpty(memory) && memory.facts.length === 0 ? (
              <div className="text-muted-foreground rounded-lg border border-dashed p-4 text-sm">
                {memoryFullyEmpty}
              </div>
            ) : null}

            <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
              <div className="flex flex-1 flex-col gap-3 sm:flex-row sm:items-center">
                <div className="relative sm:max-w-xs w-full">
                  <SearchIcon className="text-muted-foreground absolute left-2.5 top-2.5 size-4" />
                  <Input
                    value={query}
                    onChange={(event) => setQuery(event.target.value)}
                    placeholder={searchPlaceholder}
                    className="pl-9 pr-9"
                  />
                  {isSearching && normalizedQuery ? (
                    <Loader2Icon className="text-muted-foreground absolute right-2.5 top-2.5 size-4 animate-spin" />
                  ) : null}
                </div>
                <ToggleGroup
                  type="single"
                  value={filter}
                  onValueChange={(value) => {
                    if (value) setFilter(value as MemoryViewFilter);
                  }}
                  variant="outline"
                >
                  <ToggleGroupItem value="all">{filterAll}</ToggleGroupItem>
                  <ToggleGroupItem value="facts">{filterFacts}</ToggleGroupItem>
                  <ToggleGroupItem value="summaries">
                    {filterSummaries}
                  </ToggleGroupItem>
                </ToggleGroup>
              </div>

              <div className="flex flex-wrap gap-2">
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".json,application/json"
                  className="hidden"
                  onChange={(event) => void handleImportFileSelection(event)}
                />
                <Button
                  variant="outline"
                  onClick={() => fileInputRef.current?.click()}
                  disabled={importMemoryMutation.isPending}
                >
                  <UploadIcon className="mr-2 h-4 w-4" />
                  {importButton}
                </Button>
                <Button
                  variant="outline"
                  onClick={() => void handleExportMemory()}
                  disabled={isExporting}
                >
                  <DownloadIcon className="mr-2 h-4 w-4" />
                  {isExporting ? t.common.loading : exportButton}
                </Button>
                <Button variant="outline" onClick={openCreateFactDialog}>
                  <PlusIcon className="mr-2 h-4 w-4" />
                  {addFactLabel}
                </Button>
                <Button
                  variant="destructive"
                  onClick={() => setClearDialogOpen(true)}
                  disabled={clearMemory.isPending}
                >
                  {clearMemory.isPending ? t.common.loading : clearAllLabel}
                </Button>
              </div>
            </div>

            {!hasMatchingVisibleContent && normalizedQuery ? (
              <div className="text-muted-foreground rounded-lg border border-dashed p-4 text-sm">
                {noMatches}
              </div>
            ) : null}

            {shouldRenderSummariesBlock ? (
              <div className="rounded-lg border p-4">
                <div className="text-muted-foreground mb-4 text-sm">
                  {summaryReadOnly}
                </div>
                <Suspense
                  fallback={
                    <div className="whitespace-pre-wrap break-words">
                      {summariesToMarkdown(memory, filteredSectionGroups, t)}
                    </div>
                  }
                >
                  <LazyStreamdown
                    className="size-full [&>*:first-child]:mt-0 [&>*:last-child]:mb-0"
                    {...streamdownPlugins}
                  >
                    {summariesToMarkdown(memory, filteredSectionGroups, t)}
                  </LazyStreamdown>
                </Suspense>
              </div>
            ) : null}

            {shouldRenderFactsBlock ? (
              <div className="rounded-lg border p-4">
                <div className="mb-4">
                  <h3 className="text-base font-medium">
                    {t.settings.memory.markdown.facts}
                  </h3>
                </div>

                {filteredFacts.length === 0 ? (
                  <div className="text-muted-foreground text-sm">
                    {normalizedQuery ? noMatches : noFacts}
                  </div>
                ) : (
                  <div className="space-y-3">
                    {filteredFacts.map((fact) => {
                      const { key } = confidenceToLevelKey(fact.confidence);
                      const confidenceText =
                        t.settings.memory.markdown.table.confidenceLevel[key];

                      return (
                        <div
                          key={fact.id}
                          className="flex flex-col gap-3 rounded-lg border p-3 sm:flex-row sm:items-start sm:justify-between"
                        >
                          <div className="min-w-0 space-y-2">
                            <div className="flex flex-wrap gap-x-4 gap-y-1 text-sm">
                              <span>
                                <span className="text-muted-foreground">
                                  {t.settings.memory.markdown.table.category}:
                                </span>{" "}
                                {upperFirst(fact.category)}
                              </span>
                              <span>
                                <span className="text-muted-foreground">
                                  {t.settings.memory.markdown.table.confidence}:
                                </span>{" "}
                                {confidenceText}
                              </span>
                              <span>
                                <span className="text-muted-foreground">
                                  {t.settings.memory.markdown.table.createdAt}:
                                </span>{" "}
                                {formatTimeAgo(fact.createdAt)}
                              </span>
                              <span>
                                <span className="text-muted-foreground">
                                  {t.settings.memory.markdown.table.source}:
                                </span>{" "}
                                {fact.source === "manual" ? (
                                  t.settings.memory.manualFactSource
                                ) : isThreadSource(fact.source) ? (
                                  <Link
                                    to={pathOfThread(fact.source)}
                                    className="text-primary underline-offset-4 hover:underline"
                                  >
                                    {t.settings.memory.markdown.table.view}
                                  </Link>
                                ) : (
                                  fact.source
                                )}
                              </span>
                              <span>
                                <span className="text-muted-foreground">
                                  {t.settings.memory.scopeLabel}
                                </span>{" "}
                                {factScopeLabel(fact, t)}
                              </span>
                            </div>
                            <p className="text-sm break-words">
                              {fact.content}
                            </p>
                          </div>

                          <div className="flex shrink-0 items-center gap-1 self-start sm:ml-3">
                            <Button
                              variant="ghost"
                              size="icon"
                              className="shrink-0"
                              onClick={() => openEditFactDialog(fact)}
                              disabled={deleteMemoryFact.isPending}
                              title={t.common.edit}
                              aria-label={t.common.edit}
                            >
                              <PenLineIcon className="h-4 w-4" />
                            </Button>

                            <Button
                              variant="ghost"
                              size="icon"
                              className="text-destructive hover:text-destructive shrink-0"
                              onClick={() => setFactToDelete(fact)}
                              disabled={deleteMemoryFact.isPending}
                              title={t.common.delete}
                              aria-label={t.common.delete}
                            >
                              <Trash2Icon className="h-4 w-4" />
                            </Button>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            ) : null}
          </div>
        )}
      </SettingsSection>

      <Dialog open={clearDialogOpen} onOpenChange={setClearDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{clearAllConfirmTitle}</DialogTitle>
            <DialogDescription>{clearAllConfirmDescription}</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setClearDialogOpen(false)}
              disabled={clearMemory.isPending}
            >
              {t.common.cancel}
            </Button>
            <Button
              variant="destructive"
              onClick={() => void handleClearMemory()}
              disabled={clearMemory.isPending}
            >
              {clearMemory.isPending ? t.common.loading : clearAllLabel}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={factEditorOpen}
        onOpenChange={(open) => {
          setFactEditorOpen(open);
          if (!open) {
            setFactToEdit(null);
            setFactForm(DEFAULT_FACT_FORM_STATE);
          }
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {factToEdit ? editFactTitle : addFactTitle}
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <label
                className="text-sm font-medium"
                htmlFor={factContentInputId}
              >
                {factContentLabel}
              </label>
              <Textarea
                id={factContentInputId}
                value={factForm.content}
                onChange={(event) =>
                  setFactForm((current) => ({
                    ...current,
                    content: event.target.value,
                  }))
                }
                placeholder={factContentPlaceholder}
                rows={4}
              />
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-2">
                <label
                  className="text-sm font-medium"
                  htmlFor={factCategoryInputId}
                >
                  {factCategoryLabel}
                </label>
                <Input
                  id={factCategoryInputId}
                  value={factForm.category}
                  onChange={(event) =>
                    setFactForm((current) => ({
                      ...current,
                      category: event.target.value,
                    }))
                  }
                  placeholder={factCategoryPlaceholder}
                />
              </div>

              <div className="space-y-2">
                <label
                  className="text-sm font-medium"
                  htmlFor={factConfidenceInputId}
                >
                  {factConfidenceLabel}
                </label>
                <Input
                  id={factConfidenceInputId}
                  aria-describedby={factConfidenceHintId}
                  type="number"
                  min="0"
                  max="1"
                  step="0.01"
                  value={factForm.confidence}
                  onChange={(event) =>
                    setFactForm((current) => ({
                      ...current,
                      confidence: event.target.value,
                    }))
                  }
                />
                <div
                  className="text-muted-foreground text-xs"
                  id={factConfidenceHintId}
                >
                  {factConfidenceHint}
                </div>
              </div>
            </div>
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => {
                setFactEditorOpen(false);
                setFactToEdit(null);
                setFactForm(DEFAULT_FACT_FORM_STATE);
              }}
              disabled={isFactFormPending}
            >
              {t.common.cancel}
            </Button>
            <Button
              onClick={() => void handleSaveFact()}
              disabled={isFactFormPending}
            >
              {isFactFormPending ? t.common.loading : factSave}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={factToDelete !== null}
        onOpenChange={(open) => {
          if (!open) {
            setFactToDelete(null);
          }
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{factDeleteConfirmTitle}</DialogTitle>
            <DialogDescription>
              {factDeleteConfirmDescription}
            </DialogDescription>
          </DialogHeader>
          {factToDelete ? (
            <div className="bg-muted rounded-lg border p-3 text-sm">
              <div className="text-muted-foreground mb-1 font-medium">
                {factPreviewLabel}
              </div>
              <p className="break-words">
                {truncateFactPreview(factToDelete.content)}
              </p>
            </div>
          ) : null}
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setFactToDelete(null)}
              disabled={deleteMemoryFact.isPending}
            >
              {t.common.cancel}
            </Button>
            <Button
              variant="destructive"
              onClick={() => void handleDeleteFact()}
              disabled={deleteMemoryFact.isPending}
            >
              {deleteMemoryFact.isPending ? t.common.loading : t.common.delete}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={pendingImport !== null}
        onOpenChange={(open) => {
          if (!open) {
            setPendingImport(null);
          }
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t.settings.memory.importConfirmTitle}</DialogTitle>
            <DialogDescription>
              {t.settings.memory.importConfirmDescription}
            </DialogDescription>
          </DialogHeader>
          {pendingImport ? (
            <div className="bg-muted rounded-lg border p-3 text-sm">
              <div>
                <span className="text-muted-foreground">
                  {t.settings.memory.importFileLabel}:
                </span>{" "}
                {pendingImport.fileName}
              </div>
              <div>
                <span className="text-muted-foreground">
                  {t.settings.memory.markdown.facts}:
                </span>{" "}
                {pendingImport.memory.facts.length}
              </div>
              <div>
                <span className="text-muted-foreground">
                  {t.common.lastUpdated}:
                </span>{" "}
                {pendingImport.memory.lastUpdated
                  ? formatTimeAgo(pendingImport.memory.lastUpdated)
                  : "-"}
              </div>
            </div>
          ) : null}
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setPendingImport(null)}
              disabled={importMemoryMutation.isPending}
            >
              {t.common.cancel}
            </Button>
            <Button
              onClick={() => void handleConfirmImport()}
              disabled={importMemoryMutation.isPending}
            >
              {importMemoryMutation.isPending
                ? t.common.loading
                : t.common.import}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
