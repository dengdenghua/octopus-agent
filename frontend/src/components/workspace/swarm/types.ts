// Agent Workbench — types for the multi-agent swarm UI.
// See docs/agent-workbench-design.md for the full design.

export type AgentStatus =
  | "pending"
  | "reasoning"
  | "iterating"
  | "generating"
  | "analyzing"
  | "summarizing"
  | "done"
  | "failed"
  | "cancelled"
  | "timed_out";

export const STATUS_LABELS: Record<AgentStatus, string> = {
  pending: "等待中",
  reasoning: "正在推理",
  iterating: "正在迭代",
  generating: "正在生成",
  analyzing: "正在分析",
  summarizing: "正在总结",
  done: "已完成",
  failed: "失败",
  cancelled: "已取消",
  timed_out: "已超时",
};

export interface SwarmAgent {
  id: string;
  index: number;
  name: string;
  role: string;
  motto: string;
  avatarEmoji: string;
  hue: number; // 0-360, drives theme color
  skills: string[]; // equipped skill names
  stats?: {
    taskCount?: number;
    rating?: number; // 0-5
  };
  personality?: string[]; // Implementation note.
  task: string; // this dispatch's assigned task (short)
  details?: string[]; // Implementation note.
  status: AgentStatus;
  progress: number; // 0..1
  tokenUsed?: number;
  tokenBudget?: number;
  result?: string; // full LLM output after agent completes
  error?: string; // error message if agent failed
  durationSeconds?: number; // elapsed wallclock time
}

export interface WorkContract {
  contractId: string;
  agentId: string;
  role: string;
  taskIds: string[];
  dependsOn: string[];
  ownedScope: string[];
  forbiddenScope: string[];
  successCriteria: string[];
}

export interface SwarmPhase {
  phaseIndex: number;
  taskIds: string[];
  parallel: boolean;
}

export interface SwarmPlan {
  batchId: string;
  strategy: string;
  maxConcurrency: number;
  phases: SwarmPhase[];
  contracts: WorkContract[];
}

export interface TraceEntry {
  id: string;
  agentId: string;
  timestamp: number;
  kind: "search" | "read" | "think" | "write" | "tool";
  title: string;
  detail?: string;
  url?: string;
  faviconEmoji?: string;
  sequence?: number;
  toolName?: string;
  inputPreview?: string;
  outputPreview?: string;
  artifactPaths?: string[];
  status?: string;
}

export interface DeliverableFile {
  name: string;
  path: string;
  ownerAgentIds: string[];
}

export interface AgentHandoff {
  agentId: string;
  taskId: string;
  phaseIndex: number;
  nodeIds: string[];
  status: string;
  summary: string;
  artifacts: string[];
  costUsd: number;
  reason?: string;
}

export interface SwarmPhaseReport {
  phaseIndex: number;
  nodeIds: string[];
  assignmentCount: number;
  handoffCount: number;
  succeeded: number;
  failed: number;
  status: "success" | "partial" | "failed" | "empty";
  wallMs: number;
  costUsd: number;
}

export interface SwarmWorkflowSnapshot {
  stage?: string;
  status?: string;
  progress?: number;
  totalTasks: number;
  completedTasks: number;
  failedTasks: number;
  cancelledTasks: number;
  updatedAt: number;
}

export interface SwarmSession {
  id: string;
  title: string;
  status: "dispatching" | "running" | "done";
  mode?: "live" | "replay" | "result" | "clone";
  agents: SwarmAgent[];
  trace: TraceEntry[];
  deliverables: DeliverableFile[];
  handoffs?: AgentHandoff[];
  phaseReports?: SwarmPhaseReport[];
  workflow?: SwarmWorkflowSnapshot;
  plan?: SwarmPlan;
  summary?: string;
  sourcePrompt?: string;
}
