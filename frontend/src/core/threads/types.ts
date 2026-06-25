import type { Message, Thread } from "@/core/api/types";

import type { Todo } from "../todos";

export interface AgentRosterEntry {
  name: string;
  display_name: string;
  avatar_url?: string;
  role: "tl" | "member";
}

export interface ExecutionMetrics {
  iteration?: number;
  tool_calls_count?: number;
  current_tool?: string | null;
  last_tools?: string[];
  last_duration_ms?: number;
}

export interface ExecutionPlanStep {
  step_id: string;
  description: string;
  tools_needed: string[];
  estimated_duration: "fast" | "medium" | "slow";
  risk: "low" | "medium" | "high";
  status: "pending" | "in_progress" | "completed" | "skipped";
}

export interface ExecutionPlan {
  plan_id: string;
  title: string;
  steps: ExecutionPlanStep[];
  estimated_actions: number;
  risk_level: "low" | "medium" | "high";
  status:
    | "pending_review"
    | "approved"
    | "modified"
    | "rejected"
    | "executing"
    | "completed";
  created_at: number;
  user_message?: string;
}

export interface AgentThreadState extends Record<string, unknown> {
  title: string;
  messages: Message[];
  artifacts: string[];
  todos?: Todo[];
  agent_roster?: AgentRosterEntry[];
  current_speaker?: string | null;
  execution_metrics?: ExecutionMetrics | null;
  execution_plan?: ExecutionPlan | null;
}

export interface AgentThread extends Thread<AgentThreadState> {}

export type ReasoningEffort =
  | "minimal"
  | "low"
  | "medium"
  | "high"
  | "xhigh"
  | "max";

export interface AgentThreadContext extends Record<string, unknown> {
  thread_id: string;
  model_name: string | undefined;
  thinking_enabled: boolean;
  is_plan_mode: boolean;
  subagent_enabled: boolean;
  reasoning_effort?: ReasoningEffort;
  interaction_mode?: "office" | "coding";
  mode_preset?: string;
  workflow_preset?: string;
  skill_pack_profile?: string;
  verification_policy?: "light" | "standard" | "strict" | "visual";
  default_skill_packs?: string[];
  default_plugins?: string[];
  mode_contract?: string;
  agent_name?: string;
  permission_mode?:
    | "default"
    | "acceptEdits"
    | "bypassPermissions"
    | "plan"
    | "sandbox"
    | "full";
  execution_environment?: "sandbox" | "local";
  /* Implementation note. */
  ephemeral?: boolean;
}
