export const AGENT_WORKBENCH_FOCUS_EVENT = "octopus:agent-workbench-focus";
export const AGENT_WORKBENCH_OPEN_EVENT = "octopus:agent-workbench-open";

export type AgentWorkbenchTab =
  | "agent"
  | "subagents"
  | "artifacts"
  | "plan"
  | "diff"
  | "terminal"
  | "browser";

/** Sub-view of the per-agent workbench page: "summary" is the activity
 * trace, "screen" is the agent's computer view. Omitted = panel default. */
export type AgentWorkbenchFocusView = "summary" | "screen";
export type AgentWorkbenchEventView = "summary" | "trace" | "screen";
export type AgentWorkbenchProcessEventKind = "thinking" | "execution";

export type AgentWorkbenchProcessEventSnapshot = {
  /** Only explicitly public text belongs here; never raw provider reasoning. */
  summary: string;
  detail?: string;
  kind: AgentWorkbenchProcessEventKind;
  status?: "running" | "waiting" | "error" | "pending" | "done";
  count?: number;
  phaseId?: string;
  parentItemId?: string;
  timelineSequence?: number;
};

export type AgentWorkbenchFocusDetail = {
  agentId: string;
  tab?: AgentWorkbenchTab;
  view?: AgentWorkbenchFocusView;
};

export type AgentWorkbenchOpenDetail = {
  tab?: AgentWorkbenchTab;
  /** Stable id shared by the transcript event and its workbench block. */
  eventId?: string;
  /** Durable external-effect receipt selected from the transcript. */
  effectKey?: string;
  eventKind?: AgentWorkbenchProcessEventKind;
  /** Public snapshot used when the selected transcript row has no tool block. */
  processEvent?: AgentWorkbenchProcessEventSnapshot;
  /** The workbench surface that best explains the selected event. */
  view?: AgentWorkbenchEventView;
};

export function emitAgentWorkbenchFocus(detail: AgentWorkbenchFocusDetail) {
  if (typeof window === "undefined") return;
  window.dispatchEvent(
    new CustomEvent<AgentWorkbenchFocusDetail>(AGENT_WORKBENCH_FOCUS_EVENT, {
      detail,
    }),
  );
}

export function emitOpenAgentWorkbench(detail?: AgentWorkbenchOpenDetail) {
  if (typeof window === "undefined") return;
  window.dispatchEvent(
    new CustomEvent<AgentWorkbenchOpenDetail>(AGENT_WORKBENCH_OPEN_EVENT, {
      detail: detail ?? {},
    }),
  );
}
