export type TeamTaskStatus =
  | "pending"
  | "running"
  | "done"
  | "failed"
  | "cancelled";

export type TaskAssigneeKind = "agent" | "participant";

export interface TaskAssignee {
  kind: TaskAssigneeKind;
  ref: string;
}

export interface TeamTaskArtifact {
  [key: string]: unknown;
}

export interface TeamTaskMetadata {
  [key: string]: unknown;
}

export interface TeamTask {
  id: string;
  room_id: string;
  title: string;
  description: string;
  sop_template: string;
  status: TeamTaskStatus;
  assignees: TaskAssignee[];
  created_by?: string | null;
  created_at: string;
  updated_at: string;
  started_at?: string | null;
  completed_at?: string | null;
  produced_artifacts: TeamTaskArtifact[];
  metadata: TeamTaskMetadata;
}

export interface ListTeamTasksResponse {
  tasks: TeamTask[];
  count: number;
}

export interface CreateTeamTaskInput {
  room_id: string;
  title: string;
  description?: string;
  sop_template?: string;
  assignees?: TaskAssignee[];
  metadata?: TeamTaskMetadata;
}

export interface UpdateTeamTaskInput {
  title?: string;
  description?: string;
  status?: TeamTaskStatus;
  assignees?: TaskAssignee[];
  sop_template?: string;
}

export interface DeleteTeamTaskResponse {
  ok: boolean;
  deleted: boolean;
  task_id: string;
}
