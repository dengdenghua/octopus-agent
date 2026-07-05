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

export type AgentWorkbenchFocusDetail = {
  agentId: string;
  tab?: AgentWorkbenchTab;
  view?: AgentWorkbenchFocusView;
};

export type AgentWorkbenchOpenDetail = {
  tab?: AgentWorkbenchTab;
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
