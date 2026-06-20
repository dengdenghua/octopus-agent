export const AGENT_WORKBENCH_FOCUS_EVENT = "octopus:agent-workbench-focus";

export type AgentWorkbenchFocusDetail = {
  agentId: string;
};

export function emitAgentWorkbenchFocus(detail: AgentWorkbenchFocusDetail) {
  if (typeof window === "undefined") return;
  window.dispatchEvent(
    new CustomEvent<AgentWorkbenchFocusDetail>(AGENT_WORKBENCH_FOCUS_EVENT, {
      detail,
    }),
  );
}
