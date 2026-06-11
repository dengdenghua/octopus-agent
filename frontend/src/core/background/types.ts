/** Data types for the Background Tasks API. */

export type BackgroundTaskStatus =
  | "queued"
  | "running"
  | "paused"
  | "completed"
  | "failed"
  | "cancelled"
  | "interrupted";

export interface BackgroundTask {
  task_id: string;
  name: string;
  prompt: string;
  assistant_id: string;
  thread_id: string | null;
  status: BackgroundTaskStatus;
  created_at: string;
  updated_at: string;
  heartbeat_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
  output_count: number;
  max_duration: number;
  max_iterations: number;
  extra: Record<string, unknown>;
}

export interface BackgroundTaskOutput {
  task_id: string;
  seq: number;
  role: string;
  content: string;
  timestamp: string;
  metadata: Record<string, unknown>;
}

export interface SubmitBackgroundTaskRequest {
  prompt: string;
  name?: string;
  assistant_id?: string;
  thread_id?: string | null;
  max_duration?: number;
  max_iterations?: number;
  extra?: Record<string, unknown>;
}

export const TERMINAL_STATUSES: BackgroundTaskStatus[] = [
  "completed",
  "failed",
  "cancelled",
];

export const ACTIVE_STATUSES: BackgroundTaskStatus[] = ["queued", "running"];

export function isTerminalStatus(status: BackgroundTaskStatus): boolean {
  return TERMINAL_STATUSES.includes(status);
}

export function isActiveStatus(status: BackgroundTaskStatus): boolean {
  return ACTIVE_STATUSES.includes(status);
}
