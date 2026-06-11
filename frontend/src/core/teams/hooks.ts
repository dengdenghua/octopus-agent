
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { getBackendBaseURL } from "../config";

export interface TeamMember {
  name: string;
  display_name?: string | null;
  avatar_url?: string | null;
}

export interface Team {
  id: string;
  name: string;
  members: TeamMember[];
  leader_id: string | null;
  mode: string;
  created_at: string;
  thread_ids: string[];
}

const BASE = () => `${getBackendBaseURL()}/api/teams`;

export function useTeams() {
  return useQuery<Team[]>({
    queryKey: ["teams"],
    queryFn: async () => {
      const res = await fetch(BASE());
      if (!res.ok) return [];
      return res.json();
    },
  });
}

export function useTeamByThread(threadId: string | null) {
  return useQuery<Team | null>({
    queryKey: ["teams", "by-thread", threadId],
    queryFn: async () => {
      if (!threadId) return null;
      const res = await fetch(`${BASE()}/by-thread/${threadId}`);
      if (!res.ok) return null;
      const data = await res.json();
      return data ?? null;
    },
    enabled: !!threadId,
  });
}

export function useCreateTeam() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (data: {
      name: string;
      members: TeamMember[];
      leader_id?: string | null;
      mode?: string;
    }) => {
      const res = await fetch(BASE(), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      });
      return (await res.json()) as Team;
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["teams"] });
    },
  });
}

export function useDeleteTeam() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: string) => {
      await fetch(`${BASE()}/${id}`, { method: "DELETE" });
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["teams"] });
    },
  });
}

export function useLinkThreadToTeam() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({
      teamId,
      threadId,
    }: {
      teamId: string;
      threadId: string;
    }) => {
      const res = await fetch(`${BASE()}/${teamId}/threads/${threadId}`, {
        method: "POST",
      });
      return res.json();
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["teams"] });
    },
  });
}
