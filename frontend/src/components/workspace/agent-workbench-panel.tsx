import {
  ArrowLeftIcon,
  ChevronRightIcon,
  DownloadIcon,
  GlobeIcon,
  PackageIcon,
  SparklesIcon,
  TerminalIcon,
} from "lucide-react";
import {
  memo,
  Suspense,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  lazy,
} from "react";

import { useI18n } from "@/core/i18n/hooks";
import {
  artifactDisplayPath,
  normalizeWorkspaceArtifactRef,
  urlOfArtifact,
} from "@/core/artifacts/utils";
import { useArtifactContent } from "@/core/artifacts/hooks";
import type { OutlineRound } from "@/core/threads/progress-outline";
import type { GroundingSource } from "@/core/realtime/items";
import { TerminalPanel } from "@/components/workspace/terminal-panel";
import { ToolEffectDetailPanel } from "@/components/workspace/tool-effect-detail-panel";
import { useArtifacts } from "@/components/workspace/artifacts/context";
import { ArtifactLink } from "@/components/workspace/citations/artifact-link";
import { checkCodeFile, getFileIcon, getFileName } from "@/core/utils/files";
import { useStreamdownPlugins } from "@/core/streamdown";
import type {
  AgentWorkbenchEventView,
  AgentWorkbenchProcessEventSnapshot,
  AgentWorkbenchProcessEventKind,
} from "./agent-workbench-events";
import type { LiveToolEvent } from "./live-tool-timeline";
import { cn } from "@/lib/utils";
import { CoworkCollabBar } from "./cowork-collab-bar";
import { CollaborationSessionPanel } from "./collaboration-session-view";
import type { ExtractedCodeBlocks } from "@/lib/extract-code-blocks";
import type { StreamdownProps } from "streamdown";
import type { AgentWorkbenchTabId, DiffEntry } from "./agent-workbench-utils";
import { useAgentWorkbenchI18n } from "./use-agent-workbench-i18n";
import { AgentDiffPage } from "./agent-workbench-pages";
import { useAgentWorkbenchSnapshot } from "./agent-workbench-snapshot";
import { deriveAgentPhases, type AgentPhase } from "./agent-phases";
import { type AgentRunState, workbenchRunState } from "./agent-run-status";
import { MachineScopeRail } from "./agent-workbench-panel/machine-scope-rail";
import { EmptyShellView } from "./agent-workbench-panel/empty-shell-view";
import {
  WorkbenchTabHeader,
  type WorkbenchTab,
} from "./agent-workbench-panel/workbench-tab-header";
import { BrowserTabPage } from "./agent-workbench-panel/browser-tab-page";
import { AgentKanbanView } from "./agent-workbench-panel/agent-kanban-view";
import type { WorkbenchRosterSeat } from "./agent-workbench-panel/helpers";
import { useWorkbenchSelection } from "./agent-workbench-panel/use-workbench-selection";
import { WorkbenchSnapshotCache } from "@/core/cache/workbench-snapshot-cache";

// Re-export items that were exported from the original file
export { hasAgentWorkbenchContent, __testing } from "./agent-workbench-utils";
export type { AgentWorkbenchTabId } from "./agent-workbench-utils";
export { workspaceFocusTabFromEvents } from "./agent-workbench-utils";
export type { WorkbenchRosterSeat } from "./agent-workbench-panel/helpers";

function AgentWorkbenchPanelImpl({
  activeTab,
  events,
  progressOutline,
  userInput,
  groundingSources,
  focusedAgentId,
  focusedAgentView,
  focusedAgentNonce,
  focusedEventId,
  focusedEventKind,
  focusedEventView,
  focusedEventNonce,
  focusedProcessEvent,
  focusedEffectKey,
  hasAnswer,
  isLoading,
  onSelectTab,
  onClose,
  onOpenArtifact,
  runSettled,
  runFailed,
  runInterrupted,
  paused,
  className,
  threadId,
  workDir,
  browserPreviewBlocks,
  resultPreviewUrl,
  mainAgentName,
  contextTokens,
  maxContextTokens,
  isCompressingContext,
  onCompressContext,
  rosterSeats = [],
}: {
  activeTab?: AgentWorkbenchTabId;
  events: LiveToolEvent[];
  /** 「进展」面板的叙事大纲（按 iteration 分组）；缺省时回退为 phase 平铺。 */
  progressOutline?: OutlineRound[];
  userInput?: {
    text: string;
    uploadedFiles: Array<{ filename: string; path: string }>;
    attachments: Array<{ filename: string }>;
  } | null;
  /** Sources the runtime actually injected into this turn before tool use. */
  groundingSources?: GroundingSource[];
  focusedAgentId?: string | null;
  /** Which activity view a focusedAgentId intent lands on; defaults to the
   * live computer screen when the caller doesn't say. */
  focusedAgentView?: "summary" | "screen" | "role" | null;
  /** Bumped by the parent on every focus emission. Without it, a second
   * intent for the same agent (e.g. 查看过程 then 查看电脑 on one row) would be
   * swallowed by the consume-once guard below. */
  focusedAgentNonce?: number;
  /** One-shot transcript navigation intent for an exact process event. */
  focusedEventId?: string | null;
  focusedEventKind?: AgentWorkbenchProcessEventKind | null;
  focusedEventView?: AgentWorkbenchEventView | null;
  focusedEventNonce?: number;
  focusedProcessEvent?: AgentWorkbenchProcessEventSnapshot | null;
  /** Durable effect receipt selected from the transcript timeline. */
  focusedEffectKey?: string | null;
  hasAnswer?: boolean;
  /** A turn is in flight. The panel is otherwise driven purely by tool
   * events, so between "turn started" and "first tool ran" it has no
   * blocks and would claim nothing is running — which is false, and is
   * exactly the window a user stares at the panel waiting for signs of
   * life. Knowing the turn is live lets the empty shell say so. */
  isLoading?: boolean;
  onSelectTab?: (tab: AgentWorkbenchTabId) => void;
  onClose?: () => void;
  /** Opens a generated artifact in the artifacts side panel (path comes from
   * the summary page's artifact rows). */
  onOpenArtifact?: (path: string) => void;
  runSettled?: boolean;
  runFailed?: boolean;
  runInterrupted?: boolean;
  threadId?: string | null;
  workDir?: string;
  paused?: boolean;
  className?: string;
  browserPreviewBlocks?: ExtractedCodeBlocks | null;
  /** Deployed preview URL (vercel/netlify/localhost). When set, the browser
   * tab renders the live deployed site via BrowserPreviewPanel instead of
   * falling back to inline srcDoc. */
  resultPreviewUrl?: string | null;
  /** Public identity shown above the main-agent evidence surface. */
  mainAgentName?: string | null;
  /** Current conversation-window usage, shared with the composer. */
  contextTokens?: number;
  maxContextTokens?: number;
  isCompressingContext?: boolean;
  onCompressContext?: () => void | Promise<void>;
  rosterSeats?: WorkbenchRosterSeat[];
}) {
  const { t } = useI18n();
  const { deriveAgentTiles, workbenchStatus } = useAgentWorkbenchI18n();

  // IndexedDB 缓存实例（跨刷新持久化）
  const snapshotCacheRef = useRef<WorkbenchSnapshotCache | null>(null);
  const [cachedSnapshot, setCachedSnapshot] = useState<ReturnType<typeof useAgentWorkbenchSnapshot> | null>(null);
  const enableCache = typeof window !== "undefined" &&
    localStorage.getItem("octopus:cache-workbench") === "1";

  // 初始化缓存
  useEffect(() => {
    if (enableCache && !snapshotCacheRef.current) {
      snapshotCacheRef.current = new WorkbenchSnapshotCache();
    }
  }, [enableCache]);

  // 页面加载时尝试从缓存恢复
  useEffect(() => {
    if (!enableCache || !threadId || cachedSnapshot) return;

    const restoreFromCache = async () => {
      try {
        // 使用最后一个事件的时间戳作为 turnId
        const lastEvent = events[events.length - 1];
        if (!lastEvent) return;

        const turnId = `turn_${lastEvent.startedAt}`;
        const cached = await snapshotCacheRef.current?.load(threadId, turnId);
        if (cached) {
          console.log(`[WorkbenchCache] Restored snapshot from cache (${cached.events.length} events)`);
          setCachedSnapshot(cached.snapshot);
        }
      } catch (error) {
        console.warn("[WorkbenchCache] Failed to restore from cache:", error);
      }
    };

    restoreFromCache();
  }, [enableCache, threadId, events, cachedSnapshot]);

  const workbenchSnapshot = useAgentWorkbenchSnapshot(events, {
    deriveAgentTiles,
    hasAnswer,
    isLoading,
    runSettled,
    runFailed,
    paused,
    workDir,
  });

  // 如果缓存快照可用且事件匹配，优先使用缓存
  const activeSnapshot = useMemo(() => {
    if (cachedSnapshot && cachedSnapshot.fingerprint === workbenchSnapshot.fingerprint) {
      console.log('[WorkbenchCache] Using cached snapshot');
      return cachedSnapshot;
    }
    return workbenchSnapshot;
  }, [cachedSnapshot, workbenchSnapshot]);

  // 快照更新时保存到缓存
  useEffect(() => {
    if (!enableCache || !threadId || !workbenchSnapshot) return;

    const saveToCache = async () => {
      try {
        // 使用最后一个事件的时间戳作为 turnId
        const lastEvent = events[events.length - 1];
        if (!lastEvent) return;

        const turnId = `turn_${lastEvent.startedAt}`;
        await snapshotCacheRef.current?.save(
          threadId,
          turnId,
          workbenchSnapshot,
          events
        );
        console.log(`[WorkbenchCache] Saved snapshot to cache (v${workbenchSnapshot.version})`);
      } catch (error) {
        console.warn("[WorkbenchCache] Failed to save to cache:", error);
      }
    };

    // 防抖保存，避免频繁写入
    const timer = setTimeout(saveToCache, 500);
    return () => clearTimeout(timer);
  }, [enableCache, threadId, workbenchSnapshot, events]);

  const {
    agentTiles,
    blocks,
    currentPhase: snapshotCurrentPhase,
    focusedTab,
    inferredWorkDir,
    phases: snapshotPhases,
    visibleDiffEntries,
    evidence,
  } = activeSnapshot;
  const typedGroundingSources = useMemo<GroundingSource[]>(
    () =>
      evidence
        .filter((item) => item.kind === "file" && Boolean(item.uri?.trim()))
        .map((item) => ({
          kind: "source",
          title: item.title,
          path: item.uri!.trim(),
        })),
    [evidence],
  );
  const effectiveGroundingSources = useMemo(() => {
    const seen = new Set<string>();
    return [...typedGroundingSources, ...(groundingSources ?? [])].filter(
      (source) => {
        const key = `${source.kind}:${source.path}`;
        if (seen.has(key)) return false;
        seen.add(key);
        return true;
      },
    );
  }, [groundingSources, typedGroundingSources]);
  // Visibility (capability routing / delegation / skill-catalog) decisions,
  // surfaced as a de-emphasised collapsed section on the Agent kanban view.
  const visibilityEvents = useMemo(
    () => events.filter((event) => event.name === "visibility"),
    [events],
  );

  // Directly derive phases from raw events (same logic as composer-step-progress)
  // to ensure workbench always shows task plan when expanded, regardless of
  // whether server snapshot has been populated or survived a refresh/interrupt.
  const directDerived = useMemo(
    () =>
      deriveAgentPhases(events, { hasAnswer, runSettled, runFailed, paused }),
    [events, hasAnswer, runSettled, runFailed, paused],
  );
  const phases = useMemo<AgentPhase[]>(() => {
    return snapshotPhases.length > 0 ? snapshotPhases : directDerived.phases;
  }, [snapshotPhases, directDerived.phases]);
  const currentPhase =
    phases.find((phase) => phase.status === "waiting_approval") ??
    phases.find((phase) => phase.status === "running") ??
    snapshotCurrentPhase ??
    directDerived.currentPhase;

  const {
    selectedEffectKey,
    setSelectedEffectKey,
    setActivityView,
    locatableTranscriptEventId,
    selectedAgent,
    screenBlocks,
    mainBlocks,
    mainPhases,
    screenFrame,
    screenProgress,
    visibleRosterSeats,
    leaderRosterSeat,
    selectedRosterSeat,
    rosterBlocks,
    activeScreenBlocks,
    openMainProcess,
    openSubagentProcess,
    openRosterProcess,
    setSelectedBlockId,
    setManualBlockSelection,
    activityView,
  } = useWorkbenchSelection({
    blocks,
    currentPhase,
    phases,
    agentTiles,
    focusedAgentId,
    focusedAgentView,
    focusedAgentNonce,
    focusedEventId,
    focusedEventKind,
    focusedEventView,
    focusedEventNonce,
    focusedEffectKey,
    focusedProcessEvent,
    rosterSeats,
    onSelectTab,
  });

  // Keep task preview discoverable as a first-class workbench surface. Diff and
  // terminal remain opt-in until a run focuses them; tab CONTENT is still lazy,
  // so showing the browser tab does not create an extra browser session.
  const [closedTabs, setClosedTabs] = useState<Set<AgentWorkbenchTabId>>(
    () => new Set<AgentWorkbenchTabId>(["diff", "terminal"]),
  );
  // Browser tab source: while the run streams, the inline srcDoc blocks are
  // the freshest view; once the run settles a deployed URL wins. The override
  // lets the user flip between the two when both exist.
  const [browserSourceOverride, setBrowserSourceOverride] = useState<
    "deployed" | "inline" | null
  >(null);

  useEffect(() => {
    if (!onClose) return;
    const handleEscape = (event: KeyboardEvent) => {
      if (event.defaultPrevented || event.key !== "Escape") return;
      const target = event.target;
      if (target instanceof HTMLElement) {
        const tagName = target.tagName.toLowerCase();
        if (
          target.isContentEditable ||
          tagName === "input" ||
          tagName === "textarea" ||
          tagName === "select"
        ) {
          return;
        }
      }
      event.preventDefault();
      onClose();
    };
    window.addEventListener("keydown", handleEscape);
    return () => window.removeEventListener("keydown", handleEscape);
  }, [onClose]);

  const emptyShell =
    blocks.length === 0 &&
    agentTiles.length === 0 &&
    visibleRosterSeats.length === 0 &&
    (progressOutline?.length ?? 0) === 0;
  const mainRunStatus = workbenchStatus(mainBlocks, mainPhases, {
    settled: runSettled,
    failed: runFailed,
    interrupted: runInterrupted,
  });
  const mainRunState: AgentRunState = runFailed
    ? "error"
    : runInterrupted
      ? "waiting"
      : isLoading
        ? "running"
        : runSettled
          ? "done"
          : workbenchRunState({
              blocks: mainBlocks,
              phases: mainPhases,
              paused,
            });
  const machineRail = (
    <MachineScopeRail
      agents={agentTiles}
      leaderSeat={leaderRosterSeat}
      mainRunState={mainRunState}
      rosterSeats={visibleRosterSeats}
      selectedAgentId={selectedAgent?.id ?? selectedRosterSeat?.id ?? null}
      onSelectMain={openMainProcess}
      onSelectAgent={openSubagentProcess}
      onSelectRoster={openRosterProcess}
    />
  );
  const requestedActiveTab: AgentWorkbenchTabId =
    activeTab ?? (focusedAgentId ? "agent" : focusedTab) ?? "agent";
  const effectiveActiveTab:
    | "agent"
    | "diff"
    | "terminal"
    | "browser"
    | "artifacts" =
    requestedActiveTab === "subagents" || requestedActiveTab === "plan"
      ? "agent"
      : requestedActiveTab;
  const workbenchTabs: WorkbenchTab[] = useMemo(
    () => [
      {
        id: "diff",
        label: t.agentWorkbenchPages.diffTab,
        Icon: ChevronRightIcon,
      },
      {
        id: "terminal",
        label: t.agentWorkbenchPages.terminalTab,
        Icon: TerminalIcon,
      },
      {
        id: "browser",
        label: t.agentWorkbenchPages.browserTab,
        Icon: GlobeIcon,
      },
      {
        id: "artifacts",
        label: t.conversation.artifactsTitle,
        Icon: PackageIcon,
      },
    ],
    [t.agentWorkbenchPages, t.conversation],
  );

  // Auto-open a tab if it becomes the effective active tab
  useEffect(() => {
    if (closedTabs.has(effectiveActiveTab)) {
      setClosedTabs((prev) => {
        const next = new Set(prev);
        next.delete(effectiveActiveTab);
        return next;
      });
    }
  }, [effectiveActiveTab]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleCloseTab = useCallback(
    (tabId: AgentWorkbenchTabId) => {
      setClosedTabs((prev) => {
        const next = new Set(prev);
        next.add(tabId);
        return next;
      });
      if (effectiveActiveTab === tabId) {
        onSelectTab?.("agent");
      }
    },
    [effectiveActiveTab, onSelectTab],
  );

  const handleOpenTab = useCallback(
    (tabId: AgentWorkbenchTabId) => {
      setClosedTabs((prev) => {
        const next = new Set(prev);
        next.delete(tabId);
        return next;
      });
      onSelectTab?.(tabId);
    },
    [onSelectTab],
  );

  const visibleTabs = useMemo(
    () => workbenchTabs.filter((tab) => !closedTabs.has(tab.id)),
    [workbenchTabs, closedTabs],
  );
  const inferredWorkspaceLabel = inferredWorkDir
    ?.split(/[\\/]/)
    .filter(Boolean)
    .pop();
  const workspaceLabel =
    !inferredWorkspaceLabel || inferredWorkspaceLabel === threadId
      ? t.agentWorkbenchPanel.mainComputer
      : inferredWorkspaceLabel;

  // Browser tab content, shared by the empty shell and the main render path.
  const canShowDeployedPreview = Boolean(resultPreviewUrl);
  const canShowInlinePreview = Boolean(browserPreviewBlocks);
  const autoBrowserSource: "deployed" | "inline" | "session" =
    canShowDeployedPreview && (runSettled || !canShowInlinePreview)
      ? "deployed"
      : canShowInlinePreview
        ? "inline"
        : canShowDeployedPreview
          ? "deployed"
          : "session";
  const browserPreviewSource =
    (browserSourceOverride === "deployed" && canShowDeployedPreview) ||
    (browserSourceOverride === "inline" && canShowInlinePreview)
      ? browserSourceOverride
      : autoBrowserSource;
  const browserTabPage = (
    <BrowserTabPage
      canShowDeployedPreview={canShowDeployedPreview}
      canShowInlinePreview={canShowInlinePreview}
      browserPreviewSource={browserPreviewSource}
      setBrowserSourceOverride={setBrowserSourceOverride}
      resultPreviewUrl={resultPreviewUrl}
      threadId={threadId}
      inferredWorkDir={inferredWorkDir}
      browserPreviewBlocks={browserPreviewBlocks}
    />
  );
  // The main conversation owns the global execution narrative. A selected
  // sub-agent may still open its own computer: a complete, isolated streaming
  // conversation rather than a duplicate mixed activity trace.
  const effectiveActivityView: "summary" | "screen" | "role" = selectedAgent
    ? activityView === "role"
      ? "role"
      : activityView === "screen"
        ? "screen"
        : "summary"
    : "summary";

  // Workbench view: summary / computer view.
  if (emptyShell && !selectedEffectKey && !focusedProcessEvent) {
    return (
      <EmptyShellView
        mainButton={{
          active: effectiveActiveTab === "agent",
          label: isLoading
            ? t.agentWorkbenchPanel.agentStatusRunning
            : mainRunStatus.label,
          onClick: openMainProcess,
          runState: mainRunState,
          title: isLoading
            ? t.agentWorkbenchPanel.startingRobotProcess
            : mainRunStatus.label,
        }}
        visibleTabs={visibleTabs}
        workbenchTabs={workbenchTabs}
        closedTabs={closedTabs}
        effectiveActiveTab={effectiveActiveTab}
        onTabClick={handleOpenTab}
        onTabClose={handleCloseTab}
        locatableTranscriptEventId={locatableTranscriptEventId}
        onClose={onClose}
        visibleDiffEntries={visibleDiffEntries}
        threadId={threadId}
        inferredWorkDir={inferredWorkDir}
        browserTabPage={browserTabPage}
        isLoading={isLoading}
        className={className}
        machineRail={machineRail}
      />
    );
  }

  const agentKanbanPage = (
    <AgentKanbanView
      effectiveActivityView={effectiveActivityView}
      selectedRosterSeat={selectedRosterSeat}
      selectedAgent={selectedAgent}
      screenBlocks={screenBlocks}
      currentScreenBlockId={screenFrame.block?.id ?? null}
      phases={phases}
      blocks={blocks}
      agentTiles={agentTiles}
      visibleDiffEntries={visibleDiffEntries}
      focusedProcessEvent={focusedProcessEvent ?? null}
      focusedEventId={focusedEventId}
      progressOutline={progressOutline}
      userInput={userInput ?? null}
      groundingSources={effectiveGroundingSources}
      preferStructuredReferences={evidence.length > 0}
      mainAgentName={mainAgentName}
      terminalState={
        runInterrupted ? "interrupted" : runFailed ? "failed" : null
      }
      contextTokens={contextTokens}
      maxContextTokens={maxContextTokens}
      isCompressingContext={isCompressingContext}
      onCompressContext={onCompressContext}
      setActivityView={setActivityView}
      onSelectTab={onSelectTab}
      onOpenArtifact={onOpenArtifact}
      openMainProcess={openMainProcess}
      setSelectedBlockId={setSelectedBlockId}
      setManualBlockSelection={setManualBlockSelection}
      visibilityEvents={visibilityEvents}
    />
  );

  const effectiveEmbeddedPage =
    selectedEffectKey && effectiveActiveTab === "agent" ? (
      <ToolEffectDetailPanel
        effectKey={selectedEffectKey}
        onBack={() => setSelectedEffectKey(null)}
      />
    ) : effectiveActiveTab === "diff" ? (
      <AgentDiffPage
        entries={visibleDiffEntries}
        onBackToSummary={() => handleOpenTab("agent")}
      />
    ) : effectiveActiveTab === "terminal" ? (
      <TerminalPanel
        sessionId={`agent-workbench-${threadId ?? "local"}`}
        cwd={inferredWorkDir}
        className="min-h-0 flex-1"
      />
    ) : effectiveActiveTab === "browser" ? (
      browserTabPage
    ) : effectiveActiveTab === "artifacts" && threadId ? (
      // Reuses the outer ArtifactsProvider (page-level) so the artifact list
      // synced from the backend stays visible. Wrapping in a fresh provider
      // here reset artifacts to [] and showed "暂无预览内容" for generated
      // outputs even though the files existed on disk.
      <ArtifactInlinePreviewEmbedded
        threadId={threadId}
        currentTurnEntries={visibleDiffEntries}
      />
    ) : (
      agentKanbanPage
    );

  return (
    <div
      className={cn(
        "flex size-full min-h-0 flex-col bg-[color:color-mix(in_oklch,var(--muted)_46%,var(--background))]",
        className,
      )}
    >
      <WorkbenchTabHeader
        mainButton={{
          active:
            effectiveActiveTab === "agent" &&
            !selectedEffectKey &&
            !selectedAgent &&
            !selectedRosterSeat,
          label: mainRunStatus.label,
          onClick: openMainProcess,
          runState: mainRunState,
          title: t.agentWorkbenchPanel.viewMainAgentSlot,
        }}
        visibleTabs={visibleTabs}
        workbenchTabs={workbenchTabs}
        closedTabs={closedTabs}
        effectiveActiveTab={effectiveActiveTab}
        onTabClick={handleOpenTab}
        onTabClose={handleCloseTab}
        locatableTranscriptEventId={locatableTranscriptEventId}
        onClose={onClose}
        workspaceLabel={workspaceLabel}
        showWorkspaceLabel
        mainRunStatusLabel={mainRunStatus.label}
      />

      {threadId ? (
        <CoworkCollabBar threadId={threadId} rosterSeats={rosterSeats} />
      ) : null}
      {threadId ? (
        <CollaborationSessionPanel
          threadId={threadId}
          onlyWhenRoomLinked
          className="px-3 pb-2"
        />
      ) : null}

      <section
        aria-label={t.sidebar.ariaAgentWorkbench}
        className="flex min-h-0 flex-1 flex-col overflow-hidden bg-background/70"
      >
        {effectiveEmbeddedPage}
      </section>
      {machineRail}
    </div>
  );
}

const LazyStreamdown = lazy(
  () => import("@/components/ai-elements/streamdown-host"),
);

/**
 * Two-state artifact panel for the workbench's "产物" tab.
 *
 * State 1 – List view (default):
 *   A single flat list of all artifacts. Current-turn files appear first
 *   with a ✨ "本轮" badge; history files follow without grouping headers.
 *
 * State 2 – Preview view:
 *   Full-bleed preview of the selected file with a back button in the
 *   header to return to the list. This mirrors the drawer's ArtifactPanel
 *   / ArtifactFileDetail two-state pattern so the two surfaces feel
 *   consistent.
 */
function ArtifactInlinePreviewEmbedded({
  threadId,
  currentTurnEntries = [],
}: {
  threadId: string;
  currentTurnEntries?: DiffEntry[];
}) {
  const {
    artifacts,
    selectedArtifact: externalSelected,
    select,
  } = useArtifacts();
  const { t } = useI18n();
  const streamdownPlugins = useStreamdownPlugins();

  const currentTurnRefs = useMemo(() => {
    const seen = new Set<string>();
    const refs: string[] = [];
    for (const entry of currentTurnEntries) {
      const ref = normalizeWorkspaceArtifactRef(entry.path, threadId);
      if (seen.has(ref)) continue;
      seen.add(ref);
      refs.push(ref);
    }
    return refs;
  }, [currentTurnEntries, threadId]);

  const currentTurnSet = useMemo(
    () => new Set(currentTurnRefs),
    [currentTurnRefs],
  );

  // Single flat list: current-turn first (in their natural order), then history.
  const allFiles = useMemo(() => {
    const cur: string[] = [];
    const hist: string[] = [];
    for (const f of artifacts ?? []) {
      if (currentTurnSet.has(f)) cur.push(f);
      else hist.push(f);
    }
    return [...cur, ...hist];
  }, [artifacts, currentTurnSet]);

  // Preview state: which file is being viewed full-screen. `null` = list view.
  const [previewing, setPreviewing] = useState<string | null>(null);

  // When an external selection arrives (e.g. clicking a filename in chat),
  // jump straight to the preview view for that file.
  useEffect(() => {
    if (externalSelected && allFiles.includes(externalSelected)) {
      setPreviewing(externalSelected);
      // Also sync the shared context so the drawer stays in sync.
      select(externalSelected);
    }
  }, [externalSelected, allFiles, select]);

  const handleSelect = useCallback(
    (path: string) => {
      setPreviewing(path);
      select(path);
    },
    [select],
  );

  const handleBack = useCallback(() => {
    setPreviewing(null);
  }, []);

  if (allFiles.length === 0) {
    return (
      <div className="flex flex-1 items-center justify-center p-4 text-sm text-muted-foreground">
        {t.conversation.noPreviewArtifacts}
      </div>
    );
  }

  // ── Preview view ──
  if (previewing) {
    return (
      <PreviewPane
        filepath={previewing}
        threadId={threadId}
        streamdownPlugins={streamdownPlugins}
        onBack={handleBack}
      />
    );
  }

  // ── List view ──
  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
      <div className="flex-1 overflow-y-auto">
        {allFiles.map((f) => (
          <FileListRow
            key={f}
            filepath={f}
            isCurrentTurn={currentTurnSet.has(f)}
            onSelect={handleSelect}
          />
        ))}
      </div>
    </div>
  );
}

/* ─────────────────────── List row ─────────────────────── */

function FileListRow({
  filepath,
  isCurrentTurn = false,
  onSelect,
}: {
  filepath: string;
  isCurrentTurn?: boolean;
  onSelect: (path: string) => void;
}) {
  const displayPath = artifactDisplayPath(filepath);
  const name = getFileName(displayPath);
  return (
    <button
      type="button"
      onClick={() => onSelect(filepath)}
      className="flex w-full items-center gap-2 px-3 py-2 text-left transition-colors hover:bg-muted/50"
    >
      <span className="flex size-5 shrink-0 items-center justify-center text-muted-foreground">
        {getFileIcon(displayPath, "size-3.5")}
      </span>
      <span className="min-w-0 flex-1 truncate text-xs text-foreground">
        {name}
      </span>
      {isCurrentTurn && (
        <span className="inline-flex shrink-0 items-center gap-0.5 rounded-full bg-accent/15 px-1.5 py-0.5 text-[10px] font-medium text-accent">
          <SparklesIcon className="size-2.5" />
          本轮
        </span>
      )}
    </button>
  );
}

/* ─────────────────────── Preview pane (full-screen) ─────────────────────── */

function PreviewPane({
  filepath,
  threadId,
  streamdownPlugins,
  onBack,
}: {
  filepath: string;
  threadId: string;
  streamdownPlugins: Pick<StreamdownProps, "remarkPlugins" | "rehypePlugins">;
  onBack: () => void;
}) {
  const { t } = useI18n();
  const displayPath = artifactDisplayPath(filepath);
  const isWriteFile = filepath.startsWith("write-file:");
  const { content, url, isLoading } = useArtifactContent({
    filepath,
    threadId,
    enabled: !isWriteFile,
  });
  const effectiveContent = isWriteFile ? "" : (content ?? "");
  const iframeRef = useRef<HTMLIFrameElement | null>(null);

  const lang = checkCodeFile(displayPath).language;
  const isHtml = lang === "html";
  const isMarkdown = lang === "markdown";

  return (
    <div className="flex min-h-0 size-full flex-col">
      {/* Header with back button */}
      <div className="flex shrink-0 items-center gap-2 border-b border-border-subtle bg-muted/30 px-2 py-1.5">
        <button
          type="button"
          onClick={onBack}
          className="flex size-6 shrink-0 items-center justify-center rounded text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          aria-label={t.common.back}
        >
          <ArrowLeftIcon className="size-3.5" />
        </button>
        <span className="flex size-5 shrink-0 items-center justify-center">
          {getFileIcon(displayPath, "size-3")}
        </span>
        <span className="min-w-0 flex-1 truncate text-xs font-medium">
          {getFileName(displayPath)}
        </span>
        {lang && (
          <span className="shrink-0 text-[10px] text-muted-foreground uppercase">
            {lang}
          </span>
        )}
        <a
          href={urlOfArtifact({ filepath, threadId, download: true })}
          target="_blank"
          rel="noopener noreferrer"
          className="rounded p-1 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          aria-label={t.common.download}
        >
          <DownloadIcon className="size-3" />
        </a>
      </div>

      {/* Content */}
      <div className="relative min-h-0 flex-1 overflow-hidden">
        {isLoading && (
          <div className="absolute inset-0 z-10 flex items-center justify-center bg-background/60 text-xs text-muted-foreground">
            {t.common.loading}…
          </div>
        )}
        {isMarkdown ? (
          <div className="size-full overflow-auto px-4 py-3">
            <Suspense
              fallback={
                <div className="size-full whitespace-pre-wrap break-words py-2 text-sm text-muted-foreground">
                  {effectiveContent}
                </div>
              }
            >
              <LazyStreamdown
                className="size-full"
                {...streamdownPlugins}
                components={{ a: ArtifactLink }}
              >
                {effectiveContent}
              </LazyStreamdown>
            </Suspense>
          </div>
        ) : isHtml ? (
          <iframe
            ref={iframeRef}
            className="size-full border-0"
            sandbox="allow-scripts allow-forms"
            title={`${getFileName(displayPath)} preview`}
            {...(url ? { src: url } : { srcDoc: effectiveContent })}
          />
        ) : (
          <div className="flex size-full items-center justify-center p-4 text-xs text-muted-foreground">
            此文件类型暂不支持预览
          </div>
        )}
      </div>
    </div>
  );
}

export const AgentWorkbenchPanel = memo(AgentWorkbenchPanelImpl);
