/** Types for the Teach & Repeat (workflow record/replay) system. */

export interface WorkflowParam {
  name: string;
  description: string;
  param_type: "string" | "number" | "boolean" | "json";
  default_value: string | null;
  required: boolean;
}

export interface WorkflowStep {
  id: string;
  type:
    | "user_message"
    | "agent_message"
    | "tool_call"
    | "tool_result"
    | "system_event";
  content: string;
  tool_name: string | null;
  tool_args: Record<string, unknown>;
  tool_result: string | null;
  expected_output_pattern: string | null;
  is_parameterised: boolean;
  metadata: Record<string, unknown>;
  timestamp: string;
}

export interface WorkflowTemplate {
  id: string;
  name: string;
  description: string;
  steps: WorkflowStep[];
  params: WorkflowParam[];
  tags: string[];
  use_count: number;
  last_used_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface WorkflowTemplateListItem {
  id: string;
  name: string;
  description: string;
  step_count: number;
  param_count: number;
  tags: string[];
  use_count: number;
  last_used_at: string | null;
  created_at: string;
  updated_at: string;
  params?: WorkflowParam[];
}

export interface TemplateListResponse {
  templates: WorkflowTemplateListItem[];
  total: number;
}

export interface StartRecordingRequest {
  thread_id: string;
  name: string;
  description?: string;
}

export interface StartRecordingResponse {
  recording: boolean;
  thread_id: string;
  name: string;
}

export interface StopRecordingRequest {
  thread_id: string;
  use_llm?: boolean;
  model_name?: string | null;
}

export interface StopRecordingResponse {
  name: string;
  // Active-forge result (REC stop now forges a skill from the conversation's
  // trajectory): "promoted" | "quarantined" | "shadow_failed" |
  // "no_candidate" | "no_successful_trajectory" | "no_runtime".
  status?: string;
  forged?: string[];
  quarantined?: string[];
  candidates_total?: number;
  thread_id?: string;
  step_count?: number;
  // Legacy stub fields (no longer returned by the forge-backed stop):
  template_id?: string;
  description?: string;
  param_count?: number;
}

export interface RecordingStatus {
  recording: boolean;
  step_count: number;
  name: string;
}

export interface StepResult {
  step_id: string;
  status: "success" | "adapted" | "skipped" | "failed";
  output: string;
  error: string | null;
  adaptation_note: string | null;
  duration_ms: number;
}

export interface ReplayResult {
  workflow_id: string;
  status: "pending" | "running" | "completed" | "failed" | "adapted";
  step_results: StepResult[];
  params_used: Record<string, unknown>;
  total_duration_ms: number;
  error: string | null;
  started_at: string;
  completed_at: string | null;
}

export interface ReplayRequest {
  params: Record<string, unknown>;
}

export interface AdaptiveReplayRequest {
  params: Record<string, unknown>;
  context?: Record<string, unknown>;
}

export interface TemplateUpdateRequest {
  name?: string;
  description?: string;
  tags?: string[];
}
