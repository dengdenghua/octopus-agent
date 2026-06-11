export type ProjectStage =
  | "idea"
  | "validation"
  | "prototype"
  | "pilot"
  | "commercial";

export type ProjectStatus = "active" | "paused" | "completed" | "cancelled";

export type MilestoneStatus =
  | "not_started"
  | "in_progress"
  | "blocked"
  | "done"
  | "cancelled";

export type ProjectTaskStatus =
  | "todo"
  | "doing"
  | "blocked"
  | "done"
  | "cancelled";

export type ProjectTaskPriority = "low" | "medium" | "high" | "urgent";

export type ProjectTaskSource =
  | "manual"
  | "meeting"
  | "risk"
  | "milestone"
  | "agent"
  | "dingtalk";

export type ProjectTaskDependencyType =
  | "finish_to_start"
  | "start_to_start"
  | "finish_to_finish"
  | "start_to_finish";

export interface CompanyProject {
  id: string;
  name: string;
  description: string;
  industry: string;
  stage: ProjectStage;
  owner_id?: string | null;
  team_room_id?: string | null;
  ding_talk_group_id?: string | null;
  start_date?: string | null;
  target_end_date?: string | null;
  status: ProjectStatus;
  created_at: string;
  updated_at: string;
  metadata: Record<string, unknown>;
}

export interface ProjectMilestone {
  id: string;
  project_id: string;
  title: string;
  description: string;
  planned_start_at?: string | null;
  planned_end_at?: string | null;
  actual_start_at?: string | null;
  actual_end_at?: string | null;
  target_date?: string | null;
  status: MilestoneStatus;
  progress: number;
  owner_id?: string | null;
  sort_order: number;
  created_at: string;
  updated_at: string;
  metadata: Record<string, unknown>;
}

export interface ProjectTaskAssignee {
  kind: "human" | "agent" | "digital_twin" | "participant";
  ref: string;
  display_name?: string | null;
}

export interface ProjectTask {
  id: string;
  project_id: string;
  milestone_id?: string | null;
  parent_task_id?: string | null;
  title: string;
  description: string;
  source: ProjectTaskSource;
  status: ProjectTaskStatus;
  priority: ProjectTaskPriority;
  planned_start_at?: string | null;
  planned_end_at?: string | null;
  actual_start_at?: string | null;
  actual_end_at?: string | null;
  due_at?: string | null;
  progress: number;
  estimate_hours?: number | null;
  actual_hours?: number | null;
  owner_name?: string | null;
  owner_user_id?: string | null;
  assignees: ProjectTaskAssignee[];
  ding_todo_id?: string | null;
  team_task_id?: string | null;
  created_at: string;
  updated_at: string;
  metadata: Record<string, unknown>;
}

export interface ProjectTaskDependency {
  id: string;
  project_id: string;
  from_task_id: string;
  to_task_id: string;
  type: ProjectTaskDependencyType;
  lag_days: number;
  created_at: string;
}

export interface GanttTaskView {
  id: string;
  name: string;
  milestone_id?: string | null;
  start?: string | null;
  end?: string | null;
  progress: number;
  status: string;
  assignee?: string | null;
  dependencies: string[];
  is_milestone: boolean;
  critical: boolean;
}

export interface ProjectArtifact {
  id: string;
  project_id: string;
  task_id: string;
  team_task_id?: string | null;
  source: string;
  type: string;
  title: string;
  content: string;
  path?: string | null;
  url?: string | null;
  created_at?: string | null;
  metadata: Record<string, unknown>;
}

export type ProjectInsightKind = "risk" | "next_action" | "decision";

export interface ProjectInsight {
  id: string;
  project_id: string;
  task_id?: string | null;
  team_task_id?: string | null;
  source_artifact_id?: string | null;
  kind: ProjectInsightKind;
  title: string;
  detail: string;
  severity?: string | null;
  owner?: string | null;
  due_at?: string | null;
  status?: string | null;
  created_at?: string | null;
  metadata: Record<string, unknown>;
}

export interface ListCompanyProjectsResponse {
  projects: CompanyProject[];
  count: number;
}

export interface ListProjectMilestonesResponse {
  milestones: ProjectMilestone[];
  count: number;
}

export interface ListProjectTasksResponse {
  tasks: ProjectTask[];
  count: number;
}

export interface ListProjectArtifactsResponse {
  artifacts: ProjectArtifact[];
  count: number;
}

export interface ListProjectInsightsResponse {
  insights: ProjectInsight[];
  count: number;
  counts: Record<ProjectInsightKind, number>;
}

export interface ListProjectDependenciesResponse {
  dependencies: ProjectTaskDependency[];
  count: number;
}

export interface GanttViewResponse {
  items: GanttTaskView[];
  count: number;
}

export interface DispatchedTeamTask {
  id: string;
  room_id: string;
  title: string;
  description?: string;
  status?: string;
  metadata?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface DispatchProjectTaskInput {
  room_id?: string | null;
  sop_template?: string;
  run?: boolean;
  force_new?: boolean;
}

export interface DispatchProjectTaskResponse {
  created: boolean;
  run_requested: boolean;
  team_task_id: string;
  team_task: DispatchedTeamTask | null;
  project_task: ProjectTask;
}

export interface BindProjectTeamRoomInput {
  team_room_id?: string | null;
  name?: string | null;
  members?: Array<Record<string, unknown>>;
  leaderId?: string | null;
  force_new?: boolean;
}

export interface BoundTeamRoom {
  id: string;
  name: string;
  members?: Array<Record<string, unknown>>;
  leaderId?: string | null;
  [key: string]: unknown;
}

export interface BindProjectTeamRoomResponse {
  created: boolean;
  team_room_id: string;
  team: BoundTeamRoom | null;
  project: CompanyProject;
}

export interface DeleteCompanyProjectResponse {
  deleted: boolean;
  project_id: string;
}

export type ProjectBudgetTier = "lean" | "standard" | "premium" | "enterprise";

export interface ProjectBudgetProfile {
  label?: string;
  monthly_budget?: string;
  monthly_budget_min?: number | null;
  monthly_budget_max?: number | null;
  team_size?: string;
  fit?: string;
  delivery_speed?: string;
  human_ratio?: string;
  recommended_parallel_agents?: number;
  [key: string]: unknown;
}

export interface ProjectRolePricing {
  currency?: string;
  monthly_low?: number | null;
  monthly_high?: number | null;
  basis?: string;
}

export interface ProjectRoleSkillPack {
  id?: string;
  level?: string;
  skills?: string[];
}

export interface ProjectRoleValueModel {
  level?: string;
  capability_score?: number;
  automation_weight?: number;
  human_approval_required?: boolean;
}

export interface ProjectBlueprintRoleMetadata {
  pricing?: ProjectRolePricing;
  skill_pack?: ProjectRoleSkillPack;
  tool_pack?: string[];
  value_model?: ProjectRoleValueModel;
  [key: string]: unknown;
}

export interface ProjectBlueprintRole {
  kind: "agent" | "digital_twin" | "human" | "participant" | "system" | string;
  role: string;
  display_name?: string;
  level?: string;
  capability_score?: number;
  monthly_cost?: string;
  skills?: string[];
  responsibility?: string;
  metadata?: ProjectBlueprintRoleMetadata;
  [key: string]: unknown;
}

export interface ProjectCapabilityModel {
  version?: number;
  budget_tier?: ProjectBudgetTier | string;
  pricing_currency?: string;
  recommended_parallel_agents?: number;
  levels?: Record<string, unknown>;
  role_value_basis?: string[];
  [key: string]: unknown;
}

export interface ProjectBlueprintMetadata {
  version?: number;
  kind?: string;
  prompt?: string;
  budget_tier?: ProjectBudgetTier | string;
  budget_profile?: ProjectBudgetProfile;
  capability_model?: ProjectCapabilityModel;
  horizon_days?: number;
  start_date?: string;
  target_end_date?: string;
  team_roles?: ProjectBlueprintRole[];
  [key: string]: unknown;
}

export interface ProjectTeamAssemblyMember {
  id: string;
  project_id: string;
  slot_id: string;
  kind: ProjectBlueprintRole["kind"];
  role: string;
  display_name: string;
  level?: string;
  status: string;
  source_agent_id?: string | null;
  source_agent_name?: string | null;
  source_agent_category?: string | null;
  match_score?: number;
  capability_score?: number;
  monthly_cost?: string;
  responsibility?: string;
  skills?: string[];
  installed_skills?: string[];
  arms?: string[];
  metadata?: ProjectBlueprintRoleMetadata & Record<string, unknown>;
}

export interface ProjectTeamAssemblySummary {
  total_slots?: number;
  matched_agents?: number;
  requires_human?: number;
  needs_digital_twin?: number;
  needs_agent?: number;
  budget_label?: string;
  monthly_budget?: string;
  team_size?: string;
  monthly_budget_min?: number | null;
  monthly_budget_max?: number | null;
  estimated_monthly_low?: number;
  estimated_monthly_high?: number | null;
  estimated_monthly_label?: string;
  budget_fit?: "within_budget" | "over_budget" | "under_budget" | "custom" | string;
  over_budget?: boolean;
  human_cost_excluded?: boolean;
  unknown_cost_slots?: number;
  recommended_parallel_agents?: number;
  level_counts?: Record<string, number>;
  [key: string]: unknown;
}

export interface ProjectTeamAssemblyMetadata {
  version?: number;
  generated_at?: string;
  budget_profile?: ProjectBudgetProfile;
  summary?: ProjectTeamAssemblySummary;
  members?: ProjectTeamAssemblyMember[];
  [key: string]: unknown;
}

export interface ProjectTeamAssemblyResponse {
  project: CompanyProject;
  members: ProjectTeamAssemblyMember[];
  budget_profile: ProjectBudgetProfile;
  summary: ProjectTeamAssemblySummary;
  available_agents_count: number;
}

export interface MaterializeTeamAssemblyMemberInput {
  agent_id?: string | null;
  display_name?: string | null;
  model?: string | null;
}

export interface MaterializedAgent {
  id: string;
  name: string;
  description?: string;
  agent_dir: string;
  identity_card?: Record<string, unknown>;
}

export interface MaterializeTeamAssemblyMemberResponse {
  project: CompanyProject;
  member: ProjectTeamAssemblyMember;
  agent: MaterializedAgent;
  created: boolean;
  hot_loaded: boolean;
  requires_reload: boolean;
  team_room_synced?: boolean;
  team_room_id?: string | null;
}

export interface CreateProjectBlueprintInput {
  prompt: string;
  name?: string | null;
  industry?: string;
  budget_tier?: ProjectBudgetTier;
  horizon_days?: number;
  start_date?: string | null;
  owner_id?: string | null;
  metadata?: Record<string, unknown>;
}

export interface CreateProjectBlueprintResponse {
  project: CompanyProject;
  milestones: ProjectMilestone[];
  tasks: ProjectTask[];
  dependencies: ProjectTaskDependency[];
  blueprint: Record<string, unknown>;
}

export interface CreateCompanyProjectInput {
  name: string;
  description?: string;
  industry?: string;
  stage?: ProjectStage;
  owner_id?: string | null;
  team_room_id?: string | null;
  ding_talk_group_id?: string | null;
  start_date?: string | null;
  target_end_date?: string | null;
  metadata?: Record<string, unknown>;
}

export interface UpdateCompanyProjectInput
  extends Partial<CreateCompanyProjectInput> {
  status?: ProjectStatus;
}

export interface CreateProjectMilestoneInput {
  title: string;
  description?: string;
  planned_start_at?: string | null;
  planned_end_at?: string | null;
  target_date?: string | null;
  owner_id?: string | null;
  sort_order?: number;
  metadata?: Record<string, unknown>;
}

export interface UpdateProjectMilestoneInput
  extends Partial<CreateProjectMilestoneInput> {
  actual_start_at?: string | null;
  actual_end_at?: string | null;
  status?: MilestoneStatus;
  progress?: number;
}

export interface CreateProjectTaskInput {
  milestone_id?: string | null;
  parent_task_id?: string | null;
  title: string;
  description?: string;
  source?: ProjectTaskSource;
  priority?: ProjectTaskPriority;
  planned_start_at?: string | null;
  planned_end_at?: string | null;
  due_at?: string | null;
  estimate_hours?: number | null;
  owner_name?: string | null;
  owner_user_id?: string | null;
  assignees?: ProjectTaskAssignee[];
  ding_todo_id?: string | null;
  team_task_id?: string | null;
  metadata?: Record<string, unknown>;
}

export interface UpdateProjectTaskInput extends Partial<CreateProjectTaskInput> {
  status?: ProjectTaskStatus;
  actual_start_at?: string | null;
  actual_end_at?: string | null;
  progress?: number;
  actual_hours?: number | null;
}

export interface CreateProjectTaskDependencyInput {
  from_task_id: string;
  to_task_id: string;
  type?: ProjectTaskDependencyType;
  lag_days?: number;
}
