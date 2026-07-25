import {
  BotIcon,
  CheckIcon,
  ChevronRightIcon,
  GlobeIcon,
  LayoutGridIcon,
  ListChecksIcon,
  LocateFixedIcon,
  MonitorIcon,
  PanelRightCloseIcon,
  TerminalIcon,
  XIcon,
} from "lucide-react";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";

import { useI18n } from "@/core/i18n/hooks";
import type { Translations } from "@/core/i18n/locales/types";
import type { OutlineRound } from "@/core/threads/progress-outline";
import {
  findTimelineItemElement,
  getTimelineLinkageState,
  subscribeTimelineLinkage,
  activateTimelineItem,
} from "@/core/threads/timeline-linkage";
import { TerminalPanel } from "@/components/workspace/terminal-panel";
import { ToolEffectDetailPanel } from "@/components/workspace/tool-effect-detail-panel";
import type {
  AgentWorkbenchEventView,
  AgentWorkbenchProcessEventSnapshot,
  AgentWorkbenchProcessEventKind,
} from "./agent-workbench-events";
import { emitLocateAgentWorkbenchEvent } from "./agent-workbench-events";
import type { LiveToolEvent } from "./live-tool-timeline";
import {
  pickCurrentWorkBlock,
  progressForWorkBlocks,
  statusText,
} from "./work-blocks";
import { cn } from "@/lib/utils";
import { DotProgress } from "@/components/workspace/swarm/dot-progress";
import { BrowserPreviewPanel } from "./browser-preview-panel";
import { LivePreviewPanel } from "./live-preview-panel";
import { CoworkCollabBar } from "./cowork-collab-bar";
import { CollaborationSessionPanel } from "./collaboration-session-view";
import { WorkstationSeat } from "./workstation-seat";
import type { ExtractedCodeBlocks } from "@/lib/extract-code-blocks";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  type AgentTile,
  type AgentWorkbenchTabId,
  blockIcon,
  compactDetail,
  agentProgressPercent,
  repairMojibakeText,
  __testing,
} from "./agent-workbench-utils";
import { useAgentWorkbenchI18n } from "./use-agent-workbench-i18n";
import {
  StatusGlyph,
  AgentSummaryPage,
  AgentCreationCard,
  AgentDiffPage,
  WorkbenchEmptyPage,
  isAgentCreationBlock,
  agentTileForBlock,
  findAgentTileByFocusId,
} from "./agent-workbench-pages";
import {
  currentScreenFrame,
  screenBlocksForAgent,
  useAgentWorkbenchSnapshot,
} from "./agent-workbench-snapshot";
import type { AgentPhase } from "./agent-phases";
import type { WorkBlock } from "./work-blocks";
import {
  type AgentRunState,
  agentRunBadgeClass,
  agentRunDotClass,
  agentRunHue,
  agentRunIconClass,
  agentRunRobotButtonClass,
  agentRunStatusLightClass,
  agentRunStatusLightPulseClass,
  workbenchRunState,
} from "./agent-run-status";

// Re-export items that were exported from the original file
export { hasAgentWorkbenchContent, __testing } from "./agent-workbench-utils";
export type { AgentWorkbenchTabId } from "./agent-workbench-utils";
export { workspaceFocusTabFromEvents } from "./agent-workbench-utils";

export type WorkbenchRosterSeat = {
  id: string;
  name: string;
  avatarUrl?: string | null;
  icon?: string | null;
  role?: "tl" | "member" | string | null;
};

function rosterSeatRoleLabel(
  seat: WorkbenchRosterSeat,
  t: Translations,
): string {
  if (seat.role === "tl") return t.agentWorkbenchPanel.leaderSeat;
  if (seat.role && seat.role !== "member") return seat.role;
  return t.agentWorkbenchPanel.collaboratorSeat;
}

function mainPhaseStatusLabel(phases: AgentPhase[], t: Translations) {
  if (phases.some((p) => p.status === "error")) {
    return t.agentWorkbenchPanel.agentStatusError;
  }
  if (phases.some((p) => p.status === "waiting_approval")) {
    return t.agentWorkbenchPages.statusWaitingApproval;
  }
  if (phases.some((p) => p.status === "running")) {
    return t.agentWorkbenchPanel.agentStatusRunning;
  }
  if (phases.some((p) => p.status === "pending")) {
    return t.agentWorkbenchPanel.agentStatusPending;
  }
  return t.agentWorkbenchPanel.agentStatusDone;
}

function MainComputerStatusButton({
  active,
  label,
  onClick,
  runState,
  title,
}: {
  active: boolean;
  label: string;
  onClick: () => void;
  runState: AgentRunState;
  title: string;
}) {
  const { t } = useI18n();
  const buttonClassName = cn(
    "relative flex size-9 shrink-0 items-center justify-center rounded-md border font-mono shadow-[var(--shadow-xs)] transition-colors",
    active && "ring-1 ring-primary/30",
    agentRunRobotButtonClass(runState),
  );
  const iconClassName = cn(
    "size-4 transition-colors",
    agentRunIconClass(runState),
  );
  const pulseClassName = agentRunStatusLightPulseClass(runState);

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          onClick={onClick}
          className={buttonClassName}
          aria-label={`${t.agentWorkbenchPanel.mainComputer} · ${label}`}
          title={`${t.agentWorkbenchPanel.mainComputer} · ${label}`}
        >
          <MonitorIcon className={iconClassName} />
          {pulseClassName && (
            <span
              className={cn(
                "absolute -top-0.5 -right-0.5 size-2 rounded-full",
                agentRunStatusLightClass(runState),
                pulseClassName,
              )}
            />
          )}
        </button>
      </TooltipTrigger>
      <TooltipContent align="start" side="bottom" className="max-w-52">
        <div className="font-medium">{t.agentWorkbenchPanel.mainComputer}</div>
        <div className="mt-0.5 text-xs opacity-80">
          {t.agentWorkbenchPanel.currentConversation}
          {" · "}
          {label}
        </div>
        <div className="mt-1 text-xs opacity-75">{title}</div>
      </TooltipContent>
    </Tooltip>
  );
}

function statusFromBlocks(blocks: WorkBlock[]): AgentPhase["status"] {
  if (blocks.some((block) => block.status === "waiting_approval")) {
    return "waiting_approval";
  }
  if (blocks.some((block) => block.status === "running")) {
    return "running";
  }
  if (blocks.some((block) => block.status === "error")) return "error";
  return blocks.length > 0 ? "done" : "pending";
}

export function AgentWorkbenchPanel({
  activeTab,
  events,
  progressOutline,
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
  const {
    deriveAgentTiles,
    agentStatusLabel,
    agentStatusClass,
    workbenchStatus,
  } = useAgentWorkbenchI18n();

  const workbenchSnapshot = useAgentWorkbenchSnapshot(events, {
    deriveAgentTiles,
    hasAnswer,
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
  const [selectedBlockId, setSelectedBlockId] = useState<string | null>(null);
  const [selectedEffectKey, setSelectedEffectKey] = useState<string | null>(
    null,
  );
  const [manualBlockSelection, setManualBlockSelection] = useState(false);
  const [activityView, setActivityView] = useState<
    "summary" | "trace" | "screen"
  >("summary");
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

  const phaseBlocks = useMemo(
    () =>
      currentPhase
        ? blocks.filter((block) => currentPhase.blockIds.includes(block.id))
        : blocks,
    [blocks, currentPhase],
  );
  const defaultBlock = useMemo(
    () => pickCurrentWorkBlock(phaseBlocks) ?? phaseBlocks[0] ?? null,
    [phaseBlocks],
  );
  const selectedBlock =
    phaseBlocks.find((block) => block.id === selectedBlockId) ?? defaultBlock;
  const locatableTranscriptEventId =
    focusedEventId?.trim() ||
    (selectedBlock
      ? selectedBlock.event.id || selectedBlock.id
      : focusedProcessEvent
        ? focusedEventId?.trim()
        : "");
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null);
  const [selectedRosterSeatId, setSelectedRosterSeatId] = useState<
    string | null
  >(null);
  const selectableAgentIds = useMemo(
    () => new Set(agentTiles.map((agent) => agent.id)),
    [agentTiles],
  );
  const selectedAgent =
    selectedAgentId && selectableAgentIds.has(selectedAgentId)
      ? (agentTiles.find((agent) => agent.id === selectedAgentId) ?? null)
      : null;
  const creationFocusAgent = isAgentCreationBlock(selectedBlock)
    ? agentTileForBlock(selectedBlock, agentTiles)
    : undefined;
  const screenBlocks = useMemo(
    () => screenBlocksForAgent(blocks, selectedAgent?.id ?? null),
    [blocks, selectedAgent?.id],
  );
  const mainBlocks = useMemo(
    () => screenBlocksForAgent(blocks, null),
    [blocks],
  );
  const mainPhases = useMemo(() => {
    // When there are main blocks, phases with no main block belong to a
    // sub-agent (or are stale server snapshot entries) and must not make the
    // main workstation look pending. Before the first block arrives, keep
    // the server phases so an actually-running turn still has a heartbeat.
    if (mainBlocks.length === 0) return phases;
    return phases
      .map((phase) => ({
        ...phase,
        blockIds: phase.blockIds.filter((id) =>
          mainBlocks.some((block) => block.id === id),
        ),
        status: statusFromBlocks(
          mainBlocks.filter((block) => phase.blockIds.includes(block.id)),
        ),
      }))
      .filter((phase) => phase.blockIds.length > 0);
  }, [mainBlocks, phases]);
  const screenFrame = useMemo(
    () =>
      currentScreenFrame(
        screenBlocks,
        manualBlockSelection ? selectedBlockId : null,
      ),
    [manualBlockSelection, screenBlocks, selectedBlockId],
  );
  const screenProgress = useMemo(() => {
    if (!screenFrame.block || screenBlocks.length === 0) {
      return { current: 0, total: 0 };
    }
    return progressForWorkBlocks(screenBlocks, screenFrame.block);
  }, [screenBlocks, screenFrame.block]);
  useEffect(() => {
    if (manualBlockSelection) {
      // A manual pick is made against what the active view actually shows:
      // the process replay lists screenBlocks (per-agent history, including
      // done blocks that no phase references anymore), the phase card lists
      // phaseBlocks. Only drop the pick once the block left both sets —
      // judging by phaseBlocks alone evicts every historical frame.
      const stillVisible = Boolean(
        selectedBlockId &&
        (screenBlocks.some((block) => block.id === selectedBlockId) ||
          phaseBlocks.some((block) => block.id === selectedBlockId)),
      );
      if (stillVisible) return;
      setManualBlockSelection(false);
      setSelectedBlockId(defaultBlock?.id ?? null);
      return;
    }
    setSelectedBlockId(defaultBlock?.id ?? null);
  }, [
    defaultBlock,
    manualBlockSelection,
    phaseBlocks,
    screenBlocks,
    selectedBlockId,
  ]);

  useEffect(() => {
    setSelectedAgentId((current) =>
      current && selectableAgentIds.has(current) ? current : null,
    );
  }, [selectableAgentIds]);

  const openMainProcess = useCallback(() => {
    setSelectedEffectKey(null);
    setSelectedAgentId(null);
    setSelectedRosterSeatId(null);
    setActivityView("screen");
    setManualBlockSelection(false);
    onSelectTab?.("agent");
  }, [onSelectTab]);

  const openSubagentProcess = useCallback(
    (agentId: string) => {
      setSelectedEffectKey(null);
      setSelectedAgentId(agentId);
      setSelectedRosterSeatId(null);
      setActivityView("screen");
      setManualBlockSelection(false);
      onSelectTab?.("agent");
    },
    [onSelectTab],
  );

  // Focus is a one-shot navigation intent, not a persistent pin: consume each
  // focusedAgentId value once, so snapshot churn re-running this effect (new
  // agentTiles identity every streaming frame) cannot yank the user back after
  // they navigated away.
  const consumedFocusedAgentIdRef = useRef<string | null>(null);
  useEffect(() => {
    if (!focusedAgentId) {
      // Parent cleared the intent; a later re-focus of the same agent counts
      // as a new intent.
      consumedFocusedAgentIdRef.current = null;
      return;
    }
    // The nonce distinguishes successive intents for the same agent (view
    // switches); it must be part of the consumed key, not the plain id.
    const intentKey = `${focusedAgentNonce ?? 0}:${focusedAgentId}`;
    if (consumedFocusedAgentIdRef.current === intentKey) return;
    if (agentTiles.length === 0) return;
    const target = findAgentTileByFocusId(focusedAgentId, agentTiles);
    if (!target) return;
    consumedFocusedAgentIdRef.current = intentKey;
    setSelectedAgentId(target.id);
    setSelectedRosterSeatId(null);
    setActivityView(focusedAgentView ?? "screen");
  }, [focusedAgentId, focusedAgentView, focusedAgentNonce, agentTiles]);

  // Transcript rows and workbench blocks share the tool-call event id. A
  // click can therefore land on the exact replay frame instead of merely
  // opening the panel. Thinking summaries intentionally have no private block
  // payload, so they land on the public summary surface.
  const consumedFocusedEventRef = useRef<string | null>(null);
  useEffect(() => {
    setSelectedEffectKey(focusedEffectKey?.trim() || null);
  }, [focusedEffectKey, focusedEventNonce]);

  useEffect(() => {
    if (!focusedEventId && !focusedEventView) {
      consumedFocusedEventRef.current = null;
      return;
    }
    const intentKey = `${focusedEventNonce ?? 0}:${focusedEventKind ?? "event"}:${focusedEventId ?? "view"}:${focusedEventView ?? "summary"}`;
    if (consumedFocusedEventRef.current === intentKey) return;

    const targetBlock = focusedEventId
      ? blocks.find(
          (block) =>
            block.id === focusedEventId || block.event.id === focusedEventId,
        )
      : null;
    if (focusedEventKind === "execution" && focusedEventId && !targetBlock) {
      // A tool-call message can render one frame before its workbench event.
      // Keep the navigation intent pending until the shared event arrives.
      return;
    }

    consumedFocusedEventRef.current = intentKey;
    setSelectedRosterSeatId(null);
    if (targetBlock) {
      const targetAgent = agentTileForBlock(targetBlock, agentTiles);
      setSelectedAgentId(targetAgent?.id ?? null);
      setSelectedBlockId(targetBlock.id);
      setManualBlockSelection(true);
    } else {
      setSelectedAgentId(null);
      setManualBlockSelection(false);
    }
    setActivityView(focusedEventView ?? "summary");
    onSelectTab?.(targetBlock ? evidenceTabForWorkBlock(targetBlock) : "agent");
  }, [
    agentTiles,
    blocks,
    focusedEventId,
    focusedEventKind,
    focusedEventNonce,
    focusedEventView,
    onSelectTab,
  ]);

  // 对话区 → 侧边栏联动：监听共享 linkage store 中来自对话区的激活，
  // 滚动定位到侧边栏同 id 条目（条目详情的展开仍由上面的 focused*
  // 流程负责，这里只追加定位）。目标尚未渲染（视图切换中）时不消费
  // 意图，等下一次渲染重试；消费过的意图不重复滚动。两侧共用同一 id，
  // 因此查找时以 "sidebar" lane 限定只命中侧边栏条目。
  const timelineLinkage = useSyncExternalStore(
    subscribeTimelineLinkage,
    getTimelineLinkageState,
    getTimelineLinkageState,
  );
  const consumedTimelineLinkageRef = useRef<string | null>(null);
  useEffect(() => {
    const itemId = timelineLinkage.activeTimelineItemId;
    if (timelineLinkage.activeSource !== "chat" || !itemId) return;
    const intentKey = `${timelineLinkage.nonce}:${itemId}`;
    if (consumedTimelineLinkageRef.current === intentKey) return;
    const target = findTimelineItemElement(itemId, "sidebar");
    if (!target) return;
    consumedTimelineLinkageRef.current = intentKey;
    target.scrollIntoView({ block: "nearest" });
  }, [timelineLinkage, activityView, blocks]);

  const visibleRosterSeats = useMemo(() => {
    const runningAgentIds = new Set(
      agentTiles.flatMap((agent) => [
        agent.id,
        agent.name,
        agent.label,
        agent.codename ?? "",
      ]),
    );
    return rosterSeats.filter((seat) => {
      const id = seat.id.trim();
      if (!id) return false;
      return !runningAgentIds.has(id) && seat.role !== "tl";
    });
  }, [agentTiles, rosterSeats]);
  const leaderRosterSeat =
    rosterSeats.find((seat) => seat.role === "tl") ?? null;
  const selectedRosterSeat = selectedRosterSeatId
    ? (visibleRosterSeats.find((seat) => seat.id === selectedRosterSeatId) ??
      rosterSeats.find((seat) => seat.id === selectedRosterSeatId) ??
      null)
    : null;
  useEffect(() => {
    setSelectedRosterSeatId((current) =>
      current && rosterSeats.some((seat) => seat.id === current)
        ? current
        : null,
    );
  }, [rosterSeats]);
  const rosterBlocks = useMemo(
    () => screenBlocksForAgent(blocks, selectedRosterSeat?.id),
    [blocks, selectedRosterSeat?.id],
  );
  const activeScreenBlocks = selectedRosterSeat ? rosterBlocks : screenBlocks;
  const openRosterProcess = useCallback(
    (seatId: string) => {
      setSelectedEffectKey(null);
      setSelectedAgentId(null);
      setSelectedRosterSeatId(seatId);
      setActivityView("screen");
      setManualBlockSelection(false);
      onSelectTab?.("agent");
    },
    [onSelectTab],
  );
  const emptyShell =
    blocks.length === 0 &&
    agentTiles.length === 0 &&
    visibleRosterSeats.length === 0 &&
    (progressOutline?.length ?? 0) === 0;
  const mainRunStatus = workbenchStatus(mainBlocks, mainPhases, {
    settled: runSettled,
    failed: runFailed,
  });
  const mainRunState: AgentRunState = runFailed
    ? "error"
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
  // page.tsx still emits "subagents" / "artifacts" / "plan" intents
  // (openArtifactsPanel / openAgentPlanPanel); the workbench renders all of
  // them on the agent page, so every tab id maps onto a real embedded page.
  const effectiveActiveTab: "agent" | "diff" | "terminal" | "browser" =
    requestedActiveTab === "subagents" ||
    requestedActiveTab === "artifacts" ||
    requestedActiveTab === "plan"
      ? "agent"
      : requestedActiveTab;
  const workbenchTabs: Array<{
    id: AgentWorkbenchTabId;
    label: string;
    Icon: typeof MonitorIcon;
  }> = [
    // Sort by expected usage frequency and priority.
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
  ];

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

  const visibleTabs = workbenchTabs.filter((tab) => !closedTabs.has(tab.id));
  const workspaceLabel =
    inferredWorkDir?.split(/[\\/]/).filter(Boolean).pop() ||
    t.agentWorkbenchPanel.mainComputer;

  // Browser tab content, shared by the empty shell and the main render path.
  // While the run is live the inline srcDoc blocks track the agent's latest
  // output; once it settles the deployed site is the "real" preview. A
  // deployed URL without inline blocks always wins over the generic session
  // panel.
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
  const browserTabPage = (
    <div className="flex min-h-0 flex-1 flex-col">
      {canShowDeployedPreview && canShowInlinePreview && (
        <div className="flex shrink-0 items-center gap-1 border-b border-border-subtle px-3 py-1.5">
          {(
            [
              { id: "inline", label: t.livePreview.title },
              { id: "deployed", label: t.codeStatus.deployed },
            ] as const
          ).map((source) => (
            <button
              key={source.id}
              type="button"
              onClick={() => setBrowserSourceOverride(source.id)}
              className={cn(
                "rounded-md px-2 py-0.5 text-xs font-medium transition-colors",
                browserPreviewSource === source.id
                  ? "bg-muted/70 text-foreground"
                  : "text-muted-foreground hover:bg-muted/40 hover:text-foreground",
              )}
            >
              {source.label}
            </button>
          ))}
        </div>
      )}
      {browserPreviewSource === "deployed" ? (
        <LivePreviewPanel
          previewUrl={resultPreviewUrl}
          threadId={threadId ?? "default"}
          workspacePath={inferredWorkDir}
          className="min-h-0 flex-1"
        />
      ) : browserPreviewSource === "inline" ? (
        <LivePreviewPanel
          htmlContent={browserPreviewBlocks?.html}
          cssContent={browserPreviewBlocks?.css}
          jsContent={browserPreviewBlocks?.js}
          className="min-h-0 flex-1"
        />
      ) : (
        <BrowserPreviewPanel
          threadId={threadId ?? "default"}
          workspacePath={inferredWorkDir}
          className="min-h-0 flex-1"
        />
      )}
    </div>
  );

  // Workbench view: summary / computer view.
  if (emptyShell && !selectedEffectKey && !focusedProcessEvent) {
    const emptyEmbeddedPage =
      effectiveActiveTab === "diff" ? (
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
      ) : (
        <WorkbenchEmptyPage
          title={t.agentWorkbenchPanel.robot}
          description={
            isLoading
              ? t.agentWorkbenchPanel.startingRobotProcess
              : t.agentWorkbenchPanel.noRunningRobotProcess
          }
        />
      );

    return (
      <div
        className={cn(
          "flex size-full min-h-0 flex-col bg-[color:color-mix(in_oklch,var(--muted)_46%,var(--background))]",
          className,
        )}
      >
        <header className="relative shrink-0 border-b border-border-default px-3 py-2.5">
          <div className="flex items-center gap-2.5">
            <MainComputerStatusButton
              active={effectiveActiveTab === "agent"}
              label={
                isLoading
                  ? t.agentWorkbenchPanel.agentStatusRunning
                  : mainRunStatus.label
              }
              onClick={openMainProcess}
              runState={mainRunState}
              title={
                isLoading
                  ? t.agentWorkbenchPanel.startingRobotProcess
                  : mainRunStatus.label
              }
            />
            <div
              role="tablist"
              aria-label={t.agentWorkbench.agentComputer}
              className="flex min-w-0 flex-1 items-center gap-1 overflow-x-auto pr-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
            >
              {visibleTabs.map((tab) => {
                const active = effectiveActiveTab === tab.id;
                const Icon = tab.Icon;
                return (
                  <div
                    key={tab.id}
                    className={cn(
                      "group inline-flex h-8 max-w-[11rem] shrink-0 items-center gap-1.5 border border-transparent text-sm font-medium shadow-none transition-colors",
                      active
                        ? "border-border-subtle text-foreground"
                        : "text-muted-foreground hover:border-border-subtle hover:bg-background/45 hover:text-foreground",
                    )}
                  >
                    <button
                      type="button"
                      role="tab"
                      aria-selected={active}
                      title={tab.label}
                      onClick={() => handleOpenTab(tab.id)}
                      className="flex h-full min-w-0 items-center gap-1.5 pl-2.5"
                    >
                      <Icon className="size-4 shrink-0" />
                      <span className="truncate">{tab.label}</span>
                    </button>
                    <button
                      type="button"
                      aria-label={t.editorTabs.closeTabAria(tab.label)}
                      title={t.editorTabs.closeTabAria(tab.label)}
                      onClick={() => handleCloseTab(tab.id)}
                      className={cn(
                        "mr-0.5 flex size-8 shrink-0 items-center justify-center rounded-lg transition-all duration-200",
                        active
                          ? "text-muted-foreground/70 hover:bg-muted hover:text-foreground focus-visible:bg-muted"
                          : "text-muted-foreground/0 group-hover:text-muted-foreground/70 hover:!bg-muted hover:!text-foreground focus-visible:text-muted-foreground/70 focus-visible:bg-muted",
                      )}
                    >
                      <XIcon className="size-3" />
                    </button>
                  </div>
                );
              })}
            </div>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <button
                  type="button"
                  className="flex size-8 shrink-0 items-center justify-center rounded-lg border border-transparent bg-transparent text-muted-foreground transition-all duration-200 hover:border-border-subtle hover:bg-muted/45 hover:text-foreground"
                  title={t.agentWorkbenchPanel.tabList}
                  aria-label={t.agentWorkbenchPanel.tabList}
                >
                  <LayoutGridIcon className="size-3.5" />
                </button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-40">
                {workbenchTabs.map(({ id, label, Icon }) => {
                  const visible = !closedTabs.has(id);
                  return (
                    <DropdownMenuItem
                      key={id}
                      className="gap-2"
                      onClick={() =>
                        visible ? handleCloseTab(id) : handleOpenTab(id)
                      }
                    >
                      <Icon className="size-4 shrink-0 text-muted-foreground" />
                      <span className="flex-1 truncate">{label}</span>
                      {visible && (
                        <CheckIcon className="size-3.5 text-primary" />
                      )}
                    </DropdownMenuItem>
                  );
                })}
              </DropdownMenuContent>
            </DropdownMenu>
            {locatableTranscriptEventId ? (
              <button
                type="button"
                className="flex size-8 shrink-0 items-center justify-center rounded-lg border border-transparent bg-transparent text-muted-foreground transition-all duration-200 hover:border-border-subtle hover:bg-muted/45 hover:text-foreground"
                title={t.agentWorkbenchPanel.locateTranscriptEvent}
                aria-label={t.agentWorkbenchPanel.locateTranscriptEvent}
                onClick={() =>
                  emitLocateAgentWorkbenchEvent({
                    eventId: locatableTranscriptEventId,
                  })
                }
              >
                <LocateFixedIcon className="size-3.5" />
              </button>
            ) : null}
            {onClose ? (
              <button
                type="button"
                className="flex size-8 shrink-0 items-center justify-center rounded-lg border border-transparent bg-transparent text-muted-foreground transition-all duration-200 hover:border-border-subtle hover:bg-muted/45 hover:text-foreground"
                title={t.agentWorkbenchPanel.collapseWorkbench}
                aria-label={t.agentWorkbenchPanel.collapseWorkbench}
                onClick={onClose}
              >
                <PanelRightCloseIcon className="size-3.5" />
              </button>
            ) : null}
          </div>
        </header>
        <section
          aria-label={t.sidebar.ariaAgentWorkbench}
          className="flex min-h-0 flex-1 flex-col overflow-hidden bg-background/70"
        >
          {emptyEmbeddedPage}
        </section>
        {machineRail}
      </div>
    );
  }

  const agentKanbanPage = (
    <div className="flex min-h-0 flex-1 flex-col">
      {/* Keep the workbench focused: computer replay only becomes a peer view
          when there is a real browser or independent-agent process to show. */}
      <div className="flex items-center gap-4 border-b border-border-subtle px-5 py-2">
        {[
          { id: "summary" as const, label: t.agentWorkbenchPanel.summaryLabel },
          ...(hasIndependentTrace
            ? [
                {
                  id: "trace" as const,
                  label: t.agentWorkbench.activityTrace,
                },
              ]
            : []),
          ...(hasComputerActivity
            ? [
                {
                  id: "screen" as const,
                  label: t.agentWorkbench.computerView,
                },
              ]
            : []),
        ].map((view) => (
          <button
            key={view.id}
            type="button"
            onClick={() => setActivityView(view.id)}
            className={cn(
              "border-b border-transparent pb-1 text-xs font-medium transition-colors",
              effectiveActivityView === view.id
                ? "border-foreground/70 text-foreground"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            {view.label}
          </button>
        ))}
        <span className="ml-auto text-xs text-muted-foreground font-mono">
          {selectedRosterSeat
            ? selectedRosterSeat.name
            : (selectedAgent?.label ??
              mainAgentName ??
              t.agentWorkbenchPanel.mainComputer)}
        </span>
      </div>

      {/* View content */}
      {effectiveActivityView === "summary" ? (
        creationFocusAgent ? (
          <div className="flex min-h-0 flex-1 flex-col overflow-y-auto bg-background/70 p-3">
            <div className="mx-auto w-full max-w-xl">
              <AgentCreationCard
                agent={creationFocusAgent}
                agentStatusClass={agentStatusClass}
                agentStatusLabel={agentStatusLabel}
              />
            </div>
          </div>
        ) : (
          <AgentSummaryPage
            phases={phases}
            diffEntries={visibleDiffEntries}
            agentTiles={agentTiles}
            blocks={blocks}
            focusedProcessEvent={focusedProcessEvent}
            focusedEventId={focusedEventId}
            progressOutline={progressOutline}
            onSelectTab={onSelectTab}
            onOpenArtifact={onOpenArtifact}
          />
        )
      ) : effectiveActivityView === "trace" ? (
        selectedRosterSeat ? (
          rosterBlocks.length > 0 ? (
            <ActivityTraceView
              blocks={rosterBlocks}
              currentBlockId={pickCurrentWorkBlock(rosterBlocks)?.id ?? null}
              emptyText={t.agentWorkbenchPanel.waitingForSubagentOutput}
              subtitle={rosterSeatRoleLabel(selectedRosterSeat, t)}
              title={selectedRosterSeat.name}
              onSelectBlock={(blockId) => {
                setSelectedBlockId(blockId);
                setManualBlockSelection(true);
              }}
            />
          ) : (
            <RosterComputerPlaceholder
              seat={selectedRosterSeat}
              onOpenMain={openMainProcess}
            />
          )
        ) : (
          <ActivityTraceView
            blocks={screenBlocks}
            currentBlockId={screenFrame.block?.id ?? null}
            emptyText={
              selectedAgent
                ? t.agentWorkbenchPanel.waitingForSubagentOutput
                : t.agentWorkbench.traceFeedEmpty
            }
            subtitle={
              selectedAgent
                ? repairMojibakeText(
                    selectedAgent.role ??
                      selectedAgent.taskLabel ??
                      selectedAgent.task,
                  )
                : (currentPhase?.title ?? t.agentWorkbench.activityTrace)
            }
            title={
              selectedAgent
                ? `${selectedAgent.label} · ${repairMojibakeText(
                    selectedAgent.codename ??
                      selectedAgent.name ??
                      selectedAgent.label,
                  )}`
                : t.agentWorkbenchPanel.mainComputer
            }
            onSelectBlock={(blockId) => {
              setSelectedBlockId(blockId);
              setManualBlockSelection(true);
            }}
          />
        )
      ) : (
        <div className="flex min-h-0 flex-1 flex-col bg-background/35">
          {/* Header: agent identity + progress (hidden for roster seats — the placeholder shows identity inline) */}
          {!selectedRosterSeat && (
            <div className="flex shrink-0 items-center gap-2 border-b border-border-subtle px-5 py-2.5">
              <MonitorIcon className="size-4 shrink-0 text-muted-foreground" />
              <span className="inline-flex items-center gap-1.5 text-xs font-medium text-foreground">
                <span
                  className={cn(
                    "inline-block size-1.5 rounded-full",
                    selectedAgent
                      ? agentRunDotClass(selectedAgent.status)
                      : agentRunDotClass(mainRunState),
                  )}
                />
                {selectedAgent
                  ? `${selectedAgent.label} · ${repairMojibakeText(
                      selectedAgent.codename ?? selectedAgent.name,
                    )}`
                  : mainPhaseStatusLabel(mainPhases, t)}
              </span>
              <span className="ml-auto shrink-0 text-xs text-muted-foreground">
                {t.agentWorkbench.stepCount(
                  screenProgress.total || phases.length,
                )}
              </span>
            </div>
          )}

          {/* Agent filter chip row — quick switch between main process and sub-agents */}
          {!selectedRosterSeat && agentTiles.length > 0 && (
            <div className="flex shrink-0 items-center gap-1.5 overflow-x-auto border-b border-border-subtle px-5 py-2">
              <span className="shrink-0 text-xs font-medium text-muted-foreground/70">
                {t.agentWorkbenchPanel.filterByAgent}
              </span>
              <button
                type="button"
                onClick={openMainProcess}
                className={cn(
                  "inline-flex h-6 shrink-0 items-center gap-1 rounded-full border px-2 text-xs font-medium transition-colors",
                  !selectedAgent
                    ? "border-foreground/40 bg-foreground/10 text-foreground"
                    : "border-border-default bg-transparent text-muted-foreground hover:bg-muted/40 hover:text-foreground",
                )}
              >
                <MonitorIcon className="size-3" />
                {t.agentWorkbenchPanel.filterChipMain}
              </button>
              {agentTiles.map((agent) => {
                const isActive = selectedAgent?.id === agent.id;
                const agentLabel = repairMojibakeText(
                  agent.codename ?? agent.name ?? agent.label,
                );
                return (
                  <button
                    key={agent.id}
                    type="button"
                    onClick={() => openSubagentProcess(agent.id)}
                    className={cn(
                      "inline-flex h-6 shrink-0 items-center gap-1 rounded-full border px-2 text-xs font-medium transition-colors",
                      isActive
                        ? "border-foreground/40 bg-foreground/10 text-foreground"
                        : "border-border-default bg-transparent text-muted-foreground hover:bg-muted/40 hover:text-foreground",
                    )}
                  >
                    {agent.avatar ? (
                      <span aria-hidden="true" className="text-xs">
                        {agent.avatar}
                      </span>
                    ) : null}
                    <span className="font-mono">{agent.label}</span>
                    <span
                      className={cn(
                        "inline-block size-1.5 shrink-0 rounded-full",
                        agentRunDotClass(agent.status),
                      )}
                    />
                    <span className="max-w-[100px] truncate text-xs font-normal opacity-70">
                      {agent.role ? repairMojibakeText(agent.role) : agentLabel}
                    </span>
                  </button>
                );
              })}
            </div>
          )}

          {/* Tool call timeline */}
          {selectedRosterSeat ? (
            rosterBlocks.length > 0 ? (
              <ActivityTraceView
                blocks={rosterBlocks}
                currentBlockId={pickCurrentWorkBlock(rosterBlocks)?.id ?? null}
                emptyText={t.agentWorkbenchPanel.waitingForSubagentOutput}
                subtitle={rosterSeatRoleLabel(selectedRosterSeat, t)}
                title={selectedRosterSeat.name}
                onSelectBlock={(blockId) => {
                  setSelectedBlockId(blockId);
                  setManualBlockSelection(true);
                }}
              />
            ) : (
              <RosterComputerPlaceholder
                seat={selectedRosterSeat}
                onOpenMain={openMainProcess}
              />
            )
          ) : selectedAgent ? (
            <SubagentProcessView
              agent={selectedAgent}
              blocks={screenBlocks}
              currentBlockId={screenFrame.block?.id ?? null}
              onOpenMain={openMainProcess}
              onSelectBlock={(blockId) => {
                setSelectedBlockId(blockId);
                setManualBlockSelection(true);
              }}
            />
          ) : agentTiles.length > 0 ? (
            <div className="flex min-h-0 flex-1 flex-col overflow-y-auto bg-background/35">
              <div className="mx-auto w-full max-w-2xl px-5 py-4">
                <div className="mb-3 text-center">
                  <MonitorIcon className="mx-auto mb-2 size-8 text-muted-foreground/50" />
                  <p className="text-sm font-medium text-foreground">
                    {t.agentWorkbenchPanel.computerViewSubtitle}
                  </p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {t.agentWorkbenchPanel.computerViewSelectHint}
                  </p>
                </div>
                <div className="space-y-2">
                  {agentTiles.map((agent) => {
                    const agentLabel = repairMojibakeText(
                      agent.codename ?? agent.name ?? agent.label,
                    );
                    return (
                      <button
                        key={agent.id}
                        type="button"
                        onClick={() => openSubagentProcess(agent.id)}
                        className={cn(
                          "group flex w-full items-center gap-3 rounded-lg border border-border-default bg-background/80 px-4 py-3 text-left transition-colors hover:border-border hover:bg-muted/30",
                        )}
                      >
                        <div className="flex size-10 shrink-0 items-center justify-center rounded-md border border-border-default bg-muted/30 text-xl">
                          {agent.avatar ? (
                            <span aria-hidden="true">{agent.avatar}</span>
                          ) : (
                            <BotIcon className="size-5 text-muted-foreground" />
                          )}
                        </div>
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-2">
                            <span className="font-mono text-xs font-semibold text-foreground">
                              {agent.label}
                            </span>
                            <span
                              className={cn(
                                "inline-flex size-1.5 shrink-0 rounded-full",
                                agentRunDotClass(agent.status),
                              )}
                            />
                            <span className="text-xs text-muted-foreground">
                              {dockAgentStatusLabel(agent.status, t)}
                            </span>
                          </div>
                          <div className="mt-0.5 truncate text-xs text-muted-foreground">
                            {agent.role
                              ? repairMojibakeText(agent.role)
                              : agentLabel}
                          </div>
                          {agent.task && (
                            <div className="mt-1 truncate text-xs text-muted-foreground/70">
                              {repairMojibakeText(agent.task)}
                            </div>
                          )}
                        </div>
                        <ChevronRightIcon className="size-4 shrink-0 text-muted-foreground/50 transition-colors group-hover:text-foreground" />
                      </button>
                    );
                  })}
                </div>
              </div>
            </div>
          ) : (
            <div className="flex min-h-0 flex-1 flex-col items-center justify-center bg-muted/30 px-6 text-center">
              <div className="relative mb-3.5">
                <div className="relative flex size-12 items-center justify-center rounded-lg border border-border bg-card">
                  <MonitorIcon
                    className="size-5 text-muted-foreground/50"
                    strokeWidth={1.5}
                  />
                </div>
              </div>
              <p className="text-sm font-medium text-muted-foreground/80">
                {t.agentWorkbenchPanel.computerViewEmpty}
              </p>
              <p className="mt-1.5 max-w-xs text-xs leading-relaxed text-muted-foreground/55">
                {t.agentWorkbenchPanel.computerViewEmptyDesc}
              </p>
            </div>
          )}
        </div>
      )}
    </div>
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
      <header className="relative shrink-0 border-b border-border-default px-3 py-2.5">
        <div className="flex items-center gap-2.5">
          <MainComputerStatusButton
            active={
              effectiveActiveTab === "agent" &&
              !selectedEffectKey &&
              !selectedAgent &&
              !selectedRosterSeat
            }
            label={mainRunStatus.label}
            onClick={openMainProcess}
            runState={mainRunState}
            title={t.agentWorkbenchPanel.viewMainAgentSlot}
          />
          {visibleTabs.length === 0 ? (
            <div className="min-w-0 flex-1 px-0.5">
              <div
                className="truncate text-xs font-medium text-foreground/85"
                title={inferredWorkDir || workspaceLabel}
              >
                {workspaceLabel}
              </div>
              <div className="mt-0.5 truncate text-xs text-muted-foreground/65">
                {mainRunStatus.label}
              </div>
            </div>
          ) : null}
          <div
            role="tablist"
            aria-label={t.agentWorkbench.agentComputer}
            className={cn(
              "min-w-0 items-center gap-1 overflow-x-auto pr-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden",
              visibleTabs.length === 0 ? "hidden" : "flex flex-1",
            )}
          >
            {visibleTabs.map(({ id, label, Icon }) => {
              const active = id === effectiveActiveTab;
              return (
                <div
                  key={id}
                  className={cn(
                    "group inline-flex h-8 max-w-[11rem] shrink-0 items-center gap-1.5 border border-transparent text-sm font-medium shadow-none transition-colors",
                    active
                      ? "border-border-subtle text-foreground"
                      : "text-muted-foreground hover:border-border-subtle hover:bg-background/45 hover:text-foreground",
                  )}
                >
                  <button
                    type="button"
                    role="tab"
                    aria-selected={active}
                    title={label}
                    onClick={() => onSelectTab?.(id)}
                    className="flex h-full min-w-0 items-center gap-1.5 pl-2.5"
                  >
                    <Icon className="size-4 shrink-0" />
                    <span className="truncate">{label}</span>
                  </button>
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      handleCloseTab(id);
                    }}
                    className={cn(
                      "mr-0.5 flex size-8 shrink-0 items-center justify-center rounded-md transition-colors",
                      active
                        ? "text-muted-foreground/70 hover:bg-muted hover:text-foreground focus-visible:bg-muted"
                        : "text-muted-foreground/0 group-hover:text-muted-foreground/70 hover:!bg-muted hover:!text-foreground focus-visible:text-muted-foreground/70 focus-visible:bg-muted",
                    )}
                    aria-label={t.editorTabs.closeTabAria(label)}
                    title={t.editorTabs.closeTabAria(label)}
                  >
                    <XIcon className="size-3" />
                  </button>
                </div>
              );
            })}
          </div>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button
                type="button"
                className="flex size-8 shrink-0 items-center justify-center rounded-md border border-transparent bg-transparent text-muted-foreground transition-colors hover:border-border-subtle hover:bg-muted/45 hover:text-foreground"
                title={t.agentWorkbenchPanel.tabList}
                aria-label={t.agentWorkbenchPanel.tabList}
              >
                <LayoutGridIcon className="size-3.5" />
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-40">
              {workbenchTabs.map(({ id, label, Icon }) => {
                const visible = !closedTabs.has(id);
                return (
                  <DropdownMenuItem
                    key={id}
                    className="gap-2"
                    onClick={() =>
                      visible ? handleCloseTab(id) : handleOpenTab(id)
                    }
                  >
                    <Icon className="size-4 shrink-0 text-muted-foreground" />
                    <span className="flex-1 truncate">{label}</span>
                    {visible && <CheckIcon className="size-3.5 text-primary" />}
                  </DropdownMenuItem>
                );
              })}
            </DropdownMenuContent>
          </DropdownMenu>
          {locatableTranscriptEventId ? (
            <button
              type="button"
              className="flex size-8 shrink-0 items-center justify-center rounded-md border border-transparent bg-transparent text-muted-foreground transition-colors hover:border-border-subtle hover:bg-muted/45 hover:text-foreground"
              title={t.agentWorkbenchPanel.locateTranscriptEvent}
              aria-label={t.agentWorkbenchPanel.locateTranscriptEvent}
              onClick={() =>
                emitLocateAgentWorkbenchEvent({
                  eventId: locatableTranscriptEventId,
                })
              }
            >
              <LocateFixedIcon className="size-3.5" />
            </button>
          ) : null}
          {onClose ? (
            <button
              type="button"
              className="flex size-8 shrink-0 items-center justify-center rounded-md border border-transparent bg-transparent text-muted-foreground transition-colors hover:border-border-subtle hover:bg-muted/45 hover:text-foreground"
              title={t.agentWorkbenchPanel.collapseWorkbench}
              aria-label={t.agentWorkbenchPanel.collapseWorkbench}
              onClick={onClose}
            >
              <PanelRightCloseIcon className="size-3.5" />
            </button>
          ) : null}
        </div>
      </header>

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

function MachineScopeRail({
  agents,
  leaderSeat,
  mainRunState,
  rosterSeats,
  selectedAgentId,
  onSelectMain,
  onSelectAgent,
  onSelectRoster,
}: {
  agents: AgentTile[];
  leaderSeat: WorkbenchRosterSeat | null;
  mainRunState: AgentRunState;
  rosterSeats: WorkbenchRosterSeat[];
  selectedAgentId: string | null;
  onSelectMain: () => void;
  onSelectAgent: (agentId: string) => void;
  onSelectRoster: (seatId: string) => void;
}) {
  const { t } = useI18n();
  const hasCollaborators = rosterSeats.length > 0;
  const hasMachineChoices =
    Boolean(leaderSeat) || agents.length > 0 || hasCollaborators;
  if (!hasMachineChoices) return null;
  const mainSeatLabel =
    leaderSeat && hasCollaborators
      ? `${leaderSeat.name} · ${t.agentWorkbenchPanel.leaderSeat}`
      : leaderSeat?.name;
  const mainDockShowsPresence = Boolean(leaderSeat && hasCollaborators);
  return (
    <div
      className="flex min-w-0 shrink-0 items-center gap-2 border-t border-border-subtle bg-background/80 px-3 py-1.5"
      data-testid="workstation-bottom-rail"
    >
      <div className="flex min-w-0 flex-1 items-center gap-1.5 overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
        <WorkstationSeat
          name={leaderSeat?.name ?? t.agentWorkbenchPanel.mainController}
          avatar={leaderSeat?.icon ?? null}
          avatarUrl={leaderSeat?.avatarUrl ?? null}
          avatarNode={
            leaderSeat ? undefined : (
              <BotIcon
                className="size-3.5 text-muted-foreground"
                aria-hidden="true"
              />
            )
          }
          fallbackInitial={leaderSeat?.name.charAt(0)}
          selected={selectedAgentId === null}
          onClick={onSelectMain}
          dotClassName={
            mainDockShowsPresence
              ? "bg-emerald-500"
              : agentRunDotClass(mainRunState)
          }
          dotLabel={
            mainDockShowsPresence
              ? t.agentWorkbenchPanel.dockStatusPresent
              : undefined
          }
          ariaLabel={mainSeatLabel ?? t.agentWorkbenchPanel.viewMainAgentSlot}
          title={mainSeatLabel ?? t.agentWorkbenchPanel.mainAgentProcessTitle}
          iconOnly
          iconCaption={
            hasCollaborators ? t.agentWorkbenchPanel.leaderSeat : undefined
          }
          className="shrink-0"
        />
        {agents.map((agent) => {
          const label = agent.codename ?? agent.name ?? agent.label;
          return (
            <WorkstationSeat
              key={agent.id}
              name={repairMojibakeText(label)}
              avatar={agent.avatar}
              avatarNode={
                <BotIcon
                  className="size-3.5 text-muted-foreground"
                  aria-hidden="true"
                />
              }
              selected={selectedAgentId === agent.id}
              onClick={() => onSelectAgent(agent.id)}
              dotClassName={agentRunDotClass(agent.status)}
              dotLabel={dockAgentStatusLabel(agent.status, t)}
              ariaLabel={t.agentWorkbenchPanel.viewAgentProcess(label)}
              title={`${label}: ${agent.task}`}
              iconOnly
              className="shrink-0"
            />
          );
        })}
        {rosterSeats.map((seat) => {
          const roleLabel = rosterSeatRoleLabel(seat, t);
          return (
            <WorkstationSeat
              key={seat.id}
              name={seat.name}
              avatar={seat.icon ?? null}
              avatarUrl={seat.avatarUrl ?? null}
              showBotBadge
              fallbackInitial={seat.name.charAt(0)}
              dotClassName="bg-emerald-500"
              dotLabel={t.agentWorkbenchPanel.dockStatusPresent}
              title={`${seat.name} · ${roleLabel} · ${t.agentWorkbenchPanel.dockStatusPresent}`}
              ariaLabel={`${seat.name} · ${roleLabel} · ${t.agentWorkbenchPanel.dockStatusPresent}`}
              selected={selectedAgentId === seat.id}
              onClick={() => onSelectRoster(seat.id)}
              iconOnly
              className="shrink-0"
            />
          );
        })}
      </div>
    </div>
  );
}

function dockAgentStatusLabel(
  status: AgentTile["status"],
  t: Translations,
): string {
  if (status === "running") return t.agentWorkbenchPanel.dockStatusRunning;
  if (status === "waiting_approval")
    return t.agentWorkbenchPages.statusWaitingApproval;
  if (status === "error") return t.agentWorkbenchPanel.dockStatusError;
  if (status === "done") return t.agentWorkbenchPanel.dockStatusDone;
  return t.agentWorkbenchPanel.dockStatusPending;
}

function ComputerScopeSwitch({
  subLabel,
  onOpenMain,
}: {
  subLabel: string;
  onOpenMain: () => void;
}) {
  const { t } = useI18n();
  return (
    <div className="border-b border-border-subtle px-3 pt-2">
      <div className="flex min-w-0 items-center gap-4 text-xs font-medium">
        <span className="min-w-0 truncate border-b-2 border-foreground pb-2 text-foreground">
          {subLabel}
        </span>
        <button
          type="button"
          onClick={onOpenMain}
          className="min-w-0 truncate border-b-2 border-transparent pb-2 text-muted-foreground transition-colors hover:border-border hover:text-foreground"
          title={t.agentWorkbenchPanel.switchToMainComputer}
        >
          {t.agentWorkbenchPanel.mainComputer}
        </button>
      </div>
    </div>
  );
}

function AgentComputerStatusCard({
  avatar,
  avatarUrl,
  fallbackInitial,
  label,
  status,
  statusClassName,
  title,
}: {
  avatar?: string | null;
  avatarUrl?: string | null;
  fallbackInitial?: string;
  label: string;
  status: string;
  statusClassName: string;
  title: string;
}) {
  return (
    <div className="border-t border-border-subtle px-3 py-2">
      <div className="flex min-w-0 items-center gap-2">
        <div className="flex size-8 shrink-0 items-center justify-center overflow-hidden rounded-sm border border-border-default bg-muted/20 text-base font-semibold text-foreground">
          {avatarUrl ? (
            <img
              src={avatarUrl}
              alt={label}
              className="size-full object-cover"
            />
          ) : avatar?.trim() ? (
            <span aria-hidden="true">{avatar}</span>
          ) : fallbackInitial ? (
            fallbackInitial
          ) : (
            <BotIcon className="size-4 text-muted-foreground" />
          )}
        </div>
        <div className="min-w-0">
          <div className="truncate font-mono text-xs font-semibold text-foreground">
            {title}
          </div>
          <div className={cn("mt-0.5 truncate text-xs", statusClassName)}>
            {status}
          </div>
        </div>
      </div>
    </div>
  );
}

function RosterComputerPlaceholder({
  seat,
  onOpenMain,
}: {
  seat: WorkbenchRosterSeat;
  onOpenMain: () => void;
}) {
  const { t } = useI18n();
  const roleLabel = rosterSeatRoleLabel(seat, t);
  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
      <div className="mx-auto w-full max-w-2xl px-5 py-5">
        <section className="border-b border-border-subtle pb-4">
          <div className="flex items-center gap-3">
            <div className="flex size-11 shrink-0 items-center justify-center overflow-hidden rounded-full border border-border bg-muted/30 text-xl">
              {seat.avatarUrl ? (
                <img
                  src={seat.avatarUrl}
                  alt={seat.name}
                  className="size-full object-cover"
                />
              ) : seat.icon?.trim() ? (
                <span aria-hidden="true">{seat.icon}</span>
              ) : (
                <BotIcon className="size-7 text-muted-foreground" />
              )}
            </div>
            <div className="min-w-0">
              <div className="truncate text-sm font-semibold text-foreground">
                {seat.name}
              </div>
              <div className="mt-0.5 text-xs text-muted-foreground">
                {roleLabel}
              </div>
              <span className="mt-1.5 inline-flex items-center gap-1 rounded-full bg-emerald-500/10 px-2 py-0.5 text-xs font-medium text-emerald-700 dark:text-emerald-300">
                <span className="size-1 rounded-full bg-emerald-500" />
                {t.agentWorkbenchPanel.dockStatusPresent}
              </span>
            </div>
          </div>
          <div className="mt-4 flex items-start gap-2.5 rounded-lg border border-dashed border-border-default bg-muted/10 px-3 py-3">
            <MonitorIcon className="mt-0.5 size-4 shrink-0 text-muted-foreground/55" />
            <div>
              <div className="text-xs font-medium text-foreground">
                {t.agentWorkbenchPanel.noIndependentProcessActivity}
              </div>
              <p className="mt-1 text-xs leading-5 text-muted-foreground">
                {t.agentWorkbenchPanel.noIndependentProcessActivityDescription}
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onOpenMain}
            className="mt-3 text-xs text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
          >
            {t.agentWorkbenchPanel.switchToMainComputer}
          </button>
        </section>
      </div>
    </div>
  );
}

/**
 * The transcript is the narrative; the workbench is the proof surface. Map a
 * selected action to the one panel where it adds information instead of
 * opening a second copy of the activity log.
 */
function evidenceTabForWorkBlock(block: WorkBlock): AgentWorkbenchTabId {
  if (block.kind === "terminal") return "terminal";
  if (block.kind === "browser") return "browser";

  const eventName = block.event.name.trim().toLowerCase();
  if (
    /(?:^|_)(?:write|edit|create|delete|rename|move|patch|replace)(?:_|$)/.test(
      eventName,
    )
  ) {
    return "diff";
  }

  return "agent";
}

function ActivityTraceView({
  blocks,
  currentBlockId,
  emptyText,
  onSelectBlock,
  subtitle,
  title,
}: {
  blocks: WorkBlock[];
  currentBlockId: string | null;
  emptyText: string;
  onSelectBlock: (blockId: string) => void;
  subtitle: string;
  title: string;
}) {
  const { t } = useI18n();
  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-y-auto bg-background/35">
      <div className="mx-auto w-full max-w-2xl px-5 py-4">
        <div className="mb-3 flex min-w-0 items-center gap-2 border-b border-border-subtle pb-3">
          <ListChecksIcon className="size-4 shrink-0 text-muted-foreground" />
          <div className="min-w-0 flex-1">
            <div className="truncate text-xs font-semibold text-foreground">
              {title}
            </div>
            <div className="mt-0.5 truncate text-xs text-muted-foreground">
              {subtitle}
            </div>
          </div>
          <span className="shrink-0 text-xs text-muted-foreground">
            {t.agentWorkbench.stepCount(blocks.length)}
          </span>
        </div>

        {blocks.length === 0 ? (
          <div className="flex min-h-40 items-center justify-center px-4 text-center text-sm text-muted-foreground">
            {emptyText}
          </div>
        ) : (
          <div className="divide-y divide-border/30">
            {blocks.map((block, index) => {
              const Icon = blockIcon(block.kind);
              const active = currentBlockId === block.id;
              const target =
                block.target ||
                (block.title !== block.actionLabel ? block.title : "");
              const detail =
                block.subtitle && block.subtitle !== target
                  ? block.subtitle
                  : "";
              const showStatusText =
                block.status === "running" ||
                block.status === "waiting_approval" ||
                block.status === "error";
              return (
                <button
                  key={block.id}
                  type="button"
                  onClick={() => {
                    onSelectBlock(block.id);
                    // 侧边栏 → 对话区联动：激活共享 id，对话区滚动定位并短暂高亮
                    activateTimelineItem(block.event.id || block.id, "sidebar");
                  }}
                  className={cn(
                    "flex w-full min-w-0 items-start gap-2 border-l-2 px-1 py-2 text-left transition-colors",
                    active
                      ? "border-l-primary bg-muted/25"
                      : "border-l-transparent hover:bg-muted/20",
                  )}
                  data-timeline-item-id={block.event.id || block.id}
                  data-timeline-lane="sidebar"
                >
                  <span className="mt-0.5 w-5 shrink-0 font-mono text-xs text-muted-foreground">
                    {index + 1}
                  </span>
                  <StatusGlyph
                    status={block.status}
                    className="mt-0.5 size-3.5"
                  />
                  <Icon className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" />
                  <div className="min-w-0 flex-1">
                    <div className="flex min-w-0 items-center gap-1.5">
                      <span className="shrink-0 text-xs text-muted-foreground">
                        {block.actionLabel}
                      </span>
                      {target ? (
                        <span className="min-w-0 flex-1 truncate text-xs font-semibold text-foreground">
                          {target}
                        </span>
                      ) : null}
                    </div>
                    {detail ? (
                      <div className="mt-1 line-clamp-2 text-xs leading-4 text-muted-foreground">
                        {compactDetail(detail, 150)}
                      </div>
                    ) : null}
                  </div>
                  {showStatusText ? (
                    <span className="shrink-0 pt-0.5 text-xs text-muted-foreground/70">
                      {statusText(block.status, {
                        running: t.messageGrouping.liveProcessRunning,
                        waiting_approval: t.messageGrouping.liveProcessWaiting,
                        warning: t.messageGrouping.liveProcessDone,
                        error: t.messageGrouping.liveProcessError,
                        done: t.messageGrouping.liveProcessDone,
                      })}
                    </span>
                  ) : null}
                </button>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

function SubagentProcessView({
  agent,
  blocks,
  currentBlockId,
  onOpenMain,
  onSelectBlock,
}: {
  agent: AgentTile;
  blocks: WorkBlock[];
  currentBlockId: string | null;
  onOpenMain: () => void;
  onSelectBlock: (blockId: string) => void;
}) {
  const { t } = useI18n();
  const label = repairMojibakeText(agent.codename ?? agent.name ?? agent.label);
  const progress = agentProgressPercent(agent.status) / 100;
  const hue = agentRunHue(agent.status);
  const brief = repairMojibakeText(
    agent.prompt ?? agent.task ?? agent.lastThought ?? "",
  );

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
      <div className="mx-auto flex w-full max-w-2xl flex-col">
        <ComputerScopeSwitch
          subLabel={`${t.agentWorkbench.kindAgent} ${agent.label}`}
          onOpenMain={onOpenMain}
        />
        <section className="border-b border-border-default bg-background/85">
          <div className="flex items-center justify-center border-b border-border-subtle px-3 py-2 text-sm font-medium text-muted-foreground">
            {t.agentWorkbenchPanel.agentClusterIndependentProcess}
          </div>
          <div className="grid gap-4 p-4 sm:grid-cols-[8rem_1fr]">
            <div className="border-b border-border-subtle pb-3 sm:border-b-0 sm:border-r sm:pb-0 sm:pr-4">
              <div className="border-b border-border-default pb-1.5 font-mono text-sm font-semibold text-foreground">
                {agent.label}
              </div>
              <div className="mt-7 flex size-20 items-center justify-center rounded-sm border border-border bg-background text-4xl">
                {agent.avatar ? (
                  <span aria-hidden="true">{agent.avatar}</span>
                ) : (
                  <BotIcon className="size-10 text-foreground" />
                )}
              </div>
              <div className="mt-4 truncate text-sm font-semibold text-foreground">
                {label}
              </div>
              <div className="mt-1 truncate text-xs text-muted-foreground">
                {repairMojibakeText(agent.role ?? "Subagent")}
              </div>
            </div>
            <div className="min-w-0">
              <div className="flex items-start gap-3">
                <div className="min-w-0 flex-1">
                  <div className="truncate text-lg font-semibold text-foreground">
                    {label}
                  </div>
                  <div className="mt-1 truncate text-sm text-muted-foreground">
                    {repairMojibakeText(
                      agent.role ??
                        agent.taskLabel ??
                        t.agentWorkbenchPanel.subAgent,
                    )}
                  </div>
                </div>
                <span
                  className={cn(
                    "inline-flex shrink-0 items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs font-medium",
                    agentRunBadgeClass(agent.status),
                  )}
                >
                  <span
                    className={cn(
                      "size-2 rounded-full",
                      agentRunDotClass(agent.status),
                    )}
                  />
                  {dockAgentStatusLabel(agent.status, t)}
                </span>
              </div>
              <div className="mt-4 flex items-center gap-3">
                <DotProgress
                  progress={progress}
                  hue={hue}
                  cols={18}
                  rows={3}
                  className={cn(agent.status === "running" && "animate-pulse")}
                />
                <span className="text-xs text-muted-foreground">
                  {t.agentWorkbenchPanel.processRecords(agent.eventCount)}
                </span>
                {agent.iterationCount !== undefined && (
                  <span className="text-xs text-muted-foreground">
                    {t.agentWorkbenchPanel.iterationRounds(
                      agent.iterationCount,
                    )}
                  </span>
                )}
              </div>
              <div className="mt-4 max-h-36 overflow-y-auto whitespace-pre-wrap break-words border-l-2 border-border-default bg-muted/20 px-3 py-2 text-sm leading-6 text-foreground">
                {brief || t.agentWorkbenchPanel.noTaskDescription}
              </div>
            </div>
          </div>
        </section>

        {blocks.length === 0 ? (
          <div className="flex min-h-32 items-center justify-center border-b border-border-subtle bg-muted/15 px-4 text-sm text-muted-foreground">
            {t.agentWorkbenchPanel.waitingForSubagentOutput}
          </div>
        ) : (
          <section className="border-b border-border-subtle bg-background/70">
            <div className="flex items-center gap-2 px-3 py-2 text-sm font-medium text-muted-foreground">
              <MonitorIcon className="size-4" aria-hidden="true" />
              {t.agentWorkbenchPanel.processReplay}
              <span className="ml-auto text-xs font-normal">
                {t.agentWorkbench.stepCount(blocks.length)}
              </span>
            </div>
            <div className="divide-y divide-border/35">
              {blocks.map((block, index) => {
                const Icon = blockIcon(block.kind);
                const active = currentBlockId === block.id;
                const detail =
                  block.outputText ||
                  block.inputText ||
                  block.subtitle ||
                  block.title;
                return (
                  <button
                    key={block.id}
                    type="button"
                    onClick={() => onSelectBlock(block.id)}
                    className={cn(
                      "flex w-full items-start gap-2 border-l-2 px-3 py-2 text-left transition-colors",
                      active
                        ? "border-l-primary bg-muted/30"
                        : "border-l-transparent hover:bg-muted/25",
                    )}
                  >
                    <span className="mt-0.5 w-5 shrink-0 font-mono text-xs text-muted-foreground">
                      {index + 1}
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="flex min-w-0 items-center gap-1.5">
                        <StatusGlyph
                          status={block.status}
                          className="size-3.5"
                        />
                        <Icon className="size-3.5 shrink-0 text-muted-foreground" />
                        <span className="truncate text-xs font-semibold text-foreground">
                          {block.title}
                        </span>
                        {block.subtitle && (
                          <span className="max-w-[38%] shrink-0 truncate text-xs text-muted-foreground">
                            {block.subtitle}
                          </span>
                        )}
                      </div>
                      {detail && (
                        <div className="mt-1 line-clamp-2 text-xs leading-4 text-muted-foreground">
                          {compactDetail(detail, 150)}
                        </div>
                      )}
                    </div>
                    <span className="shrink-0 text-xs text-muted-foreground/70">
                      {statusText(block.status, {
                        running: t.messageGrouping.liveProcessRunning,
                        waiting_approval: t.messageGrouping.liveProcessWaiting,
                        warning: t.messageGrouping.liveProcessDone,
                        error: t.messageGrouping.liveProcessError,
                        done: t.messageGrouping.liveProcessDone,
                      })}
                    </span>
                  </button>
                );
              })}
            </div>
          </section>
        )}
        <AgentComputerStatusCard
          avatar={agent.avatar}
          label={label}
          status={dockAgentStatusLabel(agent.status, t)}
          statusClassName={agentStatusTextClass(agent.status)}
          title={agent.label}
        />
      </div>
    </div>
  );
}

function agentStatusTextClass(status: AgentTile["status"]): string {
  if (status === "running") return "text-primary";
  if (status === "waiting_approval")
    return "text-amber-600 dark:text-amber-300";
  if (status === "error") return "text-destructive";
  if (status === "done") return "text-emerald-600 dark:text-emerald-300";
  return "text-muted-foreground";
}
