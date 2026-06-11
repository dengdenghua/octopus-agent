import { authHeaders, jsonAuthHeaders } from "@/core/auth/api";
import { getBackendBaseURL } from "@/core/config";

import type {
  CompanyProject,
  BindProjectTeamRoomInput,
  BindProjectTeamRoomResponse,
  CreateCompanyProjectInput,
  CreateProjectBlueprintInput,
  CreateProjectBlueprintResponse,
  CreateProjectMilestoneInput,
  CreateProjectTaskDependencyInput,
  CreateProjectTaskInput,
  DeleteCompanyProjectResponse,
  DispatchProjectTaskInput,
  DispatchProjectTaskResponse,
  GanttTaskView,
  GanttViewResponse,
  ListCompanyProjectsResponse,
  ListProjectArtifactsResponse,
  ListProjectDependenciesResponse,
  ListProjectInsightsResponse,
  ListProjectMilestonesResponse,
  ListProjectTasksResponse,
  MaterializeTeamAssemblyMemberInput,
  MaterializeTeamAssemblyMemberResponse,
  ProjectArtifact,
  ProjectInsight,
  ProjectMilestone,
  ProjectTeamAssemblyResponse,
  ProjectTask,
  ProjectTaskDependency,
  UpdateCompanyProjectInput,
  UpdateProjectMilestoneInput,
  UpdateProjectTaskInput,
} from "./types";

const BASE = () => `${getBackendBaseURL()}/api/company`;

async function parseJson<T>(res: Response, action: string): Promise<T> {
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new Error(
      `${action} failed: ${res.status}${detail ? ` ${detail}` : ` ${res.statusText}`}`,
    );
  }
  return (await res.json()) as T;
}

export async function listCompanyProjects(): Promise<CompanyProject[]> {
  const res = await fetch(`${BASE()}/projects`, { headers: authHeaders() });
  const data = await parseJson<ListCompanyProjectsResponse>(
    res,
    "List company projects",
  );
  return data.projects;
}

export async function createCompanyProject(
  input: CreateCompanyProjectInput,
): Promise<CompanyProject> {
  const res = await fetch(`${BASE()}/projects`, {
    method: "POST",
    headers: jsonAuthHeaders(),
    body: JSON.stringify({
      description: "",
      industry: "",
      stage: "idea",
      metadata: {},
      ...input,
    }),
  });
  return parseJson<CompanyProject>(res, "Create company project");
}

export async function createProjectBlueprint(
  input: CreateProjectBlueprintInput,
): Promise<CreateProjectBlueprintResponse> {
  const res = await fetch(`${BASE()}/projects/blueprint`, {
    method: "POST",
    headers: jsonAuthHeaders(),
    body: JSON.stringify({
      budget_tier: "standard",
      horizon_days: 90,
      metadata: {},
      ...input,
    }),
  });
  return parseJson<CreateProjectBlueprintResponse>(
    res,
    "Create project blueprint",
  );
}

export async function updateCompanyProject(
  projectId: string,
  input: UpdateCompanyProjectInput,
): Promise<CompanyProject> {
  const res = await fetch(`${BASE()}/projects/${encodeURIComponent(projectId)}`, {
    method: "PATCH",
    headers: jsonAuthHeaders(),
    body: JSON.stringify(input),
  });
  return parseJson<CompanyProject>(res, "Update company project");
}

export async function deleteCompanyProject(
  projectId: string,
): Promise<DeleteCompanyProjectResponse> {
  const res = await fetch(`${BASE()}/projects/${encodeURIComponent(projectId)}`, {
    method: "DELETE",
    headers: authHeaders(),
  });
  return parseJson<DeleteCompanyProjectResponse>(
    res,
    "Delete company project",
  );
}

export async function assembleProjectTeam(
  projectId: string,
): Promise<ProjectTeamAssemblyResponse> {
  const res = await fetch(
    `${BASE()}/projects/${encodeURIComponent(projectId)}/team-assembly`,
    {
      method: "POST",
      headers: authHeaders(),
    },
  );
  return parseJson<ProjectTeamAssemblyResponse>(
    res,
    "Assemble project team",
  );
}

export async function materializeTeamAssemblyMember(
  projectId: string,
  memberId: string,
  input: MaterializeTeamAssemblyMemberInput = {},
): Promise<MaterializeTeamAssemblyMemberResponse> {
  const res = await fetch(
    `${BASE()}/projects/${encodeURIComponent(projectId)}/team-assembly/${encodeURIComponent(memberId)}/materialize`,
    {
      method: "POST",
      headers: jsonAuthHeaders(),
      body: JSON.stringify(input),
    },
  );
  return parseJson<MaterializeTeamAssemblyMemberResponse>(
    res,
    "Materialize team assembly member",
  );
}

export async function bindProjectTeamRoom(
  projectId: string,
  input: BindProjectTeamRoomInput = {},
): Promise<BindProjectTeamRoomResponse> {
  const res = await fetch(
    `${BASE()}/projects/${encodeURIComponent(projectId)}/team-room`,
    {
      method: "POST",
      headers: jsonAuthHeaders(),
      body: JSON.stringify(input),
    },
  );
  return parseJson<BindProjectTeamRoomResponse>(
    res,
    "Bind project team room",
  );
}

export async function listProjectMilestones(
  projectId: string,
): Promise<ProjectMilestone[]> {
  const res = await fetch(
    `${BASE()}/projects/${encodeURIComponent(projectId)}/milestones`,
    { headers: authHeaders() },
  );
  const data = await parseJson<ListProjectMilestonesResponse>(
    res,
    "List project milestones",
  );
  return data.milestones;
}

export async function createProjectMilestone(
  projectId: string,
  input: CreateProjectMilestoneInput,
): Promise<ProjectMilestone> {
  const res = await fetch(
    `${BASE()}/projects/${encodeURIComponent(projectId)}/milestones`,
    {
      method: "POST",
      headers: jsonAuthHeaders(),
      body: JSON.stringify({
        description: "",
        sort_order: 0,
        metadata: {},
        ...input,
      }),
    },
  );
  return parseJson<ProjectMilestone>(res, "Create project milestone");
}

export async function updateProjectMilestone(
  milestoneId: string,
  input: UpdateProjectMilestoneInput,
): Promise<ProjectMilestone> {
  const res = await fetch(
    `${BASE()}/milestones/${encodeURIComponent(milestoneId)}`,
    {
      method: "PATCH",
      headers: jsonAuthHeaders(),
      body: JSON.stringify(input),
    },
  );
  return parseJson<ProjectMilestone>(res, "Update project milestone");
}

export async function listProjectTasks(
  projectId: string,
): Promise<ProjectTask[]> {
  const res = await fetch(
    `${BASE()}/projects/${encodeURIComponent(projectId)}/tasks`,
    { headers: authHeaders() },
  );
  const data = await parseJson<ListProjectTasksResponse>(
    res,
    "List project tasks",
  );
  return data.tasks;
}

export async function listProjectArtifacts(
  projectId: string,
): Promise<ProjectArtifact[]> {
  const res = await fetch(
    `${BASE()}/projects/${encodeURIComponent(projectId)}/artifacts`,
    { headers: authHeaders() },
  );
  const data = await parseJson<ListProjectArtifactsResponse>(
    res,
    "List project artifacts",
  );
  return data.artifacts;
}

export async function listProjectInsights(
  projectId: string,
): Promise<ProjectInsight[]> {
  const res = await fetch(
    `${BASE()}/projects/${encodeURIComponent(projectId)}/insights`,
    { headers: authHeaders() },
  );
  const data = await parseJson<ListProjectInsightsResponse>(
    res,
    "List project insights",
  );
  return data.insights;
}

export async function createProjectTask(
  projectId: string,
  input: CreateProjectTaskInput,
): Promise<ProjectTask> {
  const res = await fetch(
    `${BASE()}/projects/${encodeURIComponent(projectId)}/tasks`,
    {
      method: "POST",
      headers: jsonAuthHeaders(),
      body: JSON.stringify({
        description: "",
        source: "manual",
        priority: "medium",
        assignees: [],
        metadata: {},
        ...input,
      }),
    },
  );
  return parseJson<ProjectTask>(res, "Create project task");
}

export async function updateProjectTask(
  taskId: string,
  input: UpdateProjectTaskInput,
): Promise<ProjectTask> {
  const res = await fetch(`${BASE()}/tasks/${encodeURIComponent(taskId)}`, {
    method: "PATCH",
    headers: jsonAuthHeaders(),
    body: JSON.stringify(input),
  });
  return parseJson<ProjectTask>(res, "Update project task");
}

export async function dispatchProjectTask(
  taskId: string,
  input: DispatchProjectTaskInput = {},
): Promise<DispatchProjectTaskResponse> {
  const res = await fetch(
    `${BASE()}/tasks/${encodeURIComponent(taskId)}/dispatch`,
    {
      method: "POST",
      headers: jsonAuthHeaders(),
      body: JSON.stringify(input),
    },
  );
  return parseJson<DispatchProjectTaskResponse>(res, "Dispatch project task");
}

export async function listProjectDependencies(
  projectId: string,
): Promise<ProjectTaskDependency[]> {
  const res = await fetch(
    `${BASE()}/projects/${encodeURIComponent(projectId)}/dependencies`,
    { headers: authHeaders() },
  );
  const data = await parseJson<ListProjectDependenciesResponse>(
    res,
    "List project dependencies",
  );
  return data.dependencies;
}

export async function createProjectTaskDependency(
  projectId: string,
  input: CreateProjectTaskDependencyInput,
): Promise<ProjectTaskDependency> {
  const res = await fetch(
    `${BASE()}/projects/${encodeURIComponent(projectId)}/dependencies`,
    {
      method: "POST",
      headers: jsonAuthHeaders(),
      body: JSON.stringify({
        type: "finish_to_start",
        lag_days: 0,
        ...input,
      }),
    },
  );
  return parseJson<ProjectTaskDependency>(
    res,
    "Create project task dependency",
  );
}

export async function getProjectGantt(
  projectId: string,
): Promise<GanttTaskView[]> {
  const res = await fetch(
    `${BASE()}/projects/${encodeURIComponent(projectId)}/gantt`,
    { headers: authHeaders() },
  );
  const data = await parseJson<GanttViewResponse>(res, "Get project gantt");
  return data.items;
}
