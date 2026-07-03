import {
  BotIcon,
  CheckIcon,
  ChevronDownIcon,
  ChevronRightIcon,
  CircleIcon,
  CopyIcon,
  FolderIcon,
  GlobeIcon,
  LayoutGridIcon,
  MonitorIcon,
  TerminalIcon,
  UsersIcon,
  XIcon,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { useI18n } from "@/core/i18n/hooks";
import type { Translations } from "@/core/i18n/locales/types";
import { TerminalPanel } from "@/components/workspace/terminal-panel";
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
  statusIcon,
  kindLabel,
  eventTime,
  copyText,
  compactDetail,
  agentProgressPercent,
  stringFromKeys,
  textFromUnknown,
  commandForBlock,
  repairMojibakeText,
  __testing,
} from "./agent-workbench-utils";
import { useAgentWorkbenchI18n } from "./use-agent-workbench-i18n";
import {
  StatusGlyph,
  WorkBlockDetailSection,
  AgentSummaryPage,
  AgentCreationCard,
  AgentFilesPage,
  AgentDiffPage,
  WorkbenchEmptyPage,
  isAgentCreationBlock,
  agentTileForBlock,
  findAgentTileByFocusId,
} from "./agent-workbench-pages";
import {
  currentScreenFrame,
  screenBlocksForAgent,
  type ScreenFrameSnapshot,
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
  agentRunProgressBarClass,
  agentRunRobotButtonClass,
  agentRunStatusLightClass,
  agentRunStatusLightPulseClass,
  workbenchRunState,
} from "./agent-run-status";

// Re-export items that were exported from the original file
export { hasAgentWorkbenchContent, __testing } from "./agent-workbench-utils";
export type { AgentWorkbenchTabId } from "./agent-workbench-utils";
export { workspaceFocusTabFromEvents } from "./agent-workbench-utils";

type ScreenPhaseGroup = {
  id: string;
  title: string;
  detail?: string;
  status: AgentPhase["status"];
  blocks: WorkBlock[];
};

export type WorkbenchRosterSeat = {
  id: string;
  name: string;
  avatarUrl?: string | null;
  icon?: string | null;
  role?: "tl" | "member" | string | null;
};

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

function MainProcessPhaseTimeline({
  phases,
  screenBlocks,
  screenFrame,
  currentPhaseId,
  selectedBlockId,
  onSelectBlock,
}: {
  phases: AgentPhase[];
  screenBlocks: WorkBlock[];
  screenFrame: ScreenFrameSnapshot;
  currentPhaseId: string | null;
  selectedBlockId: string | null;
  onSelectBlock: (blockId: string, phaseId: string | null) => void;
}) {
  const { t } = useI18n();
  const groups = useMemo(
    () => buildScreenPhaseGroups(phases, screenBlocks, currentPhaseId, t),
    [currentPhaseId, phases, screenBlocks, t],
  );
  const currentBlockId = screenFrame.block?.id ?? null;
  const currentGroupId = useMemo(() => {
    if (currentBlockId) {
      const group = groups.find((candidate) =>
        candidate.blocks.some((block) => block.id === currentBlockId),
      );
      if (group) return group.id;
    }
    return currentPhaseId ?? groups[0]?.id ?? null;
  }, [currentBlockId, currentPhaseId, groups]);
  const [openPhaseIds, setOpenPhaseIds] = useState<Set<string>>(
    () => new Set(currentGroupId ? [currentGroupId] : []),
  );

  useEffect(() => {
    if (!currentGroupId) return;
    setOpenPhaseIds(new Set([currentGroupId]));
  }, [currentGroupId]);

  if (screenBlocks.length === 0) {
    return (
      <div className="flex min-h-32 items-center justify-center px-4 text-xs text-muted-foreground">
        {t.agentWorkbenchPanel.noOperationRecords}
      </div>
    );
  }

  if (!screenFrame.block) {
    return (
      <div className="flex min-h-32 items-center justify-center px-4 text-xs text-muted-foreground">
        {t.agentWorkbenchPanel.noCurrentOperation}
      </div>
    );
  }

  return (
    <div className="space-y-0">
      {groups.map((group) => {
        const open = openPhaseIds.has(group.id);
        const groupIsCurrent = group.id === currentGroupId;
        const recoveredCount = group.blocks.filter(
          (block) => block.status === "warning",
        ).length;
        const displayStatus =
          recoveredCount > 0 && group.status === "done"
            ? "warning"
            : group.status;
        const groupStatusMeta =
          group.blocks.length > 0
            ? [
                t.agentWorkbenchPanel.frameCount(group.blocks.length),
                recoveredCount > 0 ? statusText("warning") : null,
              ]
                .filter(Boolean)
                .join(" · ")
            : phaseStatusLabel(group.status, t);
        return (
          <section key={group.id} className="border-b border-border/25 py-2.5">
            <button
              type="button"
              onClick={() =>
                setOpenPhaseIds((prev) => {
                  const next = new Set(prev);
                  if (next.has(group.id)) next.delete(group.id);
                  else next.add(group.id);
                  return next;
                })
              }
              className="flex w-full items-center gap-2 text-left transition-colors hover:text-foreground"
            >
              <ChevronDownIcon
                className={cn(
                  "size-3.5 shrink-0 text-muted-foreground transition-transform",
                  open ? "rotate-0" : "-rotate-90",
                )}
              />
              <StatusGlyph status={displayStatus} />
              <span className="min-w-0 flex-1 truncate text-[11px] font-medium text-foreground">
                {group.title}
              </span>
              {group.detail && (
                <span className="hidden max-w-[35%] truncate text-[10px] text-muted-foreground sm:inline">
                  {group.detail}
                </span>
              )}
              <span
                className={cn(
                  "shrink-0 text-[10px] font-medium",
                  groupIsCurrent ? "text-foreground" : "text-muted-foreground",
                )}
              >
                {groupStatusMeta}
              </span>
            </button>
            {open && (
              <div className="mt-2">
                {group.blocks.length === 0 ? (
                  <div className="py-1 text-[11px] text-muted-foreground">
                    {phaseStatusLabel(group.status, t)}
                  </div>
                ) : (
                  <div className="space-y-1">
                    {group.blocks.map((block) => {
                      const frameIndex = Math.max(
                        0,
                        screenBlocks.findIndex((item) => item.id === block.id),
                      );
                      const expanded =
                        block.id === (selectedBlockId ?? currentBlockId);
                      return (
                        <ScreenFrameRow
                          key={block.id}
                          block={block}
                          expanded={expanded}
                          frameIndex={frameIndex}
                          isCurrent={block.id === currentBlockId}
                          onSelect={() => onSelectBlock(block.id, group.id)}
                          total={screenFrame.total}
                        />
                      );
                    })}
                  </div>
                )}
              </div>
            )}
          </section>
        );
      })}
    </div>
  );
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
    "relative flex size-9 shrink-0 items-center justify-center rounded-md border font-mono shadow-sm transition-colors",
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
        <div className="mt-0.5 text-[11px] opacity-80">
          {t.agentWorkbenchPanel.currentConversation}
          {" · "}
          {label}
        </div>
        <div className="mt-1 text-[11px] opacity-75">{title}</div>
      </TooltipContent>
    </Tooltip>
  );
}

function ScreenFrameRow({
  block,
  expanded,
  frameIndex,
  isCurrent,
  onSelect,
  total,
}: {
  block: WorkBlock;
  expanded: boolean;
  frameIndex: number;
  isCurrent: boolean;
  onSelect: () => void;
  total: number;
}) {
  const { t } = useI18n();
  const Icon = blockIcon(block.kind);
  const cmd = block.kind === "terminal" ? commandForBlock(block) : null;
  const cwd =
    block.kind === "terminal"
      ? stringFromKeys(block.event.input, ["cwd", "work_dir"])
      : null;
  const output =
    block.kind === "terminal"
      ? block.outputText || textFromUnknown(block.event.output) || ""
      : null;
  const statusLabel =
    block.status === "done" || block.status === "running"
      ? null
      : statusText(block.status);

  return (
    <div>
      <button
        type="button"
        onClick={onSelect}
        className={cn(
          "flex w-full items-center gap-2 py-1.5 text-left transition-colors hover:text-foreground",
          expanded && "text-foreground",
        )}
      >
        <span className="w-10 shrink-0 font-mono text-[10px] text-muted-foreground/75">
          {isCurrent
            ? t.agentWorkbenchPanel.currentFrameLabel(frameIndex + 1, total)
            : t.agentWorkbenchPanel.frameLabel(frameIndex + 1, total)}
        </span>
        <StatusGlyph status={block.status} />
        <Icon className="size-3.5 shrink-0 text-muted-foreground" />
        <span className="min-w-0 flex-1 truncate text-[11px] font-medium text-foreground">
          {block.title}
        </span>
        {block.subtitle && (
          <span className="max-w-[40%] shrink-0 truncate text-[10px] text-muted-foreground">
            {block.subtitle}
          </span>
        )}
        {statusLabel && (
          <span
            className={cn(
              "shrink-0 rounded-sm px-1.5 py-0.5 text-[10px] font-medium",
              block.status === "warning" &&
                "bg-amber-500/10 text-amber-700 dark:text-amber-300",
              block.status === "waiting_approval" &&
                "bg-amber-500/10 text-amber-700 dark:text-amber-300",
              block.status === "error" && "bg-destructive/10 text-destructive",
            )}
          >
            {statusLabel}
          </span>
        )}
        <ChevronDownIcon
          className={cn(
            "size-3.5 shrink-0 text-muted-foreground transition-transform",
            expanded ? "rotate-0" : "-rotate-90",
          )}
        />
      </button>
      {expanded && (cmd || cwd || output) && (
        <div className="ml-12 border-l border-border/25 pl-3">
          {cmd && (
            <div className="flex items-start gap-1.5 py-1.5">
              <span className="mt-0.5 shrink-0 font-mono text-[10px] text-emerald-600">
                $
              </span>
              <pre className="min-w-0 flex-1 whitespace-pre-wrap break-all font-mono text-[11px] leading-4 text-foreground">
                {cmd}
              </pre>
            </div>
          )}
          {cwd && (
            <div className="pb-1 font-mono text-[10px] text-muted-foreground">
              {cwd}
            </div>
          )}
          {output && (
            <pre className="max-h-32 overflow-auto border-t border-border/25 py-1.5 font-mono text-[10px] leading-4 text-foreground/70">
              {output}
            </pre>
          )}
        </div>
      )}
    </div>
  );
}

function buildScreenPhaseGroups(
  phases: AgentPhase[],
  screenBlocks: WorkBlock[],
  currentPhaseId: string | null,
  t: Translations,
): ScreenPhaseGroup[] {
  if (phases.length === 0) {
    return [
      {
        id: "screen:all",
        title: t.agentWorkbenchPanel.processFrames,
        status: statusFromBlocks(screenBlocks),
        blocks: screenBlocks,
      },
    ];
  }

  const screenOrder = new Map(
    screenBlocks.map((block, index) => [block.id, index]),
  );
  const blockById = new Map(screenBlocks.map((block) => [block.id, block]));
  const assigned = new Set<string>();
  const groups = phases.map((phase) => {
    const phaseBlocks = phase.blockIds
      .map((blockId) => blockById.get(blockId))
      .filter((block): block is WorkBlock => Boolean(block))
      .sort(
        (left, right) =>
          (screenOrder.get(left.id) ?? 0) - (screenOrder.get(right.id) ?? 0),
      );
    for (const block of phaseBlocks) assigned.add(block.id);
    return {
      id: phase.id,
      title: phase.title,
      detail: phase.detail,
      status: phase.status,
      blocks: phaseBlocks,
    };
  });

  const orphanBlocks = screenBlocks.filter((block) => !assigned.has(block.id));
  if (orphanBlocks.length > 0) {
    const target =
      groups.find((group) => group.id === currentPhaseId) ??
      groups.find((group) => group.status === "running") ??
      groups.find((group) => group.status !== "pending") ??
      groups[0];
    if (target) {
      const merged = new Map(target.blocks.map((block) => [block.id, block]));
      for (const block of orphanBlocks) {
        if (!merged.has(block.id)) merged.set(block.id, block);
      }
      target.blocks = Array.from(merged.values());
      target.blocks.sort(
        (left, right) =>
          (screenOrder.get(left.id) ?? 0) - (screenOrder.get(right.id) ?? 0),
      );
    }
  }

  return groups;
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

function phaseStatusLabel(status: AgentPhase["status"], t: Translations) {
  if (status === "running") return t.agentWorkbenchPanel.phaseStatusRunning;
  if (status === "waiting_approval")
    return t.agentWorkbenchPages.statusWaitingApproval;
  if (status === "error") return t.agentWorkbenchPanel.phaseStatusError;
  if (status === "done") return t.agentWorkbenchPanel.phaseStatusDone;
  return t.agentWorkbenchPanel.phaseStatusPending;
}

export function AgentWorkbenchPanel({
  activeTab,
  events,
  focusedAgentId,
  hasAnswer,
  onSelectTab,
  runSettled,
  runFailed,
  paused,
  className,
  threadId,
  workDir,
  browserPreviewBlocks,
  rosterSeats = [],
}: {
  activeTab?: AgentWorkbenchTabId;
  events: LiveToolEvent[];
  focusedAgentId?: string | null;
  hasAnswer?: boolean;
  onSelectTab?: (tab: AgentWorkbenchTabId) => void;
  runSettled?: boolean;
  runFailed?: boolean;
  threadId?: string | null;
  workDir?: string;
  paused?: boolean;
  className?: string;
  onClose?: () => void;
  browserPreviewBlocks?: ExtractedCodeBlocks | null;
  rosterSeats?: WorkbenchRosterSeat[];
}) {
  const { t } = useI18n();
  const {
    deriveAgentTiles,
    phaseBlockSummary,
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
    recentFileEvents,
    visibleDiffEntries,
  } = workbenchSnapshot;
  const [selectedPhaseId, setSelectedPhaseId] = useState<string | null>(
    currentPhase?.id ?? null,
  );
  const [manualPhaseSelection, setManualPhaseSelection] = useState(false);
  const [selectedBlockId, setSelectedBlockId] = useState<string | null>(null);
  const [manualBlockSelection, setManualBlockSelection] = useState(false);
  const [activityView, setActivityView] = useState<"summary" | "screen">(
    "summary",
  );
  // Start lean: only the file tree is shown. Diff / terminal / browser stay
  // hidden until there's something in them — they auto-reveal when a run
  // focuses them (latestWorkspaceFocusTab → activeTab → the auto-open effect
  // below) or when the user adds them from the tab menu. Tab CONTENT is already
  // lazy (only the active tab mounts), so this is purely about decluttering the
  // bar, not load cost.
  const [closedTabs, setClosedTabs] = useState<Set<AgentWorkbenchTabId>>(
    () => new Set<AgentWorkbenchTabId>(["diff", "terminal", "browser"]),
  );

  const selectedPhase =
    phases.find((phase) => phase.id === selectedPhaseId) ?? currentPhase;
  const phaseBlocks = useMemo(
    () =>
      selectedPhase
        ? blocks.filter((block) => selectedPhase.blockIds.includes(block.id))
        : blocks,
    [blocks, selectedPhase],
  );
  const defaultBlock = useMemo(
    () => pickCurrentWorkBlock(phaseBlocks) ?? phaseBlocks[0] ?? null,
    [phaseBlocks],
  );
  const selectedBlock =
    phaseBlocks.find((block) => block.id === selectedBlockId) ?? defaultBlock;
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
  const mainPhases = useMemo(
    () =>
      phases.map((phase) => ({
        ...phase,
        blockIds: phase.blockIds.filter((id) =>
          mainBlocks.some((block) => block.id === id),
        ),
        status: statusFromBlocks(
          mainBlocks.filter((block) => phase.blockIds.includes(block.id)),
        ),
      })),
    [mainBlocks, phases],
  );
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
    if (!currentPhase) {
      setSelectedPhaseId(null);
      setManualPhaseSelection(false);
      return;
    }
    setSelectedPhaseId((current) => {
      const currentStillExists = Boolean(
        current && phases.some((phase) => phase.id === current),
      );
      if (!manualPhaseSelection || !currentStillExists) {
        return currentPhase.id;
      }
      return current;
    });
  }, [currentPhase, phases, manualPhaseSelection]);

  useEffect(() => {
    if (!defaultBlock) {
      setSelectedBlockId(null);
      setManualBlockSelection(false);
      return;
    }
    setSelectedBlockId((current) => {
      const currentStillExists = Boolean(
        current && phaseBlocks.some((block) => block.id === current),
      );
      if (!manualBlockSelection || !currentStillExists) {
        return defaultBlock.id;
      }
      return current;
    });
  }, [defaultBlock, phaseBlocks, manualBlockSelection]);

  useEffect(() => {
    setSelectedAgentId((current) =>
      current && selectableAgentIds.has(current) ? current : null,
    );
  }, [selectableAgentIds]);

  const openMainProcess = useCallback(() => {
    setSelectedAgentId(null);
    setSelectedRosterSeatId(null);
    setActivityView("screen");
    setManualBlockSelection(false);
    onSelectTab?.("agent");
  }, [onSelectTab]);

  const openSubagentProcess = useCallback(
    (agentId: string) => {
      setSelectedAgentId(agentId);
      setSelectedRosterSeatId(null);
      setActivityView("screen");
      setManualBlockSelection(false);
      onSelectTab?.("agent");
    },
    [onSelectTab],
  );

  useEffect(() => {
    if (!focusedAgentId || agentTiles.length === 0) return;
    const target = findAgentTileByFocusId(focusedAgentId, agentTiles);
    if (!target) return;
    setSelectedAgentId(target.id);
    setSelectedRosterSeatId(null);
    setActivityView("screen");
  }, [focusedAgentId, agentTiles]);

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
      null)
    : null;
  useEffect(() => {
    setSelectedRosterSeatId((current) =>
      current && visibleRosterSeats.some((seat) => seat.id === current)
        ? current
        : null,
    );
  }, [visibleRosterSeats]);
  const openRosterProcess = useCallback(
    (seatId: string) => {
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
    visibleRosterSeats.length === 0;
  const mainRunStatus = workbenchStatus(mainBlocks, mainPhases);
  const mainRunState = workbenchRunState({
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
  const SelectedIcon = selectedBlock
    ? blockIcon(selectedBlock.kind)
    : MonitorIcon;
  const SelectedStatusIcon = selectedBlock
    ? statusIcon(selectedBlock.status)
    : CircleIcon;
  const requestedActiveTab: AgentWorkbenchTabId =
    activeTab ?? (focusedAgentId ? "agent" : focusedTab) ?? "agent";
  const effectiveActiveTab: AgentWorkbenchTabId =
    requestedActiveTab === "subagents" ? "agent" : requestedActiveTab;
  const workbenchTabs: Array<{
    id: AgentWorkbenchTabId;
    label: string;
    Icon: typeof MonitorIcon;
  }> = [
    // Sort by expected usage frequency and priority.
    {
      id: "files",
      label: t.agentWorkbenchPages.filesTab,
      Icon: FolderIcon,
    },
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

  // Workbench view: summary / computer view.
  if (emptyShell) {
    const emptyEmbeddedPage =
      effectiveActiveTab === "files" ? (
        <AgentFilesPage
          workDir={inferredWorkDir}
          threadId={threadId}
          recentFileEvents={recentFileEvents}
          onBackToSummary={() => handleOpenTab("agent")}
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
        browserPreviewBlocks ? (
          <LivePreviewPanel
            htmlContent={browserPreviewBlocks.html}
            cssContent={browserPreviewBlocks.css}
            jsContent={browserPreviewBlocks.js}
            className="min-h-0 flex-1"
          />
        ) : (
          <BrowserPreviewPanel
            threadId={threadId ?? "default"}
            workspacePath={inferredWorkDir}
            className="min-h-0 flex-1"
          />
        )
      ) : (
        <WorkbenchEmptyPage
          title={t.agentWorkbenchPanel.robot}
          description={t.agentWorkbenchPanel.noRunningRobotProcess}
        />
      );

    return (
      <div
        className={cn(
          "flex size-full min-h-0 flex-col bg-[color:color-mix(in_oklch,var(--muted)_46%,var(--background))]",
          className,
        )}
      >
        <header className="relative shrink-0 border-b border-border/60 px-3 py-2.5">
          <div className="flex items-center gap-2.5">
            <MainComputerStatusButton
              active={effectiveActiveTab === "agent"}
              label={t.agentWorkbenchPanel.agentStatusPending}
              onClick={openMainProcess}
              runState="pending"
              title={t.agentWorkbenchPanel.noRunningRobotProcess}
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
                      "group inline-flex h-8 max-w-[11rem] shrink-0 items-center gap-1.5 rounded-md border border-transparent text-sm font-medium shadow-none transition-colors",
                      active
                        ? "border-border/45 text-foreground"
                        : "text-muted-foreground hover:border-border/35 hover:bg-background/45 hover:text-foreground",
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
                      aria-label={`Close ${tab.label}`}
                      title={`Close ${tab.label}`}
                      onClick={() => handleCloseTab(tab.id)}
                      className={cn(
                        "mr-0.5 flex size-8 shrink-0 items-center justify-center rounded-md transition-colors",
                        active
                          ? "text-muted-foreground/70 hover:bg-muted hover:text-foreground"
                          : "text-muted-foreground/0 group-hover:text-muted-foreground/70 hover:!bg-muted hover:!text-foreground",
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
                  className="flex size-8 shrink-0 items-center justify-center rounded-md border border-transparent bg-transparent text-muted-foreground transition-colors hover:border-border/45 hover:bg-muted/45 hover:text-foreground"
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
          </div>
        </header>
        <main className="flex min-h-0 flex-1 flex-col overflow-hidden bg-background/70">
          {emptyEmbeddedPage}
        </main>
        {machineRail}
      </div>
    );
  }

  const agentKanbanPage = (
    <div className="flex min-h-0 flex-1 flex-col">
      {/* View switch tabs */}
      <div className="flex items-center gap-4 border-b border-border/30 px-5 py-2">
        {[
          { id: "summary" as const, label: t.agentWorkbenchPanel.summaryLabel },
          { id: "screen" as const, label: t.agentWorkbench.computerView },
        ].map((view) => (
          <button
            key={view.id}
            type="button"
            onClick={() => setActivityView(view.id)}
            className={cn(
              "border-b border-transparent pb-1 text-[11px] font-medium transition-colors",
              activityView === view.id
                ? "border-foreground/70 text-foreground"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            {view.label}
          </button>
        ))}
        <span className="ml-auto text-[10px] text-muted-foreground font-mono">
          {selectedRosterSeat
            ? t.agentWorkbenchPanel.subComputer
            : (selectedAgent?.label ?? "Agent 01")}
        </span>
      </div>

      {/* View content */}
      {activityView === "summary" ? (
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
            onSelectTab={onSelectTab}
          />
        )
      ) : (
        <div className="flex min-h-0 flex-1 flex-col bg-background/35">
          {/* Header: agent identity + status */}
          <div className="flex shrink-0 items-center gap-2 border-b border-border/30 px-5 py-3">
            <MonitorIcon className="size-4 shrink-0 text-muted-foreground" />
            <span className="inline-flex items-center gap-1.5 text-xs font-medium text-foreground">
              <span
                className={cn(
                  "inline-block size-1.5 rounded-full",
                  selectedRosterSeat
                    ? "bg-emerald-500"
                    : selectedAgent
                      ? agentRunDotClass(selectedAgent.status)
                      : agentRunDotClass(mainRunState),
                )}
              />
              {selectedRosterSeat ? (
                t.agentWorkbenchPanel.subComputer
              ) : (
                <>
                  {t.agentWorkbench.currentProgress}{" "}
                  {screenProgress.total > 0
                    ? `${screenProgress.current}/${screenProgress.total}`
                    : phases.length > 0
                      ? `${Math.max(1, phases.findIndex((p) => p.id === currentPhase?.id) + 1)}/${phases.length}`
                      : "0/0"}
                </>
              )}
            </span>
            <span className="h-4 w-px bg-border/45" />
            <span className="min-w-0 flex-1 truncate text-xs text-muted-foreground">
              {selectedRosterSeat
                ? `${t.agentWorkbenchPanel.subComputer} · ${selectedRosterSeat.name}`
                : selectedAgent
                  ? `${selectedAgent.label} · ${repairMojibakeText(
                      selectedAgent.codename ?? selectedAgent.name,
                    )}${
                      selectedAgent.role
                        ? ` · ${repairMojibakeText(selectedAgent.role)}`
                        : ""
                    }`
                  : (currentPhase?.title ?? t.agentWorkbench.computerView)}
            </span>
            <span className="ml-auto flex shrink-0 items-center gap-1 text-[10px] text-muted-foreground">
              <span>
                {selectedRosterSeat
                  ? t.agentWorkbenchPanel.dockStatusPresent
                  : selectedAgent
                    ? dockAgentStatusLabel(selectedAgent.status, t)
                    : mainPhaseStatusLabel(mainPhases, t)}
              </span>
            </span>
          </div>

          {/* Tool call timeline */}
          {selectedRosterSeat ? (
            <RosterComputerPlaceholder
              seat={selectedRosterSeat}
              onOpenMain={openMainProcess}
            />
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
          ) : (
            <>
              <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
                <div className="mx-auto w-full max-w-2xl px-5 py-3">
                  <MainProcessPhaseTimeline
                    currentPhaseId={currentPhase?.id ?? null}
                    onSelectBlock={(blockId, phaseId) => {
                      if (phaseId) {
                        setSelectedPhaseId(phaseId);
                        setManualPhaseSelection(true);
                      }
                      setSelectedBlockId(blockId);
                      setManualBlockSelection(true);
                    }}
                    phases={phases}
                    screenBlocks={screenBlocks}
                    screenFrame={screenFrame}
                    selectedBlockId={selectedBlockId}
                  />
                </div>
              </div>

              {/* Bottom agent switcher */}
            </>
          )}
        </div>
      )}
    </div>
  );

  const effectiveEmbeddedPage =
    effectiveActiveTab === "agent" ? (
      agentKanbanPage
    ) : effectiveActiveTab === "files" ? (
      <AgentFilesPage
        workDir={inferredWorkDir}
        threadId={threadId}
        recentFileEvents={recentFileEvents}
        onBackToSummary={() => handleOpenTab("agent")}
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
      browserPreviewBlocks ? (
        <LivePreviewPanel
          htmlContent={browserPreviewBlocks.html}
          cssContent={browserPreviewBlocks.css}
          jsContent={browserPreviewBlocks.js}
          className="min-h-0 flex-1"
        />
      ) : (
        <BrowserPreviewPanel
          threadId={threadId ?? "default"}
          workspacePath={inferredWorkDir}
        />
      )
    ) : undefined;

  return (
    <div
      className={cn(
        "flex size-full min-h-0 flex-col bg-[color:color-mix(in_oklch,var(--muted)_46%,var(--background))]",
        className,
      )}
    >
      <header className="relative shrink-0 border-b border-border/60 px-3 py-2.5">
        <div className="flex items-center gap-2.5">
          <MainComputerStatusButton
            active={
              effectiveActiveTab === "agent" &&
              !selectedAgent &&
              !selectedRosterSeat
            }
            label={mainRunStatus.label}
            onClick={openMainProcess}
            runState={mainRunState}
            title={t.agentWorkbenchPanel.viewMainAgentSlot}
          />
          <div
            role="tablist"
            aria-label={t.agentWorkbench.agentComputer}
            className="flex min-w-0 flex-1 items-center gap-1 overflow-x-auto pr-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
          >
            {visibleTabs.map(({ id, label, Icon }) => {
              const active = id === effectiveActiveTab;
              return (
                <div
                  key={id}
                  className={cn(
                    "group inline-flex h-8 max-w-[11rem] shrink-0 items-center gap-1.5 rounded-md border border-transparent text-sm font-medium shadow-none transition-colors",
                    active
                      ? "border-border/45 text-foreground"
                      : "text-muted-foreground hover:border-border/35 hover:bg-background/45 hover:text-foreground",
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
                        ? "text-muted-foreground/70 hover:bg-muted hover:text-foreground"
                        : "text-muted-foreground/0 group-hover:text-muted-foreground/70 hover:!bg-muted hover:!text-foreground",
                    )}
                    aria-label={`Close ${label}`}
                    title={`Close ${label}`}
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
                className="flex size-8 shrink-0 items-center justify-center rounded-md border border-transparent bg-transparent text-muted-foreground transition-colors hover:border-border/45 hover:bg-muted/45 hover:text-foreground"
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
        </div>
      </header>

      {threadId ? (
        <>
          <CoworkCollabBar threadId={threadId} rosterSeats={rosterSeats} />
          <div className="px-3 pb-2">
            <CollaborationSessionPanel threadId={threadId} onlyWhenRoomLinked />
          </div>
        </>
      ) : null}

      {effectiveEmbeddedPage ? (
        <main className="flex min-h-0 flex-1 flex-col overflow-hidden bg-background/70">
          {effectiveEmbeddedPage}
        </main>
      ) : (
        <main className="flex min-h-0 flex-1 flex-col">
          <div className="flex min-h-0 flex-1 flex-col overflow-y-auto bg-background/70">
            <div className="flex items-center border-b border-border/45 px-4 py-1 text-[11px]">
              <span className="mx-auto font-mono text-foreground">
                {selectedAgent
                  ? `${t.agentWorkbench.kindAgent} ${selectedAgent.label}`
                  : `${t.agentWorkbench.kindAgent} 01`}
              </span>
              <button
                type="button"
                onClick={() =>
                  setActivityView((value) =>
                    value === "summary" ? "screen" : "summary",
                  )
                }
                className="ml-auto inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] text-muted-foreground transition-colors hover:bg-muted/50 hover:text-foreground"
              >
                <UsersIcon className="size-3.5" />
                {activityView === "summary"
                  ? t.agentWorkbench.computerViewLabel
                  : t.agentWorkbench.activityTrace}
              </button>
            </div>

            <div className="mx-auto flex w-full max-w-2xl flex-1 flex-col px-3 py-3">
              {activityView === "screen" ? (
                <div className="flex min-h-48 flex-1 items-center justify-center rounded-lg border border-border/55 bg-background/80 px-4 text-sm text-muted-foreground shadow-sm">
                  {t.agentWorkbench.computerViewHint}
                </div>
              ) : selectedPhase ? (
                <section className="rounded-lg border border-border/55 bg-background/85 px-3 py-3 shadow-sm">
                  <div className="flex items-center gap-2 text-sm font-medium text-foreground">
                    <StatusGlyph status={selectedPhase.status} />
                    <span>{selectedPhase.title}</span>
                    <span className="ml-auto text-xs text-muted-foreground">
                      {phaseBlockSummary(selectedPhase, blocks)}
                    </span>
                  </div>
                  <div className="mt-3 space-y-1.5">
                    {phaseBlocks.length === 0 ? (
                      <div className="py-4 text-center text-sm text-muted-foreground">
                        {selectedPhase.status === "done"
                          ? t.agentWorkbench.phaseCompleted
                          : selectedPhase.status === "error"
                            ? t.agentWorkbench.statusError
                            : t.agentWorkbench.waitingForPhase}
                      </div>
                    ) : (
                      phaseBlocks.map((block) => {
                        const Icon = blockIcon(block.kind);
                        const active = selectedBlock?.id === block.id;
                        return (
                          <button
                            key={block.id}
                            type="button"
                            onClick={() => {
                              setSelectedBlockId(block.id);
                              setManualBlockSelection(true);
                            }}
                            className={cn(
                              "flex w-full items-center gap-2.5 rounded-md px-2.5 py-1.5 text-left text-sm transition-colors",
                              active
                                ? "bg-muted/70 text-foreground"
                                : "text-muted-foreground hover:bg-muted/45 hover:text-foreground",
                            )}
                          >
                            <StatusGlyph status={block.status} />
                            <Icon className="size-4 shrink-0" />
                            <span className="min-w-0 flex-1 truncate">
                              {block.title}
                            </span>
                            <span className="max-w-[45%] truncate text-xs text-muted-foreground">
                              {block.subtitle}
                            </span>
                            <ChevronDownIcon className="size-3.5 -rotate-90 opacity-50" />
                          </button>
                        );
                      })
                    )}
                  </div>
                </section>
              ) : (
                <WorkbenchEmptyPage
                  title={t.agentWorkbenchPanel.robot}
                  description={t.agentWorkbenchPanel.noRunningRobotProcess}
                />
              )}

              {selectedBlock && (
                <section className="mt-3 overflow-hidden rounded-lg border border-border/55 bg-background/85 shadow-sm">
                  <div className="flex items-center justify-between border-b border-border/45 px-3 py-2">
                    <div className="flex min-w-0 items-center gap-2">
                      <SelectedIcon className="size-4 shrink-0 text-muted-foreground" />
                      <span className="truncate text-xs font-semibold text-foreground">
                        {selectedBlock.title}
                      </span>
                      <span className="shrink-0 text-xs font-normal text-muted-foreground">
                        {kindLabel(selectedBlock.kind, t.agentWorkbench)} ·{" "}
                        {eventTime(selectedBlock)}
                      </span>
                    </div>
                    <button
                      type="button"
                      className="rounded-md p-1 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                      onClick={() =>
                        copyText(
                          selectedBlock.outputText ||
                            selectedBlock.inputText ||
                            selectedBlock.subtitle,
                        )
                      }
                      title={t.agentWorkbench.copyDetails}
                    >
                      <CopyIcon className="size-3.5" />
                    </button>
                  </div>
                  <div className="grid divide-y divide-border/45">
                    <WorkBlockDetailSection
                      key={`${selectedBlock.id}:request`}
                      title={t.agentWorkbench.request}
                      content={
                        selectedBlock.inputText || selectedBlock.subtitle
                      }
                    />
                    <WorkBlockDetailSection
                      key={`${selectedBlock.id}:response`}
                      title={t.agentWorkbench.response}
                      content={selectedBlock.outputText}
                      empty={
                        <div className="flex min-h-16 items-center gap-2 px-3 py-2.5 text-sm text-muted-foreground">
                          {selectedBlock.status === "running" ? (
                            <>
                              <CircleIcon className="size-3 animate-pulse" />
                              {t.agentWorkbench.waitingForToolResult}
                            </>
                          ) : (
                            <>
                              <SelectedStatusIcon className="size-3.5" />
                              {statusText(selectedBlock.status)}
                            </>
                          )}
                        </div>
                      }
                    />
                  </div>
                </section>
              )}
            </div>
          </div>

          {agentTiles.length > 0 && (
            <div className="shrink-0 border-t border-border/55 bg-background/90 px-4 py-2">
              <div className="flex gap-2 overflow-x-auto pb-1">
                {agentTiles.map((agent) => {
                  const active = selectedAgent?.id === agent.id;
                  const percent = agentProgressPercent(agent.status);
                  return (
                    <button
                      key={agent.id}
                      type="button"
                      onClick={() => setSelectedAgentId(agent.id)}
                      title={`${repairMojibakeText(agent.name)}: ${repairMojibakeText(agent.task)}`}
                      className={cn(
                        "flex min-w-32 items-center gap-2 rounded-lg border px-2.5 py-1.5 text-left transition-colors",
                        active
                          ? "border-foreground/70 bg-background"
                          : "border-transparent bg-muted/45 hover:bg-muted/70",
                      )}
                    >
                      {agent.avatar ? (
                        <span
                          className="flex size-7 shrink-0 items-center justify-center rounded-full bg-background text-base"
                          aria-hidden="true"
                          title={agent.role ?? "subagent"}
                        >
                          {agent.avatar}
                        </span>
                      ) : (
                        <BotIcon className="size-7 shrink-0 rounded-full bg-background p-1 text-foreground" />
                      )}
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center justify-between gap-2 font-mono text-xs text-foreground">
                          <span>{repairMojibakeText(agent.name)}</span>
                          <span>{repairMojibakeText(agent.label)}</span>
                        </div>
                        <div className="mt-1 line-clamp-1 text-[11px] text-muted-foreground">
                          {compactDetail(agent.task, 56)}
                        </div>
                        <div
                          className={cn(
                            "mt-1 truncate text-[11px]",
                            agentStatusClass(agent.status),
                          )}
                        >
                          {dockAgentStatusLabel(agent.status, t)}
                        </div>
                        <div className="mt-1 h-1 overflow-hidden rounded-full bg-muted">
                          <div
                            className={cn(
                              "h-full rounded-full transition-all",
                              agentRunProgressBarClass(agent.status),
                            )}
                            style={{ width: `${percent}%` }}
                          />
                        </div>
                      </div>
                    </button>
                  );
                })}
              </div>
              {selectedAgent && (
                <div className="mt-0.5 truncate px-1 text-[11px] text-muted-foreground">
                  {repairMojibakeText(selectedAgent.name)} ·{" "}
                  {compactDetail(selectedAgent.task)}
                </div>
              )}
            </div>
          )}
        </main>
      )}
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
      className="flex min-w-0 shrink-0 items-center gap-2 border-t border-border/45 bg-background/80 px-3 py-1.5"
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
        {rosterSeats.map((seat) => (
          <WorkstationSeat
            key={seat.id}
            name={seat.name}
            avatar={seat.icon ?? null}
            avatarUrl={seat.avatarUrl ?? null}
            showBotBadge
            fallbackInitial={seat.name.charAt(0)}
            dotClassName="bg-emerald-500"
            dotLabel={t.agentWorkbenchPanel.dockStatusPresent}
            title={`${seat.name} · ${t.agentWorkbenchPanel.subComputer} · ${t.agentWorkbenchPanel.dockStatusPresent}`}
            ariaLabel={`${seat.name} · ${t.agentWorkbenchPanel.subComputer} · ${t.agentWorkbenchPanel.dockStatusPresent}`}
            selected={selectedAgentId === seat.id}
            onClick={() => onSelectRoster(seat.id)}
            iconOnly
            className="shrink-0"
          />
        ))}
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
    <div className="border-b border-border/45 px-3 pt-2">
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
    <div className="border-t border-border/45 px-3 py-2">
      <div className="flex min-w-0 items-center gap-2">
        <div className="flex size-8 shrink-0 items-center justify-center overflow-hidden rounded-sm border border-border/55 bg-muted/20 text-base font-semibold text-foreground">
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
          <div className={cn("mt-0.5 truncate text-[11px]", statusClassName)}>
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
  const rows = [
    {
      label: t.agentWorkbenchPanel.collaboratorJoinedConversation,
      detail: `${seat.name} · ${t.agentWorkbenchPanel.dockStatusPresent}`,
      status: "done" as const,
    },
    {
      label: t.agentWorkbenchPanel.handoffReady,
      detail: t.agentWorkbenchPanel.collaboratorComputerWaiting,
      status: "running" as const,
    },
    {
      label: t.agentWorkbenchPanel.independentProcessPending,
      detail: t.agentWorkbenchPanel.waitingForSubagentOutput,
      status: "pending" as const,
    },
  ];
  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
      <div className="mx-auto flex w-full max-w-2xl flex-col">
        <ComputerScopeSwitch
          subLabel={t.agentWorkbenchPanel.subComputer}
          onOpenMain={onOpenMain}
        />
        <section className="border-b border-border/55 bg-background/85">
          <div className="flex items-center gap-2 border-b border-border/40 px-3 py-2">
            <MonitorIcon className="size-4 text-muted-foreground" />
            <div className="min-w-0 flex-1 truncate text-sm font-medium text-foreground">
              {t.agentWorkbenchPanel.subComputerReady}
            </div>
            <span className="inline-flex shrink-0 items-center gap-1.5 rounded-md bg-emerald-500/10 px-2 py-1 text-[11px] font-medium text-emerald-700 dark:text-emerald-300">
              <span className="size-2 rounded-full bg-emerald-500" />
              {t.agentWorkbenchPanel.dockStatusPresent}
            </span>
          </div>
          <div className="grid gap-4 p-4 sm:grid-cols-[8rem_1fr]">
            <div className="border-b border-border/45 pb-3 sm:border-b-0 sm:border-r sm:pb-0 sm:pr-4">
              <div className="border-b border-border/60 pb-1.5 font-mono text-sm font-semibold text-foreground">
                {t.agentWorkbenchPanel.subComputer}
              </div>
              <div className="mt-7 flex size-20 items-center justify-center overflow-hidden rounded-sm border border-border bg-background text-4xl">
                {seat.avatarUrl ? (
                  <img
                    src={seat.avatarUrl}
                    alt={seat.name}
                    className="size-full object-cover"
                  />
                ) : seat.icon?.trim() ? (
                  <span aria-hidden="true">{seat.icon}</span>
                ) : (
                  <BotIcon className="size-10 text-foreground" />
                )}
              </div>
              <div className="mt-4 truncate text-sm font-semibold text-foreground">
                {seat.name}
              </div>
              <div className="mt-1 truncate text-xs text-muted-foreground">
                {t.agentWorkbenchPanel.collaboratorSeat}
              </div>
            </div>
            <div className="min-w-0">
              <div className="flex items-start gap-3">
                <div className="min-w-0 flex-1">
                  <div className="truncate text-lg font-semibold text-foreground">
                    {seat.name}
                  </div>
                  <div className="mt-1 truncate text-sm text-muted-foreground">
                    {t.agentWorkbenchPanel.subComputerReadyDescription}
                  </div>
                </div>
              </div>
              <div className="mt-4 flex items-center gap-3">
                <DotProgress progress={0.18} hue={118} cols={18} rows={3} />
                <span className="text-xs text-muted-foreground">
                  {t.agentWorkbenchPanel.waitingForSubagentOutput}
                </span>
              </div>
            </div>
          </div>
        </section>
        <section className="border-b border-border/45 bg-background/70">
          <div className="flex items-center gap-2 px-3 py-2 text-sm font-medium text-muted-foreground">
            <MonitorIcon className="size-4" aria-hidden="true" />
            {t.agentWorkbench.activityTrace}
            <span className="ml-auto text-xs font-normal">
              {t.agentWorkbenchPanel.processRecords(rows.length)}
            </span>
          </div>
          <div className="divide-y divide-border/35">
            {rows.map((row, index) => {
              const active = row.status === "running";
              const Icon = row.status === "done" ? CheckIcon : CircleIcon;
              return (
                <div
                  key={row.label}
                  className={cn(
                    "flex items-start gap-2 border-l-2 px-3 py-2 text-left",
                    active
                      ? "border-l-primary bg-muted/30"
                      : "border-l-transparent",
                  )}
                >
                  <span className="mt-0.5 w-5 shrink-0 font-mono text-[10px] text-muted-foreground">
                    {index + 1}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex min-w-0 items-center gap-1.5">
                      <Icon
                        className={cn(
                          "size-3.5 shrink-0",
                          row.status === "done"
                            ? "text-emerald-500"
                            : active
                              ? "animate-pulse text-primary"
                              : "text-muted-foreground",
                        )}
                      />
                      <span className="truncate text-xs font-semibold text-foreground">
                        {row.label}
                      </span>
                    </div>
                    <div className="mt-1 line-clamp-2 text-[11px] leading-4 text-muted-foreground">
                      {row.detail}
                    </div>
                  </div>
                  <span className="shrink-0 text-[10px] text-muted-foreground/70">
                    {row.status === "done"
                      ? t.agentWorkbenchPanel.dockStatusDone
                      : active
                        ? t.agentWorkbenchPanel.dockStatusRunning
                        : t.agentWorkbenchPanel.dockStatusPending}
                  </span>
                </div>
              );
            })}
          </div>
        </section>
        <AgentComputerStatusCard
          avatar={seat.icon}
          avatarUrl={seat.avatarUrl}
          fallbackInitial={seat.name.charAt(0)}
          label={seat.name}
          status={t.agentWorkbenchPanel.dockStatusPresent}
          statusClassName="text-emerald-600 dark:text-emerald-300"
          title={t.agentWorkbenchPanel.subComputer}
        />
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
        <section className="border-b border-border/55 bg-background/85">
          <div className="flex items-center justify-center border-b border-border/40 px-3 py-2 text-sm font-medium text-muted-foreground">
            {t.agentWorkbenchPanel.agentClusterIndependentProcess}
          </div>
          <div className="grid gap-4 p-4 sm:grid-cols-[8rem_1fr]">
            <div className="border-b border-border/45 pb-3 sm:border-b-0 sm:border-r sm:pb-0 sm:pr-4">
              <div className="border-b border-border/60 pb-1.5 font-mono text-sm font-semibold text-foreground">
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
              <div className="mt-4 max-h-36 overflow-y-auto whitespace-pre-wrap break-words border-l-2 border-border/60 bg-muted/20 px-3 py-2 text-sm leading-6 text-foreground">
                {brief || t.agentWorkbenchPanel.noTaskDescription}
              </div>
            </div>
          </div>
        </section>

        {blocks.length === 0 ? (
          <div className="flex min-h-32 items-center justify-center border-b border-border/45 bg-muted/15 px-4 text-sm text-muted-foreground">
            {t.agentWorkbenchPanel.waitingForSubagentOutput}
          </div>
        ) : (
          <section className="border-b border-border/45 bg-background/70">
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
                    <span className="mt-0.5 w-5 shrink-0 font-mono text-[10px] text-muted-foreground">
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
                          <span className="max-w-[38%] shrink-0 truncate text-[11px] text-muted-foreground">
                            {block.subtitle}
                          </span>
                        )}
                      </div>
                      {detail && (
                        <div className="mt-1 line-clamp-2 text-[11px] leading-4 text-muted-foreground">
                          {compactDetail(detail, 150)}
                        </div>
                      )}
                    </div>
                    <span className="shrink-0 text-[10px] text-muted-foreground/70">
                      {statusText(block.status)}
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
