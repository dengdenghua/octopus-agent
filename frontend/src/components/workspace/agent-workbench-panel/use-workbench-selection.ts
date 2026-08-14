import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";

import {
  findTimelineItemElement,
  getTimelineLinkageState,
  subscribeTimelineLinkage,
} from "@/core/threads/timeline-linkage";
import { pickCurrentWorkBlock, progressForWorkBlocks } from "../work-blocks";
import {
  agentTileForBlock,
  findAgentTileByFocusId,
} from "../agent-workbench-pages";
import {
  currentScreenFrame,
  screenBlocksForAgent,
} from "../agent-workbench-snapshot";
import type { AgentWorkbenchEventView } from "../agent-workbench-events";
import type {
  AgentWorkbenchProcessEventSnapshot,
  AgentWorkbenchProcessEventKind,
} from "../agent-workbench-events";
import type { AgentTile, AgentWorkbenchTabId } from "../agent-workbench-utils";
import type { WorkBlock } from "../work-blocks";
import type { AgentPhase } from "../agent-phases";
import { statusFromBlocks, evidenceTabForWorkBlock } from "./helpers";
import type { WorkbenchRosterSeat } from "./helpers";

type WorkbenchSelectionInput = {
  blocks: WorkBlock[];
  currentPhase: AgentPhase | null;
  phases: AgentPhase[];
  agentTiles: AgentTile[];
  focusedAgentId?: string | null;
  focusedAgentView?: "summary" | "screen" | "role" | null;
  focusedAgentNonce?: number;
  focusedEventId?: string | null;
  focusedEventKind?: AgentWorkbenchProcessEventKind | null;
  focusedEventView?: AgentWorkbenchEventView | null;
  focusedEventNonce?: number;
  focusedEffectKey?: string | null;
  focusedProcessEvent?: AgentWorkbenchProcessEventSnapshot | null;
  rosterSeats: WorkbenchRosterSeat[];
  onSelectTab?: (tab: AgentWorkbenchTabId) => void;
};

export function useWorkbenchSelection({
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
}: WorkbenchSelectionInput) {
  const [selectedBlockId, setSelectedBlockId] = useState<string | null>(null);
  const [selectedEffectKey, setSelectedEffectKey] = useState<string | null>(
    null,
  );
  const [manualBlockSelection, setManualBlockSelection] = useState(false);
  const [activityView, setActivityView] = useState<
    "summary" | "trace" | "screen" | "role"
  >("summary");

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
  const locatableTranscriptEventId: string =
    focusedEventId?.trim() ||
    (selectedBlock
      ? selectedBlock.event.id || selectedBlock.id
      : focusedProcessEvent
        ? (focusedEventId?.trim() ?? "")
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
      // Workbench roster clicks introduce the role. Conversation clicks carry
      // an explicit screen intent and land on the independent conversation.
      setActivityView("role");
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

  return {
    selectedBlockId,
    setSelectedBlockId,
    selectedEffectKey,
    setSelectedEffectKey,
    manualBlockSelection,
    setManualBlockSelection,
    activityView,
    setActivityView,
    selectedBlock,
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
  };
}
