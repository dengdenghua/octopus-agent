import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { authHeaders, jsonAuthHeaders } from "../auth/api";
import { getBackendBaseURL } from "../config";

export interface Project {
  id: string;
  name: string;
  goal?: string;
  status?: string;
  // Existing sidebar-only metadata is optional for Project OS projects.
  icon?: string;
  category?: string;
  created_at?: string;
  thread_ids?: string[];
}

const BASE = () => `${getBackendBaseURL()}/api/projects`;

export function useProjects() {
  return useQuery<Project[]>({
    queryKey: ["projects"],
    queryFn: async () => {
      const res = await fetch(BASE(), {
        headers: authHeaders(),
      });
      if (!res.ok) {
        throw new Error(`Failed to load projects: ${res.statusText}`);
      }
      const data = (await res.json()) as unknown;
      if (Array.isArray(data)) return data as Project[];
      if (
        data &&
        typeof data === "object" &&
        Array.isArray((data as { projects?: unknown }).projects)
      ) {
        return (data as { projects: Project[] }).projects;
      }
      return [];
    },
  });
}

export function useCreateProject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (data: {
      name: string;
      goal?: string;
      icon?: string;
      category?: string;
    }) => {
      const res = await fetch(BASE(), {
        method: "POST",
        headers: jsonAuthHeaders(),
        body: JSON.stringify({
          name: data.name,
          // A sidebar project starts as a lightweight plan; users can enrich
          // its goal later through the Project OS workflow.
          goal: data.goal?.trim() || data.name,
        }),
      });
      if (!res.ok) {
        throw new Error(`Failed to create project: ${res.statusText}`);
      }
      return res.json();
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["projects"] });
      qc.invalidateQueries({ queryKey: ["thread-map"] });
    },
  });
}

export function useDeleteProject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: string) => {
      const res = await fetch(`${BASE()}/${id}`, {
        method: "DELETE",
        headers: authHeaders(),
      });
      if (!res.ok) {
        throw new Error(`Failed to delete project: ${res.statusText}`);
      }
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["projects"] }),
  });
}

export function useMoveThreadToProject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({
      threadId,
      projectId,
    }: {
      threadId: string;
      projectId: string;
    }) => {
      const res = await fetch(`${BASE()}/move`, {
        method: "POST",
        headers: jsonAuthHeaders(),
        body: JSON.stringify({ thread_id: threadId, project_id: projectId }),
      });
      if (!res.ok) {
        throw new Error(`Failed to move thread: ${res.statusText}`);
      }
      return res.json();
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["projects"] });
      qc.invalidateQueries({ queryKey: ["thread-map"] });
      qc.invalidateQueries({ queryKey: ["threads"] });
    },
  });
}

export function useThreadMap() {
  return useQuery<Record<string, string>>({
    queryKey: ["thread-map"],
    queryFn: async () => {
      const res = await fetch(`${BASE()}/thread-map`, {
        headers: authHeaders(),
      });
      if (!res.ok) {
        throw new Error(`Failed to load thread map: ${res.statusText}`);
      }
      return res.json();
    },
  });
}
