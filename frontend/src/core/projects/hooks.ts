import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { authHeaders, jsonAuthHeaders } from "../auth/api";
import { getBackendBaseURL } from "../config";

interface Project {
  id: string;
  name: string;
  icon: string;
  category: string;
  created_at: string;
  thread_ids: string[];
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
      return Array.isArray(data) ? (data as Project[]) : [];
    },
  });
}

export function useCreateProject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (data: {
      name: string;
      icon?: string;
      category?: string;
    }) => {
      const res = await fetch(BASE(), {
        method: "POST",
        headers: jsonAuthHeaders(),
        body: JSON.stringify(data),
      });
      if (!res.ok) {
        throw new Error(`Failed to create project: ${res.statusText}`);
      }
      return res.json();
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["projects"] }),
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
