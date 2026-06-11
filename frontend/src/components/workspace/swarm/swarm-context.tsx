import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import {
  fetchBatch,
  streamBatch,
  type BatchStreamEvent,
} from "@/core/parallel-agents/api";

import { useI18n } from "@/core/i18n/hooks";

import { batchToSession, fetchFirstRunningSession } from "./live-driver";
import { buildMockSession } from "./mock-data";
import { generateTraceTick } from "./trace-generator";
import type {
  AgentStatus,
  SwarmSession,
  SwarmWorkflowSnapshot,
  TraceEntry,
} from "./types";

interface SwarmContextValue {
  session: SwarmSession;
  setSession: (s: SwarmSession) => void;
  selectedAgentId: string;
  setSelectedAgentId: (id: string) => void;
  panelOpen: boolean;
  openPanel: () => void;
  closePanel: () => void;
  togglePanel: () => void;
  simulating: boolean;
  startSimulation: () => void;
  resetSimulation: () => void;
  liveMode: boolean;
  enableLiveMode: () => void;
  disableLiveMode: () => void;
  /** Subscribe to a parallel agent batch via SSE. Updates session in real-time. */
  connectBatch: (batchId: string) => void;
  /** Disconnect from the current SSE batch stream. */
  disconnectBatch: () => void;
  /** The batch ID currently connected via SSE, or null. */
  connectedBatchId: string | null;
}

const SwarmContext = createContext<SwarmContextValue | null>(null);

const ACTIVE_STATUSES: AgentStatus[] = [
  "reasoning",
  "iterating",
  "generating",
  "analyzing",
  "summarizing",
];

function mapParallelStatus(status: string): AgentStatus {
  switch (status) {
    case "completed":
    case "done":
      return "done";
    case "running":
    case "busy":
    case "in_progress":
      return "reasoning";
    case "failed":
    case "error":
      return "failed";
    case "cancelled":
      return "cancelled";
    case "timed_out":
      return "timed_out";
    default:
      return "pending";
  }
}

function isTerminalStatus(status: AgentStatus): boolean {
  return (
    status === "done" ||
    status === "failed" ||
    status === "cancelled" ||
    status === "timed_out"
  );
}

function taskPhaseIndex(session: SwarmSession, taskId: string): number {
  const phase = session.plan?.phases.find((candidate) =>
    candidate.taskIds.includes(taskId),
  );
  return phase?.phaseIndex ?? 0;
}

function extractArtifacts(text: string): string[] {
  const pathRe = /(?:\/[\w.-]+)+\.\w+/g;
  return [...new Set(text.match(pathRe) ?? [])];
}

function payloadNumber(
  payload: Record<string, unknown> | undefined,
  key: string,
): number | undefined {
  const value = payload?.[key];
  return typeof value === "number" && Number.isFinite(value)
    ? value
    : undefined;
}

function workflowFromStageEvent(
  session: SwarmSession,
  event: BatchStreamEvent,
): SwarmWorkflowSnapshot {
  const previous = session.workflow;
  return {
    stage: event.stage ?? previous?.stage,
    status: event.status ?? previous?.status,
    progress: event.progress ?? previous?.progress,
    totalTasks:
      payloadNumber(event.payload, "total_tasks") ??
      previous?.totalTasks ??
      session.agents.length,
    completedTasks:
      payloadNumber(event.payload, "completed_tasks") ??
      previous?.completedTasks ??
      0,
    failedTasks:
      payloadNumber(event.payload, "failed_tasks") ??
      previous?.failedTasks ??
      0,
    cancelledTasks:
      payloadNumber(event.payload, "cancelled_tasks") ??
      previous?.cancelledTasks ??
      0,
    updatedAt: Date.now(),
  };
}

function eventTimestamp(event: BatchStreamEvent): number {
  if (event.created_at) {
    const parsed = Date.parse(event.created_at);
    if (Number.isFinite(parsed)) return parsed;
  }
  return Date.now();
}

function upsertLiveHandoff(
  session: SwarmSession,
  event: BatchStreamEvent,
): NonNullable<SwarmSession["handoffs"]> {
  const taskId = event.task_id ?? "";
  if (!taskId) return session.handoffs ?? [];

  const summary =
    event.result_preview ??
    event.message ??
    event.error ??
    event.description ??
    "";
  const next = {
    agentId: event.subagent_name ?? taskId,
    taskId,
    phaseIndex: taskPhaseIndex(session, taskId),
    nodeIds: event.node_ids?.length ? event.node_ids : [taskId],
    status: event.status ?? "pending",
    summary,
    artifacts: extractArtifacts(summary),
    costUsd: 0,
    reason: event.error,
  };
  const previous = session.handoffs ?? [];
  const existing = previous.findIndex((handoff) => handoff.taskId === taskId);
  if (existing < 0) return [...previous, next];
  return previous.map((handoff, index) =>
    index === existing ? { ...handoff, ...next } : handoff,
  );
}

function recomputePhaseReports(
  session: SwarmSession,
  handoffs: NonNullable<SwarmSession["handoffs"]>,
): NonNullable<SwarmSession["phaseReports"]> {
  const phases = session.plan?.phases;
  if (!phases?.length) {
    if (handoffs.length === 0) return [];
    const succeeded = handoffs.filter((handoff) =>
      ["completed", "success", "done"].includes(handoff.status),
    ).length;
    const failed = handoffs.filter((handoff) =>
      ["failed", "cancelled", "timed_out"].includes(handoff.status),
    ).length;
    return [{
      phaseIndex: 0,
      nodeIds: [...new Set(handoffs.flatMap((handoff) => handoff.nodeIds))],
      assignmentCount: handoffs.length,
      handoffCount: handoffs.length,
      succeeded,
      failed,
      status: succeeded === handoffs.length ? "success" : failed === handoffs.length ? "failed" : "partial",
      wallMs: 0,
      costUsd: handoffs.reduce((total, handoff) => total + handoff.costUsd, 0),
    }];
  }

  return phases.map((phase) => {
    const phaseHandoffs = handoffs.filter((handoff) =>
      phase.taskIds.includes(handoff.taskId),
    );
    const succeeded = phaseHandoffs.filter((handoff) =>
      ["completed", "success", "done"].includes(handoff.status),
    ).length;
    const failed = phaseHandoffs.filter((handoff) =>
      ["failed", "cancelled", "timed_out"].includes(handoff.status),
    ).length;
    const status =
      phaseHandoffs.length === 0
        ? "empty"
        : succeeded === phase.taskIds.length
          ? "success"
          : failed === phase.taskIds.length
            ? "failed"
            : "partial";
    return {
      phaseIndex: phase.phaseIndex,
      nodeIds: [...phase.taskIds],
      assignmentCount: phase.taskIds.length,
      handoffCount: phaseHandoffs.length,
      succeeded,
      failed,
      status,
      wallMs: session.phaseReports?.find((r) => r.phaseIndex === phase.phaseIndex)?.wallMs ?? 0,
      costUsd: phaseHandoffs.reduce((total, handoff) => total + handoff.costUsd, 0),
    };
  });
}

// Start with an empty session so the workbench opens in an idle state
// (prompting the user to start a new task). /swarm-demo and the simulation
// flow populate it explicitly when needed.
function emptySession(): SwarmSession {
  return {
    id: "idle",
    title: "",
    status: "dispatching",
    agents: [],
    trace: [],
    deliverables: [],
  };
}

export function SwarmProvider({ children }: { children: React.ReactNode }) {
  const { t } = useI18n();
  const traceLabels = t.traceGenerator;
  const [session, setSession] = useState<SwarmSession>(() => emptySession());
  const [selectedAgentId, setSelectedAgentId] = useState<string>("");
  const [panelOpen, setPanelOpen] = useState(false);
  const [simulating, setSimulating] = useState(false);
  const [liveMode, setLiveMode] = useState(false);
  const [connectedBatchId, setConnectedBatchId] = useState<string | null>(null);
  const tickRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const sseCleanupRef = useRef<(() => void) | null>(null);
  const traceSeqRef = useRef(0);

  const clearTicker = useCallback(() => {
    if (tickRef.current) {
      clearInterval(tickRef.current);
      tickRef.current = null;
    }
  }, []);

  const clearPoll = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const clearSSE = useCallback(() => {
    if (sseCleanupRef.current) {
      sseCleanupRef.current();
      sseCleanupRef.current = null;
    }
  }, []);

  const startSimulation = useCallback(() => {
    clearTicker();
    clearSSE();
    setConnectedBatchId(null);
    traceSeqRef.current = 0;
    setSession((prev) => ({
      ...prev,
      status: "running",
      agents: prev.agents.map((a, i) => ({
        ...a,
        status: ACTIVE_STATUSES[i % ACTIVE_STATUSES.length] as AgentStatus,
        progress: 0,
      })),
    }));
    setSimulating(true);
    tickRef.current = setInterval(() => {
      setSession((prev) => {
        let allDone = true;
        const newTrace: typeof prev.trace = [];
        const agents = prev.agents.map((a, i) => {
          if (a.status === "done") return a;
          const step = 0.04 + ((i * 13) % 5) / 100;
          const next = a.progress + step;
          newTrace.push(...generateTraceTick(a, traceLabels));
          if (next >= 1) {
            return { ...a, progress: 1, status: "done" as AgentStatus };
          }
          allDone = false;
          const nextStatus =
            Math.random() < 0.15
              ? ACTIVE_STATUSES[
                  Math.floor(Math.random() * ACTIVE_STATUSES.length)
                ] ?? a.status
              : a.status;
          return { ...a, progress: next, status: nextStatus };
        });
        const combinedTrace = [...prev.trace, ...newTrace].slice(-200);
        if (allDone) {
          if (tickRef.current) {
            clearInterval(tickRef.current);
            tickRef.current = null;
          }
          setSimulating(false);
          return { ...prev, status: "done", agents, trace: combinedTrace };
        }
        return { ...prev, agents, trace: combinedTrace };
      });
    }, 400);
  }, [clearTicker, clearSSE]);

  const resetSimulation = useCallback(() => {
    clearTicker();
    clearSSE();
    setSimulating(false);
    setConnectedBatchId(null);
    traceSeqRef.current = 0;
    setSession(buildMockSession());
  }, [clearTicker, clearSSE]);

  const enableLiveMode = useCallback(() => {
    clearTicker();
    clearSSE();
    setSimulating(false);
    setLiveMode(true);
    const tick = async () => {
      const live = await fetchFirstRunningSession();
      if (live) {
        setSession(live);
        if (live.agents.length > 0) {
          setSelectedAgentId((id) =>
            live.agents.find((a) => a.id === id)?.id ?? live.agents[0]!.id,
          );
        }
      }
    };
    void tick();
    pollRef.current = setInterval(tick, 3000);
  }, [clearTicker, clearSSE]);

  const disableLiveMode = useCallback(() => {
    clearPoll();
    clearSSE();
    setLiveMode(false);
  }, [clearPoll, clearSSE]);

  const connectBatch = useCallback(
    (batchId: string) => {
      clearTicker();
      clearPoll();
      clearSSE();
      setSimulating(false);
      setLiveMode(true);
      setConnectedBatchId(batchId);
      traceSeqRef.current = 0;

      const cleanup = streamBatch(batchId, {
        onStageChange: (event: BatchStreamEvent) => {
          setSession((prev) => {
            const traceEntry: TraceEntry = {
              id: `stage-${Date.now().toString(36)}-${++traceSeqRef.current}`,
              agentId: "__stage__",
              timestamp: eventTimestamp(event),
              kind: event.stage === "final_report" ? "write" : "think",
              title: event.message ?? event.stage ?? "Agent stage update",
              detail: event.stage,
              sequence: event.sequence ?? undefined,
              status: event.status,
            };
            return {
              ...prev,
              status: event.status === "completed" ? "done" : "running",
              workflow: workflowFromStageEvent(prev, event),
              trace: [...prev.trace, traceEntry].slice(-200),
            };
          });
        },
        onTaskUpdate: (event: BatchStreamEvent) => {
          setSession((prev) => {
            if (event.type === "tool_call") {
              const traceEntry: TraceEntry = {
                id: `tool-${event.task_id ?? "agent"}-${event.sequence ?? ++traceSeqRef.current}`,
                agentId: event.task_id ?? event.subagent_name ?? "agent",
                timestamp: eventTimestamp(event),
                kind: "tool",
                title: event.tool_name
                  ? `Tool: ${event.tool_name}`
                  : event.message ?? "Tool call",
                detail: event.tool_output_preview ?? event.tool_input_preview ?? event.message,
                sequence: event.sequence ?? undefined,
                toolName: event.tool_name,
                inputPreview: event.tool_input_preview,
                outputPreview: event.tool_output_preview,
                artifactPaths: event.artifact_paths,
                status: event.status,
              };
              return {
                ...prev,
                trace: [...prev.trace, traceEntry].slice(-300),
              };
            }

            const agentId = event.task_id ?? "";
            const agentStatus = mapParallelStatus(event.status ?? "pending");
            const isTerminal = isTerminalStatus(agentStatus);
            const progress = isTerminal ? 1 : 0.5;

            const traceEntry: TraceEntry = {
              id: `t-${Date.now().toString(36)}-${++traceSeqRef.current}`,
              agentId,
              timestamp: eventTimestamp(event),
              kind: event.status === "running" ? "think" : isTerminal ? "write" : "tool",
              title: event.subagent_name
                ? `${event.subagent_name}: ${event.status}`
                : `Task ${event.task_id}: ${event.status}`,
              detail: event.error ?? undefined,
              sequence: event.sequence ?? undefined,
              status: event.status,
            };

            const existingIdx = prev.agents.findIndex((a) => a.id === agentId);
            let agents: typeof prev.agents;
            if (existingIdx >= 0) {
              agents = prev.agents.map((a, i) =>
                i === existingIdx
                  ? {
                      ...a,
                      status: agentStatus,
                      progress,
                      ...(event.duration_seconds != null
                        ? { tokenUsed: Math.round(event.duration_seconds * 100) }
                        : {}),
                    }
                  : a,
              );
            } else {
              const name = event.subagent_name ?? `Agent-${prev.agents.length + 1}`;
              agents = [
                ...prev.agents,
                {
                  id: agentId,
                  index: prev.agents.length + 1,
                  name,
                  role: name,
                  motto: "",
                  avatarEmoji: "🤖",
                  hue: (prev.agents.length * 47 + 28) % 360,
                  skills: [],
                  task: name,
                  status: agentStatus,
                  progress,
                },
              ];
            }

            const handoffs = upsertLiveHandoff(prev, event);
            const phaseReports = recomputePhaseReports(prev, handoffs);
            const allDone = agents.every((a) => isTerminalStatus(a.status));
            return {
              ...prev,
              status: allDone ? "done" : "running",
              agents,
              handoffs,
              phaseReports,
              trace: [...prev.trace, traceEntry].slice(-200),
            };
          });
        },
        onBatchComplete: () => {
          // SSE only carries status pings — the actual LLM output lives in
          // the batch's TaskResult.result on the server. Fetch it so the
          // workbench shows real content + deliverables instead of a bare
          // "completed" pill.
          void (async () => {
            const fresh = await fetchBatch(batchId);
            if (fresh) {
              const next = batchToSession(fresh);
              setSession((prev) => ({
                ...next,
                // Keep the live trace we accumulated; batch doesn't have it.
                trace: prev.trace,
              }));
            } else {
              setSession((prev) => ({ ...prev, status: "done" }));
            }
          })();
          setConnectedBatchId(null);
        },
        onError: () => {
          setConnectedBatchId(null);
        },
      });

      sseCleanupRef.current = cleanup;
    },
    [clearTicker, clearPoll, clearSSE],
  );

  const disconnectBatch = useCallback(() => {
    clearSSE();
    setConnectedBatchId(null);
    setLiveMode(false);
  }, [clearSSE]);

  useEffect(() => {
    return () => {
      clearTicker();
      clearPoll();
      clearSSE();
    };
  }, [clearTicker, clearPoll, clearSSE]);

  const value = useMemo<SwarmContextValue>(
    () => ({
      session,
      setSession,
      selectedAgentId,
      setSelectedAgentId,
      panelOpen,
      openPanel: () => setPanelOpen(true),
      closePanel: () => setPanelOpen(false),
      togglePanel: () => setPanelOpen((v) => !v),
      simulating,
      startSimulation,
      resetSimulation,
      liveMode,
      enableLiveMode,
      disableLiveMode,
      connectBatch,
      disconnectBatch,
      connectedBatchId,
    }),
    [
      session,
      selectedAgentId,
      panelOpen,
      simulating,
      startSimulation,
      resetSimulation,
      liveMode,
      enableLiveMode,
      disableLiveMode,
      connectBatch,
      disconnectBatch,
      connectedBatchId,
    ],
  );

  return (
    <SwarmContext.Provider value={value}>{children}</SwarmContext.Provider>
  );
}

export function useSwarm(): SwarmContextValue {
  const ctx = useContext(SwarmContext);
  if (!ctx) {
    throw new Error("useSwarm must be used inside <SwarmProvider>");
  }
  return ctx;
}

export function useOptionalSwarm(): SwarmContextValue | null {
  return useContext(SwarmContext);
}
