import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  assembleProjectTeam,
  bindProjectTeamRoom,
  createCompanyProject,
  createProjectBlueprint,
  createProjectMilestone,
  createProjectTask,
  createProjectTaskDependency,
  deleteCompanyProject,
  dispatchProjectTask,
  getProjectGantt,
  listCompanyProjects,
  listProjectArtifacts,
  listProjectInsights,
  listProjectMilestones,
  listProjectTasks,
  materializeTeamAssemblyMember,
  updateCompanyProject,
  updateProjectMilestone,
  updateProjectTask,
} from "./api";
import type {
  BindProjectTeamRoomInput,
  CompanyProject,
  CreateCompanyProjectInput,
  CreateProjectBlueprintInput,
  CreateProjectBlueprintResponse,
  CreateProjectMilestoneInput,
  CreateProjectTaskDependencyInput,
  CreateProjectTaskInput,
  DispatchProjectTaskInput,
  GanttTaskView,
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

const COMPANY_KEY = ["company"] as const;

export const companyQueryKeys = {
  all: COMPANY_KEY,
  projects: [...COMPANY_KEY, "projects"] as const,
  milestones: (projectId?: string | null) =>
    [...COMPANY_KEY, "projects", projectId ?? "none", "milestones"] as const,
  tasks: (projectId?: string | null) =>
    [...COMPANY_KEY, "projects", projectId ?? "none", "tasks"] as const,
  artifacts: (projectId?: string | null) =>
    [...COMPANY_KEY, "projects", projectId ?? "none", "artifacts"] as const,
  insights: (projectId?: string | null) =>
    [...COMPANY_KEY, "projects", projectId ?? "none", "insights"] as const,
  gantt: (projectId?: string | null) =>
    [...COMPANY_KEY, "projects", projectId ?? "none", "gantt"] as const,
};

export function useCompanyProjects() {
  return useQuery<CompanyProject[]>({
    queryKey: companyQueryKeys.projects,
    queryFn: listCompanyProjects,
  });
}

export function useProjectMilestones(projectId?: string | null) {
  return useQuery<ProjectMilestone[]>({
    queryKey: companyQueryKeys.milestones(projectId),
    queryFn: () => listProjectMilestones(projectId ?? ""),
    enabled: Boolean(projectId),
  });
}

export function useProjectTasks(projectId?: string | null) {
  return useQuery<ProjectTask[]>({
    queryKey: companyQueryKeys.tasks(projectId),
    queryFn: () => listProjectTasks(projectId ?? ""),
    enabled: Boolean(projectId),
    refetchInterval: (query) => {
      const tasks = query.state.data ?? [];
      return tasks.some((task) => task.team_task_id && task.status === "doing")
        ? 1500
        : false;
    },
  });
}

export function useProjectArtifacts(projectId?: string | null) {
  return useQuery<ProjectArtifact[]>({
    queryKey: companyQueryKeys.artifacts(projectId),
    queryFn: () => listProjectArtifacts(projectId ?? ""),
    enabled: Boolean(projectId),
    refetchInterval: 3000,
  });
}

export function useProjectInsights(projectId?: string | null) {
  return useQuery<ProjectInsight[]>({
    queryKey: companyQueryKeys.insights(projectId),
    queryFn: () => listProjectInsights(projectId ?? ""),
    enabled: Boolean(projectId),
    refetchInterval: 3000,
  });
}

export function useProjectGantt(projectId?: string | null) {
  return useQuery<GanttTaskView[]>({
    queryKey: companyQueryKeys.gantt(projectId),
    queryFn: () => getProjectGantt(projectId ?? ""),
    enabled: Boolean(projectId),
    refetchInterval: 3000,
  });
}

export function useCreateCompanyProject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: CreateCompanyProjectInput) =>
      createCompanyProject(input),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: companyQueryKeys.projects });
    },
  });
}

export function useCreateProjectBlueprint() {
  const qc = useQueryClient();
  return useMutation<CreateProjectBlueprintResponse, Error, CreateProjectBlueprintInput>({
    mutationFn: createProjectBlueprint,
    onSuccess: (result) => {
      const projectId = result.project.id;
      void qc.invalidateQueries({ queryKey: companyQueryKeys.projects });
      void qc.invalidateQueries({
        queryKey: companyQueryKeys.milestones(projectId),
      });
      void qc.invalidateQueries({ queryKey: companyQueryKeys.tasks(projectId) });
      void qc.invalidateQueries({ queryKey: companyQueryKeys.gantt(projectId) });
      void qc.invalidateQueries({
        queryKey: companyQueryKeys.artifacts(projectId),
      });
      void qc.invalidateQueries({
        queryKey: companyQueryKeys.insights(projectId),
      });
    },
  });
}

export function useUpdateCompanyProject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      projectId,
      input,
    }: {
      projectId: string;
      input: UpdateCompanyProjectInput;
    }) => updateCompanyProject(projectId, input),
    onSuccess: (project) => {
      void qc.invalidateQueries({ queryKey: companyQueryKeys.projects });
      void qc.invalidateQueries({
        queryKey: companyQueryKeys.gantt(project.id),
      });
    },
  });
}

export function useDeleteCompanyProject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (projectId: string) => deleteCompanyProject(projectId),
    onSuccess: (result) => {
      const projectId = result.project_id;
      void qc.invalidateQueries({ queryKey: companyQueryKeys.projects });
      void qc.removeQueries({
        queryKey: companyQueryKeys.milestones(projectId),
      });
      void qc.removeQueries({ queryKey: companyQueryKeys.tasks(projectId) });
      void qc.removeQueries({ queryKey: companyQueryKeys.gantt(projectId) });
      void qc.removeQueries({ queryKey: companyQueryKeys.artifacts(projectId) });
      void qc.removeQueries({ queryKey: companyQueryKeys.insights(projectId) });
    },
  });
}

export function useAssembleProjectTeam() {
  const qc = useQueryClient();
  return useMutation<ProjectTeamAssemblyResponse, Error, string>({
    mutationFn: assembleProjectTeam,
    onSuccess: (result) => {
      void qc.invalidateQueries({ queryKey: companyQueryKeys.projects });
      void qc.invalidateQueries({
        queryKey: companyQueryKeys.gantt(result.project.id),
      });
    },
  });
}

export function useMaterializeTeamAssemblyMember() {
  const qc = useQueryClient();
  return useMutation<
    MaterializeTeamAssemblyMemberResponse,
    Error,
    {
      projectId: string;
      memberId: string;
      input?: MaterializeTeamAssemblyMemberInput;
    }
  >({
    mutationFn: ({ projectId, memberId, input }) =>
      materializeTeamAssemblyMember(projectId, memberId, input),
    onSuccess: (result) => {
      void qc.invalidateQueries({ queryKey: companyQueryKeys.projects });
      void qc.invalidateQueries({
        queryKey: companyQueryKeys.gantt(result.project.id),
      });
    },
  });
}

export function useBindProjectTeamRoom() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      projectId,
      input,
    }: {
      projectId: string;
      input?: BindProjectTeamRoomInput;
    }) => bindProjectTeamRoom(projectId, input),
    onSuccess: (result) => {
      void qc.invalidateQueries({ queryKey: companyQueryKeys.projects });
      void qc.invalidateQueries({
        queryKey: companyQueryKeys.gantt(result.project.id),
      });
    },
  });
}

export function useCreateProjectMilestone() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      projectId,
      input,
    }: {
      projectId: string;
      input: CreateProjectMilestoneInput;
    }) => createProjectMilestone(projectId, input),
    onSuccess: (milestone) => {
      void qc.invalidateQueries({
        queryKey: companyQueryKeys.milestones(milestone.project_id),
      });
      void qc.invalidateQueries({
        queryKey: companyQueryKeys.gantt(milestone.project_id),
      });
    },
  });
}

export function useUpdateProjectMilestone() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      milestoneId,
      input,
    }: {
      milestoneId: string;
      input: UpdateProjectMilestoneInput;
    }) => updateProjectMilestone(milestoneId, input),
    onSuccess: (milestone) => {
      void qc.invalidateQueries({
        queryKey: companyQueryKeys.milestones(milestone.project_id),
      });
      void qc.invalidateQueries({
        queryKey: companyQueryKeys.gantt(milestone.project_id),
      });
    },
  });
}

export function useCreateProjectTask() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      projectId,
      input,
    }: {
      projectId: string;
      input: CreateProjectTaskInput;
    }) => createProjectTask(projectId, input),
    onSuccess: (task) => {
      void qc.invalidateQueries({ queryKey: companyQueryKeys.tasks(task.project_id) });
      void qc.invalidateQueries({
        queryKey: companyQueryKeys.artifacts(task.project_id),
      });
      void qc.invalidateQueries({
        queryKey: companyQueryKeys.insights(task.project_id),
      });
      void qc.invalidateQueries({ queryKey: companyQueryKeys.gantt(task.project_id) });
    },
  });
}

export function useUpdateProjectTask() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      taskId,
      input,
    }: {
      taskId: string;
      input: UpdateProjectTaskInput;
    }) => updateProjectTask(taskId, input),
    onSuccess: (task) => {
      void qc.invalidateQueries({ queryKey: companyQueryKeys.tasks(task.project_id) });
      void qc.invalidateQueries({
        queryKey: companyQueryKeys.artifacts(task.project_id),
      });
      void qc.invalidateQueries({
        queryKey: companyQueryKeys.insights(task.project_id),
      });
      void qc.invalidateQueries({ queryKey: companyQueryKeys.gantt(task.project_id) });
    },
  });
}

export function useDispatchProjectTask() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      taskId,
      input,
    }: {
      taskId: string;
      input?: DispatchProjectTaskInput;
    }) => dispatchProjectTask(taskId, input),
    onSuccess: (result) => {
      const task = result.project_task;
      void qc.invalidateQueries({
        queryKey: companyQueryKeys.tasks(task.project_id),
      });
      void qc.invalidateQueries({
        queryKey: companyQueryKeys.artifacts(task.project_id),
      });
      void qc.invalidateQueries({
        queryKey: companyQueryKeys.insights(task.project_id),
      });
      void qc.invalidateQueries({
        queryKey: companyQueryKeys.gantt(task.project_id),
      });
      void qc.invalidateQueries({ queryKey: ["team-tasks"] });
    },
  });
}

export function useCreateProjectTaskDependency() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      projectId,
      input,
    }: {
      projectId: string;
      input: CreateProjectTaskDependencyInput;
    }) => createProjectTaskDependency(projectId, input),
    onSuccess: (dependency: ProjectTaskDependency) => {
      void qc.invalidateQueries({
        queryKey: companyQueryKeys.tasks(dependency.project_id),
      });
      void qc.invalidateQueries({
        queryKey: companyQueryKeys.gantt(dependency.project_id),
      });
    },
  });
}
