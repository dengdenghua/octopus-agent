import { ChevronRightIcon, GlobeIcon, PackageIcon, TerminalIcon } from "lucide-react";
import { memo, useCallback, useEffect, useMemo, useState } from "react";

import { useI18n } from "@/core/i18n/hooks";
import type { OutlineRound } from "@/core/threads/progress-outline";
import { TerminalPanel } from "@/components/workspace/terminal-panel";
import { ToolEffectDetailPanel } from "@/components/workspace/tool-effect-detail-panel";
import {
  ArtifactsProvider,
  useArtifacts,
} from "@/components/workspace/artifacts/context";
import { ArtifactInlinePreview } from "@/components/workspace/artifacts/artifact-file-list";
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
import type { AgentWorkbenchTabId } from "./agent-workbench-utils";
import { useAgentWorkbenchI18n } from "./use-agent-workbench-i18n";
import { AgentDiffPage } from "./agent-workbench-pages";
import { useAgentWorkbenchSnapshot } from "./agent-workbench-snapshot";
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
import { ArtifactPanel } from "./artifacts/artifact-panel";

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
  focusedAgentId?: string | null;
  /** Which activity view a focusedAgentId intent lands on; defaults to the
   * live computer screen when the caller doesn't say. */
  focusedAgentView?: "summary" | "screen" | null;
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
  rosterSeats?: WorkbenchRosterSeat[];
}) {
  const { t } = useI18n();
  const { deriveAgentTiles, workbenchStatus } = useAgentWorkbenchI18n();

  const workbenchSnapshot = useAgentWorkbenchSnapshot(events, {
    deriveAgentTiles,
    hasAnswer,
    isLoading,
    runSettled,
    runFailed,
    paused,
    workDir,
  });
  const {
    agentTiles,
    blocks,
    currentPhase,
    focusedTab,
    inferredWorkDir,
    phases,
    visibleDiffEntries,
  } = workbenchSnapshot;

  const {
    selectedEffectKey,
    setSelectedEffectKey,
    setActivityView,
    locatableTranscriptEventId,
    selectedAgent,
    creationFocusAgent,
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

  // Start lean: only the file tree is shown. Diff / terminal / browser stay
  // hidden until there's something in them — they auto-reveal when a run
  // focuses them (latestWorkspaceFocusTab → activeTab → the auto-open effect
  // below) or when the user adds them from the tab menu. Tab CONTENT is already
  // lazy (only the active tab mounts), so this is purely about decluttering the
  // bar, not load cost.
  const [closedTabs, setClosedTabs] = useState<Set<AgentWorkbenchTabId>>(
    () => new Set<AgentWorkbenchTabId>(["diff", "terminal", "browser"]),
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
  const effectiveActiveTab: "agent" | "diff" | "terminal" | "browser" | "artifacts" =
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
      { id: "browser", label: t.agentWorkbenchPages.browserTab, Icon: GlobeIcon },
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
  // "电脑视图" is a visual replay surface, not another spelling of the
  // activity list. Do not show it for ordinary file/search work merely
  // because the agent has run some tools.
  const hasComputerActivity =
    Boolean(selectedAgent) ||
    Boolean(selectedRosterSeat) ||
    activeScreenBlocks.some((block) => block.kind === "browser") ||
    canShowDeployedPreview ||
    canShowInlinePreview;
  // The main conversation is already the narrative timeline. A second,
  // identical tool-by-tool trace in the workbench only earns its place once
  // the user enters an independent agent's workstation.
  const hasIndependentTrace = Boolean(
    selectedAgent || (selectedRosterSeat && activeScreenBlocks.length > 0),
  );
  const effectiveActivityView =
    activityView === "screen" && hasComputerActivity
      ? "screen"
      : activityView === "screen"
        ? "summary"
        : activityView === "trace" && !hasIndependentTrace
          ? "summary"
          : activityView;

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
      hasIndependentTrace={hasIndependentTrace}
      hasComputerActivity={hasComputerActivity}
      selectedRosterSeat={selectedRosterSeat}
      selectedAgent={selectedAgent}
      creationFocusAgent={creationFocusAgent}
      phases={phases}
      blocks={blocks}
      agentTiles={agentTiles}
      visibleDiffEntries={visibleDiffEntries}
      rosterBlocks={rosterBlocks}
      screenBlocks={screenBlocks}
      screenFrame={screenFrame}
      focusedProcessEvent={focusedProcessEvent ?? null}
      focusedEventId={focusedEventId}
      progressOutline={progressOutline}
      userInput={userInput ?? null}
      mainPhases={mainPhases}
      mainRunState={mainRunState}
      screenProgress={screenProgress}
      mainAgentName={mainAgentName}
      currentPhaseTitle={currentPhase?.title ?? t.agentWorkbench.activityTrace}
      terminalState={
        runInterrupted ? "interrupted" : runFailed ? "failed" : null
      }
      setActivityView={setActivityView}
      onSelectTab={onSelectTab}
      onOpenArtifact={onOpenArtifact}
      openMainProcess={openMainProcess}
      openSubagentProcess={openSubagentProcess}
      setSelectedBlockId={setSelectedBlockId}
      setManualBlockSelection={setManualBlockSelection}
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
      <ArtifactsProvider threadId={threadId}>
        <ArtifactInlinePreviewEmbedded />
      </ArtifactsProvider>
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

/**
 * Streamlined inline artifact preview for the workbench's "产物" tab.
 * Renders HTML (iframe) / Markdown (Streamdown) directly — no file list,
 * no tab routing, no detail-page navigation. Uses the same shared
 * preview pipeline as ArtifactFileDetail so there is exactly one
 * rendering code-path for artifact content.
 */
function ArtifactInlinePreviewEmbedded() {
  const { artifacts } = useArtifacts();
  const { t } = useI18n();

  const previewable = useMemo(() => {
    if (!artifacts) return [];
    return artifacts.filter((f) => {
      const ext = f.split(".").pop()?.toLowerCase() ?? "";
      return ["html", "htm", "md", "markdown"].includes(ext);
    });
  }, [artifacts]);

  if (previewable.length === 0) {
    return (
      <div className="flex flex-1 items-center justify-center p-4 text-sm text-muted-foreground">
        {t.conversation.noPreviewArtifacts}
      </div>
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
      <ArtifactInlinePreview files={previewable} threadId="" />
    </div>
  );
}

export const AgentWorkbenchPanel = memo(AgentWorkbenchPanelImpl);
